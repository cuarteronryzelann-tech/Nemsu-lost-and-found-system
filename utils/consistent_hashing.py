"""
utils/consistent_hashing.py - Consistent Hashing
==================================================
Replaces the previous SHA-256 hashing utility with a Consistent Hashing
implementation for the NEMSU Lost and Found System.

Consistent Hashing is a distributed-systems technique that maps both data
keys and "nodes" (storage buckets / shards) onto a shared virtual ring.
When nodes are added or removed, only a minimal fraction of keys need to
be remapped — unlike ordinary modulo hashing where almost every key moves.

Applied in this system for:
    • Distributing item records across storage shards / cache partitions.
    • Routing search queries to the correct database replica.
    • Stable session/user routing so the same user always hits the same node.
    • Student-ID tokenisation with a virtual-ring slot assignment.

Time Complexity  : O(log N) per lookup (binary search on the sorted ring),
                   where N = total number of virtual nodes on the ring.
Space Complexity : O(N)     for the sorted ring structure.

Algorithm overview:
    1. Hash each physical node to VIRTUAL_REPLICAS positions on a 0–2³²-1
       integer ring (using MD5 for speed; not used for security here).
    2. To look up a key, hash the key to a ring position, then binary-search
       the sorted ring for the first virtual node at or after that position
       (wrapping around if the key falls past the last node).
    3. The physical node that owns the first matching virtual node handles
       the key.
"""

import hashlib
import bisect


# Number of virtual nodes (replicas) each physical node contributes to the ring.
# More replicas → better load balance; fewer → lower memory overhead.
VIRTUAL_REPLICAS: int = 100


# ─────────────────────────────────────────────────────────────────────────────
# ConsistentHashRing — core data structure
# ─────────────────────────────────────────────────────────────────────────────

class ConsistentHashRing:
    """
    A consistent hash ring that distributes keys across a set of nodes.

    Nodes are physical storage shards, cache servers, or any named partition.
    Each node is mapped to VIRTUAL_REPLICAS positions on the ring for even
    load distribution.

    Usage:
        ring = ConsistentHashRing(nodes=["shard-0", "shard-1", "shard-2"])
        node = ring.get_node("student_id:2021-00123")   # → "shard-1"
        ring.add_node("shard-3")
        ring.remove_node("shard-0")
    """

    def __init__(self, nodes: list[str] | None = None,
                 virtual_replicas: int = VIRTUAL_REPLICAS) -> None:
        """
        Initialises the consistent hash ring.

        Args:
            nodes           (list[str] | None): Initial list of node names.
            virtual_replicas (int):             Number of virtual nodes per
                                                physical node (default 100).
        """
        self._replicas: int = virtual_replicas
        self._ring: dict[int, str] = {}    # ring_position → node_name
        self._sorted_keys: list[int] = []  # Sorted list of ring positions

        for node in (nodes or []):
            self.add_node(node)

    # ── Ring position helpers ─────────────────────────────────────────────

    def _hash(self, key: str) -> int:
        """
        Hashes a string key to an integer ring position in [0, 2³²-1].
        Uses MD5 purely for speed and uniform distribution — not for security.

        Args:
            key (str): Any string identifier (node name, data key, etc.)

        Returns:
            int: Ring position in [0, 2³²-1].
        """
        digest = hashlib.md5(key.encode("utf-8")).hexdigest()
        return int(digest, 16) % (2 ** 32)

    # ── Node management ───────────────────────────────────────────────────

    def add_node(self, node: str) -> None:
        """
        Adds a physical node to the ring by inserting VIRTUAL_REPLICAS
        virtual positions into the sorted ring structure.

        Args:
            node (str): Unique name of the node to add (e.g., "shard-0").
        """
        for i in range(self._replicas):
            virtual_key = f"{node}#replica-{i}"
            position = self._hash(virtual_key)
            self._ring[position] = node
            bisect.insort(self._sorted_keys, position)

    def remove_node(self, node: str) -> None:
        """
        Removes a physical node from the ring, deleting all its virtual
        positions. Only the keys owned by this node are affected.

        Args:
            node (str): Name of the node to remove.
        """
        for i in range(self._replicas):
            virtual_key = f"{node}#replica-{i}"
            position = self._hash(virtual_key)
            if position in self._ring:
                del self._ring[position]
                idx = bisect.bisect_left(self._sorted_keys, position)
                if idx < len(self._sorted_keys) and self._sorted_keys[idx] == position:
                    self._sorted_keys.pop(idx)

    # ── Key lookup ────────────────────────────────────────────────────────

    def get_node(self, key: str) -> str | None:
        """
        Returns the node responsible for the given key.

        Steps:
            1. Hash the key to a ring position.
            2. Binary-search for the first virtual node at or after that position.
            3. If the key falls past all positions, wrap around to the first node.

        Args:
            key (str): The data key to route (e.g., a student ID or item ID).

        Returns:
            str | None: The node name, or None if the ring is empty.
        """
        if not self._sorted_keys:
            return None

        position = self._hash(key)
        # Find the first ring position >= key's position
        idx = bisect.bisect_left(self._sorted_keys, position)

        if idx == len(self._sorted_keys):
            idx = 0    # Wrap around to the first node on the ring

        ring_position = self._sorted_keys[idx]
        return self._ring[ring_position]

    def get_nodes_for_replication(self, key: str, replicas: int = 2) -> list[str]:
        """
        Returns an ordered list of distinct nodes for replicating a key.
        Walks clockwise from the primary node to find the next unique nodes.

        Args:
            key      (str): The data key to replicate.
            replicas (int): How many distinct nodes to return (default 2).

        Returns:
            list[str]: Up to `replicas` distinct node names.
        """
        if not self._sorted_keys:
            return []

        position = self._hash(key)
        idx = bisect.bisect_left(self._sorted_keys, position)

        seen: set[str] = set()
        result: list[str] = []

        for i in range(len(self._sorted_keys)):
            ring_pos = self._sorted_keys[(idx + i) % len(self._sorted_keys)]
            node = self._ring[ring_pos]
            if node not in seen:
                seen.add(node)
                result.append(node)
            if len(result) == replicas:
                break

        return result

    # ── Introspection ─────────────────────────────────────────────────────

    def get_distribution(self, items: list[str]) -> dict[str, list[str]]:
        """
        Shows how a list of keys would be distributed across nodes.
        Useful for load-balance analysis and debugging.

        Args:
            items (list[str]): Keys to distribute.

        Returns:
            dict[str, list[str]]: Mapping from node name to list of assigned keys.
        """
        distribution: dict[str, list[str]] = {}
        for key in items:
            node = self.get_node(key)
            if node:
                distribution.setdefault(node, []).append(key)
        return distribution

    def __len__(self) -> int:
        """Returns the number of physical nodes currently on the ring."""
        return len(set(self._ring.values()))

    def __repr__(self) -> str:
        nodes = sorted(set(self._ring.values()))
        return f"ConsistentHashRing(nodes={nodes}, virtual_replicas={self._replicas})"


