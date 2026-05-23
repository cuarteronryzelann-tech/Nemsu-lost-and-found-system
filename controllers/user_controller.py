"""
controllers/user_controller.py - Student Dashboard Routes
"""

import os
import uuid
from flask import (Blueprint, render_template, redirect, url_for,
                   session, request, flash, current_app, jsonify)
from functools import wraps
from models.item_model import create_item, get_item_by_id, get_items_for_search, find_matching_items, get_items_by_user, update_item
from models.claim_model import (create_claim, get_claims_by_user,
                                get_claims_for_finder, finder_respond_to_claim)
from models.user_model import (update_user_profile, update_profile_picture,
                                update_last_active, log_activity, get_user_by_id)
from models.notification_model import (get_notifications, get_unread_count,
                                        mark_all_read, mark_read, add_notification,
                                        delete_notification, delete_all_notifications)
# from utils.binary_search import collect_all_matches_by_name, binary_search_by_category  # replaced by DFS
# from utils.quick_sort import sort_by_date, sort_by_name, sort_by_category, sort_by_status  # replaced by TimSort
from utils.dfs_search import collect_all_matches_by_name, collect_all_matches_by_category
from utils.tim_sort import sort_by_date, sort_by_name, sort_by_category, sort_by_status

user_bp = Blueprint("user", __name__, url_prefix="/user")

# In-memory live location store: {user_id: {"lat": float, "lng": float}}
# For production, replace with Redis or a DB column.
_location_store = {}

ALLOWED_IMAGE_EXTENSIONS = {"png", "jpg", "jpeg", "gif", "webp"}
MAX_IMAGE_SIZE_MB = 5


def allowed_image(filename):
    return "." in filename and \
           filename.rsplit(".", 1)[1].lower() in ALLOWED_IMAGE_EXTENSIONS


def save_upload(file, subfolder):
    """Save an uploaded file. Tries ImgBB first (if IMGBB_API_KEY is set),
    returns the ImgBB URL. Falls back to local filesystem and returns a filename.

    Templates should use image_src() to resolve the stored value to a URL.
    """
    from utils.imgbb import upload_file_to_imgbb
    imgbb_url = upload_file_to_imgbb(file)
    if imgbb_url:
        return imgbb_url  # full URL stored in DB; used directly in <img src>

    # Fallback: local filesystem
    ext      = file.filename.rsplit(".", 1)[1].lower()
    filename = f"{uuid.uuid4().hex}.{ext}"
    if os.environ.get("PRODUCTION") or os.environ.get("VERCEL"):
        upload_dir = os.path.join("/tmp", "uploads", subfolder)
    else:
        upload_dir = os.path.join(current_app.root_path, "static", "uploads", subfolder)
    os.makedirs(upload_dir, exist_ok=True)
    file.seek(0)
    file.save(os.path.join(upload_dir, filename))
    return filename


def image_src(value, subfolder="items"):
    """Resolve a stored image value to a usable <img src> URL.
    - ImgBB URL (starts with http): return as-is
    - base64 data URI: return as-is
    - filename: prepend /uploads/<subfolder>/
    """
    if not value:
        return ""
    if value.startswith("http") or value.startswith("data:"):
        return value
    return f"/uploads/{subfolder}/{value}"


# ─────────────────────────────────────────────────────────────────────────────
# Access Control
# ─────────────────────────────────────────────────────────────────────────────

def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if "user" not in session:
            return redirect(url_for("auth.login"))

        user_id = session["user"].get("id")

        # Guard: DB may have been wiped (Render free tier spins down and /tmp resets).
        # If the user record no longer exists, force them to log in again via Google.
        user_profile = get_user_by_id(user_id) if user_id else None
        if not user_profile:
            session.clear()
            flash("Your session expired. Please sign in again.", "warning")
            return redirect(url_for("auth.login"))

        # Keep session in sync with DB (is_registered may have changed)
        if int(user_profile.get("is_registered") or 0) != int(session["user"].get("is_registered") or 0):
            user_data = dict(session["user"])
            user_data["is_registered"] = int(user_profile.get("is_registered") or 0)
            session["user"] = user_data
            session.modified = True

        if not session["user"].get("is_registered"):
            return redirect(url_for("user.register"))

        # Check if account is temporarily disabled
        from datetime import datetime
        disable_until = user_profile.get("disable_until")
        if disable_until:
            try:
                until_dt = datetime.strptime(disable_until, "%Y-%m-%d %H:%M:%S")
                if datetime.utcnow() < until_dt:
                    session.clear()
                    flash(f"⛔ Your account is temporarily disabled until {disable_until} UTC.", "error")
                    return redirect(url_for("auth.login"))
            except Exception:
                pass

        # Update last_active on every authenticated request
        try:
            update_last_active(user_id)
        except Exception:
            pass

        return f(*args, **kwargs)
    return decorated


