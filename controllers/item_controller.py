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
from models.item_model import get_item_by_id, update_item_status
from models.user_model import get_user_by_id
from models.chat_model import get_or_create_conversation, send_message, get_messages
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
    Finder clicks 'I Found This!' on a lost item.
    Opens a private chat with the item owner and sends a greeting.
    Does NOT create any public item post.
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

    # ── Open (or resume) chat — linked to the lost item ──────────────────────
    conv = get_or_create_conversation(finder_id, owner_id, item_id=item_id)

    # ── Only send the auto-messages if this is a brand-new conversation ───────
    existing = get_messages(conv["id"], limit=5)
    if not existing:
        finder_name = session["user"]["full_name"].split()[0]
        send_message(
            conv["id"], finder_id,
            content=f"Hi! 👋 I'm {finder_name}. I think I found your lost item — I can help return it to you!"
        )
        send_message(
            conv["id"], finder_id,
            content="📦 Here's the item I found:",
            msg_type="item_card",
            ref_item_id=item_id,
        )

    # ── Notify owner (only once) ──────────────────────────────────────────────
    if not existing:
        finder_name = session["user"]["full_name"].split()[0]
        lost_name   = lost_item.get("name", "your item")
        add_notification(
            user_id=owner_id,
            message=(
                f"🎉 {finder_name} says they found '{lost_name}'! "
                f"Open the chat to coordinate the return."
            ),
            notif_type="success",
            link=f"/chat/{conv['id']}",
        )

    return redirect(url_for("chat.conversation", conv_id=conv["id"]))


# ─────────────────────────────────────────────────────────────────────────────
# Owner updates their lost item status directly from item detail page
# ─────────────────────────────────────────────────────────────────────────────

@item_bp.route("/<int:item_id>/owner-status", methods=["POST"])
def owner_update_status(item_id: int):
    """Item owner marks their own lost item as returned/claimed/listed."""
    if "user" not in session:
        return jsonify({"ok": False, "error": "Not logged in"}), 401

    item = get_item_by_id(item_id)
    if not item:
        return jsonify({"ok": False, "error": "Item not found"}), 404
    if item.get("reported_by") != session["user"]["id"]:
        return jsonify({"ok": False, "error": "Not your item"}), 403

    data       = request.get_json(silent=True) or {}
    new_status = data.get("status")
    if new_status not in ("listed", "claimed", "returned"):
        return jsonify({"ok": False, "error": "Invalid status"}), 400

    if new_status == "returned":
        from models.item_model import mark_item_returned
        mark_item_returned(item_id, found_by_user_id=None)
    else:
        update_item_status(item_id, new_status)

    return jsonify({"ok": True, "status": new_status})
