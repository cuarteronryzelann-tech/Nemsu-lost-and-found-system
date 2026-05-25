"""
controllers/chat_controller.py - Messaging / Chat Routes
=========================================================
Handles user-to-user and user-to-admin chat.
All chat routes are under /chat/

Changes from original:
  - Added Gmail email notification when a new message is sent (send route).
    Uses utils/gmail_notify.py → requires GMAIL_SENDER_EMAIL + GMAIL_APP_PASSWORD
    environment variables. Notification is non-blocking: a failure is logged
    but never surfaces to the user.
"""

from flask import (Blueprint, render_template, redirect, url_for,
                   session, request, flash, jsonify)
from functools import wraps
from models.chat_model import (
    get_or_create_conversation, get_conversation_by_id,
    get_user_conversations, get_messages, get_messages_since, send_message,
    mark_messages_read, get_total_unread, get_all_conversations_admin,
    delete_message
)
from models.user_model import get_user_by_id, get_all_users
from models.item_model import get_item_by_id, update_item_status, mark_item_returned, _item_by_id_cache
from models.notification_model import add_notification
from utils.gmail_notify import send_chat_notification
import os
import logging

logger = logging.getLogger(__name__)

chat_bp = Blueprint("chat", __name__, url_prefix="/chat")


def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if "user" not in session:
            return redirect(url_for("auth.login"))
        return f(*args, **kwargs)
    return decorated


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
# Inbox — list all conversations
# ─────────────────────────────────────────────────────────────────────────────

@chat_bp.route("/")
@login_required
def inbox():
    user_id = session["user"]["id"]
    conversations = get_user_conversations(user_id)
    total_unread = get_total_unread(user_id)
    return render_template("chat/inbox.html",
                           conversations=conversations,
                           total_unread=total_unread)


# ─────────────────────────────────────────────────────────────────────────────
# Start or open a conversation with a specific user
# ─────────────────────────────────────────────────────────────────────────────

@chat_bp.route("/start/<int:other_user_id>")
@login_required
def start_conversation(other_user_id):
    """Start or resume a conversation with another user."""
    user_id = session["user"]["id"]

    if user_id == other_user_id:
        flash("You can't chat with yourself.", "warning")
        return redirect(url_for("chat.inbox"))

    other_user = get_user_by_id(other_user_id)
    if not other_user:
        flash("User not found.", "error")
        return redirect(url_for("chat.inbox"))

    item_id = request.args.get("item_id", type=int)
    conv = get_or_create_conversation(user_id, other_user_id, item_id=item_id)
    return redirect(url_for("chat.conversation", conv_id=conv["id"]))


# ─────────────────────────────────────────────────────────────────────────────
# Conversation view
# ─────────────────────────────────────────────────────────────────────────────

@chat_bp.route("/<int:conv_id>")
@login_required
def conversation(conv_id):
    user_id = session["user"]["id"]
    conv = get_conversation_by_id(conv_id)

    if not conv:
        flash("Conversation not found.", "error")
        return redirect(url_for("chat.inbox"))

    # Access check — only participants can view
    if conv["user1_id"] != user_id and conv["user2_id"] != user_id:
        flash("Access denied.", "error")
        return redirect(url_for("chat.inbox"))

    other_id = conv["user2_id"] if conv["user1_id"] == user_id else conv["user1_id"]
    other_user = get_user_by_id(other_id)
    messages = get_messages(conv_id)
    mark_messages_read(conv_id, user_id)
    conversations = get_user_conversations(user_id)

    # Fetch linked item if any
    linked_item = get_item_by_id(conv["item_id"]) if conv.get("item_id") else None

    # Pre-load item data for item_card messages so the template can render them
    item_card_items = {}
    for msg in messages:
        if msg.get("msg_type") == "item_card" and msg.get("ref_item_id"):
            rid = msg["ref_item_id"]
            if rid not in item_card_items:
                item_card_items[rid] = get_item_by_id(rid)

    return render_template("chat/conversation.html",
                           conv=conv,
                           other_user=other_user,
                           messages=messages,
                           conversations=conversations,
                           current_user_id=user_id,
                           linked_item=linked_item,
                           item_card_items=item_card_items)


from werkzeug.utils import secure_filename
import uuid

