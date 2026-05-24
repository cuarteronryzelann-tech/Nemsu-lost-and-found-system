"""
models/item_model.py - Item Data Access Layer (Optimized)

Optimization changes:
  - Increased cache TTL from 15 s → 60 s (items change infrequently).
  - get_item_by_id now uses a per-item LRU-style cache so repeated
    detail-page hits skip the DB entirely.
  - get_all_items uses a short cache (5 s) to absorb burst admin reads.
  - find_matching_items uses the cache instead of a fresh DB call.
"""

import time
from models.database import get_connection

# ---------------------------------------------------------------------------
# Caches
# ---------------------------------------------------------------------------
_items_cache = {"data": None, "ts": 0}
_CACHE_TTL   = 60   # seconds

_item_by_id_cache: dict = {}   # {item_id: (dict, timestamp)}
_ITEM_BY_ID_TTL = 120          # 2 minutes — item details rarely change

_all_items_cache = {"data": None, "ts": 0, "key": None}
_ALL_ITEMS_TTL = 5             # short — admin views need freshness


def _invalidate_items_cache():
    _items_cache["data"] = None
    _items_cache["ts"]   = 0
    _all_items_cache["data"] = None
    _all_items_cache["ts"]   = 0


def _invalidate_item(item_id):
    _item_by_id_cache.pop(item_id, None)
    _invalidate_items_cache()


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------

def create_item(name, description, category, item_type, location,
                date_reported, reported_by, time_found=None,
                image_filename=None, pickup_lat=None, pickup_lng=None,
                pickup_address=None):
    from datetime import datetime
    conn   = get_connection()
    cursor = conn.cursor()
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
    cache_key = f"{item_type}:{status}"
    now = time.time()
    if (_all_items_cache["data"] is not None
            and _all_items_cache["key"] == cache_key
            and (now - _all_items_cache["ts"]) < _ALL_ITEMS_TTL):
        return _all_items_cache["data"]

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
    result = [dict(row) for row in rows]
    _all_items_cache["data"] = result
    _all_items_cache["ts"]   = now
    _all_items_cache["key"]  = cache_key
    return result


def get_item_by_id(item_id):
    now = time.time()
    cached = _item_by_id_cache.get(item_id)
    if cached and (now - cached[1]) < _ITEM_BY_ID_TTL:
        return cached[0]

    conn   = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM items WHERE id = ?", (item_id,))
    row = cursor.fetchone()
    conn.close()
    result = dict(row) if row else None
    if result:
        _item_by_id_cache[item_id] = (result, now)
    return result


def update_item(item_id, name, description, category, item_type, location,
                date_reported, image_filename=None):
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
    _invalidate_item(item_id)
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
    _invalidate_item(item_id)
    return updated


def delete_item(item_id):
    conn   = get_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM items WHERE id = ?", (item_id,))
    conn.commit()
    deleted = cursor.rowcount > 0
    conn.close()
    _invalidate_item(item_id)
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
    from items of the OPPOSITE type. Uses the search cache to avoid a
    redundant DB round-trip.
    """
    opposite_type = "found" if new_item.get("type") == "lost" else "lost"

    # Use cached items when available to avoid extra DB hit
    all_cached = get_items_for_search()
    candidates = [dict(r) for r in all_cached if r.get("type") == opposite_type]

    def _keywords(text: str) -> set:
        if not text:
            return set()
        return {w.lower() for w in text.split() if len(w) >= 4}

    new_name_kw  = _keywords(new_item.get("name", ""))
    new_desc_kw  = _keywords(new_item.get("description", ""))
    new_category = (new_item.get("category") or "").strip().lower()

    scored = []
    for item in candidates:
        score = 0
        if new_category and new_category == (item.get("category") or "").strip().lower():
            score += 3
        cand_name_kw = _keywords(item.get("name", ""))
        cand_desc_kw = _keywords(item.get("description", ""))
        score += len(new_name_kw & cand_name_kw) * 2
        score += len((new_name_kw | new_desc_kw) & (cand_name_kw | cand_desc_kw))
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


def get_resolved_items_by_user(user_id: int) -> list:
    """Return items posted by user that have been marked as returned/found (history)."""
    conn   = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT i.*, u.full_name AS found_by_name
        FROM items i
        LEFT JOIN users u ON u.id = i.found_by
        WHERE i.reported_by = ? AND i.status = 'returned'
        ORDER BY i.found_at DESC, i.date_reported DESC
    """, (user_id,))
    rows = cursor.fetchall()
    conn.close()
    return [dict(row) for row in rows]


def mark_item_returned(item_id: int, found_by_user_id: int) -> bool:
    """Mark a lost item as returned/found, recording who helped and when."""
    from datetime import datetime
    found_at = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
    conn   = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        UPDATE items SET status = 'returned', found_at = ?, found_by = ?
        WHERE id = ?
    """, (found_at, found_by_user_id, item_id))
    conn.commit()
    updated = cursor.rowcount > 0
    conn.close()
    _invalidate_item(item_id)
    return updated
