"""Model JSON is normalized without turning gaps into strong evidence."""

import pytest

from epistemic_ledger.ledger import LedgerError
from epistemic_ledger.normalize import normalize_claims, normalize_evidence


def test_percent_confidence_is_scaled_and_unknown_quality_is_unsupported():
    """80 and a made-up quality are recorded, not trusted as a high score."""
    claims = normalize_claims({"claims": [{"id": "c1", "text": "Rain is wet."}]})
    evidence = normalize_evidence(
        claims,
        {
            "evidence": [
                {
                    "claim_id": "c1",
                    "reasoning": "Common observation.",
                    "supports": ["wet streets"],
                    "caveats": [],
                    "quality": "certain",
                    "self_confidence": 80,
                }
            ]
        },
    )
    assert evidence[0]["quality"] == "unsupported"
    assert evidence[0]["self_confidence"] == 0.8
    assert any("percent" in note for note in evidence[0]["notes"])
    assert any("not recognized" in note for note in evidence[0]["notes"])


def test_omitted_claim_is_stored_as_unsupported():
    """A claim the model skips does not disappear from the ledger."""
    claims = [
        {"id": "c1", "text": "First."},
        {"id": "c2", "text": "Second."},
    ]
    evidence = normalize_evidence(
        claims,
        {
            "evidence": [
                {
                    "claim_id": "c1",
                    "reasoning": "ok",
                    "supports": ["x"],
                    "quality": "direct",
                }
            ]
        },
    )
    assert evidence[1]["claim_id"] == "c2"
    assert evidence[1]["quality"] == "unsupported"
    assert evidence[1]["supports"] == []


def test_decompose_without_claims_raises():
    """An empty decompose result is an error, not a silent pass."""
    with pytest.raises(LedgerError):
        normalize_claims({"claims": []})
