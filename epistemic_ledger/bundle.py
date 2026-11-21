"""Standalone export of a ledger for someone who does not have the original file."""

from __future__ import annotations

import json
from typing import Any

from epistemic_ledger.ledger import LedgerError, VerifyResult, read_entries
from epistemic_ledger.protocol import verify_entries, verify_protocol

BUNDLE_PROTOCOL = "epistemic-ledger"
BUNDLE_VERSION = "1.0"


def build_bundle(entries: list[dict[str, Any]]) -> dict[str, Any]:
    """Assemble the JSON document a third party can verify on its own."""
    roots = []
    signers = []
    seen = set()
    for entry in entries:
        signer = entry.get("signer")
        if isinstance(signer, str) and signer not in seen:
            seen.add(signer)
            signers.append(signer)
        if entry.get("step") != "checkpoint":
            continue
        payload = entry.get("payload")
        if not isinstance(payload, dict):
            continue
        roots.append(
            {
                "session_id": entry.get("session_id"),
                "checkpoint_index": entry.get("index"),
                "root": payload.get("root"),
                "leaf_count": payload.get("leaf_count"),
            }
        )
    head = entries[-1]["hash"] if entries else None
    return {
        "protocol": BUNDLE_PROTOCOL,
        "version": BUNDLE_VERSION,
        "entries": entries,
        "head": head,
        "signers": signers,
        "merkle_roots": roots,
    }


def export_path(path: str) -> dict[str, Any]:
    """Verify ``path`` and return its bundle. Refuses a ledger that does not verify."""
    report = verify_protocol(path)
    if not report.ok:
        raise LedgerError(report.reason or "ledger failed verification")
    return build_bundle(read_entries(path))


def _bundle_failure(reason: str) -> VerifyResult:
    return VerifyResult(
        ok=False,
        path="bundle",
        entries=0,
        head=None,
        failure_index=None,
        reason=reason,
    )


def _roots_match(document: dict[str, Any], entries: list[dict[str, Any]]) -> str | None:
    expected = build_bundle(entries)["merkle_roots"]
    stated = document.get("merkle_roots")
    if stated is None:
        return None
    if stated != expected:
        return "bundle merkle_roots do not match the checkpoint entries"
    return None


def _bundle_reason(document: dict[str, Any]) -> str | None:
    if document.get("protocol") != BUNDLE_PROTOCOL or document.get("version") != BUNDLE_VERSION:
        return "bundle protocol or version is not epistemic-ledger 1.0"
    entries = document.get("entries")
    if not isinstance(entries, list):
        return "bundle entries field is not a list"
    if any(not isinstance(item, dict) for item in entries):
        return "bundle entries must be JSON objects"
    return None


def verify_bundle_document(document: dict[str, Any]) -> VerifyResult:
    """Verify a bundle from memory. The entries alone are sufficient."""
    reason = _bundle_reason(document)
    if reason is not None:
        return _bundle_failure(reason)
    entries = document["entries"]
    result = verify_entries(entries, label="bundle")
    if not result.ok:
        return result
    if document.get("head") != result.head:
        return _bundle_failure("bundle head does not match the last entry hash")
    roots = _roots_match(document, entries)
    if roots is not None:
        return _bundle_failure(roots)
    return result


def load_bundle(path: str) -> dict[str, Any]:
    """Read a bundle JSON file."""
    with open(path, encoding="utf-8") as handle:
        loaded = json.load(handle)
    if not isinstance(loaded, dict):
        raise LedgerError("bundle file is not a JSON object")
    return loaded
