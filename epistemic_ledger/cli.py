"""Command line: ``ask``, ``show``, and ``verify``."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

from epistemic_ledger.ledger import Ledger, LedgerError, read_entries, verify
from epistemic_ledger.llm import resolve_llm
from epistemic_ledger.pipeline import run_question
from epistemic_ledger.report import format_entry, format_run, format_verification


def build_parser() -> argparse.ArgumentParser:
    """Build the argument parser. Subcommands are required."""
    parser = argparse.ArgumentParser(
        prog="epistemic-ledger",
        description="Record an AI reasoning run in a tamper-evident hash chain.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    ask = subparsers.add_parser("ask", help="Reason about a question and append the steps")
    ask.add_argument("question", help="The question to reason about")
    ask.add_argument(
        "--provider",
        choices=["auto", "mock", "grok", "openai"],
        default=None,
        help="auto uses Grok, then OpenAI, then the offline mock",
    )
    ask.add_argument("--model", default=None, help="Override the model name for a live provider")
    ask.add_argument("--ledger", default=None, help="Path to the JSONL ledger")
    ask.add_argument("--session", default=None, help="Session id to store (default: a new uuid)")

    show = subparsers.add_parser("show", help="Print ledger entries")
    show.add_argument("--ledger", default=None, help="Path to the JSONL ledger")
    show.add_argument("--session", default=None, help="Only entries from this session id")

    check = subparsers.add_parser("verify", help="Check the hash chain and pinpoint tampering")
    check.add_argument("--ledger", default=None, help="Path to the JSONL ledger")
    return parser


def ledger_path(raw: str | None) -> Path:
    """Resolve the ledger path from the flag, then ``LEDGER_PATH``, then the default."""
    chosen = raw or os.getenv("LEDGER_PATH") or "ledger.jsonl"
    return Path(chosen)


def _matches_session(entry: dict, wanted: str) -> bool:
    session = str(entry.get("session_id", ""))
    return session == wanted or session.startswith(wanted)


def _cmd_ask(args: argparse.Namespace) -> int:
    if not str(args.question).strip():
        print("error: question is empty", file=sys.stderr)
        return 2
    path = ledger_path(args.ledger)
    llm = resolve_llm(args.provider, args.model)
    ledger = Ledger(path)
    result = run_question(
        question=args.question,
        llm=llm,
        ledger=ledger,
        session_id=args.session,
    )
    print(format_run(result, verify(path)))
    return 0


def _cmd_show(args: argparse.Namespace) -> int:
    path = ledger_path(args.ledger)
    report = verify(path)
    print(format_verification(report))
    print()
    if not path.exists():
        return 1
    entries = read_entries(path)
    if args.session:
        entries = [entry for entry in entries if _matches_session(entry, args.session)]
    if not entries:
        print("No entries to show.")
        return 0 if report.ok else 1
    for entry in entries:
        print(format_entry(entry))
        print()
    return 0 if report.ok else 1


def _cmd_verify(args: argparse.Namespace) -> int:
    report = verify(ledger_path(args.ledger))
    print(format_verification(report))
    return 0 if report.ok else 1


def main(argv: list[str] | None = None) -> int:
    """Run the CLI. Returns a process exit code."""
    load_dotenv()
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "ask":
            return _cmd_ask(args)
        if args.command == "show":
            return _cmd_show(args)
        if args.command == "verify":
            return _cmd_verify(args)
    except LedgerError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(f"error: unknown command {args.command}", file=sys.stderr)
    return 2


def app() -> None:
    """Setuptools console-script entry point."""
    sys.exit(main())
