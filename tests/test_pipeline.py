"""End-to-end mock runs. The score in the ledger matches the scoring function."""

from epistemic_ledger.confidence import score_claims
from epistemic_ledger.ledger import Ledger, read_entries, verify
from epistemic_ledger.llm import MockLLM
from epistemic_ledger.pipeline import run_question
from tests.support import ticking_clock


def test_mock_run_records_every_step_and_a_recomputable_score(tmp_path):
    """A question with no API key still produces a verifiable, non-constant score."""
    ledger = Ledger(tmp_path / "ledger.jsonl", clock=ticking_clock())
    result = run_question(
        question="Why is the sky blue?",
        llm=MockLLM(),
        ledger=ledger,
        session_id="demo-session",
    )
    report = verify(ledger.path)
    assert report.ok
    entries = read_entries(ledger.path)
    steps = [entry["step"] for entry in entries]
    assert steps[0] == "question"
    assert "decompose" in steps
    assert steps.count("evidence") == len(result["claims"])
    assert "score" in steps
    assert steps[-1] == "answer"
    assert entries[0]["payload"]["provider"] == "mock"
    assert result["answer"]
    assert "Offline trace" in result["answer"]
    assert result["scores"]["overall"]["confidence"] != 0.85

    evidence = [entry["payload"] for entry in entries if entry["step"] == "evidence"]
    expected = score_claims(evidence)
    stored = next(entry["payload"] for entry in entries if entry["step"] == "score")
    assert stored["claims"] == expected["claims"]
    assert stored["overall"] == expected["overall"]
    confidences = {item["claim_id"]: item["confidence"] for item in stored["claims"]}
    assert len(set(confidences.values())) > 1


def test_question_keeps_internal_line_breaks(tmp_path):
    """A pasted snippet is stored with its indentation, not collapsed to one line."""
    question = "Is this return inside the block?\n    return 1\n"
    ledger = Ledger(tmp_path / "ledger.jsonl", clock=ticking_clock())
    result = run_question(question=question, llm=MockLLM(), ledger=ledger, session_id="indent")
    assert result["question"] == question.strip()
    stored = read_entries(ledger.path)[0]["payload"]["question"]
    assert stored == "Is this return inside the block?\n    return 1"
    assert verify(ledger.path).ok


def test_two_questions_share_one_chain(tmp_path):
    """A second ask appends after the first and the whole file still verifies."""
    ledger = Ledger(tmp_path / "ledger.jsonl", clock=ticking_clock())
    run_question(question="What is 2 + 2?", llm=MockLLM(), ledger=ledger, session_id="a")
    first_head = verify(ledger.path).head
    run_question(question="Why is the sky blue?", llm=MockLLM(), ledger=ledger, session_id="b")
    report = verify(ledger.path)
    assert report.ok
    assert report.head != first_head
    sessions = {entry["session_id"] for entry in read_entries(ledger.path)}
    assert sessions == {"a", "b"}
