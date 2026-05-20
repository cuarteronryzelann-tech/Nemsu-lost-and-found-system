"""
controllers/admin_controller.py - Admin Dashboard Routes
"""

import json
from flask import Blueprint, render_template, redirect, url_for, session, request, flash
from functools import wraps
from models.item_model import get_all_items, update_item_status, get_item_by_id, get_item_stats, get_items_per_month
from models.claim_model import get_all_claims, update_claim_status, get_claim_by_id
from models.user_model import (get_all_users, get_user_by_id,
                                get_users_with_pending_profile_pics,
                                approve_profile_picture, reject_profile_picture,
                                get_active_users_count, get_active_users, get_user_growth)
from models.notification_model import add_notification

admin_bp = Blueprint("admin", __name__, url_prefix="/admin")


@admin_bp.context_processor
def inject_pending_reports_count():
    """Make pending_reports_count available in all admin templates."""
    try:
        from models.report_model import get_pending_reports_count
        count = get_pending_reports_count()
    except Exception:
        count = 0
    return {"pending_reports_count": count}


def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if "user" not in session:
            return redirect(url_for("auth.login"))
        if session["user"]["role"] != "admin":
            return redirect(url_for("user.dashboard"))
        return f(*args, **kwargs)
    return decorated


# ─────────────────────────────────────────────────────────────────────────────
# Dashboard
# ─────────────────────────────────────────────────────────────────────────────

@admin_bp.route("/dashboard")
@admin_required
def dashboard():
    pending_items  = get_all_items(status="pending")
    listed_items   = get_all_items(status="listed")
    pending_claims = get_all_claims(status="pending")
    all_users      = get_all_users()
    pending_pics   = []  # approval removed
    active_users   = get_active_users_count(minutes=30)

    stats = {
        "pending_items_count":  len(pending_items),
        "listed_items_count":   len(listed_items),
        "pending_claims_count": len(pending_claims),
        "total_users":          len(all_users),
        "pending_pics_count":   len(pending_pics),
        "active_users":         active_users,
    }
    return render_template("admin/dashboard.html", stats=stats)


# ─────────────────────────────────────────────────────────────────────────────
# Item Management
# ─────────────────────────────────────────────────────────────────────────────

@admin_bp.route("/items")
@admin_required
def manage_items():
    all_items = get_all_items()
    return render_template("admin/manage_items.html", items=all_items)


@admin_bp.route("/items/<int:item_id>/approve", methods=["POST"])
@admin_required
def approve_item(item_id):
    admin_id = session["user"]["id"]
    success  = update_item_status(item_id, status="listed", approved_by=admin_id)
    flash("Item approved and listed." if success else "Could not update item.", "success" if success else "error")
    return redirect(url_for("admin.manage_items"))


@admin_bp.route("/items/<int:item_id>/deny", methods=["POST"])
@admin_required
def deny_item(item_id):
    admin_id = session["user"]["id"]
    success  = update_item_status(item_id, status="denied", approved_by=admin_id)
    flash("Found item denied." if success else "Could not update item.", "warning" if success else "error")
    return redirect(url_for("admin.manage_items"))


@admin_bp.route("/items/<int:item_id>/mark-returned", methods=["POST"])
@admin_required
def mark_returned(item_id):
    admin_id = session["user"]["id"]
    success  = update_item_status(item_id, status="returned", approved_by=admin_id)
    flash("Item marked as returned." if success else "Could not update item.", "success" if success else "error")
    return redirect(url_for("admin.manage_items"))


# ─────────────────────────────────────────────────────────────────────────────
# Claim Management
# ─────────────────────────────────────────────────────────────────────────────

@admin_bp.route("/claims")
@admin_required
def manage_claims():
    all_claims = get_all_claims()
    return render_template("admin/manage_claims.html", claims=all_claims)


@admin_bp.route("/claims/<int:claim_id>/approve", methods=["POST"])
@admin_required
def approve_claim(claim_id):
    admin_id        = session["user"]["id"]
    pickup_location = request.form.get("pickup_location", "").strip()
    if not pickup_location:
        flash("Pickup location is required.", "error")
        return redirect(url_for("admin.manage_claims"))
    claim_updated = update_claim_status(claim_id, status="approved",
                                        reviewed_by=admin_id,
                                        pickup_location=pickup_location)
    if claim_updated:
        claim = get_claim_by_id(claim_id)
        if claim:
            update_item_status(claim["item_id"], status="claimed", approved_by=admin_id)
            add_notification(
                user_id=claim["claimant_id"],
                message=f"✅ Your claim for '{claim['item_name']}' has been APPROVED! Pickup location: {pickup_location}",
                notif_type="success",
                link="/user/my-claims"
            )
        flash("Claim approved. Pickup instructions sent to student.", "success")
    else:
        flash("Could not update claim.", "error")
    return redirect(url_for("admin.manage_claims"))