# ─────────────────────────────────────────────────────────────────────────────
# Registration
# ─────────────────────────────────────────────────────────────────────────────

@user_bp.route("/register", methods=["GET", "POST"])
def register():
    if "user" not in session:
        return redirect(url_for("auth.login"))
    if session["user"].get("is_registered"):
        return redirect(url_for("user.dashboard"))

    if request.method == "POST":
        phone      = request.form.get("phone", "").strip()
        course     = request.form.get("course", "").strip()
        year_level = request.form.get("year_level", "").strip()

        if not phone or not course or not year_level:
            flash("Please fill in all required fields.", "error")
            return render_template("user/register.html")

        updated = update_user_profile(
            user_id=session["user"]["id"],
            phone=phone, course=course, year_level=year_level
        )

        if updated:
            user_data = dict(session["user"])
            user_data["is_registered"] = 1
            user_data["phone"]         = phone
            user_data["course"]        = course
            user_data["year_level"]    = year_level
            session["user"]  = user_data
            session.modified = True
            log_activity(session["user"]["id"], "registered", f"Course: {course}")
            add_notification(
                user_id=session["user"]["id"],
                message="🎉 Welcome to NEMSU Lost & Found! Your profile is set up. Don't forget to upload a profile picture.",
                notif_type="info"
            )
            flash("Profile saved! Welcome to NEMSU Lost & Found.", "success")
            return redirect(url_for("user.dashboard"))
        else:
            flash("Could not save profile. Please try again.", "error")

    return render_template("user/register.html")


# ─────────────────────────────────────────────────────────────────────────────
# Profile Picture Upload
# ─────────────────────────────────────────────────────────────────────────────

@user_bp.route("/upload-profile-picture", methods=["POST"])
@login_required
def upload_profile_picture():
    """
    Store profile picture as a base64 data-URI in the database.
    This avoids filesystem loss on Render free tier restarts.
    """
    redirect_to = request.form.get("redirect_to", "profile")

    if "profile_picture" not in request.files:
        flash("No file selected.", "error")
        return redirect(url_for("user." + redirect_to))

    file = request.files["profile_picture"]
    if file.filename == "":
        flash("No file selected.", "error")
        return redirect(url_for("user." + redirect_to))

    if not allowed_image(file.filename):
        flash("Invalid file type. Please upload a JPG, PNG, or WebP image.", "error")
        return redirect(url_for("user." + redirect_to))

    # Check file size
    file.seek(0, 2)
    size_mb = file.tell() / (1024 * 1024)
    file.seek(0)
    if size_mb > MAX_IMAGE_SIZE_MB:
        flash(f"File too large. Maximum size is {MAX_IMAGE_SIZE_MB}MB.", "error")
        return redirect(url_for("user." + redirect_to))

    # Try ImgBB first; fall back to base64 data-URI
    from utils.imgbb import upload_file_to_imgbb
    import base64
    imgbb_url = upload_file_to_imgbb(file)
    if imgbb_url:
        picture_value = imgbb_url
    else:
        # Fallback: base64 data-URI (persists across Render restarts)
        file.seek(0)
        img_bytes = file.read()
        ext = file.filename.rsplit(".", 1)[1].lower()
        mime = {"jpg": "image/jpeg", "jpeg": "image/jpeg",
                "png": "image/png", "gif": "image/gif",
                "webp": "image/webp"}.get(ext, "image/jpeg")
        picture_value = f"data:{mime};base64,{base64.b64encode(img_bytes).decode()}"

    update_profile_picture(session["user"]["id"], picture_value, auto_approve=True)

    # Update session so navbar avatar refreshes immediately
    user_data = dict(session["user"])
    user_data["profile_picture"] = picture_value
    user_data["profile_pic_status"] = "approved"
    session["user"] = user_data
    session.modified = True

    log_activity(session["user"]["id"], "uploaded_profile_picture")
    add_notification(
        user_id=session["user"]["id"],
        message="📷 Your profile picture has been updated successfully!",
        notif_type="success"
    )
    flash("Profile picture updated successfully!", "success")
    return redirect(url_for("user." + redirect_to))


# ─────────────────────────────────────────────────────────────────────────────
# Profile Page
# ─────────────────────────────────────────────────────────────────────────────

