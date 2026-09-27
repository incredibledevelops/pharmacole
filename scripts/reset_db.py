"""
DANGER: Drop the current database. For development only.

Usage (from the project root):
    python scripts/reset_db.py --yes
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app import create_app
from extensions import mongo


def main():
    if "--yes" not in sys.argv:
        print("Refusing to drop database. Pass --yes to confirm.")
        return

    app = create_app()
    with app.app_context():
        db_name = app.config["MONGO_DB_NAME"]
        mongo.cx.drop_database(db_name)
        print(f"Dropped database: {db_name}")


if __name__ == "__main__":
    main()