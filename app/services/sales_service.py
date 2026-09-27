import secrets
import string
from datetime import datetime, timedelta
from extensions import mongo
from utils import oid, to_float, to_int


def _generate_receipt_no():
    stamp = datetime.utcnow().strftime("%Y%m%d%H%M%S")
    suffix = "".join(secrets.choice(string.ascii_uppercase + string.digits) for _ in range(4))
    return f"RCP-{stamp}-{suffix}"


def record_sale(tenant_id, cashier, items, payment_method):
    """items: list of {id, name, price, qty}. Returns dict with receipt_no etc."""
    tid = oid(tenant_id)
    if not tid:
        raise ValueError("Invalid tenant")

    if not items:
        raise ValueError("Cart is empty")

    if payment_method not in ("cash", "card", "momo"):
        raise ValueError("Invalid payment method")

    clean_items = []
    subtotal = 0.0
    vat_total = 0.0

    for raw in items:
        iid = oid(raw.get("id"))
        if not iid:
            raise ValueError("Invalid item id")

        qty = to_int(raw.get("qty"), 0)
        if qty <= 0:
            raise ValueError("Quantity must be positive")

        stock = mongo.db.inventory.find_one({"_id": iid, "tenant_id": tid})
        if not stock:
            raise ValueError(f"Item not found: {raw.get('name', iid)}")

        available = int(stock.get("quantity", 0))
        if qty > available:
            raise ValueError(
                f"Insufficient stock for {stock.get('name')}: "
                f"{available} available, {qty} requested"
            )

        price = to_float(stock.get("selling_price"), 0.0)
        tax_rate = to_float(stock.get("tax_rate"), 5.0)

        line_subtotal = price * qty
        line_vat = line_subtotal * (tax_rate / 100.0)

        clean_items.append({
            "inventory_id": iid,
            "name": stock.get("name"),
            "sku": stock.get("sku"),
            "price": price,
            "qty": qty,
            "tax_rate": tax_rate,
            "line_subtotal": round(line_subtotal, 2),
            "line_vat": round(line_vat, 2),
        })

        subtotal += line_subtotal
        vat_total += line_vat

    total = round(subtotal + vat_total, 2)

    receipt_no = _generate_receipt_no()
    sale_doc = {
        "tenant_id": tid,
        "receipt_no": receipt_no,
        "cashier_id": oid(cashier._id) if cashier else None,
        "cashier_name": getattr(cashier, "name", "—") if cashier else "—",
        "items": clean_items,
        "subtotal": round(subtotal, 2),
        "vat": round(vat_total, 2),
        "total_amount": total,
        "payment_method": payment_method,
        "timestamp": datetime.utcnow(),
    }
    mongo.db.sales.insert_one(sale_doc)

    # Decrement stock atomically
    for line in clean_items:
        mongo.db.inventory.update_one(
            {"_id": line["inventory_id"], "tenant_id": tid},
            {
                "$inc": {"quantity": -line["qty"]},
                "$set": {"updated_at": datetime.utcnow()},
            },
        )

    return {
        "receipt_no": receipt_no,
        "subtotal": sale_doc["subtotal"],
        "vat": sale_doc["vat"],
        "total": total,
        "items": clean_items,
    }


def list_for_tenant(tenant_id, limit=500, since=None):
    tid = oid(tenant_id)
    if not tid:
        return []
    q = {"tenant_id": tid}
    if since:
        q["timestamp"] = {"$gte": since}
    cur = mongo.db.sales.find(q).sort("timestamp", -1).limit(limit)
    return list(cur)


def list_for_cashier_today(tenant_id, cashier_id):
    tid = oid(tenant_id)
    cid = oid(cashier_id)
    if not tid or not cid:
        return []
    start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    cur = (
        mongo.db.sales
        .find({"tenant_id": tid, "cashier_id": cid, "timestamp": {"$gte": start}})
        .sort("timestamp", -1)
    )
    return list(cur)


def revenue_today(tenant_id):
    tid = oid(tenant_id)
    if not tid:
        return 0.0
    start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    pipeline = [
        {"$match": {"tenant_id": tid, "timestamp": {"$gte": start}}},
        {"$group": {"_id": None, "total": {"$sum": "$total_amount"}}},
    ]
    res = list(mongo.db.sales.aggregate(pipeline))
    return float(res[0]["total"]) if res else 0.0


def summary_for_tenant(tenant_id):
    tid = oid(tenant_id)
    if not tid:
        return {"revenue": 0.0, "transactions": 0, "average": 0.0}
    pipeline = [
        {"$match": {"tenant_id": tid}},
        {
            "$group": {
                "_id": None,
                "total": {"$sum": "$total_amount"},
                "count": {"$sum": 1},
            }
        },
    ]
    res = list(mongo.db.sales.aggregate(pipeline))
    if not res:
        return {"revenue": 0.0, "transactions": 0, "average": 0.0}
    total = float(res[0]["total"])
    count = int(res[0]["count"])
    return {
        "revenue": total,
        "transactions": count,
        "average": (total / count) if count else 0.0,
    }


def recent_sales(tenant_id, limit=10):
    return list_for_tenant(tenant_id, limit=limit)