# """
# utils/quick_sort.py - Quick Sort Algorithm
# ==========================================
# Implements the quick sort algorithm for sorting lost/found items
# by various criteria: date reported, item name, category, or status.

# Applied in the NEMSU Lost and Found System whenever a student or
# admin wants to reorder the displayed item list.

# Time Complexity  : O(n log n) average, O(n²) worst case
# Space Complexity : O(log n) due to recursive call stack

# The pivot is chosen as the last element in each partition (classic Lomuto scheme).
# """


# def quick_sort(items: list[dict], key: str, ascending: bool = True) -> list[dict]:
#     """
#     Entry point for the quick sort algorithm.
#     Sorts a list of item dictionaries by the specified key field.

#     Args:
#         items     (list[dict]): The list of item records to sort (not mutated).
#         key       (str):        The dict field to sort by (e.g., "name", "date_reported").
#         ascending (bool):       True = A→Z / oldest→newest; False = Z→A / newest→oldest.

#     Returns:
#         list[dict]: A new sorted list of items (original list is not modified).

#     Example:
#         sorted_items = quick_sort(items, key="date_reported", ascending=False)
#     """
#     # Work on a shallow copy so the original list is not mutated
#     items_copy = list(items)
#     _quick_sort_recursive(items_copy, 0, len(items_copy) - 1, key)

#     # Reverse if descending order is requested
#     if not ascending:
#         items_copy.reverse()

#     return items_copy


# def _quick_sort_recursive(items: list[dict], low: int, high: int, key: str) -> None:
#     """
#     Recursive helper that performs in-place quick sort on a subarray.
#     Divides the list around a pivot and recursively sorts each partition.

#     Args:
#         items (list[dict]): The list being sorted (mutated in place).
#         low   (int):        Start index of the current subarray.
#         high  (int):        End index of the current subarray.
#         key   (str):        The field name to compare items by.
#     """
#     if low < high:
#         # Partition the array and get the final sorted position of the pivot
#         pivot_index = _partition(items, low, high, key)

#         # Recursively sort the elements before and after the pivot
#         _quick_sort_recursive(items, low, pivot_index - 1, key)   # Left partition
#         _quick_sort_recursive(items, pivot_index + 1, high, key)  # Right partition


# def _partition(items: list[dict], low: int, high: int, key: str) -> int:
#     """
#     Lomuto partition scheme: selects the last element as the pivot,
#     then rearranges the subarray so all elements ≤ pivot come before it
#     and all elements > pivot come after it.

#     Args:
#         items (list[dict]): The list being sorted (mutated in place).
#         low   (int):        Start index of the subarray.
#         high  (int):        End index (pivot is items[high]).
#         key   (str):        The field to compare.

#     Returns:
#         int: The final sorted index of the pivot element.
#     """
#     pivot_value = _get_sort_value(items[high], key)  # Choose rightmost element as pivot
#     i = low - 1  # Pointer for the boundary of elements ≤ pivot

#     for j in range(low, high):
#         # If current element belongs on the left side of the pivot
#         if _get_sort_value(items[j], key) <= pivot_value:
#             i += 1
#             items[i], items[j] = items[j], items[i]  # Swap into the left partition

#     # Place pivot in its correct sorted position
#     items[i + 1], items[high] = items[high], items[i + 1]
#     return i + 1


# def _get_sort_value(item: dict, key: str):
#     """
#     Extracts and normalizes the sort value from an item dict.
#     Handles None values and converts strings to lowercase for
#     consistent alphabetical comparison.

#     Args:
#         item (dict): A single item record dictionary.
#         key  (str):  The field name to extract (e.g., "name", "date_reported").

#     Returns:
#         str | int | float: Normalized comparable value for sorting.
#     """
#     value = item.get(key, "")

#     if value is None:
#         return ""  # Treat missing values as empty strings (sorts to the beginning)

#     if isinstance(value, str):
#         return value.lower().strip()  # Lowercase for case-insensitive alphabetical sort

#     return value  # Return numeric values (e.g., id) unchanged


# # ─────────────────────────────────────────────────────────────────────────────
# # Convenience Wrapper Functions
# # Each function wraps quick_sort with a pre-set key for common sort operations.
# # ─────────────────────────────────────────────────────────────────────────────

# def sort_by_date(items: list[dict], ascending: bool = True) -> list[dict]:
#     """
#     Sorts items by the date they were reported.
#     Default: oldest first (ascending=True). Set ascending=False for newest first.

#     Args:
#         items     (list[dict]): List of item records.
#         ascending (bool):       Sort direction.

#     Returns:
#         list[dict]: Items sorted by "date_reported".
#     """
#     return quick_sort(items, key="date_reported", ascending=ascending)


# def sort_by_name(items: list[dict], ascending: bool = True) -> list[dict]:
#     """
#     Sorts items alphabetically by item name.
#     Default: A → Z (ascending=True).

#     Args:
#         items     (list[dict]): List of item records.
#         ascending (bool):       Sort direction.

#     Returns:
#         list[dict]: Items sorted by "name".
#     """
#     return quick_sort(items, key="name", ascending=ascending)


# def sort_by_category(items: list[dict], ascending: bool = True) -> list[dict]:
#     """
#     Sorts items alphabetically by category.
#     Useful for grouping items of the same type together.

#     Args:
#         items     (list[dict]): List of item records.
#         ascending (bool):       Sort direction.

#     Returns:
#         list[dict]: Items sorted by "category".
#     """
#     return quick_sort(items, key="category", ascending=ascending)


# def sort_by_status(items: list[dict], ascending: bool = True) -> list[dict]:
#     """
#     Sorts items alphabetically by their status field.
#     Useful for admins to group pending, listed, and claimed items.

#     Args:
#         items     (list[dict]): List of item records.
#         ascending (bool):       Sort direction.

#     Returns:
#         list[dict]: Items sorted by "status".
#     """
#     return quick_sort(items, key="status", ascending=ascending)