@user_bp.route("/profile", methods=["GET", "POST"])
@login_required
def profile():
    user_id = session["user"]["id"]
    user_profile = get_user_by_id(user_id) or {}

    if request.method == "POST":
        phone      = request.form.get("phone", "").strip()
        course     = request.form.get("course", "").strip()
        year_level = request.form.get("year_level", "").strip()

        if not phone or not course or not year_level:
            flash("Please fill in all required fields.", "error")
            my_lost_items  = get_items_by_user(user_id, item_type="lost")
            my_found_items = get_items_by_user(user_id, item_type="found")
            my_claims      = get_claims_by_user(user_id)
            return render_template("user/profile.html",
                                   user_profile=user_profile,
                                   my_lost_items=my_lost_items,
                                   my_found_items=my_found_items,
                                   my_claims=my_claims)

        updated = update_user_profile(user_id=user_id, phone=phone,
                                      course=course, year_level=year_level)
        if updated:
            user_data = dict(session["user"])
            user_data["phone"]      = phone
            user_data["course"]     = course
            user_data["year_level"] = year_level
            session["user"]  = user_data
            session.modified = True
            log_activity(user_id, "updated_profile")
            flash("Profile updated successfully!", "success")
        else:
            flash("Could not update profile. Please try again.", "error")
        return redirect(url_for("user.profile"))

    my_lost_items  = get_items_by_user(user_id, item_type="lost")
    my_found_items = get_items_by_user(user_id, item_type="found")
    my_claims      = get_claims_by_user(user_id)
    return render_template("user/profile.html",
                           user_profile=user_profile,
                           my_lost_items=my_lost_items,
                           my_found_items=my_found_items,
                           my_claims=my_claims)


# ─────────────────────────────────────────────────────────────────────────────
# Dashboard
# ─────────────────────────────────────────────────────────────────────────────

@user_bp.route("/dashboard")
@login_required
def dashboard():
    user_id      = session["user"]["id"]
    user_profile = get_user_by_id(user_id) or {}
    notifications = get_notifications(user_id, limit=10)
    unread_count  = get_unread_count(user_id)
    needs_pic     = user_profile.get("profile_pic_status", "none") not in ("pending", "approved")

    # ── Dashboard search params ───────────────────────────────────────────
    search_query = request.args.get("q", "").strip()
    category     = request.args.get("category", "").strip()
    sort_by      = request.args.get("sort_by", "date_reported")
    order        = request.args.get("order", "desc")
    ascending    = (order == "asc")

    # ── User search ───────────────────────────────────────────────────────
    from models.user_model import get_all_users
    matched_users = []
    if search_query:
        q_lower = search_query.lower()
        all_users = get_all_users()
        for u in all_users:
            if u.get("id") == user_id:
                continue
            name  = (u.get("full_name") or "").lower()
            email = (u.get("email") or "").lower()
            if q_lower in name or q_lower in email:
                matched_users.append(u)

    # ── Item feed (with optional filter/sort) ────────────────────────────
    # from utils.binary_search import collect_all_matches_by_name, binary_search_by_category  # replaced by DFS
    # from utils.quick_sort import (sort_by_name, sort_by_date,                               # replaced by TimSort
    #                                sort_by_category, sort_by_status)
    raw_items = get_items_for_search()

    if search_query:
        raw_items = collect_all_matches_by_name(raw_items, search_query)

    if category:
        # DFS replaces binary-search + expand pattern for category filtering
        raw_items = collect_all_matches_by_category(raw_items, category)

    sort_fns = {
        "name": sort_by_name, "date_reported": sort_by_date,
        "category": sort_by_category, "status": sort_by_status
    }
    raw_items = sort_fns.get(sort_by, sort_by_date)(raw_items, ascending=ascending)

    # Reporter info is already JOIN-ed in get_items_for_search()
    for item in raw_items:
        item["reporter_pic_ok"] = item.get("reporter_pic_status") == "approved"
    recent_items = raw_items

    return render_template("user/dashboard.html",
                           recent_items=recent_items,
                           user_profile=user_profile,
                           notifications=notifications,
                           unread_count=unread_count,
                           needs_pic=needs_pic,
                           search_query=search_query,
                           matched_users=matched_users,
                           category=category,
                           sort_by=sort_by,
                           order=order)


# ─────────────────────────────────────────────────────────────────────────────
# Live Location API
# ─────────────────────────────────────────────────────────────────────────────

@user_bp.route("/api/location/update", methods=["POST"])
@login_required
def api_location_update():
    """
    Receives the current user's GPS coordinates and stores them
    in the in-memory location store so the other party can fetch them.
    Called every ~5 s by the Live Tracking modal in the dashboard.
    """
    from datetime import datetime
    data = request.get_json(silent=True) or {}
    lat  = data.get("lat")
    lng  = data.get("lng")
    if lat is None or lng is None:
        return jsonify({"error": "lat and lng are required"}), 400

    user_id = session["user"]["id"]
    _location_store[user_id] = {
        "lat": float(lat),
        "lng": float(lng),
        "ts":  datetime.utcnow().isoformat()
    }
    return jsonify({"ok": True})


