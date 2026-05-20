"""
utils/dfs_search.py - Depth-First Search (DFS) Algorithm
=========================================================
Replaces the previous Binary Search implementation with DFS for locating
items in the NEMSU Lost and Found System.

DFS is a graph/tree traversal algorithm that explores as far as possible
along each branch before backtracking. Here it is applied to a category
tree (a nested dictionary of category → list[item]) so that item lookups
can traverse the full item hierarchy rather than requiring a pre-sorted
flat list.

Applied when students search for lost items by name, category, or ID.

Time Complexity  : O(V + E) where V = nodes (items) and E = edges (category links)
                   In a flat category-tree this simplifies to O(n) over all items.
Space Complexity : O(D) where D = maximum depth of the category tree
                   (due to the recursion / explicit stack).

Key advantages over Binary Search:
    - Works on unsorted data — no pre-sorting step required.
    - Naturally traverses hierarchical / nested category structures.
    - Supports partial (substring) matching without an extra linear scan.
    - Easily extended to multi-level category trees (e.g. Electronics → Phones).
"""

from collections import defaultdict


# ─────────────────────────────────────────────────────────────────────────────
# Internal helpers
# ─────────────────────────────────────────────────────────────────────────────

def _build_category_tree(items: list[dict]) -> dict:
    """
    Groups a flat list of item dictionaries into a category tree.

    The tree has the shape:
        { category_name: [item, item, …], … }

    This is the graph that DFS traverses during searches.

    Args:
        items (list[dict]): Flat list of item records.

    Returns:
        dict: Mapping from category string to list of item dicts.
    """
    tree: dict = defaultdict(list)
    for item in items:
        category = (item.get("category") or "Uncategorised").strip()
        tree[category].append(item)
    return dict(tree)


def _dfs_collect(
    tree: dict,
    target_category: str | None,
    match_fn,
) -> list[dict]:
    """
    Core DFS traversal over the category tree.

    Traversal order:
        For each category node (visited in insertion order):
            • If target_category is given, only descend into matching categories.
            • Within the chosen category node, visit every item leaf and apply
              match_fn to decide whether to collect it.

    Args:
        tree            (dict):           Category tree built by _build_category_tree.
        target_category (str | None):     Restrict traversal to this category.
                                          Pass None to search all categories.
        match_fn        (callable):       Called with each item dict; return True
                                          to include the item in results.

    Returns:
        list[dict]: All items for which match_fn returned True.
    """
    results: list[dict] = []

    # Explicit stack of (category, items_in_category) — avoids recursion depth limits
    stack = list(tree.items())   # Each entry: (category_name, [items…])

    while stack:
        category, items_in_node = stack.pop()

        # ── Category filter ───────────────────────────────────────────────
        if target_category is not None:
            if category.strip().lower() != target_category.strip().lower():
                continue     # Skip this entire branch

        # ── Leaf inspection ───────────────────────────────────────────────
        for item in items_in_node:
            if match_fn(item):
                results.append(item)

    return results


# ─────────────────────────────────────────────────────────────────────────────
# Public API
# The function signatures below are drop-in replacements for the old
# binary_search functions so that all existing controller imports continue
# to work without modification.
# ─────────────────────────────────────────────────────────────────────────────

def dfs_search_by_name(items: list[dict], target_name: str) -> int:
    """
    Uses DFS to find the first item whose name exactly matches target_name
    (case-insensitive). Returns its index in the original list.

    DFS traversal:
        1. Build a category tree from the item list.
        2. Traverse every category node depth-first.
        3. At each leaf item, check for an exact name match.
        4. Return the original list index of the first match found.

    Args:
        items       (list[dict]): List of item dicts (any order).
        target_name (str):        The item name to search for.

    Returns:
        int: Index of the matched item in the original list, or -1 if not found.
    """
    target_lower = target_name.strip().lower()
    tree = _build_category_tree(items)

    def exact_match(item: dict) -> bool:
        return item.get("name", "").strip().lower() == target_lower

    matches = _dfs_collect(tree, target_category=None, match_fn=exact_match)

    if not matches:
        return -1

    # Return the index in the original flat list
    first_match = matches[0]
    for idx, item in enumerate(items):
        if item is first_match:
            return idx
    return -1


def dfs_search_by_category(items: list[dict], target_category: str) -> int:
    """
    Uses DFS to find the first item belonging to the given category.
    Returns its index in the original list.

    Unlike Binary Search, DFS does NOT require the list to be pre-sorted.

    Args:
        items           (list[dict]): List of item dicts (any order).
        target_category (str):        The category to search for
                                      (e.g., "Electronics").

    Returns:
        int: Index of the first matching item, or -1 if not found.
    """
    tree = _build_category_tree(items)

    def any_item(_: dict) -> bool:
        return True    # Accept the first item found in the matching category

    matches = _dfs_collect(tree, target_category=target_category, match_fn=any_item)

    if not matches:
        return -1

    first_match = matches[0]
    for idx, item in enumerate(items):
        if item is first_match:
            return idx
    return -1


def dfs_search_by_id(items: list[dict], target_id: int) -> int:
    """
    Uses DFS to find an item by its numeric ID.
    Returns the index of the matching item in the original list.

    Args:
        items     (list[dict]): List of item dicts (any order).
        target_id (int):        The item ID to search for.

    Returns:
        int: Index of the found item, or -1 if not found.
    """
    tree = _build_category_tree(items)

    def id_match(item: dict) -> bool:
        return item.get("id") == target_id

    matches = _dfs_collect(tree, target_category=None, match_fn=id_match)

    if not matches:
        return -1

    first_match = matches[0]
    for idx, item in enumerate(items):
        if item is first_match:
            return idx
    return -1


def collect_all_matches_by_name(items: list[dict], target_name: str) -> list[dict]:
    """
    Uses DFS to return ALL items whose name contains the target string
    (partial / substring match). Replaces the old binary-search-then-expand
    approach with a clean DFS traversal over the category tree.

    DFS traversal:
        1. Build a category tree from the full item list.
        2. Traverse every category node depth-first.
        3. At each leaf, test whether target_name is a substring of item name.
        4. Collect all matching items.

    This is the function most commonly called from user_controller.py for
    the "search items" feature.

    Args:
        items       (list[dict]): List of item dicts (any order).
        target_name (str):        Partial or full item name to match.

    Returns:
        list[dict]: All items whose name contains target_name (case-insensitive).
    """
    target_lower = target_name.strip().lower()
    tree = _build_category_tree(items)

    def substring_match(item: dict) -> bool:
        return target_lower in item.get("name", "").strip().lower()

    return _dfs_collect(tree, target_category=None, match_fn=substring_match)


def collect_all_matches_by_category(
    items: list[dict],
    target_category: str,
) -> list[dict]:
    """
    Uses DFS to return ALL items belonging to the specified category.
    Replaces the old binary-search-by-category + manual expansion approach.

    Args:
        items           (list[dict]): List of item dicts (any order).
        target_category (str):        The category to filter by.

    Returns:
        list[dict]: All items in the matching category.
    """
    tree = _build_category_tree(items)

    def any_item(_: dict) -> bool:
        return True

    return _dfs_collect(tree, target_category=target_category, match_fn=any_item)


# ─────────────────────────────────────────────────────────────────────────────
# Legacy aliases — keep old names working for any controller that still
# references binary_search_by_name / binary_search_by_category /
# binary_search_by_id directly.
# ─────────────────────────────────────────────────────────────────────────────
binary_search_by_name     = dfs_search_by_name
binary_search_by_category = dfs_search_by_category
binary_search_by_id       = dfs_search_by_id
