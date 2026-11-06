# app/blueprints/auth.py
from datetime import datetime

from flask import (
    Blueprint, render_template, request, redirect, url_for,
    flash, current_app, session, abort,
)
from flask_login import login_user, logout_user, login_required, current_user

from extensions import mongo, limiter
from models import find_user_by_email, find_tenant_by_code, find_tenant_by_id
from utils import oid
from app.services import tenant_service, user_service, branch_service


auth_bp = Blueprint("auth", __name__, url_prefix="/auth")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _role_endpoint(role):
    mapping = {
        "owner": "owner.dashboard",
        "pharmacist": "pharmacist.dashboard",
        "cashier": "cashier.pos",
        "super_admin": "super_admin.dashboard",
    }
    return mapping.get(role, "main.landing")


def _redirect_for_role(role):
    return redirect(url_for(_role_endpoint(role)))


def _safe_next(target, fallback_endpoint):
    """Return a same-host path from `target`, or the fallback endpoint's URL.

    Guards against open-redirect abuse: only relative paths starting with a
    single "/" are accepted (so "//evil.com" and "https://evil.com" are both
    rejected).
    """
    if not target:
        return url_for(fallback_endpoint)
    if target.startswith("/") and not target.startswith("//"):
        return target
    return url_for(fallback_endpoint)


def _wants_remember():
    """Read the 'remember me' checkbox from the form. Default: False."""
    v = request.form.get("remember")
    if v is None:
        return False
    return str(v).strip().lower() in ("1", "true", "yes", "on")


# ---------------------------------------------------------------------------
# Login / logout
# ---------------------------------------------------------------------------

@auth_bp.route("/login", methods=["GET", "POST"])
@limiter.limit("10 per minute", methods=["POST"])
def login():
    if current_user.is_authenticated:
        return _redirect_for_role(current_user.role)

    if request.method == "POST":
        email = (request.form.get("email") or "").lower().strip()
        password = request.form.get("password") or ""

        if not email or not password:
            flash("Email and password are required.", "danger")
            return render_template("auth/login.html", form=request.form), 400

        user = find_user_by_email(email)
        if not user or not user.check_password(password):
            flash("Invalid email or password.", "danger")
            return render_template("auth/login.html", form=request.form), 401

        if not user.is_active:
            flash("This account has been deactivated. Contact your pharmacy owner.", "warning")
            return render_template("auth/login.html", form=request.form), 403

        # Session cookie hygiene.
        session.permanent = True

        # Honour the "Keep me signed in on this device" checkbox.
        remember = _wants_remember()
        login_user(user, remember=remember)

        # Non-super-admin users whose tenant subscription has lapsed go
        # straight to the lock page instead of their dashboard.
        if user.role != "super_admin" and user.tenant_id:
            tenant = find_tenant_by_id(user.tenant_id)
            if tenant and tenant.subscription_status != "active":
                return redirect(url_for("main.subscription_locked"))

        # Send the user to their role's home page. ?next= is honoured only
        # when it's a safe, same-origin relative path.
        return redirect(_safe_next(
            request.args.get("next"),
            _role_endpoint(user.role),
        ))

    return render_template("auth/login.html", form={})


@auth_bp.route("/logout")
@login_required
def logout():
    logout_user()
    flash("You have been signed out.", "success")
    return redirect(url_for("main.landing"))


# ---------------------------------------------------------------------------
# Signup (unchanged)
# ---------------------------------------------------------------------------

