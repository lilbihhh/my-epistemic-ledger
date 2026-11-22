"""Command line: ``ask``, ``show``, and ``verify``."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

from epistemic_ledger.bundle import export_path, load_bundle, verify_bundle_document
from epistemic_ledger.ledger import Ledger, LedgerError, read_entries
from epistemic_ledger.llm import resolve_llm
from epistemic_ledger.pipeline import run_question
from epistemic_ledger.protocol import append_error, checkpoint_payload, verify_protocol
from epistemic_ledger.report import format_entry, format_run, format_verification
from epistemic_ledger.signing import Signer, generate_signer, load_signer, write_signer


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
    ask.add_argument("--key", default=None, help="PEM Ed25519 key. Signs entries when a key is set")
    ask.add_argument(
        "--no-checkpoint",
        action="store_true",
        help="Do not append a Merkle checkpoint after the answer",
    )

    show = subparsers.add_parser("show", help="Print ledger entries")
    show.add_argument("--ledger", default=None, help="Path to the JSONL ledger")
    show.add_argument("--session", default=None, help="Only entries from this session id")

    check = subparsers.add_parser(
        "verify",
        help="Check the hash chain, schema, signatures, and step order",
    )
    check.add_argument("--ledger", default=None, help="Path to the JSONL ledger")

    keygen = subparsers.add_parser("keygen", help="Write a new Ed25519 signing key")
    keygen.add_argument("--out", default="ledger.key", help="PEM path to create (mode 0600)")

    witness = subparsers.add_parser("witness", help="Attest to or dispute a recorded claim")
    witness.add_argument("--session", required=True, help="Session id that holds the claim")
    witness.add_argument("--claim", required=True, help="Claim id, such as c1")
    witness.add_argument("--stance", required=True, choices=["attest", "dispute"])
    witness.add_argument("--note", default="", help="Why the witness takes this stance")
    witness.add_argument("--name", required=True, help="Name of the person witnessing")
    witness.add_argument("--ledger", default=None)
    witness.add_argument("--key", default=None)

    checkpoint = subparsers.add_parser("checkpoint", help="Append a Merkle root for one session")
    checkpoint.add_argument("--session", required=True)
    checkpoint.add_argument("--ledger", default=None)
    checkpoint.add_argument("--key", default=None)

    export = subparsers.add_parser("export", help="Write a standalone verification bundle")
    export.add_argument("--ledger", default=None)
    export.add_argument("--out", required=True, help="Bundle JSON path")

    bundled = subparsers.add_parser("verify-bundle", help="Verify an exported bundle")
    bundled.add_argument("bundle", help="Bundle JSON path")
    return parser


def ledger_path(raw: str | None) -> Path:
    """Resolve the ledger path from the flag, then ``LEDGER_PATH``, then the default."""
    chosen = raw or os.getenv("LEDGER_PATH") or "ledger.jsonl"
    return Path(chosen)


def _resolve_signer(explicit: str | None) -> Signer | None:
    chosen = explicit or os.getenv("LEDGER_SIGNING_KEY")
    if chosen:
        return load_signer(chosen)
    default = Path("ledger.key")
    if explicit is None and default.exists():
        return load_signer(default)
    return None


def _open_ledger(args: argparse.Namespace) -> Ledger:
    return Ledger(
        ledger_path(getattr(args, "ledger", None)),
        signer=_resolve_signer(getattr(args, "key", None)),
        checker=append_error,
    )


def _matches_session(entry: dict, wanted: str) -> bool:
    session = str(entry.get("session_id", ""))
    return session == wanted or session.startswith(wanted)


def _append_checkpoint(ledger: Ledger, session_id: str) -> None:
    entries = [
        entry for entry in read_entries(ledger.path) if entry.get("session_id") == session_id
    ]
    ledger.append(
        step="checkpoint",
        session_id=session_id,
        payload=checkpoint_payload(entries),
    )


def _cmd_ask(args: argparse.Namespace) -> int:
    if not str(args.question).strip():
        print("error: question is empty", file=sys.stderr)
        return 2
    path = ledger_path(args.ledger)
    llm = resolve_llm(args.provider, args.model)
    ledger = _open_ledger(args)
    result = run_question(
        question=args.question,
        llm=llm,
        ledger=ledger,
        session_id=args.session,
    )
    if not args.no_checkpoint:
        _append_checkpoint(ledger, result["session_id"])
    print(format_run(result, verify_protocol(str(path))))
    return 0


def _cmd_keygen(args: argparse.Namespace) -> int:
    signer = generate_signer()
    write_signer(args.out, signer)
    print(f"wrote {args.out}")
    print(f"public {signer.public_hex}")
    return 0


def _cmd_witness(args: argparse.Namespace) -> int:
    ledger = _open_ledger(args)
    ledger.append(
        step="witness",
        session_id=args.session,
        payload={
            "claim_id": args.claim,
            "stance": args.stance,
            "note": args.note,
            "witness_name": args.name,
        },
    )
    print(format_verification(verify_protocol(str(ledger.path))))
    return 0


def _cmd_checkpoint(args: argparse.Namespace) -> int:
    ledger = _open_ledger(args)
    _append_checkpoint(ledger, args.session)
    print(format_verification(verify_protocol(str(ledger.path))))
    return 0


def _cmd_export(args: argparse.Namespace) -> int:
    document = export_path(str(ledger_path(args.ledger)))
    destination = Path(args.out)
    encoded = json.dumps(document, indent=2, ensure_ascii=False) + "\n"
    destination.write_text(encoded, encoding="utf-8")
    print(f"wrote {destination}")
    print(f"head {document['head']}")
    print(f"entries {len(document['entries'])}")
    return 0


def _cmd_verify_bundle(args: argparse.Namespace) -> int:
    report = verify_bundle_document(load_bundle(args.bundle))
    print(format_verification(report))
    return 0 if report.ok else 1


def _cmd_show(args: argparse.Namespace) -> int:
    path = ledger_path(args.ledger)
    report = verify_protocol(str(path))
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
    report = verify_protocol(str(ledger_path(args.ledger)))
    print(format_verification(report))
    return 0 if report.ok else 1


def main(argv: list[str] | None = None) -> int:
    """Run the CLI. Returns a process exit code."""
    load_dotenv()
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        commands = {
            "ask": _cmd_ask,
            "show": _cmd_show,
            "verify": _cmd_verify,
            "keygen": _cmd_keygen,
            "witness": _cmd_witness,
            "checkpoint": _cmd_checkpoint,
            "export": _cmd_export,
            "verify-bundle": _cmd_verify_bundle,
        }
        handler = commands.get(args.command)
        if handler is not None:
            return handler(args)
    except LedgerError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(f"error: unknown command {args.command}", file=sys.stderr)
    return 2


def app() -> None:
    """Setuptools console-script entry point."""
    sys.exit(main())
