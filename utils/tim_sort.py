"""
utils/tim_sort.py - TimSort Algorithm
======================================
Replaces the previous Quick Sort implementation with TimSort for sorting
lost/found items by various criteria: date reported, item name, category,
or status.

TimSort is a hybrid stable sorting algorithm derived from merge sort and
insertion sort. It is the default algorithm used by Python's built-in
sort() and sorted() functions.

Applied in the NEMSU Lost and Found System whenever a student or admin
wants to reorder the displayed item list.

Time Complexity  : O(n log n) — best, average, and worst case
Space Complexity : O(n)       — due to merge step auxiliary storage

Key advantages over Quick Sort:
    - Stable sort (equal elements retain their original relative order)
    - Guaranteed O(n log n) worst case (Quick Sort degrades to O(n²))
    - Adaptive: approaches O(n) on nearly-sorted data
    - No risk of stack overflow from deep recursion on sorted input

Algorithm overview:
    1. Divide the array into small chunks called "runs" (size MIN_RUN = 32).
    2. Sort each run using Insertion Sort (fast for small arrays).
    3. Merge adjacent runs using a stable merge procedure until one sorted
       array remains.
"""

# Minimum run length. Runs shorter than this are extended with Insertion Sort.
# Python's actual TimSort uses 32–64; 32 is a safe, portable default.
MIN_RUN = 32


# ─────────────────────────────────────────────────────────────────────────────
# Internal helpers
# ─────────────────────────────────────────────────────────────────────────────

def _get_sort_value(item: dict, key: str):
    """
    Extracts and normalises the sort value from an item dictionary.
    Handles None values and converts strings to lowercase for
    consistent case-insensitive alphabetical comparison.

    Args:
        item (dict): A single item record dictionary.
        key  (str):  The field name to extract (e.g., "name", "date_reported").

    Returns:
        str | int | float: Normalised comparable value for sorting.
    """
    value = item.get(key, "")
    if value is None:
        return ""                        # Treat missing values as empty string
    if isinstance(value, str):
        return value.lower().strip()     # Case-insensitive alphabetical sort
    return value                         # Return numeric values unchanged


def _insertion_sort(items: list[dict], left: int, right: int, key: str) -> None:
    """
    Sorts a small subarray items[left..right] in place using Insertion Sort.
    This is efficient for small subarrays (the "run" phase of TimSort).

    Args:
        items (list[dict]): The list being sorted (mutated in place).
        left  (int):        Start index of the subarray.
        right (int):        End index of the subarray (inclusive).
        key   (str):        The field name to compare items by.
    """
    for i in range(left + 1, right + 1):
        temp = items[i]
        temp_val = _get_sort_value(temp, key)
        j = i - 1
        # Shift elements that are greater than temp one position to the right
        while j >= left and _get_sort_value(items[j], key) > temp_val:
            items[j + 1] = items[j]
            j -= 1
        items[j + 1] = temp


def _merge(items: list[dict], left: int, mid: int, right: int, key: str) -> None:
    """
    Merges two adjacent sorted subarrays items[left..mid] and
    items[mid+1..right] back into items[left..right] in sorted order.
    This is the merge phase of TimSort — it is stable (equal elements
    keep their original relative order).

    Args:
        items (list[dict]): The list being sorted (mutated in place).
        left  (int):        Start index of the left subarray.
        mid   (int):        End index of the left subarray.
        right (int):        End index of the right subarray.
        key   (str):        The field name to compare items by.
    """
    # Copy both halves into temporary arrays
    left_part  = items[left  : mid + 1]
    right_part = items[mid + 1 : right + 1]

    i = j = 0
    k = left

    # Merge back into items[], picking the smaller front element each time
    while i < len(left_part) and j < len(right_part):
        if _get_sort_value(left_part[i], key) <= _get_sort_value(right_part[j], key):
            items[k] = left_part[i]
            i += 1
        else:
            items[k] = right_part[j]
            j += 1
        k += 1

    # Copy any remaining elements from the left half
    while i < len(left_part):
        items[k] = left_part[i]
        i += 1
        k += 1

    # Copy any remaining elements from the right half
    while j < len(right_part):
        items[k] = right_part[j]
        j += 1
        k += 1


