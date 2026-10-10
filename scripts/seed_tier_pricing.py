"""
Assign a tier to existing tenants based on their current amount.
Usage:
    python -m scripts.seed_tier_pricing --apply
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app import create_app
from extensions import mongo


def tier_for_amount(amount):
    if amount <= 300:
        return "starter"
    if amount <= 500:
        return "pro"
    if amount <= 1200:
        return "business"
    return "enterprise"


def main():
    apply = "--apply" in sys.argv
    app = create_app()
    with app.app_context():
        cur = mongo.db.tenants.find({"tier": {"$exists": False}})
        n = 0
        for t in cur:
            tier = tier_for_amount(float(t.get("subscription_amount", 500)))
            print(f"{t.get('tenant_code')}: {t.get('subscription_amount')} → {tier}")
            if apply:
                mongo.db.tenants.update_one(
                    {"_id": t["_id"]},
                    {"$set": {"tier": tier}},
                )
                n += 1
        print(f"{'Applied' if apply else 'Would apply'} to {n} tenants")


if __name__ == "__main__":
    main()