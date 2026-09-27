import os
import pytest
from app import create_app
from extensions import mongo
from config import TestingConfig


@pytest.fixture(scope="session")
def app():
    os.environ["FLASK_ENV"] = "testing"
    app = create_app(TestingConfig)
    with app.app_context():
        yield app
        # Clean test DB
        mongo.cx.drop_database(app.config["MONGO_DB_NAME"])


@pytest.fixture()
def client(app):
    return app.test_client()


@pytest.fixture()
def clean_db(app):
    with app.app_context():
        for name in [
            "tenants", "users", "inventory", "sales", "payments",
            "prescriptions", "suppliers", "stock_adjustments",
            "held_orders", "disputes", "audit_logs", "subscription_events",
        ]:
            mongo.db[name].delete_many({})
        yield