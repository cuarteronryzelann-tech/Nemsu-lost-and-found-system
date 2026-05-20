# # """
# # utils/hashing.py - Hashing Utilities for Data Integrity
# # ========================================================
# # Provides hashing functions to protect sensitive data before
# # storage in the NEMSU Lost and Found System database.

# # Applied to: Student ID numbers stored in the users table.

# # Algorithm used: SHA-256 (Secure Hash Algorithm 256-bit)
# #     - Deterministic: same input → same hash (allows verification)
# #     - One-way: original value cannot be recovered from hash
# #     - Collision-resistant: no two different inputs produce the same hash

# # Why hash student IDs?
# #     Even though student IDs are not passwords, storing them as
# #     plaintext creates unnecessary exposure. Hashing ensures that
# #     even if the database is compromised, raw student IDs are safe.
# # """

# # import hashlib


# # def hash_sensitive_data(raw_value: str) -> str:
# #     """
# #     Hashes a plain text value using SHA-256 and returns the hex digest.
# #     Used for protecting student ID numbers before storing in the database.

# #     How SHA-256 works:
# #         1. The input string is encoded to bytes (UTF-8).
# #         2. SHA-256 applies a series of mathematical transformations.
# #         3. A fixed-length 64-character hexadecimal string is produced.

# #     Args:
# #         raw_value (str): The plain text value to hash (e.g., "2021-00123").

# #     Returns:
# #         str: 64-character SHA-256 hex digest of the input.

# #     Example:
# #         hash_sensitive_data("2021-00123")
# #         → "3a7bd3e2360a3d29eea436fcfb7e44c735d117c42d1c1835420b6b9942dd4f1b"
# #     """
# #     encoded = raw_value.encode("utf-8")        # Step 1: Convert string to bytes
# #     sha256_hash = hashlib.sha256(encoded)      # Step 2: Compute SHA-256 hash object
# #     return sha256_hash.hexdigest()             # Step 3: Return lowercase hex string


# # def verify_sensitive_data(raw_value: str, stored_hash: str) -> bool:
# #     """
# #     Verifies whether a plain text value matches a previously stored SHA-256 hash.
# #     Used during claim verification to confirm a student's submitted ID
# #     matches what is stored in the database.

# #     How verification works:
# #         Hash the submitted value and compare it to the stored hash.
# #         If both hashes match, the original values were identical.

# #     Args:
# #         raw_value   (str): The plain text value to verify (submitted by the student).
# #         stored_hash (str): The SHA-256 hash stored in the database.

# #     Returns:
# #         bool: True if the values match, False otherwise.

# #     Example:
# #         verify_sensitive_data("2021-00123", stored_hash_from_db)
# #         → True
# #     """
# #     computed_hash = hash_sensitive_data(raw_value)  # Re-hash the submitted value
# #     return computed_hash == stored_hash              # Compare both hashes


# # def generate_integrity_checksum(data: str) -> str:
# #     """
# #     Generates a SHA-256 checksum for arbitrary string data.
# #     Can be used to verify the integrity of any data blob (e.g., item records
# #     exported as JSON) to detect tampering or corruption.

# #     Args:
# #         data (str): The data string to checksum.

# #     Returns:
# #         str: SHA-256 hex digest of the data.

# #     Example:
# #         checksum = generate_integrity_checksum(json.dumps(item_record))
# #     """
# #     return hashlib.sha256(data.encode("utf-8")).hexdigest()


# # def hash_with_salt(raw_value: str, salt: str) -> str:
# #     """
# #     Hashes a value combined with a salt string.
# #     A salt is a unique random string added before hashing to prevent
# #     pre-computed hash attacks (rainbow table attacks).

# #     Usage: For future enhancement if stronger security is required.

# #     Args:
# #         raw_value (str): The plain text value to hash.
# #         salt      (str): A unique random string to mix into the hash.

# #     Returns:
# #         str: SHA-256 hex digest of (salt + raw_value).