@user_bp.route("/api/location/finder")
@login_required
def api_location_finder():
    """
    Returns the live location of the person who reported the found item
    (i.e. the finder / item holder) for a given claim.

    Priority:
      1. Live GPS pushed by the finder via /api/location/update
      2. Pickup coordinates stored on the item at report time (pickup_lat/lng)
      3. Empty JSON {} — frontend shows "Waiting for holder location…"
    """
    item_id = request.args.get("item_id", type=int)
    if not item_id:
        return jsonify({}), 400

    item = get_item_by_id(item_id)
    if not item:
        return jsonify({}), 404

    finder_id   = item.get("reported_by")
    finder_user = get_user_by_id(finder_id) if finder_id else None
    finder_name = finder_user.get("full_name", "Item Holder") if finder_user else "Item Holder"

    # 1 — Live location (finder is also sharing via the map modal)
    live = _location_store.get(finder_id)
    if live:
        return jsonify({
            "lat":    live["lat"],
            "lng":    live["lng"],
            "name":   finder_name,
            "source": "live"
        })

    # 2 — Stored pickup coordinates from the item report form
    pickup_lat = item.get("pickup_lat")
    pickup_lng = item.get("pickup_lng")
    if pickup_lat and pickup_lng:
        return jsonify({
            "lat":    float(pickup_lat),
            "lng":    float(pickup_lng),
            "name":   finder_name,
            "source": "stored"
        })

    # 3 — Nothing available yet
    return jsonify({})


# ─────────────────────────────────────────────────────────────────────────────
# Notifications
# ─────────────────────────────────────────────────────────────────────────────

@user_bp.route("/notifications")
@login_required
def notifications():
    user_id = session["user"]["id"]
    notifs = get_notifications(user_id, limit=50)
    unread_count = get_unread_count(user_id)
    mark_all_read(user_id)
    return render_template("user/notifications.html",
                           notifications=notifs, unread_count=unread_count)


@user_bp.route("/notifications/mark-read", methods=["POST"])
@login_required
def mark_notifications_read():
    mark_all_read(session["user"]["id"])
    return jsonify({"ok": True})


@user_bp.route("/notifications/count")
@login_required
def notifications_count():
    count = get_unread_count(session["user"]["id"])
    return jsonify({"count": count})


@user_bp.route("/notifications/<int:notif_id>/delete", methods=["POST"])
@login_required
def delete_notification_route(notif_id):
    delete_notification(notif_id, session["user"]["id"])
    return jsonify({"ok": True})


@user_bp.route("/notifications/clear-all", methods=["POST"])
@login_required
def clear_all_notifications():
    delete_all_notifications(session["user"]["id"])
    return jsonify({"ok": True})


@user_bp.route("/delete-profile-picture", methods=["POST"])
@login_required
def delete_profile_picture():
    from models.user_model import delete_profile_picture as do_delete
    user_id = session["user"]["id"]
    do_delete(user_id)
    user_data = dict(session["user"])
    user_data["profile_picture"] = None
    user_data["profile_pic_status"] = "none"
    session["user"] = user_data
    session.modified = True
    log_activity(user_id, "deleted_profile_picture")
    flash("Profile picture removed.", "success")
    return redirect(url_for("user.profile"))




# ─────────────────────────────────────────────────────────────────────────────
# Search
# ─────────────────────────────────────────────────────────────────────────────

@user_bp.route("/search")
@login_required
def search_items():
    query     = request.args.get("q", "").strip()
    category  = request.args.get("category", "").strip()
    sort_by   = request.args.get("sort_by", "date_reported")
    order     = request.args.get("order", "desc")
    ascending = (order == "asc")
    items     = get_items_for_search()

    if query:
        items = collect_all_matches_by_name(items, query)

    if category:
        # from utils.quick_sort import sort_by_category as _sort_by_cat  # replaced by TimSort
        # DFS replaces binary-search + expand pattern for category filtering
        items = collect_all_matches_by_category(items, category)

    sort_functions = {
        "name": sort_by_name, "date_reported": sort_by_date,
        "category": sort_by_category, "status": sort_by_status
    }
    items = sort_functions.get(sort_by, sort_by_date)(items, ascending=ascending)

    # ── Count lost vs found for nav indicator (reuse already-fetched list)
    lost_count  = sum(1 for it in items if it.get("type") == "lost")
    found_count = sum(1 for it in items if it.get("type") == "found")

    # ── User search ────────────────────────────────────────────────────────
    from models.user_model import get_all_users
    matched_users = []
    if query:
        q_lower = query.lower()
        all_users = get_all_users()
        for u in all_users:
            name  = (u.get("full_name") or "").lower()
            email = (u.get("email") or "").lower()
            if q_lower in name or q_lower in email:
                matched_users.append(u)

    tab = request.args.get("tab", "items")   # "items" | "users"

    return render_template("user/search_items.html", items=items,
                           query=query, category=category,
                           sort_by=sort_by, order=order,
                           matched_users=matched_users,
                           lost_count=lost_count,
                           found_count=found_count,
                           active_tab=tab)


# ─────────────────────────────────────────────────────────────────────────────
# My Claims
# ─────────────────────────────────────────────────────────────────────────────

@user_bp.route("/my-claims")
@login_required
def my_claims():
    claims = get_claims_by_user(session["user"]["id"])
    return render_template("user/my_claims.html", claims=claims)