# Use same logic as save_upload() in user_controller:
# - PRODUCTION/VERCEL → /tmp/uploads/chat  (served by _serve_upload in app.py)
# - Local             → static/uploads/chat (served by Flask's static handler)
def _chat_upload_folder():
    if os.environ.get("PRODUCTION") or os.environ.get("VERCEL"):
        return "/tmp/uploads/chat"
    import os as _os
    from flask import current_app
    folder = _os.path.join(current_app.root_path, "static", "uploads", "chat")
    return folder

# Eagerly create upload folders at module load so they always exist.
# On Vercel/production: /tmp/uploads/chat  (ephemeral, writable)
# Locally: static/uploads/chat
_local_chat_folder = os.path.join("static", "uploads", "chat")
os.makedirs(_local_chat_folder, exist_ok=True)
os.makedirs("/tmp/uploads/chat", exist_ok=True)  # always safe to create

@chat_bp.route("/<int:conv_id>/send", methods=["POST"])
@login_required
def send(conv_id):
    user_id = session["user"]["id"]
    conv = get_conversation_by_id(conv_id)

    if not conv:
        return jsonify({"ok": False, "error": "Conversation not found"}), 404

    if conv["user1_id"] != user_id and conv["user2_id"] != user_id:
        return jsonify({"ok": False, "error": "Access denied"}), 403

    # ✅ NEW: support JSON + FormData
    if request.content_type and "multipart/form-data" in request.content_type:
        content = (request.form.get("content") or "").strip()
        file = request.files.get("image")
    else:
        data = request.get_json(silent=True) or {}
        content = (data.get("content") or "").strip()
        file = None

    # ✅ Allow image-only messages
    if not content and not file:
        return jsonify({"ok": False, "error": "Message cannot be empty"}), 400

    if content and len(content) > 1000:
        content = content[:1000]

    # Handle image upload via ImgBB — uses utils/imgbb (matches NEMSU Marketplace).
    filename = None
    if file and file.filename:
        from utils.imgbb import upload_file_to_imgbb
        filename = upload_file_to_imgbb(file)
        if not filename:
            return jsonify({"ok": False, "error": "Image upload failed. Please try again."}), 500

        # ✅ UPDATED: pass filename
    msg = send_message(conv_id, user_id, content, filename)

    # ── In-app notification (UNCHANGED) ─────────────────────────────
    other_id = conv["user2_id"] if conv["user1_id"] == user_id else conv["user1_id"]
    sender_name = session["user"]["full_name"].split()[0]
    preview = (content[:60] + ("…" if len(content) > 60 else "")) if content else "📷 Image"

    add_notification(
        user_id=other_id,
        message=f"💬 New message from {sender_name}: {preview}",
        notif_type="info",
        link=f"/chat/{conv_id}"
    )

    # ── Gmail notification (UNCHANGED) ─────────────────────────────
    try:
        from datetime import datetime, timedelta
        other_user = get_user_by_id(other_id)
        if other_user and other_user.get("email"):
            last_active = other_user.get("last_active", "")
            is_online = False
            try:
                last_dt = datetime.strptime(last_active, "%Y-%m-%d %H:%M:%S")
                is_online = datetime.utcnow() - last_dt < timedelta(minutes=2)
            except Exception:
                pass

            if other_user.get("is_online"):
                is_online = True

            if not is_online:
                app_base_url = os.environ.get("APP_BASE_URL", "")
                send_chat_notification(
                    recipient_email=other_user["email"],
                    recipient_name=other_user["full_name"].split()[0],
                    sender_name=session["user"]["full_name"],
                    message_preview=preview,
                    conv_link=f"/chat/{conv_id}",
                    app_base_url=app_base_url
                )
    except Exception as exc:
        logger.error("Gmail notification error in send route: %s", exc)

    # ✅ RETURN IMAGE TOO
    return jsonify({
        "ok": True,
        "message": {
            "id":          msg["id"],
            "content":     msg["content"],
            "image":       filename,
            "sender_id":   msg["sender_id"],
            "sender_name": msg["sender_name"],
            "sender_pic":  msg.get("sender_pic", ""),
            "created_at":  msg["created_at"],
            "is_mine":     True,
            "msg_type":    msg.get("msg_type", "text"),
            "ref_item_id": msg.get("ref_item_id"),
            "item_card":   None,
        }
    })
# ─────────────────────────────────────────────────────────────────────────────
# Poll for new messages (AJAX GET)
# ─────────────────────────────────────────────────────────────────────────────

