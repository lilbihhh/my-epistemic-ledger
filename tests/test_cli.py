"""CLI ask, show, and verify, including a hand-edited ledger."""

import json
import os
import subprocess
import sys

from epistemic_ledger.ledger import verify

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _run(args, ledger):
    env = os.environ.copy()
    for key in ("GROK_API_KEY", "XAI_API_KEY", "OPENAI_API_KEY", "LEDGER_PROVIDER"):
        env.pop(key, None)
    env["LEDGER_PATH"] = str(ledger)
    return subprocess.run(
        [sys.executable, "-m", "epistemic_ledger", *args],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def test_ask_show_and_verify_round_trip(tmp_path):
    """The module CLI answers in mock mode, shows the chain, and verifies it."""
    ledger = tmp_path / "ledger.jsonl"
    asked = _run(
        ["ask", "Why is the sky blue?", "--provider", "mock", "--ledger", str(ledger)],
        ledger,
    )
    assert asked.returncode == 0, asked.stderr
    assert "Epistemic Ledger" in asked.stdout
    assert "provider   mock" in asked.stdout
    assert "Chain" in asked.stdout
    assert "OK" in asked.stdout
    assert verify(ledger).ok

    shown = _run(["show", "--ledger", str(ledger)], ledger)
    assert shown.returncode == 0, shown.stderr
    assert "step" not in shown.stderr
    assert "question" in shown.stdout
    assert "score" in shown.stdout

    checked = _run(["verify", "--ledger", str(ledger)], ledger)
    assert checked.returncode == 0, checked.stderr
    assert "LEDGER OK" in checked.stdout
    assert "head" in checked.stdout


def test_verify_pinpoints_a_hand_edited_line(tmp_path):
    """Editing one word in the file makes verify name that entry and exit 1."""
    ledger = tmp_path / "ledger.jsonl"
    asked = _run(
        ["ask", "Why is the sky blue?", "--provider", "mock", "--session", "cli-demo"],
        ledger,
    )
    assert asked.returncode == 0, asked.stderr
    lines = ledger.read_text(encoding="utf-8").splitlines()
    answer_index = next(
        index for index, line in enumerate(lines) if '"step":"answer"' in line
    )
    entry = json.loads(lines[answer_index])
    entry["payload"]["answer"] = "This answer was edited after the fact."
    lines[answer_index] = json.dumps(entry)
    ledger.write_text("\n".join(lines) + "\n", encoding="utf-8")

    checked = _run(["verify", "--ledger", str(ledger)], ledger)
    assert checked.returncode == 1
    assert "TAMPER DETECTED" in checked.stdout
    assert f"entry    {answer_index}" in checked.stdout
    assert "stored hash does not match" in checked.stdout

    shown = _run(["show", "--ledger", str(ledger)], ledger)
    assert shown.returncode == 1
    assert "TAMPER DETECTED" in shown.stdout


def test_verify_missing_ledger_exits_nonzero(tmp_path):
    """A typo in the path is a failed check, not a quiet success."""
    missing = tmp_path / "nope.jsonl"
    checked = _run(["verify", "--ledger", str(missing)], missing)
    assert checked.returncode == 1
    assert "not found" in checked.stdout


def test_main_module_help_lists_commands():
    """``python main.py`` reaches the same parser."""
    result = subprocess.run(
        [sys.executable, "main.py", "--help"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0
    assert "ask" in result.stdout
    assert "verify" in result.stdout
