"""Plain-text views of a run and of a verification report."""

from __future__ import annotations

import unicodedata
from typing import Any

from epistemic_ledger.ledger import VerifyResult


def for_terminal(text: object) -> str:
    """Drop characters that can rewrite a terminal when a ledger is printed.

    Newlines and tabs stay. Other control characters, and Unicode line and
    paragraph separators, become the replacement character. The file on disk
    is unchanged.
    """
    rendered: list[str] = []
    for char in str(text):
        category = unicodedata.category(char)
        safe = char in "\n\t" or (
            not category.startswith("C") and category not in {"Zl", "Zp"}
        )
        rendered.append(char if safe else "\ufffd")
    return "".join(rendered)


def format_verification(result: VerifyResult) -> str:
    """Render a verify result, including the index of the first bad entry."""
    if result.ok and result.entries == 0:
        return f"LEDGER OK\n  file     {result.path}\n  entries  0\n  empty ledger"
    if result.ok:
        return (
            "LEDGER OK\n"
            f"  file     {result.path}\n"
            f"  entries  {result.entries}\n"
            f"  head     {result.head}"
        )
    lines = [
        "TAMPER DETECTED",
        f"  file     {result.path}",
        f"  entry    {result.failure_index if result.failure_index is not None else '-'}",
        f"  check    {result.reason}",
    ]
    if result.expected is not None:
        lines.append(f"  expected {result.expected}")
    if result.found is not None:
        lines.append(f"  found    {result.found}")
    if result.failure_index is not None:
        lines.append("  entries after the break were not trusted")
    return for_terminal("\n".join(lines))


def _payload_summary(step: Any, payload: dict[str, Any]) -> str:
    if step == "question":
        return str(payload.get("question", ""))
    if step == "decompose":
        claims = payload.get("claims") or []
        return "claims " + ", ".join(str(claim.get("id")) for claim in claims)
    if step == "evidence":
        claim_id = payload.get("claim_id")
        quality = payload.get("quality")
        reasoning = payload.get("reasoning", "")
        return f"{claim_id} {quality} — {reasoning}"
    if step == "score":
        overall = payload.get("overall") or {}
        return f"overall {overall.get('confidence')} via {payload.get('method')}"
    if step == "answer":
        return str(payload.get("answer", ""))
    return ""


def format_entry(entry: dict[str, Any]) -> str:
    """One ledger line, shortened for the terminal."""
    payload = entry.get("payload")
    if not isinstance(payload, dict):
        payload = {}
    digest = str(entry.get("hash", ""))
    previous = str(entry.get("prev_hash", ""))
    summary = _payload_summary(entry.get("step"), payload)
    return for_terminal(
        f"[{entry.get('index')}] {entry.get('timestamp')}  {entry.get('step')}"
        f"  session {entry.get('session_id')}\n"
        f"    prev {previous[:16]}  hash {digest[:16]}\n"
        f"    {summary}"
    )


def format_run(result: dict[str, Any], verification: VerifyResult) -> str:
    """The report printed by ``ask``."""
    scores = result["scores"]
    by_id = {item["claim_id"]: item for item in scores["claims"]}
    lines = [
        "Epistemic Ledger",
        f"  provider   {result['provider']} ({result['model']})",
        f"  session    {result['session_id']}",
        f"  ledger     {result['ledger_path']}",
        "",
        "Question",
        f"  {result['question']}",
        "",
        "Claims",
    ]
    for claim in result["claims"]:
        scored = by_id[claim["id"]]
        lines.append(f"  {claim['id']}  {scored['confidence']:.4f}  {scored['quality']}")
        lines.append(f"      {claim['text']}")
        lines.append(f"      {scored['explanation']}")
    overall = scores["overall"]["confidence"]
    lines.extend(
        [
            "",
            f"Answer  overall {overall:.4f}  ({scores['overall']['method']})",
            f"  {result['answer']}",
        ]
    )
    uncertainties = result.get("uncertainties") or []
    if uncertainties:
        lines.append("")
        lines.append("Uncertainties")
        for item in uncertainties:
            lines.append(f"  - {item}")
    lines.append("")
    lines.append("Chain")
    if verification.ok and verification.head:
        lines.append(
            f"  OK  {verification.entries} entries  head {verification.head[:16]}"
        )
    elif verification.ok:
        lines.append(f"  OK  {verification.entries} entries")
    else:
        lines.append(f"  BROKEN at {verification.failure_index}: {verification.reason}")
    return for_terminal("\n".join(lines))