@admin_bp.route("/claims/<int:claim_id>/deny", methods=["POST"])
@admin_required
def deny_claim(claim_id):
    admin_id = session["user"]["id"]
    claim    = get_claim_by_id(claim_id)
    success  = update_claim_status(claim_id, status="denied", reviewed_by=admin_id)
    if success and claim:
        add_notification(
            user_id=claim["claimant_id"],
            message=f"❌ Your claim for '{claim['item_name']}' was not approved. Please contact the admin for more info.",
            notif_type="error",
            link="/user/my-claims"
        )
    flash("Claim denied." if success else "Could not update claim.", "warning" if success else "error")
    return redirect(url_for("admin.manage_claims"))


# ─────────────────────────────────────────────────────────────────────────────
# User Management
# ─────────────────────────────────────────────────────────────────────────────

@admin_bp.route("/users")
@admin_required
def manage_users():
    from datetime import datetime, timedelta
    users        = get_all_users()
    pending_pics = []  # profile approval removed
    now = datetime.utcnow()
    threshold_5  = (now - timedelta(minutes=5)).strftime("%Y-%m-%d %H:%M:%S")
    threshold_30 = (now - timedelta(minutes=30)).strftime("%Y-%m-%d %H:%M:%S")
    now_str      = now.strftime("%Y-%m-%d %H:%M:%S")
    return render_template("admin/manage_users.html",
                           users=users, pending_pics=pending_pics,
                           active_threshold_5=threshold_5,
                           active_threshold_30=threshold_30,
                           now_str=now_str)


@admin_bp.route("/users/<int:user_id>")
@admin_required
def view_user(user_id):
    user = get_user_by_id(user_id)
    if not user:
        flash("User not found.", "error")
        return redirect(url_for("admin.manage_users"))
    from models.claim_model import get_claims_by_user
    from models.item_model import get_items_by_user
    user_claims = get_claims_by_user(user_id)
    user_items  = get_items_by_user(user_id)
    return render_template("admin/view_user.html",
                           user=user, user_claims=user_claims, user_items=user_items)


@admin_bp.route("/users/<int:user_id>/approve-picture", methods=["POST"])
@admin_required
def approve_user_picture(user_id):
    approve_profile_picture(user_id)
    add_notification(
        user_id=user_id,
        message="✅ Your profile picture has been approved by the admin!",
        notif_type="success"
    )
    flash("Profile picture approved.", "success")
    return redirect(url_for("admin.manage_users"))


@admin_bp.route("/users/<int:user_id>/reject-picture", methods=["POST"])
@admin_required
def reject_user_picture(user_id):
    reject_profile_picture(user_id)
    add_notification(
        user_id=user_id,
        message="❌ Your profile picture was rejected. Please upload a clear photo showing your face.",
        notif_type="warning",
        link="/user/dashboard"
    )
    flash("Profile picture rejected. User will need to re-upload a face photo.", "warning")
    return redirect(url_for("admin.manage_users"))


# ─────────────────────────────────────────────────────────────────────────────
# Active Users
# ─────────────────────────────────────────────────────────────────────────────

@admin_bp.route("/active-users")
@admin_required
def active_users():
    users_30min = get_active_users(minutes=30)
    users_5min  = get_active_users(minutes=5)
    all_users   = get_all_users()
    now_ids     = {u["id"] for u in users_5min}
    return render_template("admin/active_users.html",
                           users_30min=users_30min,
                           users_5min=users_5min,
                           now_ids=now_ids,
                           total_users=len(all_users))


# ─────────────────────────────────────────────────────────────────────────────
# Analytics
# ─────────────────────────────────────────────────────────────────────────────

