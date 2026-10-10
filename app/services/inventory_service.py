from datetime import datetime, timedelta
from extensions import mongo
from utils import oid, to_float, to_int
from app.services import audit_service


def create_item(tenant_id, data, branch_id=None):
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
        "branch_id": oid(branch_id) if branch_id else None,  # NEW
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
    audit_service.log(
        "inventory.create",
        tenant_id=tid,
        branch_id=doc["branch_id"],
        target=str(res.inserted_id),
        meta={"name": name, "sku": sku, "qty": doc["quantity"]},
    )
    return res.inserted_id


def list_for_tenant(tenant_id, search=None, limit=1000, branch_id=None):
    tid = oid(tenant_id)
    if not tid:
        return []
    q = {"tenant_id": tid}
    if branch_id:
        q["branch_id"] = oid(branch_id)
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


def count_for_tenant(tenant_id, branch_id=None):
    tid = oid(tenant_id)
    if not tid:
        return 0
    q = {"tenant_id": tid}
    if branch_id:
        q["branch_id"] = oid(branch_id)
    return mongo.db.inventory.count_documents(q)


def low_stock(tenant_id, limit=50, branch_id=None):
    tid = oid(tenant_id)
    if not tid:
        return []
    match = {"tenant_id": tid}
    if branch_id:
        match["branch_id"] = oid(branch_id)
    pipeline = [
        {"$match": match},
        {"$match": {"$expr": {"$lte": ["$quantity", "$min_threshold"]}}},
        {"$sort": {"quantity": 1}},
        {"$limit": limit},
    ]
    return list(mongo.db.inventory.aggregate(pipeline))


def expiring_within(tenant_id, days=30, limit=200, branch_id=None):
    tid = oid(tenant_id)
    if not tid:
        return []
    cutoff = datetime.utcnow()
    horizon = cutoff + timedelta(days=days)
    q = {
        "tenant_id": tid,
        "expiry_date": {"$gte": cutoff, "$lte": horizon},
        "quantity": {"$gt": 0},
    }
    if branch_id:
        q["branch_id"] = oid(branch_id)
    cur = mongo.db.inventory.find(q).sort("expiry_date", 1).limit(limit)
    return list(cur)


def update_item(tenant_id, item_id, data, actor_id=None):
    """Update an item and audit price changes."""
    tid = oid(tenant_id)
    iid = oid(item_id)
    if not tid or not iid:
        raise ValueError("Invalid item")

    existing = mongo.db.inventory.find_one({"_id": iid, "tenant_id": tid})
    if not existing:
        raise ValueError("Item not found")

    allowed = {
        "name", "sku", "category", "dosage_form", "pack_size", "description",
        "cost_price", "selling_price", "tax_rate", "quantity", "min_threshold",
        "batch_number", "expiry_date", "supplier",
    }
    patch = {}
    for k in allowed:
        if k in data:
            v = data[k]
            if k in ("cost_price", "selling_price", "tax_rate"):
                v = to_float(v, 0.0)
            elif k in ("quantity", "min_threshold"):
                v = to_int(v, 0)
            elif k == "expiry_date":
                v = _to_dt(v)
            patch[k] = v

    if not patch:
        return False

    patch["updated_at"] = datetime.utcnow()
    mongo.db.inventory.update_one({"_id": iid, "tenant_id": tid}, {"$set": patch})

    # Audit price changes specifically
    for field in ("selling_price", "cost_price"):
        if field in patch and float(existing.get(field, 0)) != float(patch[field]):
            audit_service.log(
                "inventory.price_change",
                tenant_id=tid,
                target=str(iid),
                meta={
                    "field": field,
                    "from": float(existing.get(field, 0)),
                    "to": float(patch[field]),
                    "name": existing.get("name"),
                },
            )

    audit_service.log(
        "inventory.update",
        tenant_id=tid,
        target=str(iid),
        meta={"fields": list(patch.keys())},
    )
    return True


def delete_item(tenant_id, item_id):
    tid = oid(tenant_id)
    iid = oid(item_id)
    if not tid or not iid:
        raise ValueError("Invalid item")

    item = mongo.db.inventory.find_one({"_id": iid, "tenant_id": tid})
    if not item:
        raise ValueError("Item not found")

    mongo.db.inventory.delete_one({"_id": iid, "tenant_id": tid})
    audit_service.log(
        "inventory.delete",
        tenant_id=tid,
        target=str(iid),
        meta={"name": item.get("name"), "sku": item.get("sku"),
              "qty": item.get("quantity")},
    )
    return True


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
        "branch_id": item.get("branch_id"),
        "inventory_id": iid,
        "delta": delta,
        "reason": (reason or "unspecified").strip(),
        "old_quantity": int(item.get("quantity", 0)),
        "new_quantity": new_qty,
        "actor_id": oid(actor_id) if actor_id else None,
        "created_at": datetime.utcnow(),
    })

    audit_service.log(
        "inventory.adjust",
        tenant_id=tid,
        target=str(iid),
        meta={"delta": delta, "reason": reason,
              "old": int(item.get("quantity", 0)), "new": new_qty},
    )
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