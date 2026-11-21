"""Confidence you can recompute from the ledger.

The model does not choose the final number. It reports evidence features.
This module turns those features into a score and stores every input it used.

Method ``structural-evidence-v1``, per claim:

    support_ratio = round(supports / (supports + caveats + 1), 4)
    disagreement = round(abs(self_confidence - support_ratio), 4)
    raw = 0.75 * quality_weight * support_ratio
          + 0.25 * self_confidence
          - 0.15 * disagreement
    confidence = round(clamp(raw, 0.05, 0.95), 4)

The ``+ 1`` keeps an empty evidence list from looking certain. Quality
weights are direct=1.0, inferred=0.7, speculative=0.4, unsupported=0.15.
Self-confidence is only a quarter of the score. A gap between that
self-report and the support ratio is subtracted, so a thin claim cannot
talk itself into a high number.

The answer score is the geometric mean of the claim scores, which follows
the weakest claim more closely than an average does. If any claim is
speculative or unsupported, that mean is multiplied by 0.85 once. The same
0.05–0.95 band applies. The ledger never stores 0 or 1: those would read as
impossibility or proof, and this pipeline does not establish either.

Rounded inputs are what enter the arithmetic, so a reader with the ledger
and a calculator can land on the stored score.
"""

from __future__ import annotations

import math
from typing import Any

METHOD = "structural-evidence-v1"
OVERALL_METHOD = "geometric-mean-with-speculative-discount"

QUALITY_WEIGHTS = {
    "direct": 1.0,
    "inferred": 0.7,
    "speculative": 0.4,
    "unsupported": 0.15,
}

STRUCTURAL_WEIGHT = 0.75
SELF_WEIGHT = 0.25
DISAGREEMENT_PENALTY = 0.15
SPECULATIVE_DISCOUNT = 0.85
FLOOR = 0.05
CAP = 0.95

FORMULA = (
    "support_ratio = round(supports / (supports + caveats + 1), 4); "
    "disagreement = round(abs(self_confidence - support_ratio), 4); "
    "confidence = round(clamp("
    f"{STRUCTURAL_WEIGHT} * quality_weight * support_ratio"
    f" + {SELF_WEIGHT} * self_confidence"
    f" - {DISAGREEMENT_PENALTY} * disagreement, {FLOOR}, {CAP}), 4)"
)

OVERALL_FORMULA = (
    "round(clamp(geometric_mean(claim confidences)"
    f" * ({SPECULATIVE_DISCOUNT} if any claim is speculative or unsupported else 1),"
    f" {FLOOR}, {CAP}), 4)"
)


def _clamp(value: float) -> float:
    return min(CAP, max(FLOOR, value))


def _round(value: float) -> float:
    return round(value, 4)


def _explain(parts: dict[str, Any]) -> str:
    return (
        f"{parts['quality']} evidence uses weight {parts['quality_weight']}. "
        f"{parts['supports']} support(s) and {parts['caveats']} caveat(s) "
        f"give support ratio {parts['support_ratio']}. "
        f"Self-confidence {parts['self_confidence']} differs from that ratio "
        f"by {parts['disagreement']}, and the difference is penalized. "
        f"Score {parts['confidence']}."
    )


def score_claim(evidence: dict[str, Any]) -> dict[str, Any]:
    """Score one evidence record. ``quality`` outside the table is unsupported."""
    quality = str(evidence.get("quality", "unsupported"))
    if quality not in QUALITY_WEIGHTS:
        quality = "unsupported"
    weight = QUALITY_WEIGHTS[quality]
    supports = len(evidence.get("supports") or [])
    caveats = len(evidence.get("caveats") or [])
    try:
        self_confidence = float(evidence.get("self_confidence", 0.5))
    except (TypeError, ValueError):
        self_confidence = 0.5
    if not math.isfinite(self_confidence):
        self_confidence = 0.5
    self_confidence = min(1.0, max(0.0, self_confidence))
    support_ratio = _round(supports / (supports + caveats + 1))
    disagreement = _round(abs(self_confidence - support_ratio))
    raw = (
        STRUCTURAL_WEIGHT * weight * support_ratio
        + SELF_WEIGHT * self_confidence
        - DISAGREEMENT_PENALTY * disagreement
    )
    confidence = _round(_clamp(raw))
    parts: dict[str, Any] = {
        "claim_id": evidence.get("claim_id"),
        "quality": quality,
        "quality_weight": weight,
        "supports": supports,
        "caveats": caveats,
        "support_ratio": support_ratio,
        "self_confidence": _round(self_confidence),
        "disagreement": disagreement,
        "confidence": confidence,
    }
    parts["explanation"] = _explain(parts)
    return parts


def score_claims(evidence_items: list[dict[str, Any]]) -> dict[str, Any]:
    """Score every claim and combine them into one answer-level confidence."""
    if not evidence_items:
        raise ValueError("cannot score an empty evidence list")
    claims = [score_claim(item) for item in evidence_items]
    mean = math.exp(
        sum(math.log(item["confidence"]) for item in claims) / len(claims)
    )
    discount = any(item["quality"] in {"speculative", "unsupported"} for item in claims)
    if discount:
        mean *= SPECULATIVE_DISCOUNT
    overall = _round(_clamp(mean))
    return {
        "method": METHOD,
        "formula": FORMULA,
        "quality_weights": dict(QUALITY_WEIGHTS),
        "claims": claims,
        "overall": {
            "method": OVERALL_METHOD,
            "formula": OVERALL_FORMULA,
            "confidence": overall,
            "speculative_discount_applied": discount,
            "claim_count": len(claims),
        },
    }
