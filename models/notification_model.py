"""
models/notification_model.py - Notifications Data Access Layer
"""

import time
from models.database import get_connection

# Per-user cache for unread counts — polled every 4s so this saves many DB round-trips
_unread_cache = {}  # {user_id: (count, timestamp)}
_UNREAD_TTL   = 8   # seconds

def _invalidate_unread(user_id):
    _unread_cache.pop(user_id, None)


def add_notification(user_id: int, message: str, notif_type: str = "info", link: str = None):
    _invalidate_unread(user_id)
    try:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO notifications (user_id, message, type, link)
            VALUES (?, ?, ?, ?)
        """, (user_id, message, notif_type, link))
        conn.commit()
        conn.close()
    except Exception:
        pass


def get_notifications(user_id: int, limit: int = 20) -> list:
    try:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT * FROM notifications
            WHERE user_id = ?
            ORDER BY created_at DESC
            LIMIT ?
        """, (user_id, limit))
        rows = cursor.fetchall()
        conn.close()
        return [dict(r) for r in rows]
    except Exception:
        return []


def get_unread_count(user_id: int) -> int:
    now = time.time()
    cached = _unread_cache.get(user_id)
    if cached and (now - cached[1]) < _UNREAD_TTL:
        return cached[0]
    try:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT COUNT(*) as cnt FROM notifications
            WHERE user_id = ? AND is_read = 0
        """, (user_id,))
        row = cursor.fetchone()
        conn.close()
        count = row["cnt"] if row else 0
        _unread_cache[user_id] = (count, now)
        return count
    except Exception:
        return 0


def mark_all_read(user_id: int):
    _invalidate_unread(user_id)
    try:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE notifications SET is_read = 1 WHERE user_id = ?
        """, (user_id,))
        conn.commit()
        conn.close()
    except Exception:
        pass


def mark_read(notif_id: int):
    try:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("UPDATE notifications SET is_read = 1 WHERE id = ?", (notif_id,))
        conn.commit()
        conn.close()
    except Exception:
        pass



def delete_notification(notif_id: int, user_id: int):
    """Delete a single notification (only if it belongs to user_id)."""
    try:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "DELETE FROM notifications WHERE id = ? AND user_id = ?",
            (notif_id, user_id)
        )
        conn.commit()
        conn.close()
    except Exception:
        pass


def delete_all_notifications(user_id: int):
    """Delete all notifications for a user."""
    try:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM notifications WHERE user_id = ?", (user_id,))
        conn.commit()
        conn.close()
    except Exception:
        pass
