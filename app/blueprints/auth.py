from datetime import datetime
from flask import (
    Blueprint, render_template, request, redirect, url_for,
    flash, current_app, session,
)
from flask_login import login_user, logout_user, login_required, current_user

from extensions import mongo, limiter
from models import find_user_by_email, find_tenant_by_code, find_tenant_by_id
from utils import oid
from app.services import tenant_service, user_service

auth_bp = Blueprint("auth", __name__)


# ---------------------------------------------------------------------------
# Landing / login
# ---------------------------------------------------------------------------

@auth_bp.route("/login", methods=["GET", "POST"])
@limiter.limit("10 per minute", methods=["POST"])
def login():
    if current_user.is_authenticated:
        return _redirect_for_role(current_user.role)

    if request.method == "POST":
        login_type = (request.form.get("login_type") or "tenant").strip()
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
            flash("This account has been deactivated.", "warning")
            return render_template("auth/login.html", form=request.form), 403

        if login_type == "tenant":
            tenant_code = (request.form.get("tenant_code") or "").strip()
            if not tenant_code:
                flash("Pharmacy code is required.", "danger")
                return render_template("auth/login.html", form=request.form), 400

            tenant = find_tenant_by_code(tenant_code)
            if not tenant:
                flash("No pharmacy found with that code.", "danger")
                return render_template("auth/login.html", form=request.form), 404

            if user.role == "super_admin":
                flash("Super admins must sign in via the Super Admin tab.", "danger")
                return render_template("auth/login.html", form=request.form), 403

            if str(user.tenant_id) != str(tenant._id):
                flash("This account does not belong to that pharmacy.", "danger")
                return render_template("auth/login.html", form=request.form), 403

        elif login_type == "super":
            if user.role != "super_admin":
                flash("You are not a super admin.", "danger")
                return render_template("auth/login.html", form=request.form), 403

        else:
            flash("Invalid login type.", "danger")
            return render_template("auth/login.html", form=request.form), 400

        session.permanent = True
        login_user(user, remember=False)

        # If tenant is expired, subscription_required will catch them, but we can
        # proactively route to the lock screen for owners/pharmacists/cashiers.
        if user.role != "super_admin":
            tenant = find_tenant_by_id(user.tenant_id)
            if tenant and tenant.subscription_status != "active":
                return redirect(url_for("main.subscription_locked"))

        return _redirect_for_role(user.role)

    return render_template("auth/login.html", form={})


@auth_bp.route("/logout")
@login_required
def logout():
    logout_user()
    flash("You have been signed out.", "success")
    return redirect(url_for("main.landing"))


def _redirect_for_role(role):
    mapping = {
        "owner": "owner.dashboard",
        "pharmacist": "pharmacist.dashboard",
        "cashier": "cashier.pos",
        "super_admin": "super_admin.dashboard",
    }
    return redirect(url_for(mapping.get(role, "main.landing")))


# ---------------------------------------------------------------------------
# Signup
# ---------------------------------------------------------------------------

@auth_bp.route("/signup", methods=["GET", "POST"])
@limiter.limit("5 per hour", methods=["POST"])
def signup():
    if current_user.is_authenticated:
        return _redirect_for_role(current_user.role)

    if request.method == "POST":
        form = request.form

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
            return render_template("auth/signup.html", form=form), 400

        if tenant_service.get_by_owner_email(email):
            flash("That email is already registered.", "danger")
            return render_template("auth/signup.html", form=form), 409

        if user_service.get_by_email(email):
            flash("That email is already registered.", "danger")
            return render_template("auth/signup.html", form=form), 409

        # Create tenant + owner
        try:
            tenant_id = tenant_service.create_tenant(
                pharmacy_name=pharmacy_name,
                owner_name=owner_name,
                owner_email=email,
                owner_phone=phone,
                address=address,
            )
        except Exception as e:
            current_app.logger.exception("Tenant creation failed")
            flash("Could not create your pharmacy. Please try again.", "danger")
            return render_template("auth/signup.html", form=form), 500

        try:
            user_service.create_user(
                email=email,
                password=password,
                full_name=owner_name,
                role="owner",
                tenant_id=tenant_id,
                phone=phone,
            )
        except ValueError as e:
            # Roll back tenant
            mongo.db.tenants.delete_one({"_id": tenant_id})
            flash(str(e), "danger")
            return render_template("auth/signup.html", form=form), 400

        # Log in and send them to payment
        user = find_user_by_email(email)
        session.permanent = True
        login_user(user, remember=False)
        flash("Account created. Complete payment to activate your workspace.", "success")
        return redirect(url_for("auth.payment"))

    return render_template("auth/signup.html", form={})


# ---------------------------------------------------------------------------
# Payment page (owner only)
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

    amount = tenant.subscription_amount
    return render_template(
        "auth/payment.html",
        tenant=tenant,
        amount=amount,
        paystack_public_key=current_app.config["PAYSTACK_PUBLIC_KEY"],
    )