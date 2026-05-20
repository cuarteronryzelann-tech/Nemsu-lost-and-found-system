"""
models/item_model.py - Item Data Access Layer
"""

import time
from models.database import get_connection

# Simple in-memory cache to avoid hammering the remote DB on every page load
_items_cache = {"data": None, "ts": 0}
_CACHE_TTL   = 15  # seconds — invalidated on any write

def _invalidate_items_cache():
    _items_cache["data"] = None
    _items_cache["ts"]   = 0


def create_item(name, description, category, item_type, location,
                date_reported, reported_by, time_found=None,
                image_filename=None, pickup_lat=None, pickup_lng=None,
                pickup_address=None):
    from datetime import datetime
    conn   = get_connection()
    cursor = conn.cursor()
    # Both lost and found items go straight to 'listed' so they show in search
    initial_status = "listed"
    now = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
    cursor.execute("""
        INSERT INTO items (name, description, category, type, status,
                           location, date_reported, time_found, image_filename,
                           reported_by, pickup_lat, pickup_lng, pickup_address, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (name, description, category, item_type, initial_status,
          location, date_reported, time_found, image_filename, reported_by,
          pickup_lat, pickup_lng, pickup_address, now))
    conn.commit()
    item_id = cursor.lastrowid
    conn.close()
    _invalidate_items_cache()
    return item_id


def get_all_items(item_type=None, status=None):
    conn   = get_connection()
    cursor = conn.cursor()
    query  = "SELECT * FROM items WHERE 1=1"
    params = []
    if item_type:
        query += " AND type = ?"
        params.append(item_type)
    if status:
        query += " AND status = ?"
        params.append(status)
    query += " ORDER BY date_reported DESC"
    cursor.execute(query, params)
    rows = cursor.fetchall()
    conn.close()
    return [dict(row) for row in rows]


def get_item_by_id(item_id):
    conn   = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM items WHERE id = ?", (item_id,))
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None


def update_item(item_id, name, description, category, item_type, location,
                date_reported, image_filename=None):
    """Update an existing item's details. image_filename=None means keep existing."""
    conn   = get_connection()
    cursor = conn.cursor()
    if image_filename is not None:
        cursor.execute("""
            UPDATE items SET name=?, description=?, category=?, type=?,
                             location=?, date_reported=?, image_filename=?
            WHERE id=?
        """, (name, description, category, item_type, location,
              date_reported, image_filename, item_id))
    else:
        cursor.execute("""
            UPDATE items SET name=?, description=?, category=?, type=?,
                             location=?, date_reported=?
            WHERE id=?
        """, (name, description, category, item_type, location,
              date_reported, item_id))
    conn.commit()
    updated = cursor.rowcount > 0
    conn.close()
    _invalidate_items_cache()
    return updated


def update_item_status(item_id, status, approved_by=None):
    conn   = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        UPDATE items SET status = ?, approved_by = ? WHERE id = ?
    """, (status, approved_by, item_id))
    conn.commit()
    updated = cursor.rowcount > 0
    conn.close()
    _invalidate_items_cache()
    return updated


def delete_item(item_id):
    """Permanently delete an item (used by admin for illegal/fake items)."""
    conn   = get_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM items WHERE id = ?", (item_id,))
    conn.commit()
    deleted = cursor.rowcount > 0
    conn.close()
    _invalidate_items_cache()
    return deleted


def get_items_for_search():
    now = time.time()
    if _items_cache["data"] is not None and (now - _items_cache["ts"]) < _CACHE_TTL:
        return _items_cache["data"]

    conn   = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT i.*,
               u.full_name           AS reporter_name,
               u.profile_picture     AS reporter_pic,
               u.profile_pic_status  AS reporter_pic_status
        FROM   items i
        LEFT JOIN users u ON u.id = i.reported_by
        WHERE  i.status IN ('listed', 'approved')
        ORDER  BY i.date_reported DESC
    """)
    rows = cursor.fetchall()
    conn.close()
    result = [dict(row) for row in rows]
    _items_cache["data"] = result
    _items_cache["ts"]   = now
    return result


def find_matching_items(new_item: dict) -> list:
    """
    Given a newly reported item (lost or found), return candidate matches
    from items of the OPPOSITE type that are still listed/active.

    Matching strategy (OR logic — any one hit qualifies):
      1. Same category (exact, case-insensitive)
      2. Name keyword overlap  — at least one word from the new item's name
         appears in the candidate's name or description (≥4 chars to skip noise)
      3. Description keyword overlap — same rule applied to the description

    Returns a list of item dicts sorted by match_score descending.
    """
    opposite_type = "found" if new_item.get("type") == "lost" else "lost"

    conn   = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT i.*, u.full_name AS reporter_name, u.email AS reporter_email
        FROM   items i
        JOIN   users u ON u.id = i.reported_by
        WHERE  i.type   = ?
          AND  i.status IN ('listed', 'approved')
    """, (opposite_type,))
    rows = cursor.fetchall()
    conn.close()

    candidates = [dict(r) for r in rows]

    # Build keyword sets from the new item
    def _keywords(text: str) -> set:
        if not text:
            return set()
        return {w.lower() for w in text.split() if len(w) >= 4}

    new_name_kw = _keywords(new_item.get("name", ""))
    new_desc_kw = _keywords(new_item.get("description", ""))
    new_category = (new_item.get("category") or "").strip().lower()

    scored = []
    for item in candidates:
        score = 0

        # Category match
        if new_category and new_category == (item.get("category") or "").strip().lower():
            score += 3

        # Name keyword overlap
        cand_name_kw = _keywords(item.get("name", ""))
        cand_desc_kw = _keywords(item.get("description", ""))

        name_overlap = new_name_kw & cand_name_kw
        score += len(name_overlap) * 2

        # Description keyword overlap
        desc_overlap = (new_name_kw | new_desc_kw) & (cand_name_kw | cand_desc_kw)
        score += len(desc_overlap)

        if score > 0:
            item["match_score"] = score
            scored.append(item)

    scored.sort(key=lambda x: x["match_score"], reverse=True)
    return scored


def get_item_stats():
    conn   = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT type, status, COUNT(*) as count
        FROM items GROUP BY type, status
    """)
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_items_per_month():
    conn   = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT strftime('%Y-%m', created_at) as month,
               type, COUNT(*) as count
        FROM items
        WHERE created_at >= datetime('now', '-6 months')
        GROUP BY month, type
        ORDER BY month ASC
    """)
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]

def get_items_by_user(user_id: int, item_type: str = None) -> list:
    """
    Retrieves all items reported by a specific user.
    Used to populate the user's dashboard 'My Reports' section.

    Args:
        user_id   (int): The user's database ID.
        item_type (str): Optional filter — 'lost' or 'found'.

    Returns:
        list[dict]: Items reported by this user, newest first.
    """
    conn   = get_connection()
    cursor = conn.cursor()

    query  = "SELECT * FROM items WHERE reported_by = ?"
    params = [user_id]

    if item_type:
        query += " AND type = ?"
        params.append(item_type)

    query += " ORDER BY date_reported DESC"
    cursor.execute(query, params)
    rows = cursor.fetchall()
    conn.close()

    return [dict(row) for row in rows]