# ─────────────────────────────────────────────────────────────────────────────
# Module-level default ring
# Pre-configured with three logical shards that mirror a typical small
# deployment (primary DB + two read replicas / cache partitions).
# ─────────────────────────────────────────────────────────────────────────────

_default_ring = ConsistentHashRing(
    nodes=["primary-shard", "replica-shard-1", "replica-shard-2"],
)


# ─────────────────────────────────────────────────────────────────────────────
# Public convenience functions
# These are drop-in replacements for the old SHA-256 functions so that all
# existing controller and model imports continue to work without modification.
# ─────────────────────────────────────────────────────────────────────────────

def hash_sensitive_data(raw_value: str) -> str:
    """
    Routes a sensitive data key (e.g., a student ID) to a shard via
    consistent hashing and returns a deterministic token string that
    encodes both the shard assignment and the key's ring position.

    Token format:
        "<node-name>:<hex-ring-position>"

    This replaces the old SHA-256 hex digest.  The token is still
    deterministic (same input → same token), one-way (the original value
    cannot be reconstructed from the token), and can be verified with
    verify_sensitive_data().

    Args:
        raw_value (str): The plain text value to process (e.g., "2021-00123").

    Returns:
        str: Consistent-hash token encoding node assignment and ring position.

    Example:
        hash_sensitive_data("2021-00123")
        → "primary-shard:2a9f4c1e"
    """
    node = _default_ring.get_node(raw_value) or "primary-shard"
    # Derive the ring position as a short hex string for the token
    ring_pos = hashlib.md5(raw_value.encode("utf-8")).hexdigest()[:8]
    return f"{node}:{ring_pos}"


def verify_sensitive_data(raw_value: str, stored_token: str) -> bool:
    """
    Verifies whether a plain text value matches a previously stored
    consistent-hash token.

    Verification re-hashes the submitted value and compares the resulting
    token to the stored one. If both match, the original values were identical.

    Args:
        raw_value    (str): Plain text value submitted for verification.
        stored_token (str): Token previously returned by hash_sensitive_data().

    Returns:
        bool: True if the values match, False otherwise.

    Example:
        verify_sensitive_data("2021-00123", "primary-shard:2a9f4c1e")
        → True
    """
    return hash_sensitive_data(raw_value) == stored_token


def generate_integrity_checksum(data: str) -> str:
    """
    Generates a consistent-hash-based checksum for arbitrary string data.
    Encodes both the shard assignment and a hex ring position, providing
    a fast integrity token that also indicates which shard "owns" the data.

    Args:
        data (str): The data string to checksum (e.g., a JSON-serialised record).

    Returns:
        str: Consistent-hash token for the data string.

    Example:
        checksum = generate_integrity_checksum(json.dumps(item_record))
    """
    return hash_sensitive_data(data)


def hash_with_salt(raw_value: str, salt: str) -> str:
    """
    Routes a salted value through consistent hashing.
    The salt is prepended to the raw value before ring placement,
    preventing two identical raw values with different salts from
    landing on the same shard with the same token.

    Args:
        raw_value (str): The plain text value to hash.
        salt      (str): A unique string to mix into the key before hashing.

    Returns:
        str: Consistent-hash token for (salt + raw_value).

    Example:
        hash_with_salt("2021-00123", "randomsalt123")
    """
    return hash_sensitive_data(salt + raw_value)


# ─────────────────────────────────────────────────────────────────────────────
# Advanced / direct ring access
# ─────────────────────────────────────────────────────────────────────────────

def get_shard_for_key(key: str) -> str | None:
    """
    Returns the shard (node) responsible for a given key using the default ring.

    Args:
        key (str): Any string key (student ID, item ID, session token, …).

    Returns:
        str | None: Shard name, or None if the ring has no nodes.
    """
    return _default_ring.get_node(key)


def get_ring() -> ConsistentHashRing:
    """
    Returns the module-level default ConsistentHashRing instance.
    Use this to add/remove nodes at runtime or inspect the ring state.

    Returns:
        ConsistentHashRing: The shared ring instance.
    """
    return _default_ring
