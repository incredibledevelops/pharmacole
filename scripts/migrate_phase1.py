"""
Phase 1 migration:
  - Drops the legacy inventory unique index [tenant_id, sku, batch_number]
    so the new [tenant_id, branch_id, sku, batch_number] index can take over.
  - Optionally backfills `branch_id = None` on inventory docs that lack it
    (safe — the new index handles both shapes).

Usage:
    python -m scripts.migrate_phase1
"""
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app import create_app
from extensions import mongo


def migrate():
    db = mongo.db

    # 1. Drop legacy inventory unique index (name is MongoDB's auto name).
    try:
        db.inventory.drop_index("tenant_id_1_sku_1_batch_number_1")
        print("· dropped legacy inventory unique index")
    except Exception as e:
        print("· legacy inventory index not present — skipping:", e)

    # 2. Backfill branch_id = None so the new index's partial filter matches.
    res = db.inventory.update_many(
        {"branch_id": {"$exists": False}},
        {"$set": {"branch_id": None}},
    )
    print(f"· backfilled branch_id on {res.modified_count} inventory docs")

    print("Done. Now run: python -m scripts.ensure_indexes")


def main():
    app = create_app()
    with app.app_context():
        migrate()


if __name__ == "__main__":
    main()