"""Ed25519 signatures over the canonical signable body of an entry.

The signed bytes are the canonical JSON of every field except ``hash`` and
``signature``. ``signer`` is inside those bytes, so a signature cannot be
moved onto a different public key. The chain hash is computed after the
signature is attached, so stripping or swapping it also breaks the hash.
"""

from __future__ import annotations

import os
from pathlib import Path

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

from epistemic_ledger.ledger import LedgerError, canonical_bytes

SIGNABLE_EXCLUDED = frozenset({"hash", "signature"})


def signable_bytes(entry: dict) -> bytes:
    """Canonical bytes a signature commits to."""
    body = {key: value for key, value in entry.items() if key not in SIGNABLE_EXCLUDED}
    return canonical_bytes(body)


class Signer:
    """An Ed25519 private key that can seal ledger entries."""

    def __init__(self, private_key: Ed25519PrivateKey) -> None:
        self._private = private_key
        public = private_key.public_key().public_bytes(
            serialization.Encoding.Raw,
            serialization.PublicFormat.Raw,
        )
        self.public_hex = public.hex()

    def sign(self, message: bytes) -> str:
        """Return the hex-encoded signature of ``message``."""
        return self._private.sign(message).hex()

    def private_pem(self) -> bytes:
        """PKCS8 PEM with no encryption."""
        return self._private.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )


def signer_from_seed(seed: bytes) -> Signer:
    """Build a signer from a 32-byte seed. Test vectors use a public seed."""
    if len(seed) != 32:
        raise LedgerError("Ed25519 seed must be 32 bytes")
    return Signer(Ed25519PrivateKey.from_private_bytes(seed))


def generate_signer() -> Signer:
    """Generate a new random signer."""
    return Signer(Ed25519PrivateKey.generate())


def load_signer(path: str | Path) -> Signer:
    """Load a PEM private key. Raises ``LedgerError`` when the file is unusable."""
    key_path = Path(path)
    try:
        pem = key_path.read_bytes()
        loaded = serialization.load_pem_private_key(pem, password=None)
    except (OSError, ValueError, TypeError) as exc:
        raise LedgerError(f"could not read signing key {key_path}: {exc}") from exc
    if not isinstance(loaded, Ed25519PrivateKey):
        raise LedgerError(f"signing key {key_path} is not Ed25519")
    return Signer(loaded)


def write_signer(path: str | Path, signer: Signer) -> None:
    """Write a private key as mode 0600 PEM."""
    key_path = Path(path)
    key_path.parent.mkdir(parents=True, exist_ok=True)
    pem = signer.private_pem()
    descriptor = os.open(key_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        os.fchmod(descriptor, 0o600)
        os.write(descriptor, pem)
    finally:
        os.close(descriptor)


def signature_error(entry: dict) -> str | None:
    """Return a reason when a present signature does not verify.

    Entries with neither ``signer`` nor ``signature`` are unsigned and allowed.
    """
    signer = entry.get("signer")
    signature = entry.get("signature")
    if signer is None and signature is None:
        return None
    if not isinstance(signer, str) or not isinstance(signature, str):
        return "signature: signer and signature must both be hex strings"
    try:
        public_bytes = bytes.fromhex(signer)
        signature_bytes = bytes.fromhex(signature)
    except ValueError:
        return "signature: signer or signature is not hex"
    if len(public_bytes) != 32 or len(signature_bytes) != 64:
        return "signature: wrong length for Ed25519"
    public = Ed25519PublicKey.from_public_bytes(public_bytes)
    try:
        public.verify(signature_bytes, signable_bytes(entry))
    except InvalidSignature:
        return "signature does not verify for the stated signer"
    return None
