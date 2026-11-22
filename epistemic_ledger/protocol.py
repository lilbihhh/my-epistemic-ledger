"""Protocol checks beyond the hash chain.

Hash linkage lives in ``ledger.verify``. This module adds the v1 rules:
JSON Schema, Ed25519 signatures, the step state machine, recomputed
confidence, Merkle checkpoints, and witness claim references.
"""

from __future__ import annotations

from typing import Any

from epistemic_ledger.confidence import score_claims
from epistemic_ledger.ledger import (
    GENESIS_HASH,
    VerifyResult,
    entry_hash,
    read_entries,
    verify,
)
from epistemic_ledger.merkle import MERKLE_ALGORITHM, merkle_root
from epistemic_ledger.schema import schema_error
from epistemic_ledger.signing import signature_error

_TRANSITIONS = {
    "question": frozenset({None}),
    "decompose": frozenset({"question"}),
    "evidence": frozenset({"decompose", "evidence"}),
    "score": frozenset({"evidence"}),
    "answer": frozenset({"score"}),
    "checkpoint": frozenset({"answer", "checkpoint"}),
}
_WITNESS_STATES = frozenset({"decompose", "evidence", "score", "answer", "checkpoint"})


def _semantic_failure(path: str, index: int, reason: str) -> VerifyResult:
    return VerifyResult(
        ok=False,
        path=path,
        entries=index,
        head=None,
        failure_index=index,
        reason=reason,
        mismatch=None,
    )


def _order_problem(state: str | None, step: str) -> str | None:
    if step == "witness":
        if state not in _WITNESS_STATES:
            return "step witness is not allowed before a claim has been recorded"
        return None
    allowed = _TRANSITIONS.get(step)
    if allowed is None:
        return f"step {step} is not part of protocol 1.0"
    if state not in allowed:
        where = "the start of the session" if state is None else f"state {state}"
        return f"step {step} is not allowed after {where}"
    return None


def _next_state(state: str | None, step: str) -> str | None:
    if step == "witness":
        return state
    if step == "evidence":
        return "evidence"
    return step


def _claim_ids(payload: dict[str, Any]) -> list[str]:
    claims = payload.get("claims")
    if not isinstance(claims, list):
        return []
    found = []
    for claim in claims:
        if isinstance(claim, dict) and isinstance(claim.get("id"), str):
            found.append(claim["id"])
    return found


def _score_problem(evidence: list[dict[str, Any]], payload: dict[str, Any]) -> str | None:
    if not evidence:
        return "score entry has no evidence records in this session"
    expected = score_claims(evidence)
    for key in ("method", "formula", "quality_weights", "claims", "overall"):
        if payload.get(key) != expected[key]:
            return "score entry does not match structural-evidence-v1 recomputed from the evidence"
    return None


def _checkpoint_problem(leaves: list[dict[str, Any]], payload: dict[str, Any]) -> str | None:
    if payload.get("algorithm") != MERKLE_ALGORITHM:
        return "checkpoint algorithm is not merkle-sha256-v1"
    hashes = [str(item.get("hash")) for item in leaves]
    if payload.get("leaf_count") != len(hashes):
        return "checkpoint leaf_count does not match the session entries before it"
    if not hashes:
        return "checkpoint has no leaves"
    indexes = [int(item["index"]) for item in leaves]
    if payload.get("first_index") != min(indexes) or payload.get("last_index") != max(indexes):
        return "checkpoint index range does not match the session entries before it"
    if payload.get("root") != merkle_root(hashes):
        return "checkpoint Merkle root does not match the session entries before it"
    return None


def _witness_problem(known_claims: set[str], payload: dict[str, Any]) -> str | None:
    claim_id = payload.get("claim_id")
    if claim_id not in known_claims:
        return f"witness refers to unknown claim {claim_id}"
    if payload.get("stance") not in {"attest", "dispute"}:
        return "witness stance must be attest or dispute"
    return None


