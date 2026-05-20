"""
controllers/item_controller.py - Shared Item Routes
====================================================
Handles item detail views accessible to both students and admins.
Provides shared API-style endpoints used across both dashboards.

Routes:
    GET /items/<item_id>  → View full details of a specific item
"""

from flask import Blueprint, render_template, redirect, url_for, session
from models.item_model import get_item_by_id
from models.user_model import get_user_by_id

item_bp = Blueprint("item", __name__, url_prefix="/items")


@item_bp.route("/<int:item_id>")
def item_detail(item_id: int):
    """
    Renders the full detail page for a specific item.
    Accessible to both authenticated students and admins.
    Unauthenticated users are redirected to the login page.

    Loads:
        - Full item record from the database.
        - Reporter's name (the student who submitted the report).

    Args:
        item_id (int): The database ID of the item to display.

    Returns:
        Response: Rendered item detail page, or redirect to login/search
                  if the item does not exist or access is unauthorized.
    """
    # Require authentication to view item details
    if "user" not in session:
        return redirect(url_for("auth.login"))

    # Fetch the item from the database
    item = get_item_by_id(item_id)

    if not item:
        # Item does not exist — redirect to search with an appropriate signal
        return redirect(url_for("user.search_items"))

    # Load the name of the student who reported this item (for display)
    reporter = None
    if item.get("reported_by"):
        reporter = get_user_by_id(item["reported_by"])

    return render_template("item_detail.html", item=item, reporter=reporter)