@chat_bp.route("/<int:conv_id>/poll")
@login_required
def poll(conv_id):
    try:
        return _poll_impl(conv_id)
    except Exception as _e:
        logger.warning("poll DB error (overload?): %s", _e)
        return jsonify({"ok": True, "messages": [], "other_online": False,
                        "other_typing": False, "seen_ids": []}), 200

def _poll_impl(conv_id):
    user_id = session["user"]["id"]
    conv = get_conversation_by_id(conv_id)

    if not conv or (conv["user1_id"] != user_id and conv["user2_id"] != user_id):
        return jsonify({"ok": True, "messages": [], "error": "not_participant"}), 200

    since_id = request.args.get("since", 0, type=int)
    new_msgs = get_messages_since(conv_id, since_id)
    mark_messages_read(conv_id, user_id)

    # Other user's online status (active in last 2 min)
    # Cache the user lookup for 10 s to avoid a DB hit on every poll tick
    other_id = conv["user2_id"] if conv["user1_id"] == user_id else conv["user1_id"]
    import time as _t
    _now = _t.time()
    _cache_key = f"poll_user_{other_id}"
    if not hasattr(_poll_impl, "_user_cache"):
        _poll_impl._user_cache = {}
    _cached = _poll_impl._user_cache.get(_cache_key)
    if _cached and (_now - _cached[1]) < 10:
        other_user = _cached[0]
    else:
        other_user = get_user_by_id(other_id)
        _poll_impl._user_cache[_cache_key] = (other_user, _now)
    other_online = False
    try:
        from datetime import datetime, timedelta
        last_active = (other_user or {}).get("last_active", "")
        if last_active:
            last_dt = datetime.strptime(last_active, "%Y-%m-%d %H:%M:%S")
            other_online = datetime.utcnow() - last_dt < timedelta(minutes=2)
    except Exception:
        pass

    # seen_ids — messages we sent that the other user has now read
    seen_ids = [m["id"] for m in new_msgs if m["sender_id"] == user_id and m.get("is_read")]

    # Pre-load item data for any item_card messages in this batch
    item_cards = {}
    for m in new_msgs:
        if m.get("msg_type") == "item_card" and m.get("ref_item_id"):
            rid = m["ref_item_id"]
            if rid not in item_cards:
                item_cards[rid] = get_item_by_id(rid)

    def _item_card_data(rid):
        item = item_cards.get(rid)
        if not item:
            return None
        return {
            "id":             item["id"],
            "name":           item.get("name", ""),
            "type":           item.get("type", ""),
            "status":         item.get("status", ""),
            "category":       item.get("category", ""),
            "location":       item.get("location", ""),
            "date_reported":  item.get("date_reported", ""),
            "image_filename": item.get("image_filename", ""),
            "url":            f"/items/{item['id']}",
        }

    return jsonify({
        "ok": True,
        "other_online": other_online,
        "other_typing": False,
        "seen_ids": seen_ids,
        "messages": [
            {
                "id":          m["id"],
                "content":     m["content"],
                "image":       (m["image_filename"] if m.get("image_filename") and m["image_filename"].startswith("http") else ""),
                "sender_id":   m["sender_id"],
                "sender_name": m["sender_name"],
                "sender_pic":  m.get("sender_pic", ""),
                "created_at":  m["created_at"],
                "is_mine":     m["sender_id"] == user_id,
                "is_deleted":  bool(m.get("is_deleted")),
                "msg_type":    m.get("msg_type", "text"),
                "ref_item_id": m.get("ref_item_id"),
                "item_card":   _item_card_data(m["ref_item_id"]) if m.get("msg_type") == "item_card" and m.get("ref_item_id") else None,
            } for m in new_msgs
        ]
    })


# ─────────────────────────────────────────────────────────────────────────────
# Unread count (AJAX) — returns 401 when not logged in so JS stops polling
# ─────────────────────────────────────────────────────────────────────────────

@chat_bp.route("/unread-count")
def unread_count():
    if "user" not in session:
        return jsonify({"error": "unauthenticated"}), 401
    try:
        count = get_total_unread(session["user"]["id"])
    except Exception:
        count = 0  # DB overloaded — return 0 silently, client retries on next poll
    return jsonify({"count": count})


# ─────────────────────────────────────────────────────────────────────────────
# Admin: Contact a user (start conversation from admin panel)
# ─────────────────────────────────────────────────────────────────────────────

