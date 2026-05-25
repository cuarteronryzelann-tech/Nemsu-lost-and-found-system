"""
models/user_model.py - User Data Access Layer (Optimized)

Optimization changes:
  - Added LRU cache for get_user_by_id (most-called function in login_required).
  - Cache is invalidated on any write to that user's record.
  - update_last_active batched: only writes to DB if >= 30 s since last write,
    eliminating the DB write on every single authenticated page request.
  - get_all_users result cached for 30 s (admin page, infrequent writes).
"""

import time
import functools
from models.database import get_connection
from utils.consistent_hashing import hash_sensitive_data

# ---------------------------------------------------------------------------
# Simple TTL cache helpers
# ---------------------------------------------------------------------------
_user_by_id_cache: dict = {}   # {user_id: (user_dict, timestamp)}
_USER_ID_TTL = 60              # seconds — covers a full page navigation chain

_all_users_cache: dict = {"data": None, "ts": 0}
_ALL_USERS_TTL = 30

_last_active_written: dict = {}  # {user_id: timestamp}
_LAST_ACTIVE_INTERVAL = 30       # only write DB every 30 s per user

_last_online_written: dict = {}  # {user_id: (is_online, timestamp)}
_ONLINE_INTERVAL = 60            # only write is_online to DB every 60 s


def _invalidate_user(user_id):
    _user_by_id_cache.pop(user_id, None)


def _invalidate_all_users():
    _all_users_cache["data"] = None
    _all_users_cache["ts"] = 0


# ---------------------------------------------------------------------------
# Core functions
# ---------------------------------------------------------------------------

def create_or_update_user(student_id, full_name, email, role="user"):
    conn = get_connection()
    cursor = conn.cursor()
    hashed_student_id = hash_sensitive_data(student_id)
    cursor.execute("""
        INSERT INTO users (student_id, full_name, email, role, is_registered, last_active)
        VALUES (?, ?, ?, ?, 0, datetime('now'))
        ON CONFLICT(email) DO UPDATE SET
            full_name   = excluded.full_name,
            last_active = datetime('now')
    """, (hashed_student_id, full_name, email, role))
    conn.commit()
    user = get_user_by_email(email)
    conn.close()
    if user:
        _invalidate_user(user["id"])
        _invalidate_all_users()
    return user


def get_user_by_email(email):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM users WHERE email = ?", (email,))
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None


def get_user_by_id(user_id):
    now = time.time()
    cached = _user_by_id_cache.get(user_id)
    if cached and (now - cached[1]) < _USER_ID_TTL:
        return cached[0]
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM users WHERE id = ?", (user_id,))
    row = cursor.fetchone()
    conn.close()
    result = dict(row) if row else None
    if result:
        _user_by_id_cache[user_id] = (result, now)
    return result


def get_all_users():
    now = time.time()
    if _all_users_cache["data"] is not None and (now - _all_users_cache["ts"]) < _ALL_USERS_TTL:
        return _all_users_cache["data"]
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT id, full_name, email, course, year_level,
               profile_picture, profile_pic_status
        FROM users WHERE role != 'admin' ORDER BY full_name ASC
    """)
    rows = cursor.fetchall()
    conn.close()
    result = [dict(row) for row in rows]
    _all_users_cache["data"] = result
    _all_users_cache["ts"] = now
    return result


def get_users_with_pending_profile_pics():
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT * FROM users
        WHERE profile_pic_status = 'pending'
        ORDER BY created_at DESC
    """)
    rows = cursor.fetchall()
    conn.close()
    return [dict(row) for row in rows]


def update_user_profile(user_id, phone, course, year_level):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        UPDATE users
           SET phone = ?, course = ?, year_level = ?, is_registered = 1
         WHERE id = ?
    """, (phone, course, year_level, user_id))
    updated = cursor.rowcount > 0
    conn.commit()
    conn.close()
    _invalidate_user(user_id)
    _invalidate_all_users()
    return updated


def update_profile_picture(user_id, filename_or_data, auto_approve=False):
    conn = get_connection()
    cursor = conn.cursor()
    status = 'approved' if auto_approve else 'pending'
    cursor.execute("""
        UPDATE users SET profile_picture = ?, profile_pic_status = ?
        WHERE id = ?
    """, (filename_or_data, status, user_id))
    conn.commit()
    conn.close()
    _invalidate_user(user_id)
    _invalidate_all_users()


def delete_profile_picture(user_id):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        UPDATE users SET profile_picture = NULL, profile_pic_status = 'none'
        WHERE id = ?
    """, (user_id,))
    conn.commit()
    conn.close()
    _invalidate_user(user_id)
    _invalidate_all_users()


