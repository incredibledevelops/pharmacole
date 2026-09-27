from datetime import datetime
from extensions import mongo
from utils import oid, to_float, to_int


def create_item(tenant_id, data):
    """Insert one inventory batch. data must have name, sku, quantity, expiry_date."""
    tid = oid(tenant_id)
    if not tid:
        raise ValueError("Invalid tenant")

    name = (data.get("name") or "").strip()
    sku = (data.get("sku") or "").strip()
    if not name or not sku:
        raise ValueError("Name and SKU are required")

    expiry = _to_dt(data.get("expiry_date"))
    if not expiry:
        raise ValueError("Expiry date is required")

    doc = {
        "tenant_id": tid,
        "name": name,
        "sku": sku,
        "category": (data.get("category") or "").strip() or None,
        "dosage_form": (data.get("dosage_form") or "").strip() or None,
        "pack_size": (data.get("pack_size") or "").strip() or None,
        "description": (data.get("description") or "").strip() or None,
        "cost_price": to_float(data.get("cost_price"), 0.0),
        "selling_price": to_float(data.get("selling_price"), 0.0),
        "tax_rate": to_float(data.get("tax_rate"), 5.0),
        "quantity": to_int(data.get("quantity"), 0),
        "min_threshold": to_int(data.get("min_threshold"), 10),
        "batch_number": (data.get("batch_number") or "").strip() or None,
        "expiry_date": expiry,
        "supplier": (data.get("supplier") or "").strip() or None,
        "created_at": datetime.utcnow(),
        "updated_at": datetime.utcnow(),
    }
    res = mongo.db.inventory.insert_one(doc)
    return res.inserted_id


def list_for_tenant(tenant_id, search=None, limit=1000):
    tid = oid(tenant_id)
    if not tid:
        return []
    q = {"tenant_id": tid}
    if search:
        s = search.strip()
        q["$or"] = [
            {"name": {"$regex": s, "$options": "i"}},
            {"sku": {"$regex": s, "$options": "i"}},
        ]
    cur = mongo.db.inventory.find(q).sort("name", 1).limit(limit)
    return list(cur)


def get_item(tenant_id, item_id):
    tid = oid(tenant_id)
    iid = oid(item_id)
    if not tid or not iid:
        return None
    return mongo.db.inventory.find_one({"_id": iid, "tenant_id": tid})


def count_for_tenant(tenant_id):
    tid = oid(tenant_id)
    if not tid:
        return 0
    return mongo.db.inventory.count_documents({"tenant_id": tid})


def low_stock(tenant_id, limit=50):
    tid = oid(tenant_id)
    if not tid:
        return []
    pipeline = [
        {"$match": {"tenant_id": tid}},
        {"$match": {"$expr": {"$lte": ["$quantity", "$min_threshold"]}}},
        {"$sort": {"quantity": 1}},
        {"$limit": limit},
    ]
    return list(mongo.db.inventory.aggregate(pipeline))


def expiring_within(tenant_id, days=30, limit=200):
    tid = oid(tenant_id)
    if not tid:
        return []
    cutoff = datetime.utcnow()
    horizon = cutoff.replace(hour=23, minute=59, second=59) 
    from datetime import timedelta
    horizon = cutoff + timedelta(days=days)
    cur = (
        mongo.db.inventory
        .find({
            "tenant_id": tid,
            "expiry_date": {"$gte": cutoff, "$lte": horizon},
            "quantity": {"$gt": 0},
        })
        .sort("expiry_date", 1)
        .limit(limit)
    )
    return list(cur)


def adjust_stock(tenant_id, item_id, delta, reason=None, actor_id=None):
    tid = oid(tenant_id)
    iid = oid(item_id)
    if not tid or not iid:
        raise ValueError("Invalid item")

    delta = to_int(delta, 0)
    if delta == 0:
        raise ValueError("Adjustment must be non-zero")

    item = mongo.db.inventory.find_one({"_id": iid, "tenant_id": tid})
    if not item:
        raise ValueError("Item not found")

    new_qty = int(item.get("quantity", 0)) + delta
    if new_qty < 0:
        raise ValueError("Adjustment would make quantity negative")

    mongo.db.inventory.update_one(
        {"_id": iid},
        {"$set": {"quantity": new_qty, "updated_at": datetime.utcnow()}},
    )
    mongo.db.stock_adjustments.insert_one({
        "tenant_id": tid,
        "inventory_id": iid,
        "delta": delta,
        "reason": (reason or "unspecified").strip(),
        "old_quantity": int(item.get("quantity", 0)),
        "new_quantity": new_qty,
        "actor_id": oid(actor_id) if actor_id else None,
        "created_at": datetime.utcnow(),
    })
    return new_qty


def _to_dt(value):
    if not value:
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        try:
            return datetime.strptime(value.strip()[:10], "%Y-%m-%d")
        except Exception:
            return None
    return None