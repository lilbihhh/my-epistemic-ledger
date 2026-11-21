"""Merkle roots for a session, algorithm ``merkle-sha256-v1``.

Leaves are the raw 32-byte entry hashes, in ledger order. A single leaf is
the root unchanged. An odd level duplicates its last node, then each parent
is SHA-256 of the left child bytes followed by the right child bytes.
"""

from __future__ import annotations

import hashlib

MERKLE_ALGORITHM = "merkle-sha256-v1"


def _digest(left: bytes, right: bytes) -> bytes:
    return hashlib.sha256(left + right).digest()


def merkle_root(leaf_hashes: list[str]) -> str:
    """Hex SHA-256 Merkle root. An empty leaf list hashes the empty byte string."""
    if not leaf_hashes:
        return hashlib.sha256(b"").hexdigest()
    level = [bytes.fromhex(item) for item in leaf_hashes]
    while len(level) > 1:
        if len(level) % 2 == 1:
            level.append(level[-1])
        level = [_digest(level[index], level[index + 1]) for index in range(0, len(level), 2)]
    return level[0].hex()
