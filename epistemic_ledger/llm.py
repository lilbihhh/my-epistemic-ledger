"""Model clients: xAI Grok, OpenAI, and a deterministic offline mock.

``auto`` uses Grok when ``GROK_API_KEY`` or ``XAI_API_KEY`` is set, otherwise
OpenAI when ``OPENAI_API_KEY`` is set, otherwise the mock. The mock never
opens a socket. Tests and ``ask --provider mock`` depend on that.
"""

from __future__ import annotations

import json
import os
import re
from typing import Any

from openai import OpenAI, OpenAIError

from epistemic_ledger.ledger import LedgerError

DEFAULT_GROK_MODEL = "grok-4.7"
DEFAULT_GROK_BASE_URL = "https://api.x.ai/v1"
DEFAULT_OPENAI_MODEL = "gpt-4o-mini"
DEFAULT_OPENAI_BASE_URL = "https://api.openai.com/v1"
_SECTION_STOPS = ("\nQUESTION:", "\nCLAIMS_JSON:", "\nSCORES_JSON:", "\nReturn ")


def parse_json_object(text: str) -> dict[str, Any]:
    """Parse a JSON object, including one wrapped in a markdown fence."""
    stripped = text.strip()
    if stripped.startswith("```"):
        lines = stripped.splitlines()
        lines = lines[1:]
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        stripped = "\n".join(lines).strip()
    try:
        parsed = json.loads(stripped)
    except json.JSONDecodeError:
        start = stripped.find("{")
        end = stripped.rfind("}")
        if start == -1 or end <= start:
            raise LedgerError("model response did not contain a JSON object") from None
        try:
            parsed = json.loads(stripped[start : end + 1])
        except json.JSONDecodeError as exc:
            raise LedgerError(f"model response was not valid JSON: {exc.msg}") from exc
    if not isinstance(parsed, dict):
        raise LedgerError("model response JSON was not an object")
    return parsed


def _section(user: str, label: str) -> str:
    marker = f"{label}:\n"
    start = user.find(marker)
    if start < 0:
        raise LedgerError(f"offline prompt is missing {label}")
    rest = user[start + len(marker) :]
    stop_at = len(rest)
    for header in _SECTION_STOPS:
        if header.endswith(f"{label}:"):
            continue
        found = rest.find(header)
        if found != -1:
            stop_at = min(stop_at, found)
    return rest[:stop_at].strip()


def _mock_decompose(question: str) -> dict[str, Any]:
    core = " ".join(question.strip().split()).rstrip("?").strip()
    core = core or "The question was empty"
    pieces = [
        part.strip()
        for part in re.split(r"\s+and\s+", core, maxsplit=1, flags=re.IGNORECASE)
    ]
    claims: list[dict[str, str]] = []
    long_enough = len(pieces) == 2 and all(len(part.split()) >= 3 for part in pieces)
    if long_enough:
        claims.append({"id": "c1", "text": pieces[0]})
        claims.append({"id": "c2", "text": pieces[1]})
    else:
        claims.append(
            {
                "id": "c1",
                "text": f"This question has a checkable core: {core}",
            }
        )
    next_id = f"c{len(claims) + 1}"
    claims.append(
        {
            "id": next_id,
            "text": (
                "A careful answer should state the assumptions behind this question "
                f"rather than treat it as already settled: {core}"
            ),
        }
    )
    return {"claims": claims}


def _mock_evidence(claim: dict[str, str]) -> dict[str, Any]:
    text = claim["text"]
    lowered = text.lower()
    tokens = set(re.findall(r"[a-z0-9']+", lowered))
    hedging_words = {"assumption", "assumptions", "might", "could", "maybe"}
    hedging = bool(tokens & hedging_words)
    word_count = len(text.split())
    if hedging or word_count > 16:
        return {
            "claim_id": claim["id"],
            "reasoning": "Offline trace: the claim reaches past what the question itself states.",
            "supports": ["The claim is a hypothesis suggested by the wording of the question."],
            "caveats": [
                "No external source was checked in offline mode.",
                "The claim is broad enough that a different reading is easy to make.",
            ],
            "quality": "speculative",
            "self_confidence": 0.42,
        }
    if word_count > 8:
        return {
            "claim_id": claim["id"],
            "reasoning": "Offline trace: the claim follows from the question, with one open check.",
            "supports": [
                "The claim restates part of the question in a form that can be checked.",
                "Nothing in the claim contradicts the rest of the question.",
            ],
            "caveats": ["The inference has not been compared with an external source."],
            "quality": "inferred",
            "self_confidence": 0.61,
        }
    return {
        "claim_id": claim["id"],
        "reasoning": "Offline trace: the claim is narrow enough to score from its wording alone.",
        "supports": [
            "The claim is narrow.",
            "Its terms are used consistently.",
            "A direct reading does not add a new assumption.",
        ],
        "caveats": [],
        "quality": "direct",
        "self_confidence": 0.74,
    }