class _SessionLog:
    """Per-session state used while walking a ledger once."""

    def __init__(self) -> None:
        self.states: dict[str, str | None] = {}
        self.evidence: dict[str, list[dict[str, Any]]] = {}
        self.claims: dict[str, set[str]] = {}
        self.entries: dict[str, list[dict[str, Any]]] = {}

    def _payload_issue(self, session: str, step: str, payload: dict[str, Any]) -> str | None:
        if step == "decompose":
            self.claims.setdefault(session, set()).update(_claim_ids(payload))
            return None
        if step == "evidence":
            self.evidence.setdefault(session, []).append(payload)
            return None
        if step == "score":
            return _score_problem(self.evidence.get(session, []), payload)
        if step == "checkpoint":
            return _checkpoint_problem(self.entries.get(session, []), payload)
        if step == "witness":
            return _witness_problem(self.claims.get(session, set()), payload)
        return None

    def observe(self, entry: dict[str, Any]) -> str | None:
        """Apply one entry. Return a reason when it breaks the protocol."""
        session = str(entry.get("session_id"))
        step = str(entry.get("step"))
        order = _order_problem(self.states.get(session), step)
        if order is not None:
            return order
        payload = entry.get("payload")
        if not isinstance(payload, dict):
            return "payload is not an object"
        issue = self._payload_issue(session, step, payload)
        if issue is not None:
            return issue
        self.states[session] = _next_state(self.states.get(session), step)
        self.entries.setdefault(session, []).append(entry)
        return None


def _semantics(path: str, entries: list[dict[str, Any]]) -> VerifyResult | None:
    """Return the first protocol failure, or None when the entries hold."""
    log = _SessionLog()
    for index, entry in enumerate(entries):
        problem = schema_error(entry) or signature_error(entry) or log.observe(entry)
        if problem is not None:
            return _semantic_failure(path, index, problem)
    return None


def checkpoint_payload(session_entries: list[dict[str, Any]]) -> dict[str, Any]:
    """Merkle checkpoint body for the session entries that already exist."""
    if not session_entries:
        raise ValueError("cannot checkpoint an empty session")
    hashes = [str(item["hash"]) for item in session_entries]
    indexes = [int(item["index"]) for item in session_entries]
    return {
        "algorithm": MERKLE_ALGORITHM,
        "root": merkle_root(hashes),
        "leaf_count": len(hashes),
        "first_index": min(indexes),
        "last_index": max(indexes),
    }


def append_error(prior: list[dict[str, Any]], entry: dict[str, Any]) -> str | None:
    """Reason the sealed ``entry`` must not be appended after ``prior``."""
    failure = _semantics("append", prior + [entry])
    if failure is None:
        return None
    return failure.reason


def verify_entries(entries: list[dict[str, Any]], *, label: str) -> VerifyResult:
    """Check a parsed entry list: chain, schema, signatures, and step rules."""
    previous = GENESIS_HASH
    head: str | None = None
    for index, entry in enumerate(entries):
        if entry.get("index") != index:
            return _semantic_failure(label, index, "index field does not match the line position")
        if entry.get("prev_hash") != previous:
            return _semantic_failure(
                label,
                index,
                "prev_hash does not match the previous entry's hash",
            )
        computed = entry_hash(entry)
        if entry.get("hash") != computed:
            return VerifyResult(
                ok=False,
                path=label,
                entries=index,
                head=None,
                failure_index=index,
                reason="stored hash does not match the entry contents",
                mismatch=(computed, str(entry.get("hash"))),
            )
        previous = computed
        head = computed
    semantic = _semantics(label, entries)
    if semantic is not None:
        return semantic
    return VerifyResult(
        ok=True,
        path=label,
        entries=len(entries),
        head=head,
        failure_index=None,
        reason=None,
    )


def verify_protocol(path: str) -> VerifyResult:
    """File verification: the hash chain, then the protocol rules."""
    chain = verify(path)
    if not chain.ok or chain.entries == 0:
        return chain
    semantic = _semantics(str(path), read_entries(path))
    if semantic is not None:
        return semantic
    return chain
