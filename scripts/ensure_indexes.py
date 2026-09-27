"""
Create all MongoDB indexes.

Usage (from the project root):
    python scripts/ensure_indexes.py
"""
import os
import sys

# Make the project root importable regardless of cwd
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app import create_app
from models import ensure_indexes


def main():
    app = create_app()
    with app.app_context():
        ensure_indexes()
        print("Indexes ensured.")


if __name__ == "__main__":
    main()