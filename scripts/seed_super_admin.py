"""
Create the super admin user (idempotent).

Usage (from the project root):
    python scripts/seed_super_admin.py
"""
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app import create_app
from extensions import mongo
from models import User


def main():
    app = create_app()
    with app.app_context():
        email = app.config["SUPER_ADMIN_EMAIL"].lower().strip()
        password = app.config["SUPER_ADMIN_PASSWORD"]

        existing = mongo.db.users.find_one({"email": email})
        if existing:
            print(f"Super admin already exists: {email}")
            return

        mongo.db.users.insert_one({
            "email": email,
            "password_hash": User.hash_password(password),
            "full_name": "Platform Owner",
            "role": "super_admin",
            "tenant_id": None,
            "phone": None,
            "is_active": True,
            "session_version": 1,
            "created_at": datetime.utcnow(),
        })
        print(f"Created super admin: {email}")
        print("Change the password after first login!")


if __name__ == "__main__":
    main()