"""Append-only JSONL ledger with a SHA-256 hash chain.

The hash of an entry covers every field except ``hash`` itself, serialized
with sorted keys and no extra whitespace. The first entry commits to a
genesis value of 64 zeros. Each later entry commits to the previous hash.
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

GENESIS_HASH = "0" * 64
HASH_ALG = "sha256"


class LedgerError(Exception):
    """The ledger cannot be read, extended, or trusted."""


def canonical_bytes(body: dict[str, Any]) -> bytes:
    """Serialize ``body`` so the same object always yields the same bytes."""
    encoded = json.dumps(
        body,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )
    return encoded.encode("utf-8")


def entry_hash(entry: dict[str, Any]) -> str:
    """SHA-256 hex digest of every field except ``hash``."""
    body = {key: value for key, value in entry.items() if key != "hash"}
    return hashlib.sha256(canonical_bytes(body)).hexdigest()


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _missing_newline_prefix(descriptor: int, index: int) -> bytes:
    """Bytes to write before a new record so it stays on its own line.

    An empty chain truncates leftover whitespace. A non-empty chain that
    lost its trailing newline gets that newline back before the new record.
    """
    if index == 0:
        os.ftruncate(descriptor, 0)
        return b""
    size = os.lseek(descriptor, 0, os.SEEK_END)
    if size == 0:
        return b""
    os.lseek(descriptor, size - 1, os.SEEK_SET)
    if os.read(descriptor, 1) == b"\n":
        return b""
    return b"\n"


def record_lines(text: str) -> list[str]:
    """Split on the physical newline only.

    ``str.splitlines`` also splits on Unicode separators such as U+2028.
    Those characters are legal inside a JSON string, so they must stay
    inside the record. A trailing newline is the delimiter after the last
    record, not an extra blank record.
    """
    if text.strip() == "":
        return []
    parts = text.split("\n")
    if parts[-1] == "":
        parts.pop()
    return parts


Mismatch = tuple[str | None, str | None]


@dataclass(frozen=True)
class VerifyResult:
    """What ``verify`` found in one ledger file."""

    ok: bool
    path: str
    entries: int
    head: str | None
    failure_index: int | None
    reason: str | None
    mismatch: Mismatch | None = None

    @property
    def expected(self) -> str | None:
        """Value the check wanted, when a comparison failed."""
        if self.mismatch is None:
            return None
        return self.mismatch[0]

    @property
    def found(self) -> str | None:
        """Value the check actually saw, when a comparison failed."""
        if self.mismatch is None:
            return None
        return self.mismatch[1]


def _failure(
    path: Path,
    index: int | None,
    entries_before: int,
    reason: str,
    mismatch: Mismatch,
) -> VerifyResult:
    return VerifyResult(
        ok=False,
        path=str(path),
        entries=entries_before,
        head=None,
        failure_index=index,
        reason=reason,
        mismatch=mismatch,
    )


def _parse_line(line: str) -> tuple[dict[str, Any] | None, Mismatch | None, str | None]:
    """Return ``(entry, None, None)`` or ``(None, mismatch, reason)``."""
    if not line.strip():
        return None, (None, None), "blank line inside the ledger"
    try:
        parsed = json.loads(line)
    except json.JSONDecodeError as exc:
        return None, (None, line[:80]), f"invalid JSON: {exc.msg}"
    if not isinstance(parsed, dict):
        found = type(parsed).__name__
        return None, ("object", found), "entry is not a JSON object"
    return parsed, None, None


def _chain_problem(
    parsed: dict[str, Any],
    index: int,
    previous_hash: str,
) -> tuple[str, Mismatch] | None:
    """Return a reason and the expected/found pair, or None when the entry fits."""
    if parsed.get("index") != index:
        mismatch = (str(index), str(parsed.get("index")))
        return "index field does not match the line position", mismatch
    found_prev = parsed.get("prev_hash")
    if found_prev != previous_hash:
        return (
            "prev_hash does not match the previous entry's hash",
            (previous_hash, str(found_prev)),
        )
    computed = entry_hash(parsed)
    stored = parsed.get("hash")
    if stored != computed:
        return "stored hash does not match the entry contents", (computed, str(stored))
    return None


def _check_entry(
    path: Path,
    index: int,
    line: str,
    previous_hash: str,
) -> tuple[VerifyResult | None, str | None]:
    """Return ``(failure, None)`` or ``(None, entry_hash)``."""
    parsed, mismatch, reason = _parse_line(line)
    if reason is not None:
        return _failure(path, index, index, reason, mismatch or (None, None)), None
    problem = _chain_problem(parsed or {}, index, previous_hash)
    if problem is not None:
        chain_reason, chain_mismatch = problem
        return _failure(path, index, index, chain_reason, chain_mismatch), None
    return None, entry_hash(parsed or {})


def verify(path: str | Path) -> VerifyResult:
    """Walk the chain and stop at the first entry that does not check out.

    A missing file is a failure. An empty file is a valid ledger with no
    entries. A content edit that leaves the stored hash untouched fails the
    hash check. An edit that recomputes that entry's hash but not the next
    entry's ``prev_hash`` fails the link check on the next line.
    """
    ledger_path = Path(path)
    if not ledger_path.exists():
        return _failure(ledger_path, None, 0, "ledger file not found", (None, None))
    text = ledger_path.read_text(encoding="utf-8")
    if text.strip() == "":
        return VerifyResult(
            ok=True,
            path=str(ledger_path),
            entries=0,
            head=None,
            failure_index=None,
            reason=None,
        )
    previous = GENESIS_HASH
    head: str | None = None
    count = 0
    for index, line in enumerate(record_lines(text)):
        failure, digest = _check_entry(ledger_path, index, line, previous)
        if failure is not None:
            return failure
        previous = digest or previous
        head = digest
        count += 1
    return VerifyResult(
        ok=True,
        path=str(ledger_path),
        entries=count,
        head=head,
        failure_index=None,
        reason=None,
    )


def read_entries(path: str | Path) -> list[dict[str, Any]]:
    """Parse every JSON object in the file. Does not check the hash chain."""
    ledger_path = Path(path)
    if not ledger_path.exists():
        raise LedgerError(f"ledger not found: {ledger_path}")
    text = ledger_path.read_text(encoding="utf-8")
    if text.strip() == "":
        return []
    entries: list[dict[str, Any]] = []
    for index, line in enumerate(record_lines(text)):
        if not line.strip():
            raise LedgerError(f"blank line at index {index}")
        try:
            parsed = json.loads(line)
        except json.JSONDecodeError as exc:
            raise LedgerError(f"invalid JSON at index {index}: {exc.msg}") from exc
        if not isinstance(parsed, dict):
            raise LedgerError(f"entry {index} is not a JSON object")
        entries.append(parsed)
    return entries


class Ledger:
    """Append-only writer. Refuses to extend a chain that does not verify."""

    def __init__(
        self,
        path: str | Path,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.path = Path(path)
        self._clock = clock or _utc_now

    def _position(self) -> tuple[int, str]:
        """Next index and the hash it must commit to. Call this under the lock."""
        if not self.path.exists() or self.path.stat().st_size == 0:
            return 0, GENESIS_HASH
        report = verify(self.path)
        if not report.ok:
            raise LedgerError(
                "refusing to append; ledger is broken at "
                f"index {report.failure_index}: {report.reason}"
            )
        if report.entries == 0:
            return 0, GENESIS_HASH
        previous = report.head if report.head is not None else GENESIS_HASH
        return report.entries, previous

    def _seal(
        self,
        *,
        index: int,
        previous: str,
        step: str,
        session_id: str,
        payload: dict[str, Any],
    ) -> tuple[dict[str, Any], bytes]:
        stamped = self._clock()
        if stamped.tzinfo is None:
            raise LedgerError("ledger clock must return a timezone-aware datetime")
        entry: dict[str, Any] = {
            "index": index,
            "timestamp": stamped.isoformat(),
            "session_id": session_id,
            "step": step,
            "hash_alg": HASH_ALG,
            "payload": payload,
            "prev_hash": previous,
        }
        try:
            entry["hash"] = entry_hash(entry)
            line = canonical_bytes(entry)
        except ValueError as exc:
            raise LedgerError(f"entry is not strict JSON: {exc}") from exc
        return entry, line

    def append(
        self,
        *,
        step: str,
        session_id: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        """Seal ``payload`` as the next entry and write it as one JSON line.

        An exclusive lock covers the read of the current head and the write,
        so two processes cannot seal the same index. A new file is mode 0600.
        """
        self.path.parent.mkdir(parents=True, exist_ok=True)
        created = not self.path.exists()
        descriptor = os.open(self.path, os.O_RDWR | os.O_CREAT | os.O_APPEND, 0o600)
        try:
            if created:
                os.fchmod(descriptor, 0o600)
            fcntl.flock(descriptor, fcntl.LOCK_EX)
            index, previous = self._position()
            entry, line = self._seal(
                index=index,
                previous=previous,
                step=step,
                session_id=session_id,
                payload=payload,
            )
            prefix = _missing_newline_prefix(descriptor, index)
            os.write(descriptor, prefix + line + b"\n")
            return entry
        finally:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
            os.close(descriptor)