# ─────────────────────────────────────────────────────────────────────────────
# Match-and-Notify Helpers
# ─────────────────────────────────────────────────────────────────────────────
# MIN_MATCH_SCORE: minimum score (from find_matching_items) required before
# we bother sending a notification. Raise this to reduce noise; lower it to
# catch more borderline matches.
_MIN_MATCH_SCORE = 3


def _notify_matches_for_lost(lost_reporter_id: int, lost_item_name: str,
                              lost_item: dict) -> None:
    """
    Called right after a LOST item is created.
    Finds existing FOUND items that match and notifies the lost-item reporter
    (in-app notification + email).
    """
    from models.notification_model import add_notification
    from models.user_model import get_user_by_id
    from config import Config

    try:
        matches = find_matching_items(lost_item)
        if not matches:
            return

        reporter = get_user_by_id(lost_reporter_id)
        if not reporter:
            return

        app_base_url = Config.APP_BASE_URL or ""

        for found_item in matches:
            if found_item.get("match_score", 0) < _MIN_MATCH_SCORE:
                break  # list is sorted descending; no point continuing

            found_id   = found_item["id"]
            found_name = found_item.get("name", "an item")
            item_link  = f"/item/{found_id}"

            # In-app notification
            add_notification(
                user_id=lost_reporter_id,
                message=(
                    f"🔍 A found item \"{found_name}\" may match your lost item "
                    f"\"{lost_item_name}\". Click to view."
                ),
                notif_type="match",
                link=item_link,
            )

            # Email notification
            try:
                from utils.gmail_notify import send_match_notification
                send_match_notification(
                    recipient_email=reporter.get("email", ""),
                    recipient_name=reporter.get("full_name", ""),
                    lost_item_name=lost_item_name,
                    found_item_name=found_name,
                    found_item_id=found_id,
                    app_base_url=app_base_url,
                )
            except Exception as email_err:
                import logging
                logging.getLogger(__name__).warning(
                    "Match email skipped for lost report: %s", email_err
                )
    except Exception as err:
        import logging
        logging.getLogger(__name__).error(
            "Error in _notify_matches_for_lost: %s", err
        )


def _notify_matches_for_found(found_item_id: int, found_item_name: str,
                               found_item: dict) -> None:
    """
    Called right after a FOUND item is created.
    Finds existing LOST items that match and notifies each of their reporters
    (in-app notification + email).
    """
    from models.notification_model import add_notification
    from models.user_model import get_user_by_id
    from config import Config

    try:
        matches = find_matching_items(found_item)
        if not matches:
            return

        app_base_url = Config.APP_BASE_URL or ""
        item_link    = f"/item/{found_item_id}"

        for lost_item in matches:
            if lost_item.get("match_score", 0) < _MIN_MATCH_SCORE:
                break  # sorted descending

            lost_reporter_id = lost_item.get("reported_by")
            if not lost_reporter_id:
                continue

            lost_name = lost_item.get("name", "an item")

            # In-app notification for the person who lost this item
            add_notification(
                user_id=lost_reporter_id,
                message=(
                    f"🔍 A found item \"{found_item_name}\" may match your lost item "
                    f"\"{lost_name}\". Click to view."
                ),
                notif_type="match",
                link=item_link,
            )

            # Email notification
            try:
                reporter = get_user_by_id(lost_reporter_id)
                if reporter and reporter.get("email"):
                    from utils.gmail_notify import send_match_notification
                    send_match_notification(
                        recipient_email=reporter["email"],
                        recipient_name=reporter.get("full_name", ""),
                        lost_item_name=lost_name,
                        found_item_name=found_item_name,
                        found_item_id=found_item_id,
                        app_base_url=app_base_url,
                    )
            except Exception as email_err:
                import logging
                logging.getLogger(__name__).warning(
                    "Match email skipped for found report (lost_reporter=%s): %s",
                    lost_reporter_id, email_err,
                )
    except Exception as err:
        import logging
        logging.getLogger(__name__).error(
            "Error in _notify_matches_for_found: %s", err
        )


# ─────────────────────────────────────────────────────────────────────────────
# Report Lost Item
# ─────────────────────────────────────────────────────────────────────────────

