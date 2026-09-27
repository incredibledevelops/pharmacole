from flask_pymongo import PyMongo
from flask_login import LoginManager
from flask_wtf.csrf import CSRFProtect
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

mongo = PyMongo()

login_manager = LoginManager()
login_manager.login_view = "auth.login"
login_manager.login_message = "Please sign in to continue."
login_manager.login_message_category = "warning"
login_manager.session_protection = "strong"

csrf = CSRFProtect()

limiter = Limiter(
    key_func=get_remote_address,
    default_limits=[],          # actual default comes from config at init
    headers_enabled=True,
    storage_uri="memory://",     # overridden in create_app
)