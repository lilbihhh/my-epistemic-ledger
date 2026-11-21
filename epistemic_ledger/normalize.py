"""Turn model JSON into the records the ledger actually stores.

Bad or missing fields are recorded as notes. They are not quietly repaired
into strong evidence.
"""

from __future__ import annotations

import math
from typing import Any

from epistemic_ledger.confidence import QUALITY_WEIGHTS
from epistemic_ledger.ledger import LedgerError

MAX_CLAIMS = 6
MAX_POINTS = 8
MAX_TEXT = 2000


def _clip(value: str) -> str:
    text = " ".join(value.split())
    if len(text) <= MAX_TEXT:
        return text
    return text[: MAX_TEXT - 1].rstrip() + "…"


def _string_list(value: Any, notes: list[str], field: str) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        notes.append(f"{field} was not a list and was ignored")
        return []
    cleaned: list[str] = []
    skipped = 0
    for item in value:
        if not isinstance(item, str):
            skipped += 1
            continue
        text = _clip(item)
        if text:
            cleaned.append(text)
    if skipped:
        notes.append(f"{field} ignored {skipped} non-string item(s)")
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
    if not math.isfinite(number):
        notes.append("self_confidence was not a finite number; treated as 0.5")
        return 0.5
    if 1.0 < number <= 100.0:
        number = number / 100.0
        notes.append("self_confidence looked like a percent and was scaled to 0-1")
    if number < 0.0 or number > 1.0:
        number = min(1.0, max(0.0, number))
        notes.append("self_confidence was clamped to 0-1")
    return round(number, 4)


def _unique_claim_id(requested: Any, seen: set[str], index: int) -> tuple[str, bool]:
    """Return a claim id that is not already used, and whether it was renamed."""
    if isinstance(requested, str) and requested.strip():
        base = _clip(requested)
    else:
        base = f"c{index}"
    if base not in seen:
        return base, False
    suffix = 2
    while f"{base}-{suffix}" in seen:
        suffix += 1
    return f"{base}-{suffix}", True


def normalize_claims(raw: dict[str, Any]) -> list[dict[str, str]]:
    """Require at least one claim with text. Cap the list at six.

    Duplicate ids are renamed so later evidence cannot be copied onto both.
    """
    claims = raw.get("claims")
    if not isinstance(claims, list) or not claims:
        raise LedgerError("decompose step returned no claims")
    cleaned: list[dict[str, str]] = []
    seen: set[str] = set()
    for index, claim in enumerate(claims, start=1):
        if not isinstance(claim, dict):
            raise LedgerError(f"claim {index} was not an object")
        text_raw = claim.get("text")
        if not isinstance(text_raw, str) or not text_raw.strip():
            raise LedgerError(f"claim {index} was missing text")
        claim_id, renamed = _unique_claim_id(claim.get("id"), seen, index)
        seen.add(claim_id)
        record = {"id": claim_id, "text": _clip(text_raw)}
        if renamed:
            original = claim.get("id")
            if isinstance(original, str) and original.strip():
                record["renamed_from"] = _clip(original)
            else:
                record["renamed_from"] = f"c{index}"
        cleaned.append(record)
        if len(cleaned) >= MAX_CLAIMS:
            break
    return cleaned


def _missing_evidence(claim_id: str, *, renamed: bool) -> dict[str, Any]:
    if renamed:
        note = "claim id collided with an earlier claim; evidence was not copied"
        reasoning = "This claim id was renamed after a collision. No evidence was attached."
    else:
        note = "filled because the model omitted this claim"
        reasoning = "No evidence was returned for this claim."
    return {
        "claim_id": claim_id,
        "reasoning": reasoning,
        "supports": [],
        "caveats": ["The model omitted this claim."],
        "quality": "unsupported",
        "self_confidence": 0.5,
        "notes": [note],
    }


def _clean_evidence(claim_id: str, source: dict[str, Any]) -> dict[str, Any]:
    notes: list[str] = []
    quality_raw = source.get("quality", "")
    quality = quality_raw.strip().lower() if isinstance(quality_raw, str) else ""
    if quality not in QUALITY_WEIGHTS:
        shown = quality or "(missing)"
        notes.append(f"quality {shown} is not recognized; treated as unsupported")
        quality = "unsupported"
    reasoning_raw = source.get("reasoning", "")
    if isinstance(reasoning_raw, str) and reasoning_raw.strip():
        reasoning = _clip(reasoning_raw)
    else:
        reasoning = "No reasoning text was returned."
        if reasoning_raw not in ("", None):
            notes.append("reasoning was not text and was ignored")
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
    duplicated: set[str] = set()
    for item in items:
        if not isinstance(item, dict):
            continue
        claim_id = item.get("claim_id")
        if not isinstance(claim_id, str) or not claim_id.strip():
            continue
        if claim_id in by_id:
            duplicated.add(claim_id)
            continue
        by_id[claim_id] = item
    normalized: list[dict[str, Any]] = []
    for claim in claims:
        source = by_id.get(claim["id"])
        if source is None:
            normalized.append(_missing_evidence(claim["id"], renamed="renamed_from" in claim))
            continue
        cleaned = _clean_evidence(claim["id"], source)
        if claim["id"] in duplicated:
            cleaned["notes"].append("duplicate evidence for this claim id was ignored")
        normalized.append(cleaned)
    return normalized


def normalize_answer(raw: dict[str, Any]) -> dict[str, Any]:
    """Pull the answer text and the uncertainty list out of model JSON."""
    answer_raw = raw.get("answer")
    if not isinstance(answer_raw, str) or not answer_raw.strip():
        raise LedgerError("answer step returned an empty answer")
    answer = _clip(answer_raw)
    uncertainties_raw = raw.get("uncertainties")
    notes: list[str] = []
    uncertainties = _string_list(uncertainties_raw, notes, "uncertainties")
    if notes:
        uncertainties = uncertainties + notes
    return {"answer": answer, "uncertainties": uncertainties}