@user_bp.route("/report-lost", methods=["GET", "POST"])
@login_required
def report_lost():
    if request.method == "GET":
        return render_template("user/report_lost.html")

    name          = request.form.get("name", "").strip()
    description   = request.form.get("description", "").strip()
    category      = request.form.get("category", "").strip()
    location      = request.form.get("location", "").strip()
    date_reported = request.form.get("date_reported", "").strip()

    if not all([name, location, date_reported]):
        flash("Item name, location, and date are required.", "error")
        return render_template("user/report_lost.html")

    # Handle optional image upload
    image_filename = None
    if "item_image" in request.files:
        file = request.files["item_image"]
        if file and file.filename and allowed_image(file.filename):
            image_filename = save_upload(file, "items")

    pickup_lat     = request.form.get("pickup_lat", "").strip() or None
    pickup_lng     = request.form.get("pickup_lng", "").strip() or None
    pickup_address = request.form.get("pickup_address", "").strip() or None
    if pickup_lat:
        try: pickup_lat = float(pickup_lat)
        except: pickup_lat = None
    if pickup_lng:
        try: pickup_lng = float(pickup_lng)
        except: pickup_lng = None

    user_id = session["user"]["id"]
    new_item_id = create_item(name=name, description=description, category=category,
                item_type="lost", location=location, date_reported=date_reported,
                reported_by=user_id, image_filename=image_filename,
                pickup_lat=pickup_lat, pickup_lng=pickup_lng,
                pickup_address=pickup_address)

    log_activity(user_id, "reported_lost", f"Item: {name}")

    # ── Match-and-notify: check if any existing FOUND items match this lost report ──
    _notify_matches_for_lost(
        lost_reporter_id=user_id,
        lost_item_name=name,
        lost_item={"name": name, "description": description,
                   "category": category, "type": "lost"},
    )

    flash("Your lost item report has been submitted.", "success")
    return redirect(url_for("user.dashboard"))


# ─────────────────────────────────────────────────────────────────────────────
# Report Found Item
# ─────────────────────────────────────────────────────────────────────────────

@user_bp.route("/report-found", methods=["GET", "POST"])
@login_required
def report_found():
    if request.method == "GET":
        return render_template("user/report_found.html")

    name          = request.form.get("name", "").strip()
    description   = request.form.get("description", "").strip()
    category      = request.form.get("category", "").strip()
    location      = request.form.get("location", "").strip()
    time_found    = request.form.get("time_found", "").strip()
    date_reported = request.form.get("date_reported", "").strip()

    if not all([name, location, date_reported]):
        flash("Item name, location, and date are required.", "error")
        return render_template("user/report_found.html")

    image_filename = None
    if "item_image" in request.files:
        file = request.files["item_image"]
        if file and file.filename and allowed_image(file.filename):
            image_filename = save_upload(file, "items")

    pickup_lat     = request.form.get("pickup_lat", "").strip() or None
    pickup_lng     = request.form.get("pickup_lng", "").strip() or None
    pickup_address = request.form.get("pickup_address", "").strip() or None
    if pickup_lat:
        try: pickup_lat = float(pickup_lat)
        except: pickup_lat = None
    if pickup_lng:
        try: pickup_lng = float(pickup_lng)
        except: pickup_lng = None

    user_id = session["user"]["id"]
    new_found_id = create_item(name=name, description=description, category=category,
                item_type="found", location=location, date_reported=date_reported,
                reported_by=user_id, time_found=time_found,
                image_filename=image_filename,
                pickup_lat=pickup_lat, pickup_lng=pickup_lng,
                pickup_address=pickup_address)

    log_activity(user_id, "reported_found", f"Item: {name}")

    # ── Match-and-notify: alert owners of matching LOST items ──
    _notify_matches_for_found(
        found_item_id=new_found_id,
        found_item_name=name,
        found_item={"name": name, "description": description,
                    "category": category, "type": "found"},
    )

    flash("Your found item report has been submitted for admin review.", "success")
    return redirect(url_for("user.dashboard"))


# ─────────────────────────────────────────────────────────────────────────────
# Claim Item
# ─────────────────────────────────────────────────────────────────────────────

@user_bp.route("/edit-item/<int:item_id>", methods=["POST"])
@login_required
def edit_item(item_id):
    """Allow the item owner to edit their lost/found report."""
    item = get_item_by_id(item_id)
    user_id = session["user"]["id"]

    if not item:
        flash("Item not found.", "error")
        return redirect(url_for("user.profile"))

    if item["reported_by"] != user_id:
        flash("You can only edit your own reports.", "error")
        return redirect(url_for("user.profile"))

    name          = request.form.get("name", "").strip()
    description   = request.form.get("description", "").strip()
    category      = request.form.get("category", "").strip()
    item_type     = request.form.get("item_type", item["type"]).strip()
    location      = request.form.get("location", "").strip()
    date_reported = request.form.get("date_reported", "").strip()

    if not all([name, location, date_reported]):
        flash("Item name, location, and date are required.", "error")
        return redirect(url_for("user.profile"))

    # Handle optional new image upload
    image_filename = None
    if "item_image" in request.files:
        file = request.files["item_image"]
        if file and file.filename and allowed_image(file.filename):
            image_filename = save_upload(file, "items")

    update_item(item_id, name=name, description=description, category=category,
                item_type=item_type, location=location, date_reported=date_reported,
                image_filename=image_filename)

    log_activity(user_id, "edited_item", f"Item ID: {item_id}, Name: {name}")
    flash("Your item report has been updated.", "success")
    return redirect(url_for("user.profile"))


