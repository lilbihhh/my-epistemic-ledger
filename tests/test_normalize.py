"""Model JSON is normalized without turning gaps into strong evidence."""

import pytest

from epistemic_ledger.confidence import score_claim
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


def test_null_supports_do_not_count_as_evidence():
    """JSON null is not a supporting point, and it is not the string 'None'."""
    claims = [{"id": "c1", "text": "Rain is wet."}]
    evidence = normalize_evidence(
        claims,
        {
            "evidence": [
                {
                    "claim_id": "c1",
                    "reasoning": "observation",
                    "supports": [None, None, None],
                    "caveats": [],
                    "quality": "direct",
                    "self_confidence": 0.74,
                }
            ]
        },
    )
    assert evidence[0]["supports"] == []
    assert any("non-string" in note for note in evidence[0]["notes"])
    assert score_claim(evidence[0])["confidence"] == 0.074


def test_duplicate_claim_ids_are_not_scored_twice_on_one_record():
    """A repeated id is renamed, and its evidence is not copied onto both claims."""
    claims = normalize_claims(
        {"claims": [{"id": "c2", "text": "First claim."}, {"text": "Second claim."}]}
    )
    assert [claim["id"] for claim in claims] == ["c2", "c2-2"]
    evidence = normalize_evidence(
        claims,
        {
            "evidence": [
                {
                    "claim_id": "c2",
                    "reasoning": "only the first",
                    "supports": ["one"],
                    "quality": "direct",
                    "self_confidence": 0.5,
                }
            ]
        },
    )
    assert evidence[0]["supports"] == ["one"]
    assert evidence[1]["quality"] == "unsupported"
    assert evidence[1]["supports"] == []


def test_non_finite_confidence_falls_back():
    """'NaN' is not a probability and must not be written through as a float."""
    evidence = normalize_evidence(
        [{"id": "c1", "text": "Rain is wet."}],
        {
            "evidence": [
                {
                    "claim_id": "c1",
                    "reasoning": "unknown",
                    "supports": ["wet"],
                    "quality": "direct",
                    "self_confidence": "NaN",
                }
            ]
        },
    )
    assert evidence[0]["self_confidence"] == 0.5
    assert any("finite" in note for note in evidence[0]["notes"])


def test_null_claim_text_is_rejected():
    """A JSON null claim is not stored as the word None."""
    with pytest.raises(LedgerError, match="missing text"):
        normalize_claims({"claims": [{"id": "c1", "text": None}]})


def test_decompose_without_claims_raises():
    """An empty decompose result is an error, not a silent pass."""
    with pytest.raises(LedgerError):
        normalize_claims({"claims": []})