def delete_user(user_id):
    conn = get_connection()
    cursor = conn.cursor()
    try:
        # Delete child records first to respect foreign key constraints
        cursor.execute("DELETE FROM messages WHERE sender_id = ?", (user_id,))
        cursor.execute("DELETE FROM messages WHERE conversation_id IN (SELECT id FROM conversations WHERE user1_id = ? OR user2_id = ?)", (user_id, user_id))
        cursor.execute("DELETE FROM conversations WHERE user1_id = ? OR user2_id = ?", (user_id, user_id))
        cursor.execute("DELETE FROM notifications WHERE user_id = ?", (user_id,))
        cursor.execute("DELETE FROM reports WHERE reporter_id = ? OR reported_user_id = ? OR reviewed_by = ?", (user_id, user_id, user_id))
        cursor.execute("DELETE FROM claims WHERE claimant_id = ?", (user_id,))
        cursor.execute("DELETE FROM activity_log WHERE user_id = ?", (user_id,))
        cursor.execute("DELETE FROM items WHERE reported_by = ?", (user_id,))
        cursor.execute("DELETE FROM users WHERE id = ?", (user_id,))
        conn.commit()
        deleted = cursor.rowcount > 0
    except Exception:
        conn.rollback()
        deleted = False
    finally:
        conn.close()
    _invalidate_user(user_id)
    _invalidate_all_users()
    return deleted


def update_last_active(user_id):
    """
    Throttled: only hits the DB once every 30 s per user.
    Eliminates the per-request DB write that was slowing every page load.
    """
    now = time.time()
    last = _last_active_written.get(user_id, 0)
    if now - last < _LAST_ACTIVE_INTERVAL:
        return  # skip — written recently enough
    _last_active_written[user_id] = now
    try:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE users SET last_active = datetime('now') WHERE id = ?",
            (user_id,)
        )
        conn.commit()
        conn.close()
        _invalidate_user(user_id)
    except Exception:
        pass


def log_activity(user_id, action, details=None):
    try:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO activity_log (user_id, action, details, created_at)
            VALUES (?, ?, ?, datetime('now'))
        """, (user_id, action, details))
        conn.commit()
        conn.close()
    except Exception:
        pass


def get_active_users_count(minutes=30):
    try:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT COUNT(*) as cnt FROM users
            WHERE last_active >= datetime('now', ? || ' minutes')
              AND role != 'admin'
        """, (f"-{minutes}",))
        row = cursor.fetchone()
        conn.close()
        return row["cnt"] if row else 0
    except Exception:
        return 0


def get_active_users(minutes=30):
    try:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT * FROM users
            WHERE last_active >= datetime('now', ? || ' minutes')
              AND role != 'admin'
            ORDER BY last_active DESC
        """, (f"-{minutes}",))
        rows = cursor.fetchall()
        conn.close()
        return [dict(r) for r in rows]
    except Exception:
        return []


def get_user_growth():
    try:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT strftime('%Y-%m', created_at) as month, COUNT(*) as count
            FROM users WHERE role != 'admin'
            GROUP BY month ORDER BY month ASC
        """)
        rows = cursor.fetchall()
        conn.close()
        return [dict(r) for r in rows]
    except Exception:
        return []


def set_user_online(user_id, is_online: bool):
    """
    Throttled: only writes to DB when the value changes or every 60 s.
    Eliminates redundant DB writes on every heartbeat when status is unchanged.
    """
    now = time.time()
    prev = _last_online_written.get(user_id)
    # Skip if same state was written recently
    if prev and prev[0] == is_online and (now - prev[1]) < _ONLINE_INTERVAL:
        return
    _last_online_written[user_id] = (is_online, now)
    try:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE users SET is_online = ? WHERE id = ?",
            (1 if is_online else 0, user_id)
        )
        conn.commit()
        conn.close()
        _invalidate_user(user_id)
    except Exception:
        pass


def approve_profile_picture(user_id):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "UPDATE users SET profile_pic_status = 'approved' WHERE id = ?",
        (user_id,)
    )
    conn.commit()
    conn.close()
    _invalidate_user(user_id)
    _invalidate_all_users()


def reject_profile_picture(user_id):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "UPDATE users SET profile_picture = NULL, profile_pic_status = 'none' WHERE id = ?",
        (user_id,)
    )
    conn.commit()
    conn.close()
    _invalidate_user(user_id)
    _invalidate_all_users()


def disable_user(user_id, until_str):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "UPDATE users SET disable_until = ? WHERE id = ?",
        (until_str, user_id)
    )
    conn.commit()
    conn.close()
    _invalidate_user(user_id)


def enable_user(user_id):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "UPDATE users SET disable_until = NULL WHERE id = ?",
        (user_id,)
    )
    conn.commit()
    conn.close()
    _invalidate_user(user_id)


# Alias used by admin_controller
def get_all_users_admin():
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM users ORDER BY full_name ASC")
    rows = cursor.fetchall()
    conn.close()
    return [dict(row) for row in rows]