@user_bp.route("/claim/<int:item_id>", methods=["GET", "POST"])
@login_required
def claim_item(item_id):
    item = get_item_by_id(item_id)
    if not item or item["status"] != "listed":
        flash("This item is no longer available for claiming.", "error")
        return redirect(url_for("user.search_items"))

    if request.method == "GET":
        return render_template("user/claim_item.html", item=item)

    student_id_text = request.form.get("student_id_text", "").strip()
    full_name_text  = request.form.get("full_name_text", "").strip()
    last_location   = request.form.get("last_location", "").strip()

    if not all([student_id_text, full_name_text, last_location]):
        flash("All fields are required to submit a claim.", "error")
        return render_template("user/claim_item.html", item=item)

    user_id = session["user"]["id"]
    claim_id = create_claim(item_id=item_id, claimant_id=user_id,
                            student_id_text=student_id_text,
                            full_name_text=full_name_text,
                            last_location=last_location)

    log_activity(user_id, "submitted_claim", f"Item ID: {item_id}, Claim ID: {claim_id}")

    # Notify the claimant — now waiting for finder to respond
    add_notification(
        user_id=user_id,
        message=f"📋 Your claim for '{item.get('name', 'an item')}' has been submitted. Waiting for the finder to accept or reject it.",
        notif_type="info",
        link="/user/my-claims"
    )

    # Notify the finder — they must accept or reject
    reporter_id = item.get("reported_by")
    if reporter_id and reporter_id != user_id:
        add_notification(
            user_id=reporter_id,
            message=f"📬 Someone is claiming your found item '{item.get('name', 'an item')}'. Review their details and accept or reject the claim.",
            notif_type="info",
            link=f"/user/finder-claims"
        )
        try:
            from models.user_model import get_user_by_id as _get_user
            from utils.gmail_notify import send_claim_notification
            import os as _os
            reporter = _get_user(reporter_id)
            if reporter and reporter.get("email"):
                send_claim_notification(
                    recipient_email=reporter["email"],
                    recipient_name=reporter["full_name"].split()[0],
                    claimant_name=session["user"]["full_name"],
                    item_name=item.get("name", "your item"),
                    item_link=f"/user/finder-claims",
                    app_base_url=_os.environ.get("APP_BASE_URL", "")
                )
        except Exception:
            pass

    flash(f"📋 Your claim for '{item.get('name', 'this item')}' has been submitted! The finder will review and accept or reject it.", "success")
    return redirect(url_for("user.my_claims"))



# ─────────────────────────────────────────────────────────────────────────────
# Report a User or Item (joke / fake / abuse)
# ─────────────────────────────────────────────────────────────────────────────

@user_bp.route("/report", methods=["POST"])
@login_required
def submit_report():
    from models.report_model import create_report
    reporter_id      = session["user"]["id"]
    reported_user_id = request.form.get("reported_user_id", type=int)
    reported_item_id = request.form.get("reported_item_id", type=int)
    reason           = request.form.get("reason", "").strip()
    details          = request.form.get("details", "").strip()

    if not reason:
        flash("Please select a reason for your report.", "error")
        return redirect(request.referrer or url_for("user.dashboard"))

    if not reported_user_id and not reported_item_id:
        flash("Invalid report target.", "error")
        return redirect(request.referrer or url_for("user.dashboard"))

    create_report(
        reporter_id=reporter_id,
        reason=reason,
        details=details,
        reported_user_id=reported_user_id,
        reported_item_id=reported_item_id,
    )
    log_activity(reporter_id, "submitted_report",
                 f"user:{reported_user_id} item:{reported_item_id} reason:{reason}")
    flash("✅ Your report has been submitted. The admin will review it shortly.", "success")
    return redirect(request.referrer or url_for("user.dashboard"))


# ─────────────────────────────────────────────────────────────────────────────
# Confirm Claim Received
# ─────────────────────────────────────────────────────────────────────────────

@user_bp.route("/claims/<int:claim_id>/confirm", methods=["POST"])
@login_required
def confirm_claim(claim_id):
    from models.claim_model import confirm_claim_by_user, get_claim_by_id
    user_id = session["user"]["id"]
    claim = get_claim_by_id(claim_id)
    if not claim or claim["claimant_id"] != user_id:
        flash("Claim not found.", "error")
        return redirect(url_for("user.my_claims"))
    success = confirm_claim_by_user(claim_id, user_id)
    if success:
        log_activity(user_id, "confirmed_claim", f"Claim ID: {claim_id}")
        add_notification(
            user_id=user_id,
            message=f"✅ You confirmed receiving '{claim['item_name']}'. Thank you!",
            notif_type="success",
            link="/user/my-claims"
        )
        # Notify admin
        from models.user_model import get_user_by_email
        admin = get_user_by_email("admin@nemsu.edu.ph")
        if admin:
            add_notification(
                user_id=admin["id"],
                message=f"✅ {session['user']['full_name']} confirmed receiving '{claim['item_name']}'.",
                notif_type="success",
                link="/admin/claims"
            )
        flash("✅ You have confirmed receiving the item. Thank you!", "success")
    else:
        flash("Could not confirm. Make sure your claim is approved first.", "error")
    return redirect(url_for("user.my_claims"))


