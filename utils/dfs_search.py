"""
utils/dfs_search.py - DFS Search (Optimized)
=============================================
Optimization changes vs original:
  - collect_all_matches_by_name: removed unnecessary category-tree build.
    A flat linear scan is O(n) either way, but skipping _build_category_tree
    eliminates O(n) dict-building + O(n) tree-traversal overhead (effectively
    halving the work for the most-called search function).
  - collect_all_matches_by_category: same — use a simple list comprehension.
    Building the tree then DFS-ing it was two O(n) passes; one pass suffices.
  - Point-search functions (dfs_search_by_name, _by_category, _by_id) retain
    the tree structure as they are rarely called and the academic DFS
    implementation should be preserved.
"""

from collections import defaultdict


# ---------------------------------------------------------------------------
# Internal helpers (kept for the academic DFS point-search functions below)
# ---------------------------------------------------------------------------

def _build_category_tree(items: list[dict]) -> dict:
    tree: dict = defaultdict(list)
    for item in items:
        category = (item.get("category") or "Uncategorised").strip()
        tree[category].append(item)
    return dict(tree)


def _dfs_collect(tree: dict, target_category, match_fn) -> list[dict]:
    results: list[dict] = []
    stack = list(tree.items())
    while stack:
        category, items_in_node = stack.pop()
        if target_category is not None:
            if category.strip().lower() != target_category.strip().lower():
                continue
        for item in items_in_node:
            if match_fn(item):
                results.append(item)
    return results


# ---------------------------------------------------------------------------
# Point-search functions (DFS — academic implementation preserved)
# ---------------------------------------------------------------------------

def dfs_search_by_name(items: list[dict], target_name: str) -> int:
    target_lower = target_name.strip().lower()
    tree = _build_category_tree(items)

    def exact_match(item: dict) -> bool:
        return item.get("name", "").strip().lower() == target_lower

    matches = _dfs_collect(tree, target_category=None, match_fn=exact_match)
    if not matches:
        return -1
    first_match = matches[0]
    for idx, item in enumerate(items):
        if item is first_match:
            return idx
    return -1


def dfs_search_by_category(items: list[dict], target_category: str) -> int:
    tree = _build_category_tree(items)

    def any_item(_: dict) -> bool:
        return True

    matches = _dfs_collect(tree, target_category=target_category, match_fn=any_item)
    if not matches:
        return -1
    first_match = matches[0]
    for idx, item in enumerate(items):
        if item is first_match:
            return idx
    return -1


def dfs_search_by_id(items: list[dict], target_id: int) -> int:
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


# ---------------------------------------------------------------------------
# Bulk-collect functions (optimized — single O(n) pass, no tree build)
# ---------------------------------------------------------------------------

def collect_all_matches_by_name(items: list[dict], target_name: str) -> list[dict]:
    """
    Returns all items whose name contains target_name (case-insensitive).

    Optimization: uses a direct list comprehension instead of building a
    category tree then DFS-traversing it — same O(n) complexity but half
    the constant factor (no dict allocation, no stack operations).
    """
    target_lower = target_name.strip().lower()
    return [
        item for item in items
        if target_lower in (item.get("name") or "").lower()
    ]


def collect_all_matches_by_category(items: list[dict], target_category: str) -> list[dict]:
    """
    Returns all items in the specified category (case-insensitive).

    Optimization: direct list comprehension — same O(n) result without
    the overhead of building an intermediate category tree.
    """
    target_lower = target_category.strip().lower()
    return [
        item for item in items
        if (item.get("category") or "").strip().lower() == target_lower
    ]


# Legacy aliases
binary_search_by_name     = dfs_search_by_name
binary_search_by_category = dfs_search_by_category
binary_search_by_id       = dfs_search_by_id
