"""Prompt text shared by live models and the offline mock.

The mock reads the labeled blocks. Live models see the same text and are
asked to return one JSON object.
"""

from __future__ import annotations

import json
from typing import Any

SYSTEM = (
    "You are the reasoning engine of an auditable ledger. "
    "Every claim you produce is stored and hash-chained so a later reader can check it. "
    "Do not invent citations, studies, or quotations. "
    "If you are unsure, say so in caveats and set quality to speculative. "
    "Reply with one JSON object and no markdown."
)


def decompose_user(question: str) -> str:
    """Ask for 2–4 atomic claims."""
    return (
        "Break the question into 2 to 4 atomic claims that a careful answer "
        "would have to take a position on. Each claim is one sentence. "
        "Number them c1, c2, c3, in order.\n\n"
        f"QUESTION:\n{question}\n\n"
        'Return {"claims": [{"id": "c1", "text": "..."}]}'
    )


def evidence_user(question: str, claims: list[dict[str, Any]]) -> str:
    """Ask for evidence features. The ledger, not the model, sets the score."""
    blob = json.dumps(claims, ensure_ascii=False)
    return (
        "For each claim, record reasoning you can stand behind.\n"
        "quality must be one of: direct, inferred, speculative, unsupported.\n"
        "supports and caveats are arrays of short strings.\n"
        "self_confidence is your own probability the claim is true, from 0 to 1. "
        "The ledger will not use self_confidence as the final score.\n"
        "Use unsupported when you have nothing to say for the claim.\n\n"
        f"QUESTION:\n{question}\n\n"
        f"CLAIMS_JSON:\n{blob}\n\n"
        "Return "
        '{"evidence": [{"claim_id": "c1", "reasoning": "...", '
        '"supports": ["..."], "caveats": ["..."], '
        '"quality": "inferred", "self_confidence": 0.6}]}'
    )


def answer_user(
    question: str,
    claims: list[dict[str, Any]],
    scores: dict[str, Any],
) -> str:
    """Ask for a final answer that respects the scores already computed."""
    claim_blob = json.dumps(claims, ensure_ascii=False)
    score_blob = json.dumps(scores, ensure_ascii=False)
    return (
        "Write the final answer from the claims and the scores already computed. "
        "Do not invent a different confidence number. "
        "Say what is still uncertain.\n\n"
        f"QUESTION:\n{question}\n\n"
        f"CLAIMS_JSON:\n{claim_blob}\n\n"
        f"SCORES_JSON:\n{score_blob}\n\n"
        'Return {"answer": "...", "uncertainties": ["..."]}'
    )
