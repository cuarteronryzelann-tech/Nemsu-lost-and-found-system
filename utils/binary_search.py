# """
# utils/binary_search.py - Binary Search Algorithm
# =================================================
# Implements binary search for efficiently locating items
# in a sorted list. Applied when students search for lost items
# by name, category, or ID in the NEMSU Lost and Found System.

# Time Complexity  : O(log n) — much faster than linear search for large lists
# Space Complexity : O(1)    — no extra memory needed beyond input

# NOTE: The item list MUST be sorted before calling binary search.
#       Use quick_sort.py to sort the list prior to searching.
# """


# def binary_search_by_name(items: list[dict], target_name: str) -> int:
#     """
#     Performs binary search on a list of items sorted alphabetically by name.
#     Returns the index of the first matching item (case-insensitive).

#     How it works:
#         1. Start with the full list (low=0, high=len-1).
#         2. Check the middle element.
#         3. If the middle matches, return its index.
#         4. If target is alphabetically less, search the LEFT half.
#         5. If target is alphabetically greater, search the RIGHT half.
#         6. Repeat until found or the search space is empty.

#     Args:
#         items       (list[dict]): List of item dicts sorted by "name" ascending.
#         target_name (str):        The item name to search for.

#     Returns:
#         int: Index of the found item in the list, or -1 if not found.
#     """
#     low = 0
#     high = len(items) - 1
#     target_lower = target_name.strip().lower()  # Normalize for case-insensitive matching

#     while low <= high:
#         mid = (low + high) // 2                         # Compute midpoint index
#         mid_name = items[mid]["name"].strip().lower()   # Normalize midpoint name

#         if mid_name == target_lower:
#             # Exact match found — return the index
#             return mid
#         elif mid_name < target_lower:
#             # Target is in the RIGHT half — eliminate the left
#             low = mid + 1
#         else:
#             # Target is in the LEFT half — eliminate the right
#             high = mid - 1

#     # Target not found in the list
#     return -1


# def binary_search_by_category(items: list[dict], target_category: str) -> int:
#     """
#     Performs binary search on a list of items sorted alphabetically by category.
#     Returns the index of the first matching item (case-insensitive).

#     NOTE: Items must be pre-sorted by "category" field before calling this.

#     Args:
#         items           (list[dict]): List of item dicts sorted by "category" ascending.
#         target_category (str):        The category to search for (e.g., "Electronics").

#     Returns:
#         int: Index of the found item, or -1 if not found.
#     """
#     low = 0
#     high = len(items) - 1
#     target_lower = target_category.strip().lower()

#     while low <= high:
#         mid = (low + high) // 2
#         mid_category = items[mid]["category"].strip().lower()

#         if mid_category == target_lower:
#             return mid
#         elif mid_category < target_lower:
#             low = mid + 1
#         else:
#             high = mid - 1

#     return -1


# def binary_search_by_id(items: list[dict], target_id: int) -> int:
#     """
#     Performs binary search on a list of items sorted by their numeric ID.
#     Returns the index of the matching item.

#     NOTE: Items must be pre-sorted by "id" field (ascending) before calling this.

#     Args:
#         items     (list[dict]): List of item dicts sorted by "id" ascending.
#         target_id (int):        The item ID to search for.

#     Returns:
#         int: Index of the found item, or -1 if not found.
#     """
#     low = 0
#     high = len(items) - 1

#     while low <= high:
#         mid = (low + high) // 2
#         mid_id = items[mid]["id"]

#         if mid_id == target_id:
#             return mid           # Match found
#         elif mid_id < target_id:
#             low = mid + 1        # Search right half
#         else:
#             high = mid - 1       # Search left half

#     return -1


# def collect_all_matches_by_name(items: list[dict], target_name: str) -> list[dict]:
#     """
#     Extends binary_search_by_name to return ALL items whose name contains
#     the target string (partial/substring match). Useful for search-as-you-type.

#     Strategy:
#         1. Find any one match via binary search.
#         2. Expand left and right from that index to collect all adjacent matches.
#         3. Also scan the full list for substring matches (non-binary fallback).

#     Args:
#         items       (list[dict]): Sorted list of item dicts.
#         target_name (str):        Partial or full item name to match.

#     Returns:
#         list[dict]: All items whose name contains the target string.
#     """
#     results = []
#     target_lower = target_name.strip().lower()

#     # Linear scan for substring matching (binary search handles only exact/prefix)
#     # This ensures partial keywords like "bag" match "Backpack", "Handbag", etc.
#     for item in items:
#         if target_lower in item["name"].strip().lower():
#             results.append(item)

#     return results
