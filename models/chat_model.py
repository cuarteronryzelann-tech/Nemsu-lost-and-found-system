"""
models/chat_model.py - Chat / Messaging Data Access Layer
==========================================================
Supports user-to-user conversations (including user-to-admin).
Each conversation is unique per user pair. Messages belong to a conversation.
"""

import time
from models.database import get_connection

# Per-user cache for unread chat counts — polled every 4s by the badge system
_chat_unread_cache = {}  # {user_id: (count, timestamp)}
_CHAT_UNREAD_TTL   = 8   # seconds

def _invalidate_chat_unread(user_id):
    _chat_unread_cache.pop(user_id, None)


def get_or_create_conversation(user_a: int, user_b: int, item_id: int = None) -> dict:
    """
    Returns an existing conversation between two users, or creates one.
    user1_id is always the smaller ID to guarantee uniqueness.
    """
    u1, u2 = (min(user_a, user_b), max(user_a, user_b))
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT * FROM conversations WHERE user1_id = ? AND user2_id = ?
    """, (u1, u2))
    row = cursor.fetchone()

    if row:
        conv = dict(row)
        conn.close()
        return conv

    cursor.execute("""
        INSERT INTO conversations (user1_id, user2_id, item_id)
        VALUES (?, ?, ?)
    """, (u1, u2, item_id))
    conn.commit()
    conv_id = cursor.lastrowid
    cursor.execute("SELECT * FROM conversations WHERE id = ?", (conv_id,))
    conv = dict(cursor.fetchone())
    conn.close()
    return conv


def get_conversation_by_id(conv_id: int) -> dict | None:
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM conversations WHERE id = ?", (conv_id,))
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None


def get_user_conversations(user_id: int) -> list[dict]:
    """
    Returns all conversations for a user, enriched with the other participant's
    name, their profile picture, the last message, and unread count.
    """
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT
            c.id            AS conv_id,
            c.item_id,
            c.created_at    AS conv_created,
            CASE WHEN c.user1_id = ? THEN c.user2_id ELSE c.user1_id END AS other_id,
            u.full_name     AS other_name,
            u.profile_picture AS other_pic,
            u.profile_pic_status AS other_pic_status,
            u.role          AS other_role,
            (SELECT content   FROM messages m WHERE m.conversation_id = c.id ORDER BY m.created_at DESC LIMIT 1) AS last_message,
            (SELECT created_at FROM messages m WHERE m.conversation_id = c.id ORDER BY m.created_at DESC LIMIT 1) AS last_message_at,
            (SELECT COUNT(*) FROM messages m WHERE m.conversation_id = c.id AND m.sender_id != ? AND m.is_read = 0) AS unread_count,
            i.name          AS item_name
        FROM conversations c
        JOIN users u ON u.id = CASE WHEN c.user1_id = ? THEN c.user2_id ELSE c.user1_id END
        LEFT JOIN items i ON i.id = c.item_id
        WHERE c.user1_id = ? OR c.user2_id = ?
        ORDER BY last_message_at DESC NULLS LAST, c.created_at DESC
    """, (user_id, user_id, user_id, user_id, user_id))

    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_messages(conv_id: int, limit: int = 100) -> list[dict]:
    """Returns messages for a conversation, oldest first."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT m.*, u.full_name AS sender_name,
               u.profile_picture AS sender_pic,
               u.profile_pic_status AS sender_pic_status,
               u.role AS sender_role
        FROM messages m
        JOIN users u ON u.id = m.sender_id
        WHERE m.conversation_id = ?
        ORDER BY m.created_at ASC
        LIMIT ?
    """, (conv_id, limit))
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_messages_since(conv_id: int, since_id: int) -> list[dict]:
    """Returns only messages newer than since_id — used by the poll endpoint."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT m.*, u.full_name AS sender_name,
               u.profile_picture AS sender_pic,
               u.profile_pic_status AS sender_pic_status,
               u.role AS sender_role
        FROM messages m
        JOIN users u ON u.id = m.sender_id
        WHERE m.conversation_id = ? AND m.id > ?
        ORDER BY m.id ASC
        LIMIT 50
    """, (conv_id, since_id))
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]


def send_message(conv_id: int, sender_id: int, content: str, image_filename: str = None) -> dict:
    """Inserts a new message (text + optional image) and returns it."""
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        INSERT INTO messages (conversation_id, sender_id, content, image_filename)
        VALUES (?, ?, ?, ?)
    """, (conv_id, sender_id, content, image_filename))
    conn.commit()

    msg_id = cursor.lastrowid

    cursor.execute("""
        SELECT m.*, u.full_name AS sender_name,
               u.profile_picture AS sender_pic,
               u.profile_pic_status AS sender_pic_status,
               u.role AS sender_role
        FROM messages m
        JOIN users u ON u.id = m.sender_id
        WHERE m.id = ?
    """, (msg_id,))

    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else {}


def mark_messages_read(conv_id: int, reader_id: int):
    """Marks all messages sent by others in a conversation as read."""
    _invalidate_chat_unread(reader_id)
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        UPDATE messages SET is_read = 1
        WHERE conversation_id = ? AND sender_id != ? AND is_read = 0
    """, (conv_id, reader_id))
    conn.commit()
    conn.close()


def get_total_unread(user_id: int) -> int:
    """Total unread messages for a user across all conversations."""
    now = time.time()
    cached = _chat_unread_cache.get(user_id)
    if cached and (now - cached[1]) < _CHAT_UNREAD_TTL:
        return cached[0]
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT COUNT(*) as cnt
        FROM messages m
        JOIN conversations c ON c.id = m.conversation_id
        WHERE (c.user1_id = ? OR c.user2_id = ?)
          AND m.sender_id != ?
          AND m.is_read = 0
    """, (user_id, user_id, user_id))
    row = cursor.fetchone()
    conn.close()
    count = row["cnt"] if row else 0
    _chat_unread_cache[user_id] = (count, now)
    return count


def get_all_conversations_admin() -> list[dict]:
    """Admin view: all conversations with participant names."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT
            c.id AS conv_id,
            c.item_id,
            u1.full_name AS user1_name,
            u2.full_name AS user2_name,
            u1.id AS user1_id,
            u2.id AS user2_id,
            (SELECT content FROM messages m WHERE m.conversation_id = c.id ORDER BY m.created_at DESC LIMIT 1) AS last_message,
            (SELECT created_at FROM messages m WHERE m.conversation_id = c.id ORDER BY m.created_at DESC LIMIT 1) AS last_message_at,
            i.name AS item_name
        FROM conversations c
        JOIN users u1 ON u1.id = c.user1_id
        JOIN users u2 ON u2.id = c.user2_id
        LEFT JOIN items i ON i.id = c.item_id
        ORDER BY last_message_at DESC NULLS LAST
    """)
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]


def delete_message(msg_id: int, sender_id: int) -> bool:
    """Soft-delete a message by replacing content with deleted indicator. Only sender can delete."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT id FROM messages WHERE id = ? AND sender_id = ?",
        (msg_id, sender_id)
    )
    row = cursor.fetchone()
    if not row:
        conn.close()
        return False
    cursor.execute(
        "UPDATE messages SET content = NULL, image_filename = NULL, is_deleted = 1 WHERE id = ?",
        (msg_id,)
    )
    conn.commit()
    conn.close()
    return True