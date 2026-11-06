import re
import secrets
import string
from datetime import datetime, timedelta
from pymongo.errors import DuplicateKeyError

from extensions import mongo
from utils import oid, to_float, to_int
from app.services import audit_service


class IdempotentReplay(Exception):
    def __init__(self, existing):
        self.existing = existing
        super().__init__("Already recorded")


def _generate_receipt_no():
    stamp = datetime.utcnow().strftime("%Y%m%d%H%M%S")
    suffix = "".join(secrets.choice(string.ascii_uppercase + string.digits) for _ in range(4))
    return f"RCP-{stamp}-{suffix}"


def record_sale(tenant_id, cashier, items, payment_method,
                branch_id=None, client_uuid=None,
                customer_name=None, discount=0.0):
    tid = oid(tenant_id)
    if not tid:
        raise ValueError("Invalid tenant")
    if not items:
        raise ValueError("Cart is empty")
    if payment_method not in ("cash", "card", "momo"):
        raise ValueError("Invalid payment method")

    if client_uuid is not None:
        client_uuid = str(client_uuid).strip() or None

    if client_uuid:
        existing = mongo.db.sales.find_one({"tenant_id": tid, "client_uuid": client_uuid})
        if existing:
            raise IdempotentReplay(existing)

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

    discount = to_float(discount, 0.0)
    total = round(subtotal + vat_total - discount, 2)

    receipt_no = _generate_receipt_no()
    sale_doc = {
        "tenant_id": tid,
        "branch_id": oid(branch_id) if branch_id else None,
        "receipt_no": receipt_no,
        "client_uuid": client_uuid,
        "cashier_id": oid(cashier._id) if cashier else None,
        "cashier_name": getattr(cashier, "name", "—") if cashier else "—",
        "customer_name": (customer_name or "").strip() or None,
        "items": clean_items,
        "subtotal": round(subtotal, 2),
        "vat": round(vat_total, 2),
        "discount": round(discount, 2),
        "total_amount": total,
        "payment_method": payment_method,
        "timestamp": datetime.utcnow(),
    }

    try:
        mongo.db.sales.insert_one(sale_doc)
    except DuplicateKeyError:
        existing = mongo.db.sales.find_one({"tenant_id": tid, "client_uuid": client_uuid})
        if existing:
            raise IdempotentReplay(existing)
        raise

    for line in clean_items:
        mongo.db.inventory.update_one(
            {"_id": line["inventory_id"], "tenant_id": tid},
            {"$inc": {"quantity": -line["qty"]},
             "$set": {"updated_at": datetime.utcnow()}},
        )

    audit_service.log(
        "sale.record",
        tenant_id=tid,
        branch_id=sale_doc["branch_id"],
        target=receipt_no,
        meta={"total": total, "items": len(clean_items), "method": payment_method},
    )

    return _sale_to_dict(sale_doc)


def _sale_to_dict(doc):
    return {
        "receipt_no": doc["receipt_no"],
        "subtotal": doc["subtotal"],
        "vat": doc["vat"],
        "discount": doc.get("discount", 0.0),
        "total": doc["total_amount"],
        "total_amount": doc["total_amount"],
        "items": [
            {
                "name": i["name"],
                "qty": i["qty"],
                "price": i["price"],
                "line_subtotal": i["line_subtotal"],
                "line_vat": i["line_vat"],
                "sku": i.get("sku"),
            } for i in doc["items"]
        ],
        "payment_method": doc["payment_method"],
        "timestamp": doc["timestamp"].isoformat() if isinstance(doc["timestamp"], datetime) else doc["timestamp"],
        "branch_id": str(doc["branch_id"]) if doc.get("branch_id") else None,
    }


def list_for_tenant(tenant_id, limit=500, since=None, branch_id=None,
                    q=None, method=None):
    tid = oid(tenant_id)
    if not tid:
        return []
    query = {"tenant_id": tid}
    if since:
        query["timestamp"] = {"$gte": since}
    if branch_id:
        query["branch_id"] = oid(branch_id)
    if method and method in ("cash", "card", "momo"):
        query["payment_method"] = method
    if q:
        rx = re.compile(re.escape(q.strip()), re.IGNORECASE)
        query["$or"] = [
            {"receipt_no": rx},
            {"cashier_name": rx},
        ]
    cur = mongo.db.sales.find(query).sort("timestamp", -1).limit(limit)
    return list(cur)


