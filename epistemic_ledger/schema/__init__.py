"""JSON Schema for Epistemic Ledger Protocol 1.0 entries."""

from __future__ import annotations

import json
from functools import lru_cache
from importlib.resources import files

from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError


def entry_schema() -> dict:
    """Return the v1 entry schema document."""
    text = files("epistemic_ledger.schema").joinpath("entry.v1.json").read_text(encoding="utf-8")
    loaded = json.loads(text)
    if not isinstance(loaded, dict):
        raise RuntimeError("entry schema is not an object")
    return loaded


@lru_cache(maxsize=1)
def validator() -> Draft202012Validator:
    """Cached Draft 2020-12 validator for one ledger entry."""
    return Draft202012Validator(entry_schema())


def schema_error(entry: dict) -> str | None:
    """Return a short reason when ``entry`` violates the schema."""
    try:
        validator().validate(entry)
    except ValidationError as exc:
        path = "/".join(str(part) for part in exc.absolute_path) or "(entry)"
        message = exc.message
        if len(message) > 180:
            message = message[:177] + "..."
        return f"schema: {path}: {message}"
    return None
