"""Turn model JSON into the records the ledger actually stores.

Bad or missing fields are recorded as notes. They are not quietly repaired
into strong evidence.
"""

from __future__ import annotations

from typing import Any

from epistemic_ledger.confidence import QUALITY_WEIGHTS
from epistemic_ledger.ledger import LedgerError

MAX_CLAIMS = 6
MAX_POINTS = 8
MAX_TEXT = 2000


def _clip(value: Any) -> str:
    text = " ".join(str(value).split())
    if len(text) <= MAX_TEXT:
        return text
    return text[: MAX_TEXT - 1].rstrip() + "…"


def _string_list(value: Any, notes: list[str], field: str) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        notes.append(f"{field} was not a list and was ignored")
        return []
    cleaned = [_clip(item) for item in value if _clip(item)]
    if len(cleaned) > MAX_POINTS:
        notes.append(f"{field} truncated to {MAX_POINTS} items")
        return cleaned[:MAX_POINTS]
    return cleaned


def _self_confidence(value: Any, notes: list[str]) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        notes.append("self_confidence missing; treated as 0.5")
        return 0.5
    if 1.0 < number <= 100.0:
        number = number / 100.0
        notes.append("self_confidence looked like a percent and was scaled to 0-1")
    if number < 0.0 or number > 1.0:
        number = min(1.0, max(0.0, number))
        notes.append("self_confidence was clamped to 0-1")
    return round(number, 4)


def normalize_claims(raw: dict[str, Any]) -> list[dict[str, str]]:
    """Require at least one claim with text. Cap the list at six."""
    claims = raw.get("claims")
    if not isinstance(claims, list) or not claims:
        raise LedgerError("decompose step returned no claims")
    cleaned: list[dict[str, str]] = []
    for index, claim in enumerate(claims, start=1):
        if not isinstance(claim, dict):
            raise LedgerError(f"claim {index} was not an object")
        text = _clip(claim.get("text", ""))
        if not text:
            raise LedgerError(f"claim {index} was missing text")
        claim_id = _clip(claim.get("id") or f"c{index}") or f"c{index}"
        cleaned.append({"id": claim_id, "text": text})
        if len(cleaned) >= MAX_CLAIMS:
            break
    return cleaned


def _missing_evidence(claim_id: str) -> dict[str, Any]:
    return {
        "claim_id": claim_id,
        "reasoning": "No evidence was returned for this claim.",
        "supports": [],
        "caveats": ["The model omitted this claim."],
        "quality": "unsupported",
        "self_confidence": 0.5,
        "notes": ["filled because the model omitted this claim"],
    }


def _clean_evidence(claim_id: str, source: dict[str, Any]) -> dict[str, Any]:
    notes: list[str] = []
    quality = str(source.get("quality", "")).strip().lower()
    if quality not in QUALITY_WEIGHTS:
        notes.append(f"quality {quality or '(missing)'} is not recognized; treated as unsupported")
        quality = "unsupported"
    reasoning = _clip(source.get("reasoning", "")) or "No reasoning text was returned."
    return {
        "claim_id": claim_id,
        "reasoning": reasoning,
        "supports": _string_list(source.get("supports"), notes, "supports"),
        "caveats": _string_list(source.get("caveats"), notes, "caveats"),
        "quality": quality,
        "self_confidence": _self_confidence(source.get("self_confidence"), notes),
        "notes": notes,
    }


def normalize_evidence(
    claims: list[dict[str, str]],
    raw: dict[str, Any],
) -> list[dict[str, Any]]:
    """Align evidence with the claims, one record each, in claim order."""
    items = raw.get("evidence")
    if not isinstance(items, list):
        raise LedgerError("evidence step did not return a list")
    by_id: dict[str, dict[str, Any]] = {}
    for item in items:
        if isinstance(item, dict) and item.get("claim_id"):
            by_id[str(item["claim_id"])] = item
    normalized: list[dict[str, Any]] = []
    for claim in claims:
        source = by_id.get(claim["id"])
        if source is None:
            normalized.append(_missing_evidence(claim["id"]))
        else:
            normalized.append(_clean_evidence(claim["id"], source))
    return normalized


def normalize_answer(raw: dict[str, Any]) -> dict[str, Any]:
    """Pull the answer text and the uncertainty list out of model JSON."""
    answer = _clip(raw.get("answer", ""))
    if not answer:
        raise LedgerError("answer step returned an empty answer")
    uncertainties_raw = raw.get("uncertainties")
    notes: list[str] = []
    uncertainties = _string_list(uncertainties_raw, notes, "uncertainties")
    if notes:
        uncertainties = uncertainties + notes
    return {"answer": answer, "uncertainties": uncertainties}