@admin_bp.route("/analytics")
@admin_required
def analytics():
    # ── Item stats ──────────────────────────────────────────────────────
    item_stats   = get_item_stats()
    items_monthly = get_items_per_month()
    user_growth  = get_user_growth()
    active_30    = get_active_users_count(30)
    active_5     = get_active_users_count(5)
    all_users    = get_all_users()
    all_items    = get_all_items()
    all_claims   = get_all_claims()

    # Aggregate item stats
    total_lost   = sum(r["count"] for r in item_stats if r["type"] == "lost")
    total_found  = sum(r["count"] for r in item_stats if r["type"] == "found")
    total_claimed= sum(r["count"] for r in item_stats if r["status"] == "claimed")
    total_returned= sum(r["count"] for r in item_stats if r["status"] == "returned")

    # ── Time Complexity Analysis ────────────────────────────────────────
    n_items = len(all_items)
    n_users = len(all_users)
    n_claims= len(all_claims)

    complexity = {
        "binary_search": {
            "name": "Binary Search (Item Lookup)",
            "best":    "O(1)",
            "average": "O(log n)",
            "worst":   "O(log n)",
            "space":   "O(1)",
            "n":       n_items,
            "description": "Used when searching items by name or category. List must be pre-sorted.",
            "steps_best":  1,
            "steps_avg":   max(1, int(n_items.bit_length())) if n_items > 0 else 1,
            "steps_worst": max(1, int(n_items.bit_length())) if n_items > 0 else 1,
        },
        "quick_sort": {
            "name": "Quick Sort (Item Sorting)",
            "best":    "O(n log n)",
            "average": "O(n log n)",
            "worst":   "O(n²)",
            "space":   "O(log n)",
            "n":       n_items,
            "description": "Used to sort items by name, date, category, or status for display.",
            "steps_best":  max(1, int(n_items * n_items.bit_length())) if n_items > 0 else 1,
            "steps_avg":   max(1, int(n_items * n_items.bit_length())) if n_items > 0 else 1,
            "steps_worst": max(1, n_items * n_items) if n_items > 0 else 1,
        },
        "hash_lookup": {
            "name": "Hash Lookup (User ID Hashing)",
            "best":    "O(1)",
            "average": "O(1)",
            "worst":   "O(n)",
            "space":   "O(n)",
            "n":       n_users,
            "description": "SHA-256 hash used to store student IDs securely in database.",
            "steps_best":  1,
            "steps_avg":   1,
            "steps_worst": n_users,
        },
        "db_query": {
            "name": "Database Query (Claim Lookup)",
            "best":    "O(1)",
            "average": "O(log n)",
            "worst":   "O(n)",
            "space":   "O(k)",
            "n":       n_claims,
            "description": "SQLite indexed queries for retrieving claims by user or item ID.",
            "steps_best":  1,
            "steps_avg":   max(1, int(n_claims.bit_length())) if n_claims > 0 else 1,
            "steps_worst": n_claims,
        },
    }

    # ── Space Complexity ────────────────────────────────────────────────
    space = {
        "items_in_memory": {
            "label": "Items loaded for search",
            "value": n_items,
            "unit":  "records",
            "complexity": "O(n)",
            "note":  "All listed items are loaded into memory for binary search/sort"
        },
        "session_size": {
            "label": "Active sessions (filesystem)",
            "value": active_30,
            "unit":  "sessions",
            "complexity": "O(u)",
            "note":  "One session file per active user in /tmp/flask_session"
        },
        "db_size": {
            "label": "Total database records",
            "value": n_items + n_users + n_claims,
            "unit":  "rows",
            "complexity": "O(i + u + c)",
            "note":  "Items + Users + Claims stored in SQLite"
        },
    }

    # Prepare chart data as JSON
    months    = sorted(set(r["month"] for r in items_monthly))
    lost_data = [next((r["count"] for r in items_monthly
                       if r["month"] == m and r["type"] == "lost"), 0) for m in months]
    found_data= [next((r["count"] for r in items_monthly
                       if r["month"] == m and r["type"] == "found"), 0) for m in months]

    growth_months = [r["month"] for r in user_growth]
    growth_counts = [r["count"] for r in user_growth]

    return render_template("admin/analytics.html",
        total_users=n_users, total_items=n_items, total_claims=n_claims,
        total_lost=total_lost, total_found=total_found,
        total_claimed=total_claimed, total_returned=total_returned,
        active_30=active_30, active_5=active_5,
        complexity=complexity, space=space,
        chart_months=json.dumps(months),
        chart_lost=json.dumps(lost_data),
        chart_found=json.dumps(found_data),
        growth_months=json.dumps(growth_months),
        growth_counts=json.dumps(growth_counts),
    )


# ─────────────────────────────────────────────────────────────────────────────
# Delete Item (illegal / fake)
# ─────────────────────────────────────────────────────────────────────────────

@admin_bp.route("/items/<int:item_id>/delete", methods=["POST"])
@admin_required
def delete_item(item_id):
    from models.item_model import delete_item as do_delete, get_item_by_id
    item = get_item_by_id(item_id)
    if not item:
        flash("Item not found.", "error")
        return redirect(url_for("admin.manage_items"))

    reason = request.form.get("reason", "").strip() or "Removed by admin"
    success = do_delete(item_id)

    if success:
        # Notify the reporter
        if item.get("reported_by"):
            add_notification(
                user_id=item["reported_by"],
                message=f"🚫 Your item report '{item['name']}' was removed by an admin. Reason: {reason}",
                notif_type="error"
            )
        flash(f"Item '{item['name']}' has been permanently deleted.", "success")
    else:
        flash("Could not delete item.", "error")
    return redirect(url_for("admin.manage_items"))