# ─────────────────────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────────────────────

def tim_sort(items: list[dict], key: str, ascending: bool = True) -> list[dict]:
    """
    Entry point for the TimSort algorithm.
    Sorts a list of item dictionaries by the specified key field.

    Algorithm steps:
        1. Sort each MIN_RUN-length chunk with Insertion Sort.
        2. Iteratively merge adjacent runs, doubling the run size each pass,
           until the entire array is sorted.

    Args:
        items     (list[dict]): The list of item records to sort (not mutated).
        key       (str):        The dict field to sort by
                                (e.g., "name", "date_reported", "category").
        ascending (bool):       True  = A→Z / oldest→newest;
                                False = Z→A / newest→oldest.

    Returns:
        list[dict]: A new sorted list (the original list is not modified).

    Example:
        sorted_items = tim_sort(items, key="date_reported", ascending=False)
    """
    items_copy = list(items)   # Shallow copy — original is never mutated
    n = len(items_copy)

    # ── Phase 1: Sort individual runs with Insertion Sort ─────────────────
    for start in range(0, n, MIN_RUN):
        end = min(start + MIN_RUN - 1, n - 1)
        _insertion_sort(items_copy, start, end, key)

    # ── Phase 2: Merge runs in increasingly large passes ──────────────────
    size = MIN_RUN
    while size < n:
        for left in range(0, n, size * 2):
            mid   = min(left + size - 1, n - 1)
            right = min(left + 2 * size - 1, n - 1)
            if mid < right:   # There is a right sub-run to merge into
                _merge(items_copy, left, mid, right, key)
        size *= 2

    # Reverse in place for descending order
    if not ascending:
        items_copy.reverse()

    return items_copy


# ─────────────────────────────────────────────────────────────────────────────
# Convenience wrapper functions
# Each wraps tim_sort with a pre-set key for common sort operations.
# The function signatures are identical to the old quick_sort wrappers so
# all existing controller imports continue to work without any changes.
# ─────────────────────────────────────────────────────────────────────────────

def sort_by_date(items: list[dict], ascending: bool = True) -> list[dict]:
    """
    Sorts items by the date they were reported.
    Default: oldest first (ascending=True). Set ascending=False for newest first.

    Args:
        items     (list[dict]): List of item records.
        ascending (bool):       Sort direction.

    Returns:
        list[dict]: Items sorted by "date_reported".
    """
    return tim_sort(items, key="date_reported", ascending=ascending)


def sort_by_name(items: list[dict], ascending: bool = True) -> list[dict]:
    """
    Sorts items alphabetically by item name.
    Default: A → Z (ascending=True).

    Args:
        items     (list[dict]): List of item records.
        ascending (bool):       Sort direction.

    Returns:
        list[dict]: Items sorted by "name".
    """
    return tim_sort(items, key="name", ascending=ascending)


def sort_by_category(items: list[dict], ascending: bool = True) -> list[dict]:
    """
    Sorts items alphabetically by category.
    Useful for grouping items of the same type together.

    Args:
        items     (list[dict]): List of item records.
        ascending (bool):       Sort direction.

    Returns:
        list[dict]: Items sorted by "category".
    """
    return tim_sort(items, key="category", ascending=ascending)


def sort_by_status(items: list[dict], ascending: bool = True) -> list[dict]:
    """
    Sorts items alphabetically by their status field.
    Useful for admins to group pending, listed, and claimed items.

    Args:
        items     (list[dict]): List of item records.
        ascending (bool):       Sort direction.

    Returns:
        list[dict]: Items sorted by "status".
    """
    return tim_sort(items, key="status", ascending=ascending)
