"""
models/report_model.py - Abuse / Joke Report Data Access Layer
"""

from models.database import get_connection


def create_report(reporter_id, reason, details="",
                  reported_user_id=None, reported_item_id=None):
    conn   = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO reports
            (reporter_id, reported_user_id, reported_item_id, reason, details)
        VALUES (?, ?, ?, ?, ?)
    """, (reporter_id, reported_user_id, reported_item_id, reason, details))
    conn.commit()
    report_id = cursor.lastrowid
    conn.close()
    return report_id


def get_all_reports(status=None):
    conn   = get_connection()
    cursor = conn.cursor()
    query  = """
        SELECT r.*,
               ru.full_name  AS reporter_name,
               tu.full_name  AS reported_user_name,
               i.name        AS reported_item_name
        FROM   reports r
        LEFT JOIN users ru ON ru.id = r.reporter_id
        LEFT JOIN users tu ON tu.id = r.reported_user_id
        LEFT JOIN items i  ON i.id  = r.reported_item_id
    """
    params = []
    if status:
        query += " WHERE r.status = ?"
        params.append(status)
    query += " ORDER BY r.created_at DESC"
    cursor.execute(query, params)
    rows = cursor.fetchall()
    conn.close()
    return [dict(row) for row in rows]


def get_report_by_id(report_id):
    conn   = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT r.*,
               ru.full_name AS reporter_name,
               tu.full_name AS reported_user_name,
               i.name       AS reported_item_name
        FROM   reports r
        LEFT JOIN users ru ON ru.id = r.reporter_id
        LEFT JOIN users tu ON tu.id = r.reported_user_id
        LEFT JOIN items i  ON i.id  = r.reported_item_id
        WHERE  r.id = ?
    """, (report_id,))
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None


def resolve_report(report_id, reviewed_by, status, admin_note=""):
    conn   = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        UPDATE reports
           SET status      = ?,
               reviewed_by = ?,
               reviewed_at = datetime('now'),
               admin_note  = ?
         WHERE id = ?
    """, (status, reviewed_by, admin_note, report_id))
    conn.commit()
    updated = cursor.rowcount > 0
    conn.close()
    return updated


def get_pending_reports_count():
    conn   = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM reports WHERE status = 'pending'")
    count = cursor.fetchone()[0]
    conn.close()
    return count
