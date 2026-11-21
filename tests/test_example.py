"""The checked-in sample ledger is a real mock run, not a hand-written fixture."""

from pathlib import Path

from epistemic_ledger.ledger import Ledger, verify
from epistemic_ledger.llm import MockLLM
from epistemic_ledger.pipeline import run_question
from tests.support import ticking_clock

EXAMPLE = Path("examples/why-is-the-sky-blue.jsonl")
SESSION = "00000000-0000-4000-8000-000000000001"


def test_checked_in_example_matches_a_fresh_run(tmp_path):
    """Regenerating the sample question reproduces the file byte for byte."""
    ledger = Ledger(tmp_path / "ledger.jsonl", clock=ticking_clock())
    run_question(
        question="Why is the sky blue?",
        llm=MockLLM(),
        ledger=ledger,
        session_id=SESSION,
    )
    assert ledger.path.read_text(encoding="utf-8") == EXAMPLE.read_text(encoding="utf-8")
    report = verify(EXAMPLE)
    assert report.ok
    assert report.entries == 6
    assert report.head
