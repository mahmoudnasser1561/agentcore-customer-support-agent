import pytest

from support_agent.tools import knowledge_base as kb
from tests.conftest import call_tool


class Runtime:
    def __init__(self, results=None, error=None):
        self.calls, self.results, self.error = [], results or [], error

    def retrieve(self, **kwargs):
        self.calls.append(kwargs)
        if self.error:
            raise self.error
        return {"retrievalResults": self.results}


@pytest.fixture
def runtime(monkeypatch):
    def install(**kw):
        rt = Runtime(**kw)
        monkeypatch.setattr(kb, "_runtime_client", lambda region: rt)
        return rt

    return install


@pytest.mark.parametrize("value", [None, "", "   ", "\t\n"])
def test_guard_returns_descriptive_message_and_skips_retrieve(monkeypatch, runtime, value):
    rt = runtime()
    if value is not None:
        monkeypatch.setenv("KNOWLEDGE_BASE_ID", value)
    out = call_tool(kb.search_knowledge_base, "return policy?")
    assert out == kb.NOT_CONFIGURED
    assert "KNOWLEDGE_BASE_ID is empty or missing" in out
    assert rt.calls == []


def test_calls_retrieve_and_joins_chunks(monkeypatch, runtime):
    monkeypatch.setenv("KNOWLEDGE_BASE_ID", "KB12345678")
    rt = runtime(
        results=[{"content": {"text": "Gadgets: 14 days"}}, {"content": {"text": "Other: 30 days"}}]
    )
    out = call_tool(kb.search_knowledge_base, "return policy")
    assert rt.calls == [
        {"knowledgeBaseId": "KB12345678", "retrievalQuery": {"text": "return policy"}}
    ]
    assert out == "Gadgets: 14 days\n---\nOther: 30 days"


def test_no_results_message(monkeypatch, runtime):
    monkeypatch.setenv("KNOWLEDGE_BASE_ID", "KB12345678")
    runtime(results=[])
    assert call_tool(kb.search_knowledge_base, "zzz") == kb.NO_RESULTS


def test_api_error_degrades_gracefully(monkeypatch, runtime):
    monkeypatch.setenv("KNOWLEDGE_BASE_ID", "KB12345678")
    runtime(error=RuntimeError("throttled"))
    assert call_tool(kb.search_knowledge_base, "x") == kb.UNAVAILABLE


def test_tool_description_says_when_to_call_it():
    spec = kb.search_knowledge_base.tool_spec
    assert spec["name"] == "search_knowledge_base"
    description = " ".join(spec["description"].lower().split())  # docstring lines wrap
    for topic in ("product specifications", "return", "warranty", "loyalty", "order-status"):
        assert topic in description
