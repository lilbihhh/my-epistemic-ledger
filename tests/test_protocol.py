"""Protocol rules: schema, signatures, step order, Merkle roots, and test vectors."""

import json
from importlib.resources import files

from epistemic_ledger.bundle import build_bundle, verify_bundle_document
from epistemic_ledger.ledger import Ledger, canonical_bytes, entry_hash, read_entries
from epistemic_ledger.llm import MockLLM
from epistemic_ledger.merkle import merkle_root
from epistemic_ledger.pipeline import run_question
from epistemic_ledger.protocol import (
    append_error,
    checkpoint_payload,
    verify_entries,
    verify_protocol,
)
from epistemic_ledger.signing import signature_error, signer_from_seed
from tests.support import ticking_clock

VECTORS = json.loads(
    files("epistemic_ledger.schema").joinpath("test-vectors.json").read_text(encoding="utf-8")
)


def test_unsigned_vector_matches_the_canonical_hash():
    """The published canonical bytes are exactly what the hasher covers."""
    vector = VECTORS["unsigned_question"]
    entry = vector["entry"]
    body = {key: value for key, value in entry.items() if key != "hash"}
    assert canonical_bytes(body).decode() == vector["canonical"]
    assert entry_hash(entry) == vector["hash"]
    assert verify_entries([entry], label="vector").ok


def test_two_entry_vector_chain_and_signed_vector():
    """A linked pair verifies, and the published signature matches the public test key."""
    chain = VECTORS["two_entry_chain"]
    assert verify_entries(chain, label="vector-chain").ok
    assert chain[1]["prev_hash"] == chain[0]["hash"]
    signed = VECTORS["signed_question"]["entry"]
    assert signed["signer"] == VECTORS["public_key"]
    assert signature_error(signed) is None
    assert verify_entries([signed], label="signed").ok


def test_bad_signature_vector_is_rejected():
    """A recomputed hash does not rescue a signature that was not produced by the key."""
    entry = VECTORS["bad_signature_entry"]
    assert entry_hash(entry) == entry["hash"]
    report = verify_entries([entry], label="bad-signature")
    assert not report.ok
    assert report.failure_index == 0
    assert report.reason is not None
    assert "signature" in report.reason


def test_out_of_order_vector_is_rejected():
    """question followed immediately by answer breaks the state machine."""
    entries = VECTORS["out_of_order"]
    assert entry_hash(entries[1]) == entries[1]["hash"]
    report = verify_entries(entries, label="order")
    assert not report.ok
    assert report.failure_index == 1
    assert report.reason is not None
    assert "not allowed" in report.reason


def test_merkle_vectors():
    """Published roots follow merkle-sha256-v1, including the duplicate-last rule."""
    spec = VECTORS["merkle_sha256_v1"]
    assert merkle_root([]) == spec["empty_root"]
    assert merkle_root(spec["one_leaf"]["leaves"]) == spec["one_leaf"]["root"]
    assert spec["one_leaf"]["root"] == spec["one_leaf"]["leaves"][0]
    assert merkle_root(spec["two_leaves"]["leaves"]) == spec["two_leaves"]["root"]
    three = spec["three_leaves_duplicate_last"]
    assert merkle_root(three["leaves"]) == three["root"]


def test_hand_edit_fails_protocol_verification(tmp_path):
    """Changing a sealed payload without its hash fails verify_protocol."""
    path = tmp_path / "ledger.jsonl"
    ledger = Ledger(path, clock=ticking_clock())
    run_question(question="Why is the sky blue?", llm=MockLLM(), ledger=ledger, session_id="proto")
    lines = path.read_text(encoding="utf-8").splitlines()
    edited = json.loads(lines[0])
    edited["payload"]["question"] = "edited by hand"
    lines[0] = json.dumps(edited)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    report = verify_protocol(str(path))
    assert not report.ok
    assert report.failure_index == 0
    assert report.reason == "stored hash does not match the entry contents"


def test_signed_session_witness_checkpoint_and_bundle(tmp_path):
    """A signed run can take a human witness, a Merkle checkpoint, and a portable bundle."""
    signer = signer_from_seed(bytes.fromhex(VECTORS["seed_hex"]))
    path = tmp_path / "ledger.jsonl"
    ledger = Ledger(path, clock=ticking_clock(), signer=signer, checker=append_error)
    result = run_question(
        question="Why is the sky blue?",
        llm=MockLLM(),
        ledger=ledger,
        session_id="proto",
    )
    ledger.append(
        step="witness",
        session_id="proto",
        payload={
            "claim_id": "c1",
            "stance": "attest",
            "note": "The claim is the one the question asked.",
            "witness_name": "Ada",
        },
    )
    session_entries = [entry for entry in read_entries(path) if entry["session_id"] == "proto"]
    ledger.append(
        step="checkpoint",
        session_id="proto",
        payload=checkpoint_payload(session_entries),
    )
    report = verify_protocol(str(path))
    assert report.ok
    assert result["claims"]
    document = build_bundle(read_entries(path))
    bundle_report = verify_bundle_document(document)
    assert bundle_report.ok
    assert document["signers"] == [signer.public_hex]
    assert document["merkle_roots"][0]["root"]
    document["merkle_roots"][0]["root"] = "ab" * 32
    tampered = verify_bundle_document(document)
    assert not tampered.ok
    assert tampered.reason is not None
    assert "merkle_roots" in tampered.reason


def test_legacy_entry_without_version_still_verifies():
    """Omitting version is the pre-spec 1.0 record shape and remains acceptable."""
    entry = json.loads(json.dumps(VECTORS["unsigned_question"]["entry"]))
    del entry["version"]
    entry["hash"] = entry_hash(entry)
    report = verify_entries([entry], label="legacy")
    assert report.ok
