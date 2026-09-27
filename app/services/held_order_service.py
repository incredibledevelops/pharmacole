from datetime import datetime
from extensions import mongo
from utils import oid


def hold(tenant_id, cashier, items, label=None):
    tid = oid(tenant_id)
    if not tid:
        raise ValueError("Invalid tenant")
    if not items:
        raise ValueError("Cart is empty")

    total = 0.0
    clean = []
    for raw in items:
        price = float(raw.get("price", 0))
        qty = int(raw.get("qty", 0))
        if qty <= 0:
            continue
        clean.append({
            "inventory_id": oid(raw.get("id")),
            "name": raw.get("name"),
            "price": price,
            "qty": qty,
        })
        total += price * qty

    doc = {
        "tenant_id": tid,
        "cashier_id": oid(cashier._id) if cashier else None,
        "cashier_name": getattr(cashier, "name", "—") if cashier else "—",
        "label": (label or "").strip() or f"Held {datetime.utcnow():%H:%M}",
        "items": clean,
        "total_amount": round(total, 2),
        "created_at": datetime.utcnow(),
    }
    return mongo.db.held_orders.insert_one(doc).inserted_id


def list_for_tenant(tenant_id, limit=100):
    tid = oid(tenant_id)
    if not tid:
        return []
    cur = (
        mongo.db.held_orders
        .find({"tenant_id": tid})
        .sort("created_at", -1)
        .limit(limit)
    )
    return list(cur)


def get(tenant_id, held_id):
    tid = oid(tenant_id)
    hid = oid(held_id)
    if not tid or not hid:
        return None
    return mongo.db.held_orders.find_one({"_id": hid, "tenant_id": tid})


def delete(tenant_id, held_id):
    tid = oid(tenant_id)
    hid = oid(held_id)
    if not tid or not hid:
        return False
    res = mongo.db.held_orders.delete_one({"_id": hid, "tenant_id": tid})
    return res.deleted_count == 1