"""
models/claim_model.py - Claim Data Access Layer
================================================
Provides functions for managing item claim requests submitted
by students and reviewed by administrators.
"""

from models.database import get_connection


def create_claim(item_id: int, claimant_id: int, student_id_text: str,
                 full_name_text: str, last_location: str) -> int:
    """
    Inserts a new claim request into the database.
    The claim starts with status "pending" until an admin reviews it.

    Args:
        item_id         (int): ID of the item being claimed.
        claimant_id     (int): User ID of the student submitting the claim.
        student_id_text (str): Student ID as typed by the claimant (for verification).
        full_name_text  (str): Full name as typed by the claimant (for verification).
        last_location   (str): Where the student says the item was last located.

    Returns:
        int: The auto-generated claim ID of the inserted record.
    """
    conn = get_connection()
    cursor = conn.cursor()

    # Disable FK enforcement to work around incorrect FK definition in live schema
    # (item_id was mistakenly set to REFERENCES users(id) instead of items(id)).
    cursor.execute("PRAGMA foreign_keys = OFF")
    cursor.execute("""
        INSERT INTO claims (item_id, claimant_id, student_id_text,
                            full_name_text, last_location, status)
        VALUES (?, ?, ?, ?, ?, 'pending_finder')
    """, (item_id, claimant_id, student_id_text, full_name_text, last_location))
    cursor.execute("PRAGMA foreign_keys = ON")

    conn.commit()
    claim_id = cursor.lastrowid
    conn.close()
    return claim_id


def get_all_claims(status: str = None) -> list[dict]:
    """
    Retrieves all claim records, optionally filtered by approval status.
    Joins with items and users tables to include readable names.

    Args:
        status (str | None): Filter by "pending", "approved", or "denied". None = all.

    Returns:
        list[dict]: List of claim records with item and claimant details.
    """
    conn = get_connection()
    cursor = conn.cursor()

    # JOIN to enrich claim data with item name and claimant email
    query = """
        SELECT c.*,
               i.name           AS item_name,
               i.category       AS item_category,
               i.image_filename AS item_image,
               u.email          AS claimant_email
        FROM claims c
        JOIN items i ON c.item_id    = i.id
        JOIN users u ON c.claimant_id = u.id
        WHERE 1=1
    """
    params = []

    if status:
        query += " AND c.status = ?"
        params.append(status)

    query += " ORDER BY c.created_at DESC"

    cursor.execute(query, params)
    rows = cursor.fetchall()
    conn.close()

    return [dict(row) for row in rows]


def get_claim_by_id(claim_id: int) -> dict | None:
    """
    Retrieves a single claim record by its primary key, enriched
    with the related item name and claimant email.

    Args:
        claim_id (int): The claim's database auto-generated ID.

    Returns:
        dict | None: Claim record as a dict, or None if not found.
    """
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT c.*,
               i.name     AS item_name,
               u.email    AS claimant_email,
               u.full_name AS claimant_full_name
        FROM claims c
        JOIN items i ON c.item_id     = i.id
        JOIN users u ON c.claimant_id = u.id
        WHERE c.id = ?
    """, (claim_id,))

    row = cursor.fetchone()
    conn.close()

    return dict(row) if row else None


def update_claim_status(claim_id: int, status: str, reviewed_by: int,
                        pickup_location: str = None) -> bool:
    """
    Updates a claim's status after admin review.
    On approval, stores the pickup location for the claimant to see.

    Args:
        claim_id        (int): Target claim's database ID.
        status          (str): New status — "approved" or "denied".
        reviewed_by     (int): Admin user ID who reviewed the claim.
        pickup_location (str | None): Where the item can be picked up (on approval).

    Returns:
        bool: True if at least one row was updated, False otherwise.
    """
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        UPDATE claims
        SET status = ?, reviewed_by = ?, pickup_location = ?
        WHERE id = ?
    """, (status, reviewed_by, pickup_location, claim_id))

    conn.commit()
    updated = cursor.rowcount > 0  # Confirms the update affected a row
    conn.close()
    return updated


def get_claims_by_user(user_id: int) -> list[dict]:
    """
    Retrieves all claim requests submitted by a specific student.
    Used to populate the student's "My Claims" dashboard section.

    Args:
        user_id (int): The student's user ID.

    Returns:
        list[dict]: List of the user's claims with item details.
    """
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT c.*,
               i.name           AS item_name,
               i.category       AS item_category,
               i.location       AS item_location,
               i.image_filename AS item_image
        FROM claims c
        JOIN items i ON c.item_id = i.id
        WHERE c.claimant_id = ?
        ORDER BY c.created_at DESC
    """, (user_id,))

    rows = cursor.fetchall()
    conn.close()

    return [dict(row) for row in rows]


def confirm_claim_by_user(claim_id: int, claimant_id: int) -> bool:
    """Mark a claim as confirmed (physically received) by the user."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        UPDATE claims SET confirmed_by_user = 1
        WHERE id = ? AND claimant_id = ? AND status = 'approved'
    """, (claim_id, claimant_id))
    conn.commit()
    updated = cursor.rowcount > 0
    conn.close()
    return updated

def get_claims_for_finder(finder_user_id: int) -> list[dict]:
    """
    Retrieves all claim requests for items that the given user reported as found.
    Used so the finder can see who has claimed their found item.
    """
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT c.*,
               i.name           AS item_name,
               i.category       AS item_category,
               i.image_filename AS item_image,
               i.location       AS item_location,
               u.full_name      AS claimant_full_name,
               u.email          AS claimant_email,
               u.id             AS claimant_user_id
        FROM claims c
        JOIN items i ON c.item_id     = i.id
        JOIN users u ON c.claimant_id = u.id
        WHERE i.reported_by = ?
        ORDER BY c.created_at DESC
    """, (finder_user_id,))

    rows = cursor.fetchall()
    conn.close()
    return [dict(row) for row in rows]


def finder_respond_to_claim(claim_id: int, finder_id: int, action: str) -> dict | None:
    """
    Allows the finder to accept or reject a claim.
    Returns the updated claim dict, or None if not authorized.

    action: 'accepted' | 'rejected'
    """
    conn = get_connection()
    cursor = conn.cursor()

    # Verify finder owns the item
    cursor.execute("""
        SELECT c.*, i.reported_by, i.name AS item_name
        FROM claims c
        JOIN items i ON i.id = c.item_id
        WHERE c.id = ?
    """, (claim_id,))
    row = cursor.fetchone()
    if not row:
        conn.close()
        return None

    claim = dict(row)
    if claim["reported_by"] != finder_id:
        conn.close()
        return None

    new_status = "accepted" if action == "accepted" else "rejected"
    cursor.execute("""
        UPDATE claims SET status = ?, reviewed_by = ?
        WHERE id = ?
    """, (new_status, finder_id, claim_id))
    conn.commit()
    conn.close()

    claim["status"] = new_status
    return claim