@auth_bp.route("/signup", methods=["GET", "POST"])
@limiter.limit("5 per hour", methods=["POST"])
def signup():
    if current_user.is_authenticated:
        return _redirect_for_role(current_user.role)

    tiers = current_app.config["PRICING_TIERS"]
    tier_order = current_app.config["TIER_ORDER"]

    if request.method == "POST":
        form = request.form

        tier = (form.get("tier") or "pro").strip().lower()
        if tier not in tiers:
            tier = "pro"

        pharmacy_name = (form.get("pharmacy_name") or "").strip()
        owner_name = (form.get("owner_name") or "").strip()
        email = (form.get("email") or "").lower().strip()
        phone = (form.get("phone") or "").strip()
        address = (form.get("address") or "").strip()
        password = form.get("password") or ""
        confirm = form.get("confirm_password") or ""

        errors = []
        if not pharmacy_name:
            errors.append("Pharmacy name is required.")
        if not owner_name:
            errors.append("Owner name is required.")
        if not email or "@" not in email:
            errors.append("A valid email is required.")
        if len(password) < 8:
            errors.append("Password must be at least 8 characters.")
        if password != confirm:
            errors.append("Passwords do not match.")

        if errors:
            for e in errors:
                flash(e, "danger")
            return render_template(
                "auth/signup.html", form=form,
                tiers=tiers, tier_order=tier_order, selected_tier=tier,
            ), 400

        if tenant_service.get_by_owner_email(email):
            flash("That email is already registered.", "danger")
            return render_template(
                "auth/signup.html", form=form,
                tiers=tiers, tier_order=tier_order, selected_tier=tier,
            ), 409

        if user_service.get_by_email(email):
            flash("That email is already registered.", "danger")
            return render_template(
                "auth/signup.html", form=form,
                tiers=tiers, tier_order=tier_order, selected_tier=tier,
            ), 409

        try:
            tenant_id = tenant_service.create_tenant(
                pharmacy_name=pharmacy_name,
                owner_name=owner_name,
                owner_email=email,
                owner_phone=phone,
                address=address,
                tier=tier,
            )
        except Exception:
            current_app.logger.exception("Tenant creation failed")
            flash("Could not create your pharmacy. Please try again.", "danger")
            return render_template(
                "auth/signup.html", form=form,
                tiers=tiers, tier_order=tier_order, selected_tier=tier,
            ), 500

        try:
            user_service.create_user(
                email=email, password=password, full_name=owner_name,
                role="owner", tenant_id=tenant_id, phone=phone,
            )
        except ValueError as e:
            try:
                mongo.db.tenants.delete_one({"_id": tenant_id})
            except Exception:
                current_app.logger.warning("Tenant rollback failed", exc_info=True)
            flash(str(e), "danger")
            return render_template(
                "auth/signup.html", form=form,
                tiers=tiers, tier_order=tier_order, selected_tier=tier,
            ), 400

        try:
            branch_service.ensure_default(tenant_id)
        except Exception:
            current_app.logger.warning("Could not create default branch", exc_info=True)

        user = find_user_by_email(email)
        session.permanent = True
        login_user(user, remember=False)
        flash(
            f"Account created on the {tiers[tier]['label']} plan. "
            "Complete payment to activate your workspace.",
            "success",
        )
        return redirect(url_for("auth.payment"))

    selected_tier = (request.args.get("tier") or "pro").strip().lower()
    if selected_tier not in tiers:
        selected_tier = "pro"
    return render_template(
        "auth/signup.html", form={},
        tiers=tiers, tier_order=tier_order, selected_tier=selected_tier,
    )


# ---------------------------------------------------------------------------
# Payment page (unchanged)
# ---------------------------------------------------------------------------

@auth_bp.route("/payment", methods=["GET"])
@login_required
def payment():
    if current_user.role != "owner":
        return _redirect_for_role(current_user.role)

    tenant = find_tenant_by_id(current_user.tenant_id)
    if not tenant:
        flash("Pharmacy record not found.", "danger")
        return redirect(url_for("auth.logout"))

    tiers = current_app.config["PRICING_TIERS"]
    tier_order = current_app.config["TIER_ORDER"]
    current_tier = tenant.tier if tenant.tier in tiers else "pro"
    pending_tier = tenant.pending_tier if tenant.pending_tier in tiers else None

    qs_tier = (request.args.get("tier") or "").strip().lower()
    if qs_tier in tiers:
        selected_tier = qs_tier
    elif pending_tier:
        selected_tier = pending_tier
    else:
        selected_tier = current_tier

    tier_info = tiers[selected_tier]
    amount = float(tier_info["amount"])
    is_tier_change = selected_tier != current_tier

    return render_template(
        "auth/payment.html",
        tenant=tenant,
        amount=amount,
        current_tier=current_tier,
        selected_tier=selected_tier,
        tier_info=tier_info,
        tiers=tiers,
        tier_order=tier_order,
        is_tier_change=is_tier_change,
        paystack_public_key=current_app.config["PAYSTACK_PUBLIC_KEY"],
    )


# ---------------------------------------------------------------------------
# Trailing-slash normalization (unchanged)
# ---------------------------------------------------------------------------

@auth_bp.route("/login/", strict_slashes=False, endpoint="login_trailing")
def _login_trailing_slash():
    args = {k: v for k, v in request.args.items()}
    return redirect(url_for("auth.login", **args), code=301)


@auth_bp.route("/signup/", strict_slashes=False, endpoint="signup_trailing")
def _signup_trailing_slash():
    args = {k: v for k, v in request.args.items()}
    return redirect(url_for("auth.signup", **args), code=301)