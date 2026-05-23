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

    return render_template("chat/conversation.html",
                           conv=conv,
                           other_user=other_user,
                           messages=messages,
                           conversations=conversations,
                           current_user_id=user_id)


from werkzeug.utils import secure_filename
import uuid

# Vercel has a read-only filesystem except for /tmp
UPLOAD_FOLDER = "/tmp/chat_uploads" if os.environ.get("VERCEL") else "static/uploads/chat"
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

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

    # ✅ Handle image upload
    filename = None
    if file and file.filename:
        ext = file.filename.rsplit(".", 1)[-1].lower()
        filename = f"{uuid.uuid4().hex}.{ext}"
        filepath = os.path.join(UPLOAD_FOLDER, filename)
        file.save(filepath)

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
            "id": msg["id"],
            "content": msg["content"],
            "image": filename,  # 👈 IMPORTANT
            "sender_id": msg["sender_id"],
            "sender_name": msg["sender_name"],
            "sender_pic": msg.get("sender_pic", ""),
            "created_at": msg["created_at"],
            "is_mine": True
        }
    })
# ─────────────────────────────────────────────────────────────────────────────
# Poll for new messages (AJAX GET)
# ─────────────────────────────────────────────────────────────────────────────

@chat_bp.route("/<int:conv_id>/poll")
@login_required
def poll(conv_id):
    user_id = session["user"]["id"]
    conv = get_conversation_by_id(conv_id)

    if not conv or (conv["user1_id"] != user_id and conv["user2_id"] != user_id):
        return jsonify({"ok": True, "messages": [], "error": "not_participant"}), 200

    since_id = request.args.get("since", 0, type=int)
    new_msgs = get_messages_since(conv_id, since_id)
    mark_messages_read(conv_id, user_id)

    # Other user's online status (active in last 2 min)
    other_id = conv["user2_id"] if conv["user1_id"] == user_id else conv["user1_id"]
    other_user = get_user_by_id(other_id)
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

    return jsonify({
        "ok": True,
        "other_online": other_online,
        "other_typing": False,
        "seen_ids": seen_ids,
        "messages": [
            {
                "id": m["id"],
                "content": m["content"],
                "image": m.get("image_filename", ""),
                "sender_id": m["sender_id"],
                "sender_name": m["sender_name"],
                "sender_pic": m.get("sender_pic", ""),
                "created_at": m["created_at"],
                "is_mine": m["sender_id"] == user_id,
                "is_deleted": bool(m.get("is_deleted")),
            } for m in new_msgs
        ]
    })


# ─────────────────────────────────────────────────────────────────────────────
# Unread count (AJAX)
# ─────────────────────────────────────────────────────────────────────────────

@chat_bp.route("/unread-count")
@login_required
def unread_count():
    count = get_total_unread(session["user"]["id"])
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