@chat_bp.route("/admin/start/<int:user_id>")
@admin_required
def admin_start_conversation(user_id):
    admin_id = session["user"]["id"]
    user = get_user_by_id(user_id)
    if not user:
        flash("User not found.", "error")
        return redirect(url_for("admin.manage_users"))

    conv = get_or_create_conversation(admin_id, user_id)
    return redirect(url_for("chat.conversation", conv_id=conv["id"]))


# ─────────────────────────────────────────────────────────────────────────────
# Contact Admin (user side — creates or resumes convo with admin)
# ─────────────────────────────────────────────────────────────────────────────

@chat_bp.route("/contact-admin")
@login_required
def contact_admin():
    from models.user_model import get_user_by_email
    from config import Config
    admin = get_user_by_email("admin@nemsu.edu.ph")
    if not admin:
        flash("Admin account not found.", "error")
        return redirect(url_for("chat.inbox"))

    user_id = session["user"]["id"]
    conv = get_or_create_conversation(user_id, admin["id"])
    return redirect(url_for("chat.conversation", conv_id=conv["id"]))

# ─────────────────────────────────────────────────────────────────────────────
# Delete a message (sender only)
# ─────────────────────────────────────────────────────────────────────────────

@chat_bp.route("/<int:conv_id>/delete/<int:msg_id>", methods=["DELETE"])
@login_required
def delete_msg(conv_id, msg_id):
    user_id = session["user"]["id"]
    conv = get_conversation_by_id(conv_id)

    if not conv:
        return jsonify({"ok": False, "error": "Conversation not found"}), 404

    if conv["user1_id"] != user_id and conv["user2_id"] != user_id:
        return jsonify({"ok": False, "error": "Access denied"}), 403

    success = delete_message(msg_id, user_id)
    if success:
        return jsonify({"ok": True})
    return jsonify({"ok": False, "error": "Message not found or not yours"}), 403

# ─────────────────────────────────────────────────────────────────────────────
# Update item status from chat (owner only)
# ─────────────────────────────────────────────────────────────────────────────

@chat_bp.route("/<int:conv_id>/item-status", methods=["POST"])
@login_required
def update_item_status_from_chat(conv_id):
    user_id = session["user"]["id"]
    conv = get_conversation_by_id(conv_id)

    if not conv:
        return jsonify({"ok": False, "error": "Conversation not found"}), 404
    if conv["user1_id"] != user_id and conv["user2_id"] != user_id:
        return jsonify({"ok": False, "error": "Access denied"}), 403
    if not conv.get("item_id"):
        return jsonify({"ok": False, "error": "No item linked"}), 400

    item = get_item_by_id(conv["item_id"])
    if not item:
        return jsonify({"ok": False, "error": "Item not found"}), 404

    is_owner = item["reported_by"] == user_id
    other_id = conv["user2_id"] if conv["user1_id"] == user_id else conv["user1_id"]

    data = request.get_json(silent=True) or {}
    new_status = data.get("status")

    # Non-owner (claimant) can only set status to "claimed" or revert to "listed"
    if not is_owner:
        if new_status not in ("claimed", "listed"):
            return jsonify({"ok": False, "error": "You can only claim or unmark this item"}), 403
    else:
        if new_status not in ("listed", "claimed", "returned"):
            return jsonify({"ok": False, "error": "Invalid status"}), 400

    if new_status == "returned":
        # Record who helped return it (the other participant in the chat)
        mark_item_returned(conv["item_id"], found_by_user_id=other_id)

        # Notify the other user
        item_name = item.get("name", "the item")
        add_notification(
            user_id=other_id,
            message=f"🎉 '{item_name}' has been marked as found! Thank you for helping.",
            notif_type="success",
            link=f"/chat/{conv_id}"
        )
    elif new_status == "claimed":
        update_item_status(conv["item_id"], new_status)
        # Notify the item owner that someone has claimed it
        if not is_owner:
            item_name = item.get("name", "the item")
            add_notification(
                user_id=other_id,
                message=f"📦 '{item_name}' has been claimed by someone. Check your chat!",
                notif_type="info",
                link=f"/chat/{conv_id}"
            )
    else:
        update_item_status(conv["item_id"], new_status)

    # Bust the item cache so next fetch sees the new status
    _item_by_id_cache.pop(conv["item_id"], None)

    return jsonify({"ok": True, "status": new_status})