"""Hash-chain tests, including hand edits and rewritten hashes."""

import json

import pytest

from epistemic_ledger.ledger import GENESIS_HASH, Ledger, LedgerError, entry_hash, verify
from tests.support import ticking_clock


def _write_three(tmp_path):
    ledger = Ledger(tmp_path / "ledger.jsonl", clock=ticking_clock())
    ledger.append(step="question", session_id="s", payload={"question": "because it scatters"})
    ledger.append(step="decompose", session_id="s", payload={"claims": ["one claim"]})
    ledger.append(step="answer", session_id="s", payload={"answer": "a careful answer"})
    return ledger.path


def test_chain_links_to_genesis_and_verifies(tmp_path):
    """Each entry commits to the previous hash, and the file verifies."""
    path = _write_three(tmp_path)
    report = verify(path)
    assert report.ok
    assert report.entries == 3
    entries = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    assert entries[0]["prev_hash"] == GENESIS_HASH
    assert entries[1]["prev_hash"] == entries[0]["hash"]
    assert entries[2]["prev_hash"] == entries[1]["hash"]
    assert entries[0]["hash"] == entry_hash(entries[0])
    assert report.head == entries[2]["hash"]


def test_hand_edit_is_detected_at_that_index(tmp_path):
    """Changing a past sentence without touching its hash is caught on that line."""
    path = _write_three(tmp_path)
    lines = path.read_text(encoding="utf-8").splitlines()
    edited = json.loads(lines[1])
    edited["payload"]["claims"] = ["tampered claim"]
    lines[1] = json.dumps(edited)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    report = verify(path)
    assert not report.ok
    assert report.failure_index == 1
    assert report.reason == "stored hash does not match the entry contents"
    assert report.expected
    assert report.found != report.expected


def test_rewritten_hash_still_breaks_the_next_link(tmp_path):
    """Rehashing a changed entry does not save the edit. The next link fails."""
    path = _write_three(tmp_path)
    lines = path.read_text(encoding="utf-8").splitlines()
    edited = json.loads(lines[0])
    edited["payload"]["question"] = "quietly replaced"
    edited["hash"] = entry_hash(edited)
    lines[0] = json.dumps(edited, sort_keys=True, separators=(",", ":"))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    report = verify(path)
    assert not report.ok
    assert report.failure_index == 1
    assert "prev_hash" in report.reason


def test_deleting_a_middle_entry_breaks_the_chain(tmp_path):
    """Dropping a line makes the following prev_hash point at the wrong entry."""
    path = _write_three(tmp_path)
    lines = path.read_text(encoding="utf-8").splitlines()
    path.write_text("\n".join([lines[0], lines[2]]) + "\n", encoding="utf-8")
    report = verify(path)
    assert not report.ok
    assert report.failure_index == 1


def test_append_refuses_a_broken_ledger(tmp_path):
    """New steps are not written on top of a chain that already fails."""
    path = _write_three(tmp_path)
    original = path.read_text(encoding="utf-8")
    lines = original.splitlines()
    edited = json.loads(lines[0])
    edited["payload"]["question"] = "edited by hand"
    lines[0] = json.dumps(edited)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    ledger = Ledger(path)
    with pytest.raises(LedgerError, match="refusing to append"):
        ledger.append(step="question", session_id="s", payload={"question": "another"})
    assert path.read_text(encoding="utf-8") == "\n".join(lines) + "\n"


def test_second_session_continues_the_same_chain(tmp_path):
    """A later session links to the previous session's last hash."""
    ledger = Ledger(tmp_path / "ledger.jsonl", clock=ticking_clock())
    first = ledger.append(step="question", session_id="one", payload={"question": "first"})
    second = ledger.append(step="question", session_id="two", payload={"question": "second"})
    assert second["prev_hash"] == first["hash"]
    assert second["index"] == 1
    assert verify(ledger.path).ok


def test_empty_file_verifies_and_missing_file_does_not(tmp_path):
    """An empty ledger is fine. A missing path is reported, not treated as valid."""
    empty = tmp_path / "empty.jsonl"
    empty.write_text("", encoding="utf-8")
    empty_report = verify(empty)
    assert empty_report.ok
    assert empty_report.entries == 0

    missing = verify(tmp_path / "missing.jsonl")
    assert not missing.ok
    assert missing.reason == "ledger file not found"
    assert missing.failure_index is None


def test_swapped_hash_field_is_detected(tmp_path):
    """Replacing only the stored hash, and nothing else, still fails that entry."""
    path = _write_three(tmp_path)
    lines = path.read_text(encoding="utf-8").splitlines()
    edited = json.loads(lines[2])
    edited["hash"] = "ab" * 32
    lines[2] = json.dumps(edited)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    report = verify(path)
    assert report.failure_index == 2
    assert report.reason == "stored hash does not match the entry contents"
