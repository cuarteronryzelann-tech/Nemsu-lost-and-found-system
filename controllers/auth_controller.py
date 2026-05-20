"""
controllers/auth_controller.py - Authentication Routes
=======================================================
Two login paths:
  1. /login / /auth/login   -> Google OAuth for @nemsu.edu.ph students
  2. /admin/login           -> Email + password form for administrator only

Flow for students:
  Sign in with Google → /auth/callback
    → first login  → /user/register → /user/dashboard
    → returning    →                  /user/dashboard
"""

import os
from flask import Blueprint, redirect, url_for, session, request, render_template, flash
from requests_oauthlib import OAuth2Session
from config import Config
from models.user_model import create_or_update_user, get_user_by_email

GOOGLE_AUTH_URL     = "https://accounts.google.com/o/oauth2/auth"
GOOGLE_TOKEN_URL    = "https://accounts.google.com/o/oauth2/token"
GOOGLE_USERINFO_URL = "https://www.googleapis.com/oauth2/v1/userinfo"

ADMIN_EMAIL    = "admin@nemsu.edu.ph"
ADMIN_PASSWORD = "!admin123"

auth_bp = Blueprint("auth", __name__)


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

PERSONAL_DOMAINS = {
    "gmail.com", "yahoo.com", "outlook.com", "hotmail.com",
    "live.com", "icloud.com", "aol.com", "protonmail.com",
    "mail.com", "ymail.com", "msn.com", "googlemail.com",
}

def _is_personal_email(email: str) -> bool:
    domain = email.split("@")[-1].lower() if "@" in email else ""
    return domain in PERSONAL_DOMAINS

def _student_redirect_uri() -> str:
    return Config.GOOGLE_REDIRECT_URI


# ─────────────────────────────────────────────────────────────────────────────
# Root
# ─────────────────────────────────────────────────────────────────────────────

@auth_bp.route("/")
def index():
    if "user" not in session:
        return redirect(url_for("auth.login"))
    user = session["user"]
    if user["role"] == "admin":
        return redirect(url_for("admin.dashboard"))
    if not user.get("is_registered"):
        return redirect(url_for("user.register"))
    return redirect(url_for("user.dashboard"))


# ─────────────────────────────────────────────────────────────────────────────
# Student login — Google OAuth
# ─────────────────────────────────────────────────────────────────────────────

@auth_bp.route("/login")
def login():
    if "user" in session:
        return redirect(url_for("auth.index"))
    return render_template("login.html")


@auth_bp.route("/auth/login")
def google_login():
    redirect_uri = _student_redirect_uri()
    google = OAuth2Session(
        Config.GOOGLE_CLIENT_ID,
        redirect_uri=redirect_uri,
        scope=["openid", "email", "profile"]
    )
    authorization_url, state = google.authorization_url(
        GOOGLE_AUTH_URL,
        access_type="offline",
        prompt="select_account"
    )
    session["oauth_state"]        = state
    session["oauth_flow"]         = "student"
    session["oauth_redirect_uri"] = redirect_uri
    session.modified = True
    return redirect(authorization_url)


@auth_bp.route("/auth/callback")
def google_callback():
    try:
        saved_state  = session.get("oauth_state")
        redirect_uri = session.get("oauth_redirect_uri") or _student_redirect_uri()
        incoming_state = request.args.get("state")

        if saved_state and incoming_state and saved_state != incoming_state:
            flash("Session expired. Please sign in again.", "error")
            session.clear()
            return redirect(url_for("auth.login"))

        google = OAuth2Session(
            Config.GOOGLE_CLIENT_ID,
            redirect_uri=redirect_uri,
            state=saved_state or incoming_state
        )

        os.environ.setdefault("OAUTHLIB_INSECURE_TRANSPORT", "1")

        google.fetch_token(
            GOOGLE_TOKEN_URL,
            client_secret=Config.GOOGLE_CLIENT_SECRET,
            authorization_response=request.url
        )

        user_info = google.get(GOOGLE_USERINFO_URL).json()
        email     = user_info.get("email", "").lower().strip()
        full_name = user_info.get("name", "Unknown")

        if not email:
            flash("Could not retrieve your email from Google. Please try again.", "error")
            session.clear()
            return redirect(url_for("auth.login"))

        # Block personal emails
        if _is_personal_email(email):
            session.clear()
            flash(
                "⚠️ Personal email accounts are not available for this system. "
                "Please sign in with your @nemsu.edu.ph institutional account.",
                "error"
            )
            return redirect(url_for("auth.login"))

        # Block non-nemsu domains
        if not email.endswith(f"@{Config.ALLOWED_EMAIL_DOMAIN}"):
            session.clear()
            flash(
                f"Access denied. Only @{Config.ALLOWED_EMAIL_DOMAIN} accounts are allowed.",
                "error"
            )
            return redirect(url_for("auth.login"))

        # Admin must use admin login form, not student OAuth
        if email == ADMIN_EMAIL:
            session.clear()
            flash("Please use the Admin Login form to sign in as administrator.", "warning")
            return redirect(url_for("auth.admin_login_page"))

        # Valid student — always create/update in DB (handles DB wipe after Render spin-down)
        student_id = email.split("@")[0]
        user = create_or_update_user(
            student_id=student_id,
            full_name=full_name,
            email=email
        )

        if not user:
            flash("Could not create your account. Please try again.", "error")
            session.clear()
            return redirect(url_for("auth.login"))

        is_registered = int(user.get("is_registered") or 0)

        session.clear()
        session["user"] = {
            "id":            user["id"],
            "email":         user["email"],
            "full_name":     user["full_name"],
            "role":          user["role"],
            "is_registered": is_registered,
        }
        session.modified = True

        # Existing registered users go straight to dashboard
        if is_registered == 1:
            return redirect(url_for("user.dashboard"))

        # New/incomplete users go to register
        return redirect(url_for("user.register"))

    except Exception as e:
        import traceback
        traceback.print_exc()
        session.clear()
        flash(f"Login failed: {str(e)}", "error")
        return redirect(url_for("auth.login"))


# ─────────────────────────────────────────────────────────────────────────────
# Admin login — Email + Password form (no Google OAuth)
# ─────────────────────────────────────────────────────────────────────────────

@auth_bp.route("/admin/login", methods=["GET", "POST"])
def admin_login_page():
    # Already logged in as admin
    if "user" in session and session["user"].get("role") == "admin":
        return redirect(url_for("admin.dashboard"))

    if request.method == "POST":
        email    = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")

        if email != ADMIN_EMAIL:
            flash("Invalid admin email address.", "error")
            return render_template("admin_login.html")

        if password != ADMIN_PASSWORD:
            flash("Incorrect password. Please try again.", "error")
            return render_template("admin_login.html")

        # Credentials correct — load admin from DB
        user = get_user_by_email(ADMIN_EMAIL)
        if not user:
            flash("Admin account not found in database. Please contact support.", "error")
            return render_template("admin_login.html")

        session.clear()
        session["user"] = {
            "id":            user["id"],
            "email":         user["email"],
            "full_name":     user["full_name"],
            "role":          "admin",
            "is_registered": 1,
        }
        session.modified = True
        return redirect(url_for("admin.dashboard"))

    return render_template("admin_login.html")


# ─────────────────────────────────────────────────────────────────────────────
# Logout
# ─────────────────────────────────────────────────────────────────────────────

@auth_bp.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("auth.login"))
