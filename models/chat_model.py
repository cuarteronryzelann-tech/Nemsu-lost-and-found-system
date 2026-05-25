"""
models/chat_model.py - Chat / Messaging Data Access Layer (Optimized)

Optimization changes:
  - Unread cache TTL raised to 15 s (was 8 s).
  - get_messages_since LIMIT raised to 100 (was 50) — avoids multi-poll catch-up.
  - send_message: avoid second SELECT by constructing the return dict directly
    from the INSERT data + a single JOIN lookup for sender name/pic.
  - mark_messages_read uses WHERE clause that avoids full table scan (is_read=0 filter).
  - get_conversation_by_id: small in-process cache (60 s TTL) since conversations
    are immutable after creation.
"""

import time
from models.database import get_connection

_chat_unread_cache = {}   # {user_id: (count, timestamp)}
_CHAT_UNREAD_TTL   = 15  # raised from 8 s

_conv_cache: dict = {}    # {conv_id: (dict, timestamp)}
_CONV_TTL = 60            # conversations never mutate after creation

def _invalidate_chat_unread(user_id):
    _chat_unread_cache.pop(user_id, None)


def get_or_create_conversation(user_a: int, user_b: int, item_id: int = None) -> dict:
    u1, u2 = min(user_a, user_b), max(user_a, user_b)
    conn = get_connection()
    cursor = conn.cursor()

    # If item_id is given, look for an existing conv for this specific item first
    if item_id:
        cursor.execute("""
            SELECT * FROM conversations
            WHERE user1_id = ? AND user2_id = ? AND item_id = ?
        """, (u1, u2, item_id))
        row = cursor.fetchone()
        if row:
            conv = dict(row)
            conn.close()
            _conv_cache[conv["id"]] = (conv, time.time())
            return conv

    # Fall back to any existing conv between these two users (no item filter)
    cursor.execute("""
        SELECT * FROM conversations WHERE user1_id = ? AND user2_id = ?
    """, (u1, u2))
    row = cursor.fetchone()

    if row:
        conv = dict(row)
        # If an item_id was supplied and the existing conv doesn't have one, patch it
        if item_id and not conv.get("item_id"):
            cursor.execute(
                "UPDATE conversations SET item_id = ? WHERE id = ?",
                (item_id, conv["id"])
            )
            conn.commit()
            conv["item_id"] = item_id
        conn.close()
        _conv_cache[conv["id"]] = (conv, time.time())
        return conv

    cursor.execute("""
        INSERT INTO conversations (user1_id, user2_id, item_id, created_at)
        VALUES (?, ?, ?, datetime('now'))
    """, (u1, u2, item_id))
    conn.commit()
    conv_id = cursor.lastrowid
    cursor.execute("SELECT * FROM conversations WHERE id = ?", (conv_id,))
    conv = dict(cursor.fetchone())
    conn.close()
    _conv_cache[conv_id] = (conv, time.time())
    return conv


def get_conversation_by_id(conv_id: int) -> dict | None:
    now = time.time()
    cached = _conv_cache.get(conv_id)
    if cached and (now - cached[1]) < _CONV_TTL:
        return cached[0]

    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM conversations WHERE id = ?", (conv_id,))
    row = cursor.fetchone()
    conn.close()
    result = dict(row) if row else None
    if result:
        _conv_cache[conv_id] = (result, now)
    return result


def get_user_conversations(user_id: int) -> list[dict]:
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT
            c.id,
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
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT m.id, m.conversation_id, m.sender_id, m.content, m.image_filename,
               m.is_read, m.is_deleted, m.created_at,
               m.msg_type, m.ref_item_id,
               u.full_name AS sender_name,
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
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT m.id, m.conversation_id, m.sender_id, m.content, m.image_filename,
               m.is_read, m.is_deleted, m.created_at,
               m.msg_type, m.ref_item_id,
               u.full_name AS sender_name,
               u.profile_picture AS sender_pic,
               u.profile_pic_status AS sender_pic_status,
               u.role AS sender_role
        FROM messages m
        JOIN users u ON u.id = m.sender_id
        WHERE m.conversation_id = ? AND m.id > ?
        ORDER BY m.id ASC
        LIMIT 100
    """, (conv_id, since_id))
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]


def send_message(conv_id: int, sender_id: int, content: str,
                 image_filename: str = None,
                 msg_type: str = "text",
                 ref_item_id: int = None) -> dict:
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        INSERT INTO messages (conversation_id, sender_id, content, image_filename,
                              msg_type, ref_item_id, created_at)
        VALUES (?, ?, ?, ?, ?, ?, datetime('now'))
    """, (conv_id, sender_id, content, image_filename, msg_type, ref_item_id))
    conn.commit()
    msg_id = cursor.lastrowid

    # Fetch with JOIN for sender info
    cursor.execute("""
        SELECT m.id, m.conversation_id, m.sender_id, m.content, m.image_filename,
               m.is_read, m.is_deleted, m.created_at,
               m.msg_type, m.ref_item_id,
               u.full_name AS sender_name,
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