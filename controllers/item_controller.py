"""
controllers/item_controller.py - Shared Item Routes
====================================================
Handles item detail views accessible to both students and admins.
Provides shared API-style endpoints used across both dashboards.

Routes:
    GET /items/<item_id>  → View full details of a specific item
"""

from flask import (Blueprint, render_template, redirect, url_for,
                   session, request, flash, jsonify)
from models.item_model import get_item_by_id, create_item
from models.user_model import get_user_by_id
from models.chat_model import get_or_create_conversation
from models.notification_model import add_notification

item_bp = Blueprint("item", __name__, url_prefix="/items")


@item_bp.route("/<int:item_id>")
def item_detail(item_id: int):
    """
    Renders the full detail page for a specific item.
    Accessible to both authenticated students and admins.
    Unauthenticated users are redirected to the login page.

    Loads:
        - Full item record from the database.
        - Reporter's name (the student who submitted the report).

    Args:
        item_id (int): The database ID of the item to display.

    Returns:
        Response: Rendered item detail page, or redirect to login/search
                  if the item does not exist or access is unauthorized.
    """
    # Require authentication to view item details
    if "user" not in session:
        return redirect(url_for("auth.login"))

    # Fetch the item from the database
    item = get_item_by_id(item_id)

    if not item:
        # Item does not exist — redirect to search with an appropriate signal
        return redirect(url_for("user.search_items"))

    # Load the name of the student who reported this item (for display)
    reporter = None
    if item.get("reported_by"):
        reporter = get_user_by_id(item["reported_by"])

    return render_template("item_detail.html", item=item, reporter=reporter)


# ─────────────────────────────────────────────────────────────────────────────
# "I Found This!" flow — submitted from the modal on a LOST item's detail page
# ─────────────────────────────────────────────────────────────────────────────

@item_bp.route("/<int:item_id>/i-found-it", methods=["POST"])
def i_found_it(item_id: int):
    """
    Called when a finder fills out the 'I Found This!' modal on a lost item.
    Steps:
      1. Validate the finder is logged in and is not the item owner.
      2. Create a new 'found' item entry with the details they provided.
      3. Open (or resume) a chat between the finder and the lost-item owner,
         linking the LOST item so the owner sees the card and can mark it found.
      4. Send the owner an in-app notification.
      5. Redirect the finder straight to that conversation.
    """
    if "user" not in session:
        return redirect(url_for("auth.login"))

    lost_item = get_item_by_id(item_id)
    if not lost_item or lost_item.get("type") != "lost":
        flash("Item not found.", "error")
        return redirect(url_for("user.dashboard"))

    finder_id = session["user"]["id"]
    owner_id  = lost_item.get("reported_by")

    if finder_id == owner_id:
        flash("You cannot report finding your own item.", "warning")
        return redirect(url_for("item.item_detail", item_id=item_id))

    # ── Collect form data ────────────────────────────────────────────────────
    name          = request.form.get("name", "").strip()
    description   = request.form.get("description", "").strip()
    category      = request.form.get("category", "").strip()
    location      = request.form.get("location", "").strip()
    date_reported = request.form.get("date_reported", "").strip()
    time_found    = request.form.get("time_found", "").strip()

    if not all([name, location, date_reported]):
        flash("Item name, location where found, and date are required.", "error")
        return redirect(url_for("item.item_detail", item_id=item_id))

    # ── Optional image ───────────────────────────────────────────────────────
    image_filename = None
    if "item_image" in request.files:
        file = request.files["item_image"]
        if file and file.filename:
            ALLOWED = {"png", "jpg", "jpeg", "gif", "webp"}
            ext = file.filename.rsplit(".", 1)[-1].lower() if "." in file.filename else ""
            if ext in ALLOWED:
                try:
                    from utils.imgbb import upload_file_to_imgbb
                    image_filename = upload_file_to_imgbb(file) or None
                except Exception:
                    pass  # image optional — don't block the flow

    # ── Optional map coords ──────────────────────────────────────────────────
    pickup_lat     = request.form.get("pickup_lat", "").strip() or None
    pickup_lng     = request.form.get("pickup_lng", "").strip() or None
    pickup_address = request.form.get("pickup_address", "").strip() or None
    try:
        if pickup_lat: pickup_lat = float(pickup_lat)
    except Exception:
        pickup_lat = None
    try:
        if pickup_lng: pickup_lng = float(pickup_lng)
    except Exception:
        pickup_lng = None

    # ── Create the found-item report ─────────────────────────────────────────
    create_item(
        name=name,
        description=description,
        category=category or lost_item.get("category", ""),
        item_type="found",
        location=location,
        date_reported=date_reported,
        reported_by=finder_id,
        time_found=time_found,
        image_filename=image_filename,
        pickup_lat=pickup_lat,
        pickup_lng=pickup_lng,
        pickup_address=pickup_address,
    )

    # ── Open chat linked to the LOST item ────────────────────────────────────
    conv = get_or_create_conversation(finder_id, owner_id, item_id=item_id)

    # ── Notify the owner ─────────────────────────────────────────────────────
    finder_name  = session["user"]["full_name"].split()[0]
    lost_name    = lost_item.get("name", "your item")
    add_notification(
        user_id=owner_id,
        message=(
            f"🎉 {finder_name} says they found '{lost_name}'! "
            f"Open the chat to coordinate the return."
        ),
        notif_type="success",
        link=f"/chat/{conv['id']}",
    )

    flash(
        f"✅ Thank you! We've opened a chat with the owner of '{lost_name}' "
        f"so you can coordinate returning it.",
        "success",
    )
    return redirect(url_for("chat.conversation", conv_id=conv["id"]))