# ─────────────────────────────────────────────────────────────────────────────
# Online Heartbeat (AJAX)
# ─────────────────────────────────────────────────────────────────────────────

@user_bp.route("/heartbeat", methods=["POST"])
@login_required
def heartbeat():
    from models.user_model import set_user_online, update_last_active
    user_id = session["user"]["id"]
    set_user_online(user_id, True)
    update_last_active(user_id)
    return jsonify({"ok": True})


@user_bp.route("/offline", methods=["POST"])
def go_offline():
    if "user" in session:
        from models.user_model import set_user_online
        set_user_online(session["user"]["id"], False)
    return jsonify({"ok": True})


# ─────────────────────────────────────────────────────────────────────────────
# User online status check (for chat)
# ─────────────────────────────────────────────────────────────────────────────

@user_bp.route("/status/<int:user_id>")
@login_required
def user_status(user_id):
    from models.user_model import get_user_by_id
    from datetime import datetime, timedelta
    u = get_user_by_id(user_id)
    if not u:
        return jsonify({"online": False})
    last = u.get("last_active", "")
    try:
        last_dt = datetime.strptime(last, "%Y-%m-%d %H:%M:%S")
        online = datetime.utcnow() - last_dt < timedelta(minutes=2)
    except Exception:
        online = False
    return jsonify({"online": online, "is_online": bool(u.get("is_online"))})

# ─────────────────────────────────────────────────────────────────────────────
# Finder Claim Review — the person who found the item sees all claims and
# can accept or reject each one. On accept → chat is opened automatically.
# ─────────────────────────────────────────────────────────────────────────────

@user_bp.route("/finder-claims")
@login_required
def finder_claims():
    """Show all claims for items the current user reported as found."""
    user_id = session["user"]["id"]
    claims  = get_claims_for_finder(user_id)
    return render_template("user/finder_claims.html", claims=claims)


@user_bp.route("/finder-claims/<int:claim_id>/respond", methods=["POST"])
@login_required
def finder_respond_claim(claim_id):
    """Finder accepts or rejects a claim. On accept, open a chat conversation."""
    user_id = session["user"]["id"]
    action  = request.form.get("action")  # 'accepted' or 'rejected'

    if action not in ("accepted", "rejected"):
        flash("Invalid action.", "error")
        return redirect(url_for("user.finder_claims"))

    claim = finder_respond_to_claim(claim_id, finder_id=user_id, action=action)
    if not claim:
        flash("Claim not found or you are not authorised to respond.", "error")
        return redirect(url_for("user.finder_claims"))

    item_name    = claim.get("item_name", "the item")
    claimant_id  = claim["claimant_id"]
    item_id      = claim["item_id"]

    if action == "accepted":
        # Mark the item as claimed
        from models.item_model import update_item_status
        update_item_status(item_id, status="claimed", approved_by=user_id)

        # Open/get a chat conversation between finder and claimant
        from models.chat_model import get_or_create_conversation, send_message
        conv = get_or_create_conversation(user_id, claimant_id, item_id=item_id)

        # Send an automatic opening message from the finder
        finder_name = session["user"]["full_name"]
        send_message(
            conv_id=conv["id"],
            sender_id=user_id,
            content=(
                f"👋 Hi! I've accepted your claim for \"{item_name}\". "
                f"Let's arrange the handover. When and where would you like to meet? "
                f"Please suggest a venue or I'll propose one."
            )
        )

        log_activity(user_id, "accepted_claim", f"Claim ID: {claim_id}, Item ID: {item_id}")

        # Notify claimant
        add_notification(
            user_id=claimant_id,
            message=f"✅ The finder accepted your claim for '{item_name}'! Open the chat to set your meetup venue.",
            notif_type="success",
            link=f"/chat/{conv['id']}"
        )

        flash(f"✅ You accepted the claim for '{item_name}'. A chat has been opened to coordinate the handover.", "success")
        return redirect(url_for("chat.conversation", conv_id=conv["id"]))

    else:  # rejected
        log_activity(user_id, "rejected_claim", f"Claim ID: {claim_id}, Item ID: {item_id}")

        add_notification(
            user_id=claimant_id,
            message=f"❌ The finder rejected your claim for '{item_name}'. You may contact admin for assistance.",
            notif_type="error",
            link="/user/my-claims"
        )

        flash(f"❌ You rejected the claim for '{item_name}'. The claimant has been notified.", "warning")
        return redirect(url_for("user.finder_claims"))