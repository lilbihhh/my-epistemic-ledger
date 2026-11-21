"""The confidence method is arithmetic, not a constant."""

import math

from epistemic_ledger.confidence import (
    CAP,
    DISAGREEMENT_PENALTY,
    FLOOR,
    SELF_WEIGHT,
    SPECULATIVE_DISCOUNT,
    STRUCTURAL_WEIGHT,
    score_claim,
    score_claims,
)


def _raw(weight, support_ratio, self_confidence, disagreement):
    return (
        STRUCTURAL_WEIGHT * weight * support_ratio
        + SELF_WEIGHT * self_confidence
        - DISAGREEMENT_PENALTY * disagreement
    )


def test_inferred_claim_matches_the_published_formula():
    """2 supports, 1 caveat, inferred, self-confidence 0.8 -> 0.4175."""
    scored = score_claim(
        {
            "claim_id": "c1",
            "quality": "inferred",
            "supports": ["a", "b"],
            "caveats": ["c"],
            "self_confidence": 0.8,
        }
    )
    assert scored["quality_weight"] == 0.7
    assert scored["support_ratio"] == 0.5
    assert scored["disagreement"] == 0.3
    assert scored["confidence"] == 0.4175
    assert scored["confidence"] == round(_raw(0.7, 0.5, 0.8, 0.3), 4)
    assert "inferred" in scored["explanation"]
    assert "penalized" in scored["explanation"]


def test_scores_change_when_the_evidence_changes():
    """A direct, well-supported claim outscores a speculative one. Neither is 0.85."""
    strong = score_claim(
        {
            "claim_id": "c1",
            "quality": "direct",
            "supports": ["narrow", "consistent", "no new assumption"],
            "caveats": [],
            "self_confidence": 0.74,
        }
    )
    thin = score_claim(
        {
            "claim_id": "c2",
            "quality": "speculative",
            "supports": ["a hypothesis"],
            "caveats": ["no source", "easy to read differently"],
            "self_confidence": 0.99,
        }
    )
    assert strong["confidence"] != thin["confidence"]
    assert strong["confidence"] != 0.85
    assert thin["confidence"] != 0.85
    assert thin["confidence"] < strong["confidence"]
    assert thin["disagreement"] > 0


def test_empty_evidence_cannot_score_as_certain():
    """No supports plus a high self-report stays low. Zero evidence hits the floor."""
    overconfident = score_claim(
        {
            "claim_id": "c1",
            "quality": "unsupported",
            "supports": [],
            "caveats": ["nothing here", "still nothing"],
            "self_confidence": 0.99,
        }
    )
    assert overconfident["confidence"] < 0.15
    assert overconfident["confidence"] != 0.99

    empty = score_claim(
        {
            "claim_id": "c2",
            "quality": "unsupported",
            "supports": [],
            "caveats": ["nothing here"],
            "self_confidence": 0.0,
        }
    )
    assert empty["confidence"] == FLOOR


def test_overall_is_a_discounted_geometric_mean():
    """One speculative claim pulls the answer down once, from the claim scores."""
    bundle = score_claims(
        [
            {
                "claim_id": "c1",
                "quality": "direct",
                "supports": ["a", "b", "c"],
                "caveats": [],
                "self_confidence": 0.74,
            },
            {
                "claim_id": "c2",
                "quality": "speculative",
                "supports": ["only a hunch"],
                "caveats": ["unchecked", "broad"],
                "self_confidence": 0.42,
            },
        ]
    )
    confidences = [item["confidence"] for item in bundle["claims"]]
    geometric = math.exp(sum(math.log(value) for value in confidences) / 2)
    expected = round(min(CAP, max(FLOOR, geometric * SPECULATIVE_DISCOUNT)), 4)
    assert bundle["overall"]["speculative_discount_applied"] is True
    assert bundle["overall"]["confidence"] == expected
    assert bundle["method"] == "structural-evidence-v1"
    assert "0.75" in bundle["formula"]
