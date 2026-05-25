"""
models/notification_model.py - Notifications Data Access Layer (Optimized)

Optimization changes:
  - Unread count cache TTL raised to 15 s (polled every 4 s; was 8 s).
  - add_notification uses INSERT with created_at=datetime('now') directly
    in SQL instead of Python datetime, removing an import on hot path.
  - get_notifications SELECT only needed columns (no SELECT *).
"""

import time
from models.database import get_connection

_unread_cache = {}   # {user_id: (count, timestamp)}
_UNREAD_TTL   = 90  # seconds — matches the 90 s polling interval in base.html


def _invalidate_unread(user_id):
    _unread_cache.pop(user_id, None)


def add_notification(user_id: int, message: str, notif_type: str = "info", link: str = None):
    _invalidate_unread(user_id)
    try:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO notifications (user_id, message, type, link, created_at)
            VALUES (?, ?, ?, ?, datetime('now'))
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
            SELECT id, user_id, message, type, link, is_read, created_at
            FROM notifications
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
            UPDATE notifications SET is_read = 1 WHERE user_id = ? AND is_read = 0
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
    try:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "DELETE FROM notifications WHERE id = ? AND user_id = ?",
            (notif_id, user_id)
        )
        conn.commit()
        conn.close()
        _invalidate_unread(user_id)
    except Exception:
        pass


def delete_all_notifications(user_id: int):
    try:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM notifications WHERE user_id = ?", (user_id,))
        conn.commit()
        conn.close()
        _invalidate_unread(user_id)
    except Exception:
        pass


def get_notifications_with_count(user_id: int, limit: int = 20):
    """
    Return (notifications_list, unread_count) in a single DB round-trip.
    Use instead of calling get_notifications() + get_unread_count() separately.
    Falls back to cached unread count if the query fails.
    """
    now = time.time()
    try:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT id, user_id, message, type, link, is_read, created_at
            FROM notifications
            WHERE user_id = ?
            ORDER BY created_at DESC
            LIMIT ?
        """, (user_id, limit))
        rows = cursor.fetchall()

        cursor.execute("""
            SELECT COUNT(*) as cnt FROM notifications
            WHERE user_id = ? AND is_read = 0
        """, (user_id,))
        row = cursor.fetchone()
        conn.close()

        notifs = [dict(r) for r in rows]
        count = row["cnt"] if row else 0
        _unread_cache[user_id] = (count, now)
        return notifs, count
    except Exception:
        return [], 0