def _mock_answer(
    question: str,
    claims: list[dict[str, Any]],
    scores: dict[str, Any],
) -> dict[str, Any]:
    overall = scores["overall"]["confidence"]
    parts: list[str] = []
    uncertainties = [
        "Offline mode does not consult sources. "
        "Each claim is scored from its wording and the evidence list recorded beside it."
    ]
    by_id = {item["claim_id"]: item for item in scores["claims"]}
    for claim in claims:
        scored = by_id[claim["id"]]
        parts.append(f"{claim['id']} ({scored['quality']}, {scored['confidence']:.4f})")
        if scored["quality"] in {"speculative", "unsupported"}:
            uncertainties.append(
                f"{claim['id']} is {scored['quality']} "
                f"({scored['supports']} supports, {scored['caveats']} caveats)."
            )
    answer = (
        "Offline trace, no live model was called. "
        f"For '{question}', the ledger holds {len(claims)} claims: "
        + "; ".join(parts)
        + f". The structural-evidence score for the whole answer is {overall:.4f}. "
        "That number bounds how well the recorded evidence supports the claims. "
        "It is not a probability that the world matches the answer."
    )
    return {"answer": answer, "uncertainties": uncertainties}


class MockLLM:
    """Deterministic stand-in. Same question, same JSON, no network."""

    name = "mock"
    model = "mock-offline"

    def complete(self, *, stage: str, system: str, user: str) -> str:
        """Return stage JSON. ``system`` is accepted so the signature matches live clients."""
        del system
        if stage == "decompose":
            payload = _mock_decompose(_section(user, "QUESTION"))
        elif stage == "evidence":
            claims = json.loads(_section(user, "CLAIMS_JSON"))
            payload = {"evidence": [_mock_evidence(claim) for claim in claims]}
        elif stage == "answer":
            payload = _mock_answer(
                _section(user, "QUESTION"),
                json.loads(_section(user, "CLAIMS_JSON")),
                json.loads(_section(user, "SCORES_JSON")),
            )
        else:
            raise LedgerError(f"unknown stage: {stage}")
        return json.dumps(payload, ensure_ascii=False)


def _message_text(content: Any) -> str:
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict):
                parts.append(str(item.get("text", "")))
            else:
                parts.append(str(getattr(item, "text", "") or ""))
        return "".join(parts)
    return str(content)


class OpenAICompatibleLLM:
    """Chat completions client. Grok and OpenAI differ by base URL and key."""

    def __init__(self, *, name: str, api_key: str, base_url: str, model: str) -> None:
        self.name = name
        self.model = model
        self._client = OpenAI(api_key=api_key, base_url=base_url, timeout=120.0)

    def complete(self, *, stage: str, system: str, user: str) -> str:
        """Send one chat completion. Temperature is 0 so reruns stay close."""
        try:
            response = self._client.chat.completions.create(
                model=self.model,
                temperature=0,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": f"STEP: {stage}\n\n{user}"},
                ],
            )
        except OpenAIError as exc:
            raise LedgerError(f"{self.name} request failed: {exc}") from exc
        content = _message_text(response.choices[0].message.content)
        if not content.strip():
            raise LedgerError(f"{self.name} returned an empty message")
        return content


def _grok_key() -> str | None:
    return os.getenv("GROK_API_KEY") or os.getenv("XAI_API_KEY")


def resolve_llm(
    provider: str | None = None,
    model: str | None = None,
) -> MockLLM | OpenAICompatibleLLM:
    """Build the client named by ``provider``, ``LEDGER_PROVIDER``, or ``auto``."""
    selected = (provider or os.getenv("LEDGER_PROVIDER") or "auto").strip().lower()
    if selected == "auto":
        if _grok_key():
            selected = "grok"
        elif os.getenv("OPENAI_API_KEY"):
            selected = "openai"
        else:
            selected = "mock"
    if selected == "mock":
        return MockLLM()
    if selected == "grok":
        key = _grok_key()
        if not key:
            raise LedgerError("Grok selected but GROK_API_KEY / XAI_API_KEY is not set")
        return OpenAICompatibleLLM(
            name="grok",
            api_key=key,
            base_url=os.getenv("GROK_BASE_URL", DEFAULT_GROK_BASE_URL),
            model=model or os.getenv("GROK_MODEL", DEFAULT_GROK_MODEL),
        )
    if selected == "openai":
        key = os.getenv("OPENAI_API_KEY")
        if not key:
            raise LedgerError("OpenAI selected but OPENAI_API_KEY is not set")
        return OpenAICompatibleLLM(
            name="openai",
            api_key=key,
            base_url=os.getenv("OPENAI_BASE_URL", DEFAULT_OPENAI_BASE_URL),
            model=model or os.getenv("OPENAI_MODEL", DEFAULT_OPENAI_MODEL),
        )
    raise LedgerError(f"unknown provider: {selected}")
