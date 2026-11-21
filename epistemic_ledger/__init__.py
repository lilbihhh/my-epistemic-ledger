"""Auditable reasoning ledger.

Every step of a reasoning run is appended to a JSONL file. Each line stores
the SHA-256 hash of the line before it, so a later edit is detectable.
"""

__version__ = "0.1.0"
