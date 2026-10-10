"""
Backfill branches for existing tenants and tag existing records.
Safe to run multiple times.

Usage:
    python -m scripts.migrate_add_branches
"""
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app import create_app
from extensions import mongo
from models import Branch
from utils import oid


def backfill():
    tenants = list(mongo.db.tenants.find({}))
    print(f"Found {len(tenants)} tenants")
    for t in tenants:
        tid = t["_id"]
        # ensure a branch exists
        br = mongo.db.branches.find_one({"tenant_id": tid, "is_default": True})
        if not br:
            br = mongo.db.branches.find_one({"tenant_id": tid})
        if not br:
            code = Branch.generate_code(tid, t.get("pharmacy_name") or "Main")
            bid = mongo.db.branches.insert_one({
                "tenant_id": tid,
                "name": f"{t.get('pharmacy_name','Pharmacy')} (Main)",
                "branch_code": code,
                "address": t.get("address"),
                "phone": t.get("owner_phone"),
                "is_default": True,
                "is_active": True,
                "created_at": datetime.utcnow(),
            }).inserted_id
            print(f"  + created branch {code} for {t.get('pharmacy_name')}")
        else:
            bid = br["_id"]
            if not br.get("is_default"):
                mongo.db.branches.update_one({"_id": bid}, {"$set": {"is_default": True}})

        # backfill branch_id on scoped collections
        for col in ("inventory", "sales", "held_orders", "prescriptions"):
            res = mongo.db[col].update_many(
                {"tenant_id": tid, "branch_id": {"$exists": False}},
                {"$set": {"branch_id": bid}},
            )
            if res.modified_count:
                print(f"  · {col}: tagged {res.modified_count} docs")

        # users: don't force; leave branch_id null = all-access
    print("Done.")


def main():
    app = create_app()
    with app.app_context():
        backfill()


if __name__ == "__main__":
    main()