# #     Example:
# #         hash_with_salt("2021-00123", "randomsalt123")
# #     """
# #     salted_input = salt + raw_value                          # Prepend salt to raw value
# #     encoded = salted_input.encode("utf-8")                   # Encode to bytes
# #     return hashlib.sha256(encoded).hexdigest()               # Hash and return digest




# """
# utils/hashing.py - Consistent Hashing
# =======================================
# Replaces SHA-256 with a Consistent Hashing implementation.
# All functions are self-contained in this file — no sibling imports needed.

# Consistent Hashing maps keys onto a virtual ring so that adding/removing
# nodes remaps only a minimal fraction of keys (unlike plain modulo hashing).

# Time Complexity  : O(log N) per lookup (binary search on sorted ring)
# Space Complexity : O(N)     for the ring structure
# """

# import hashlib
# import bisect

# VIRTUAL_REPLICAS = 100


# class ConsistentHashRing:
#     """A consistent hash ring distributing keys across named nodes."""

#     def __init__(self, nodes=None, virtual_replicas=VIRTUAL_REPLICAS):
#         self._replicas = virtual_replicas
#         self._ring = {}
#         self._sorted_keys = []
#         for node in (nodes or []):
#             self.add_node(node)

#     def _hash(self, key: str) -> int:
#         digest = hashlib.md5(key.encode("utf-8")).hexdigest()
#         return int(digest, 16) % (2 ** 32)

#     def add_node(self, node: str) -> None:
#         for i in range(self._replicas):
#             pos = self._hash(f"{node}#replica-{i}")
#             self._ring[pos] = node
#             bisect.insort(self._sorted_keys, pos)

#     def remove_node(self, node: str) -> None:
#         for i in range(self._replicas):
#             pos = self._hash(f"{node}#replica-{i}")
#             if pos in self._ring:
#                 del self._ring[pos]
#                 idx = bisect.bisect_left(self._sorted_keys, pos)
#                 if idx < len(self._sorted_keys) and self._sorted_keys[idx] == pos:
#                     self._sorted_keys.pop(idx)

#     def get_node(self, key: str):
#         if not self._sorted_keys:
#             return None
#         pos = self._hash(key)
#         idx = bisect.bisect_left(self._sorted_keys, pos)
#         if idx == len(self._sorted_keys):
#             idx = 0
#         return self._ring[self._sorted_keys[idx]]

#     def __len__(self):
#         return len(set(self._ring.values()))

#     def __repr__(self):
#         return f"ConsistentHashRing(nodes={sorted(set(self._ring.values()))}, replicas={self._replicas})"


# # Module-level default ring
# _default_ring = ConsistentHashRing(
#     nodes=["primary-shard", "replica-shard-1", "replica-shard-2"]
# )


# def hash_sensitive_data(raw_value: str) -> str:
#     """
#     Routes a value through consistent hashing and returns a deterministic token.
#     Token format: "<node>:<hex-ring-position>"
#     """
#     node = _default_ring.get_node(raw_value) or "primary-shard"
#     ring_pos = hashlib.md5(raw_value.encode("utf-8")).hexdigest()[:8]
#     return f"{node}:{ring_pos}"


# def verify_sensitive_data(raw_value: str, stored_token: str) -> bool:
#     """Verifies a plain text value against a stored consistent-hash token."""
#     return hash_sensitive_data(raw_value) == stored_token


# def generate_integrity_checksum(data: str) -> str:
#     """Generates a consistent-hash token for arbitrary string data."""
#     return hash_sensitive_data(data)


# def hash_with_salt(raw_value: str, salt: str) -> str:
#     """Routes a salted value through consistent hashing."""
#     return hash_sensitive_data(salt + raw_value)


# def get_shard_for_key(key: str):
#     """Returns the shard responsible for a given key."""
#     return _default_ring.get_node(key)


# def get_ring() -> ConsistentHashRing:
#     """Returns the module-level default ring instance."""
#     return _default_ring