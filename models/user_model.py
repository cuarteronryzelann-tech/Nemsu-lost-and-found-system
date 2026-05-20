"""
models/user_model.py - User Data Access Layer
"""

from models.database import get_connection
from utils.consistent_hashing import hash_sensitive_data
# from utils.hashing import hash_sensitive_data


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
    return user


def get_user_by_email(email):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM users WHERE email = ?", (email,))
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None


def get_user_by_id(user_id):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM users WHERE id = ?", (user_id,))
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None


def get_all_users():
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT id, full_name, email, course, year_level,
               profile_picture, profile_pic_status
        FROM users WHERE role != 'admin' ORDER BY full_name ASC
    """)
    rows = cursor.fetchall()
    conn.close()
    return [dict(row) for row in rows]


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
    return updated


def update_profile_picture(user_id, filename_or_data, auto_approve=False):
    """
    filename_or_data can be:
      - a base64 data-URI string (data:image/...;base64,...) — stored directly in DB
      - a plain filename string — stored as-is (legacy)
    On Render the filesystem resets between deploys, so we store images as
    base64 data-URIs directly in the database.
    """
    conn = get_connection()
    cursor = conn.cursor()
    status = 'approved' if auto_approve else 'pending'
    cursor.execute("""
        UPDATE users SET profile_picture = ?, profile_pic_status = ?
        WHERE id = ?
    """, (filename_or_data, status, user_id))
    conn.commit()
    conn.close()


def approve_profile_picture(user_id):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        UPDATE users SET profile_pic_status = 'approved' WHERE id = ?
    """, (user_id,))
    conn.commit()
    conn.close()


def reject_profile_picture(user_id):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        UPDATE users SET profile_picture = NULL, profile_pic_status = 'rejected'
        WHERE id = ?
    """, (user_id,))
    conn.commit()
    conn.close()


def update_last_active(user_id):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        UPDATE users SET last_active = datetime('now') WHERE id = ?
    """, (user_id,))
    conn.commit()
    conn.close()


def get_active_users_count(minutes=30):
    """Count users active in the last N minutes."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT COUNT(*) as cnt FROM users
        WHERE role != 'admin'
        AND last_active >= datetime('now', ? || ' minutes')
    """, (f"-{minutes}",))
    row = cursor.fetchone()
    conn.close()
    return row["cnt"] if row else 0


def get_active_users(minutes=30):
    """Return list of users active in the last N minutes."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT id, full_name, email, course, year_level, profile_picture,
               profile_pic_status, last_active
        FROM users
        WHERE role != 'admin'
        AND last_active >= datetime('now', ? || ' minutes')
        ORDER BY last_active DESC
    """, (f"-{minutes}",))
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_user_growth():
    """Return monthly user registration counts for the past 6 months."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT strftime('%Y-%m', created_at) as month, COUNT(*) as count
        FROM users
        WHERE role != 'admin'
        AND created_at >= datetime('now', '-6 months')
        GROUP BY month
        ORDER BY month ASC
    """)
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]


def log_activity(user_id, action, details=""):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO activity_log (user_id, action, details) VALUES (?, ?, ?)
    """, (user_id, action, details))
    conn.commit()
    conn.close()


def disable_user(user_id, until_datetime_str):
    """Disable a user account until a specific datetime string."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        UPDATE users SET disable_until = ? WHERE id = ?
    """, (until_datetime_str, user_id))
    conn.commit()
    conn.close()


def enable_user(user_id):
    """Re-enable a disabled user account."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE users SET disable_until = NULL WHERE id = ?", (user_id,))
    conn.commit()
    conn.close()


def delete_user(user_id):
    """Permanently delete a user (non-admin) and all their related records."""
    conn = get_connection()
    cursor = conn.cursor()

    # 1. Delete messages sent by this user
    cursor.execute("DELETE FROM messages WHERE sender_id = ?", (user_id,))

    # 2. Delete conversations where this user is a participant
    #    (also removes any messages inside those conversations first)
    cursor.execute(
        "SELECT id FROM conversations WHERE user1_id = ? OR user2_id = ?",
        (user_id, user_id),
    )
    conv_rows = cursor.fetchall()
    for row in conv_rows:
        cursor.execute("DELETE FROM messages WHERE conversation_id = ?", (row[0],))
    cursor.execute(
        "DELETE FROM conversations WHERE user1_id = ? OR user2_id = ?",
        (user_id, user_id),
    )

    # 3. Delete notifications for this user
    cursor.execute("DELETE FROM notifications WHERE user_id = ?", (user_id,))

    # 4. Delete activity log entries for this user
    cursor.execute("DELETE FROM activity_log WHERE user_id = ?", (user_id,))

    # 5. Delete claims made by this user (or reviewed by this user as admin)
    cursor.execute("DELETE FROM claims WHERE claimant_id = ?", (user_id,))
    cursor.execute("UPDATE claims SET reviewed_by = NULL WHERE reviewed_by = ?", (user_id,))

    # 6. Nullify report references to this user
    cursor.execute("UPDATE reports SET reported_user_id = NULL WHERE reported_user_id = ?", (user_id,))
    cursor.execute("UPDATE reports SET reviewed_by = NULL WHERE reviewed_by = ?", (user_id,))
    cursor.execute("DELETE FROM reports WHERE reporter_id = ?", (user_id,))

    # 7. Nullify item references to this user
    cursor.execute("UPDATE items SET reported_by = NULL WHERE reported_by = ?", (user_id,))
    cursor.execute("UPDATE items SET approved_by = NULL WHERE approved_by = ?", (user_id,))

    # 8. Finally, delete the user
    cursor.execute("DELETE FROM users WHERE id = ? AND role != 'admin'", (user_id,))
    deleted = cursor.rowcount > 0

    conn.commit()
    conn.close()
    return deleted


def is_user_disabled(user_id):
    """Returns True if the user is currently disabled."""
    from datetime import datetime
    user = get_user_by_id(user_id)
    if not user:
        return False
    disable_until = user.get("disable_until")
    if not disable_until:
        return False
    try:
        until = datetime.strptime(disable_until, "%Y-%m-%d %H:%M:%S")
        return datetime.utcnow() < until
    except Exception:
        return False


def set_user_online(user_id, online: bool):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE users SET is_online = ? WHERE id = ?", (1 if online else 0, user_id))
    conn.commit()
    conn.close()


def delete_profile_picture(user_id):
    """Remove a user's profile picture and reset status to 'none'."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "UPDATE users SET profile_picture = NULL, profile_pic_status = 'none' WHERE id = ?",
        (user_id,)
    )
    conn.commit()
    conn.close()