def list_for_cashier_today(tenant_id, cashier_id, branch_id=None):
    tid = oid(tenant_id)
    cid = oid(cashier_id)
    if not tid or not cid:
        return []
    start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    q = {"tenant_id": tid, "cashier_id": cid, "timestamp": {"$gte": start}}
    if branch_id:
        q["branch_id"] = oid(branch_id)
    cur = mongo.db.sales.find(q).sort("timestamp", -1)
    return list(cur)


def revenue_today(tenant_id, branch_id=None):
    tid = oid(tenant_id)
    if not tid:
        return 0.0
    start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    match = {"tenant_id": tid, "timestamp": {"$gte": start}}
    if branch_id:
        match["branch_id"] = oid(branch_id)
    pipeline = [
        {"$match": match},
        {"$group": {"_id": None, "total": {"$sum": "$total_amount"}}},
    ]
    res = list(mongo.db.sales.aggregate(pipeline))
    return float(res[0]["total"]) if res else 0.0


def summary_for_tenant(tenant_id, branch_id=None):
    tid = oid(tenant_id)
    if not tid:
        return {"revenue": 0.0, "transactions": 0, "average": 0.0}
    match = {"tenant_id": tid}
    if branch_id:
        match["branch_id"] = oid(branch_id)
    pipeline = [
        {"$match": match},
        {"$group": {"_id": None, "total": {"$sum": "$total_amount"},
                    "count": {"$sum": 1}}},
    ]
    res = list(mongo.db.sales.aggregate(pipeline))
    if not res:
        return {"revenue": 0.0, "transactions": 0, "average": 0.0}
    total = float(res[0]["total"])
    count = int(res[0]["count"])
    return {"revenue": total, "transactions": count,
            "average": (total / count) if count else 0.0}


def recent_sales(tenant_id, limit=10, branch_id=None):
    return list_for_tenant(tenant_id, limit=limit, branch_id=branch_id)


def consolidated_summary(tenant_id):
    """
    Per-branch revenue/transaction summary.

    Only includes branches that:
      - are currently active (`is_active: True`), OR
      - have at least one sale on record (so a deactivated branch with
        historical revenue still appears once).

    "All / Unassigned" (null branch_id) is always included when it has sales.
    """
    tid = oid(tenant_id)
    if not tid:
        return []

    # Group sales by branch.
    pipeline = [
        {"$match": {"tenant_id": tid}},
        {"$group": {
            "_id": "$branch_id",
            "revenue": {"$sum": "$total_amount"},
            "count": {"$sum": 1},
        }},
    ]
    rows = list(mongo.db.sales.aggregate(pipeline))

    # Preload branch metadata (name + is_active).
    branch_ids = [r["_id"] for r in rows if r["_id"]]
    branches = {}
    if branch_ids:
        for b in mongo.db.branches.find(
            {"_id": {"$in": branch_ids}, "tenant_id": tid},
            {"name": 1, "is_active": 1},
        ):
            branches[b["_id"]] = b

    out = []
    for r in rows:
        bid = r["_id"]
        if bid is None:
            name = "All / Unassigned"
            is_active = True
        else:
            b = branches.get(bid)
            if not b:
                # Sale references a branch that no longer exists.
                # Skip it — it would confuse "active branch" reporting.
                continue
            name = b.get("name") or str(bid)
            is_active = bool(b.get("is_active", True))

        out.append({
            "branch_id": str(bid) if bid else None,
            "branch_name": name,
            "is_active": is_active,
            "revenue": float(r["revenue"]),
            "transactions": int(r["count"]),
        })

    # Active branches first, then by revenue desc.
    out.sort(key=lambda x: (not x["is_active"], -x["revenue"]))
    return out