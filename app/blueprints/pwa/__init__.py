from flask import Blueprint

pwa_bp = Blueprint("pwa", __name__)

from . import routes  # noqa: E402,F401