# ─────────────────────────────────────────────────────────────────────────────
# Reports Management
# ─────────────────────────────────────────────────────────────────────────────

@admin_bp.route("/reports")
@admin_required
def manage_reports():
    from models.report_model import get_all_reports
    all_reports = get_all_reports()
    pending     = [r for r in all_reports if r["status"] == "pending"]
    resolved    = [r for r in all_reports if r["status"] != "pending"]
    return render_template("admin/manage_reports.html",
                           pending_reports=pending,
                           resolved_reports=resolved)


@admin_bp.route("/reports/<int:report_id>/resolve", methods=["POST"])
@admin_required
def resolve_report(report_id):
    from models.report_model import resolve_report as do_resolve, get_report_by_id
    from models.item_model import delete_item as do_delete, update_item_status
    admin_id   = session["user"]["id"]
    action     = request.form.get("action", "dismiss")   # dismiss | delete_item | warn_user
    admin_note = request.form.get("admin_note", "").strip()

    report = get_report_by_id(report_id)
    if not report:
        flash("Report not found.", "error")
        return redirect(url_for("admin.manage_reports"))

    status = "resolved" if action != "dismiss" else "dismissed"
    do_resolve(report_id, admin_id, status, admin_note)

    if action == "delete_item" and report.get("reported_item_id"):
        item_id = report["reported_item_id"]
        from models.item_model import get_item_by_id
        item = get_item_by_id(item_id)
        do_delete(item_id)
        if item and item.get("reported_by"):
            add_notification(
                user_id=item["reported_by"],
                message=f"🚫 Your item '{item['name']}' was removed after a report. Reason: {admin_note or 'Violated community guidelines.'}",
                notif_type="error"
            )
        flash("Report resolved and item deleted.", "success")

    elif action == "warn_user":
        target_id = report.get("reported_user_id") or (
            report.get("reported_item_id") and
            __import__("models.item_model", fromlist=["get_item_by_id"])
            .get_item_by_id(report["reported_item_id"] or 0) or {}
        ).get("reported_by")
        if target_id:
            add_notification(
                user_id=target_id,
                message=f"⚠️ Admin warning: A report was filed against you or your item. {admin_note or 'Please follow community guidelines.'}",
                notif_type="warning"
            )
        flash("User warned and report resolved.", "success")

    else:
        flash("Report dismissed.", "info")

    return redirect(url_for("admin.manage_reports"))


@admin_bp.route("/users/<int:user_id>/disable", methods=["POST"])
@admin_required
def disable_user(user_id):
    from models.user_model import disable_user as do_disable
    from datetime import datetime, timedelta
    hours = request.form.get("hours", type=float) or 24.0
    until = datetime.utcnow() + timedelta(hours=hours)
    until_str = until.strftime("%Y-%m-%d %H:%M:%S")
    do_disable(user_id, until_str)
    add_notification(
        user_id=user_id,
        message=f"⛔ Your account has been temporarily disabled for {hours:.0f} hour(s) by an admin.",
        notif_type="error"
    )
    flash(f"User account disabled for {hours:.0f} hour(s).", "warning")
    return redirect(url_for("admin.manage_users"))


@admin_bp.route("/users/<int:user_id>/enable", methods=["POST"])
@admin_required
def enable_user(user_id):
    from models.user_model import enable_user as do_enable
    do_enable(user_id)
    add_notification(
        user_id=user_id,
        message="✅ Your account has been re-enabled by an admin.",
        notif_type="success"
    )
    flash("User account re-enabled.", "success")
    return redirect(url_for("admin.manage_users"))


@admin_bp.route("/users/<int:user_id>/delete", methods=["POST"])
@admin_required
def delete_user(user_id):
    from models.user_model import delete_user as do_delete, get_user_by_id
    user = get_user_by_id(user_id)
    if not user:
        flash("User not found.", "error")
        return redirect(url_for("admin.manage_users"))
    if user.get("role") == "admin":
        flash("Cannot delete admin account.", "error")
        return redirect(url_for("admin.manage_users"))
    success = do_delete(user_id)
    flash(f"User '{user['full_name']}' permanently deleted." if success else "Could not delete user.", "success" if success else "error")
    return redirect(url_for("admin.manage_users"))
