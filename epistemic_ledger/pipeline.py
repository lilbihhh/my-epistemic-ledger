"""LangGraph pipeline: question, claims, evidence, score, answer.

Scoring is local. The model proposes claims, evidence features, and the
wording of the answer. The confidence figure is computed in
``confidence.py`` and stored with the formula, so the number does not
depend on trusting the model's self-report.
"""

from __future__ import annotations

import os
import uuid
from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph

from epistemic_ledger.confidence import score_claims
from epistemic_ledger.ledger import Ledger, LedgerError
from epistemic_ledger.llm import MockLLM, OpenAICompatibleLLM, parse_json_object
from epistemic_ledger.normalize import normalize_answer, normalize_claims, normalize_evidence
from epistemic_ledger.prompts import SYSTEM, answer_user, decompose_user, evidence_user


class PipelineState(TypedDict, total=False):
    """State carried from one graph node to the next."""

    question: str
    session_id: str
    claims: list[dict[str, str]]
    evidence: list[dict[str, Any]]
    scores: dict[str, Any]
    answer: str
    uncertainties: list[str]


def _complete_json(llm: MockLLM | OpenAICompatibleLLM, *, stage: str, user: str) -> dict[str, Any]:
    last_error: Exception | None = None
    for _attempt in range(2):
        text = llm.complete(stage=stage, system=SYSTEM, user=user)
        try:
            return parse_json_object(text)
        except LedgerError as exc:
            last_error = exc
    raise LedgerError(f"{stage} step did not return JSON: {last_error}")


def build_graph(llm: MockLLM | OpenAICompatibleLLM, ledger: Ledger) -> Any:
    """Compile the four reasoning steps plus the opening question record."""

    def record_question(state: PipelineState) -> dict[str, Any]:
        ledger.append(
            step="question",
            session_id=state["session_id"],
            payload={
                "question": state["question"],
                "provider": llm.name,
                "model": llm.model,
            },
        )
        return {}

    def decompose(state: PipelineState) -> dict[str, Any]:
        raw = _complete_json(llm, stage="decompose", user=decompose_user(state["question"]))
        claims = normalize_claims(raw)
        ledger.append(
            step="decompose",
            session_id=state["session_id"],
            payload={"claims": claims},
        )
        return {"claims": claims}

    def gather(state: PipelineState) -> dict[str, Any]:
        raw = _complete_json(
            llm,
            stage="evidence",
            user=evidence_user(state["question"], state["claims"]),
        )
        evidence = normalize_evidence(state["claims"], raw)
        for item in evidence:
            ledger.append(step="evidence", session_id=state["session_id"], payload=item)
        return {"evidence": evidence}

    def score(state: PipelineState) -> dict[str, Any]:
        scores = score_claims(state["evidence"])
        ledger.append(step="score", session_id=state["session_id"], payload=scores)
        return {"scores": scores}

    def synthesize(state: PipelineState) -> dict[str, Any]:
        raw = _complete_json(
            llm,
            stage="answer",
            user=answer_user(state["question"], state["claims"], state["scores"]),
        )
        answer = normalize_answer(raw)
        ledger.append(
            step="answer",
            session_id=state["session_id"],
            payload={
                "answer": answer["answer"],
                "uncertainties": answer["uncertainties"],
                "overall_confidence": state["scores"]["overall"]["confidence"],
                "method": state["scores"]["method"],
            },
        )
        return answer

    graph = StateGraph(PipelineState)
    graph.add_node("record_question", record_question)
    graph.add_node("decompose", decompose)
    graph.add_node("gather", gather)
    graph.add_node("score", score)
    graph.add_node("synthesize", synthesize)
    graph.add_edge(START, "record_question")
    graph.add_edge("record_question", "decompose")
    graph.add_edge("decompose", "gather")
    graph.add_edge("gather", "score")
    graph.add_edge("score", "synthesize")
    graph.add_edge("synthesize", END)
    return graph.compile()


def run_question(
    *,
    question: str,
    llm: MockLLM | OpenAICompatibleLLM,
    ledger: Ledger,
    session_id: str | None = None,
) -> dict[str, Any]:
    """Run one question and append every step to ``ledger``."""
    cleaned = " ".join(question.split())
    if not cleaned:
        raise LedgerError("question is empty")
    os.environ.setdefault("LANGCHAIN_TRACING_V2", "false")
    os.environ.setdefault("LANGSMITH_TRACING", "false")
    session = session_id or str(uuid.uuid4())
    graph = build_graph(llm, ledger)
    final = dict(graph.invoke({"question": cleaned, "session_id": session}))
    final["provider"] = llm.name
    final["model"] = llm.model
    final["ledger_path"] = str(ledger.path)
    final["session_id"] = session
    return final
