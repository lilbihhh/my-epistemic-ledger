"""Provider selection and JSON parsing. No network calls."""

import pytest

from epistemic_ledger.ledger import LedgerError
from epistemic_ledger.llm import MockLLM, parse_json_object, resolve_llm

KEYS = ("GROK_API_KEY", "XAI_API_KEY", "OPENAI_API_KEY", "LEDGER_PROVIDER")


@pytest.fixture(autouse=True)
def _clear_provider_env(monkeypatch):
    for key in KEYS:
        monkeypatch.delenv(key, raising=False)


def test_auto_uses_mock_without_keys():
    """No keys means the offline client, not a failed request."""
    client = resolve_llm("auto")
    assert isinstance(client, MockLLM)
    assert client.name == "mock"


def test_auto_prefers_grok_when_both_keys_exist(monkeypatch):
    """Grok wins over OpenAI in auto mode. XAI_API_KEY is accepted as the Grok key."""
    monkeypatch.setenv("XAI_API_KEY", "xai-test")
    monkeypatch.setenv("OPENAI_API_KEY", "openai-test")
    client = resolve_llm(None)
    assert client.name == "grok"
    assert client.model == "grok-4.7"


def test_explicit_provider_and_model_override(monkeypatch):
    """A requested provider is used even when another key is present."""
    monkeypatch.setenv("OPENAI_API_KEY", "openai-test")
    monkeypatch.setenv("GROK_API_KEY", "grok-test")
    assert resolve_llm("mock").name == "mock"
    openai_client = resolve_llm("openai", model="gpt-test")
    assert openai_client.name == "openai"
    assert openai_client.model == "gpt-test"


def test_live_provider_without_a_key_raises():
    """Selecting Grok or OpenAI with no key fails before any request."""
    with pytest.raises(LedgerError, match="GROK_API_KEY"):
        resolve_llm("grok")
    with pytest.raises(LedgerError, match="OPENAI_API_KEY"):
        resolve_llm("openai")


def test_parse_json_object_accepts_fences_and_preamble():
    """Models sometimes wrap JSON. The parser keeps the object."""
    fenced = '```json\n{"claims": [{"id": "c1", "text": "hi"}]}\n```'
    assert parse_json_object(fenced)["claims"][0]["id"] == "c1"
    preamble = 'Here you go:\n{"answer": "yes", "uncertainties": []}\nThanks.'
    assert parse_json_object(preamble)["answer"] == "yes"
    with pytest.raises(LedgerError):
        parse_json_object("no json here")
