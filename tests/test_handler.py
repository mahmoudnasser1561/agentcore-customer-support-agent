import types
from contextlib import contextmanager

import pytest

from support_agent import handler
from support_agent.gateway import GatewayConnection
from support_agent.memory import CustomerMemoryHook
from support_agent.tracing import ToolTraceHook


class StubAgent:
    instances = []

    def __init__(self, **kwargs):
        self.kwargs = kwargs
        StubAgent.instances.append(self)

    async def invoke_async(self, prompt):
        self.prompt = prompt
        return types.SimpleNamespace(message={"content": [{"text": "stub answer"}]})


class StubBrowser:
    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.browser = "browser-tool"


class StubMemoryClient:
    def get_memory_strategies(self, memory_id):
        return []


@pytest.fixture
def wired(monkeypatch):
    """Replace everything that would touch AWS; expose what the handler did."""
    StubAgent.instances.clear()
    state = types.SimpleNamespace(
        cleanups=[], gateway=GatewayConnection(tools=["g1", "g2"], available=True)
    )

    @contextmanager
    def fake_gateway(url):
        state.gateway_url = url
        yield state.gateway

    monkeypatch.setattr(handler, "Agent", StubAgent)
    monkeypatch.setattr(handler, "AgentCoreBrowser", StubBrowser)
    monkeypatch.setattr(handler, "open_gateway", fake_gateway)
    monkeypatch.setattr(handler, "_memory_client", lambda region: StubMemoryClient())
    monkeypatch.setattr(handler, "_model", lambda model_id: f"model:{model_id}")
    monkeypatch.setattr(
        handler, "stop_browser_sessions_since", lambda region, since: state.cleanups.append(since)
    )
    return state


async def test_builds_the_agent_with_local_gateway_and_browser_tools(wired, monkeypatch):
    monkeypatch.setenv("GATEWAY_URL", "https://gw.example/mcp")
    monkeypatch.setenv("MEMORY_ID", "MEM-1")
    answer = await handler.handle_request(
        {"prompt": "Where is ORD-7001?", "customer_id": "CUS-2001", "session_id": "s1"}
    )

    agent = StubAgent.instances[0]
    assert answer == "stub answer" and agent.prompt == "Where is ORD-7001?"
    assert wired.gateway_url == "https://gw.example/mcp"
    tool_names = [getattr(t, "tool_name", t) for t in agent.kwargs["tools"]]
    assert tool_names == [
        "search_knowledge_base",
        "calculate_loyalty_discount",
        "browser-tool",
        "g1",
        "g2",
    ]
    assert "CUS-2001" in agent.kwargs["system_prompt"]
    assert "temporarily unavailable" not in agent.kwargs["system_prompt"]
    assert agent.kwargs["callback_handler"] is None
    assert [type(h) for h in agent.kwargs["hooks"]] == [ToolTraceHook, CustomerMemoryHook]


async def test_gateway_outage_switches_the_prompt_to_degraded_mode(wired):
    wired.gateway = GatewayConnection(tools=[], available=False)
    await handler.handle_request({"prompt": "Where is my order?"})
    agent = StubAgent.instances[0]
    assert len(agent.kwargs["tools"]) == 3  # local tools only
    assert "temporarily unavailable" in agent.kwargs["system_prompt"]


async def test_memory_is_skipped_when_no_memory_resource_is_configured(wired):
    await handler.handle_request({"prompt": "hi"})
    assert [type(h) for h in StubAgent.instances[0].kwargs["hooks"]] == [ToolTraceHook]


async def test_anonymous_customer_and_generated_session(wired):
    await handler.handle_request({"prompt": "hi"})
    assert "anonymous" in StubAgent.instances[0].kwargs["system_prompt"]


async def test_empty_prompt_gets_a_polite_reply_without_building_an_agent(wired):
    assert await handler.handle_request({"prompt": "   "}) == handler.EMPTY_PROMPT_REPLY
    assert await handler.handle_request({}) == handler.EMPTY_PROMPT_REPLY
    assert StubAgent.instances == []


async def test_any_failure_returns_a_graceful_reply(wired, monkeypatch):
    async def boom(self, prompt):
        raise RuntimeError("model unavailable")

    monkeypatch.setattr(StubAgent, "invoke_async", boom)
    assert await handler.handle_request({"prompt": "hi"}) == handler.ERROR_REPLY


async def test_browser_sessions_are_cleaned_up_on_every_path(wired, monkeypatch):
    await handler.handle_request({"prompt": "hi"})  # success
    await handler.handle_request({"prompt": ""})  # early return
    monkeypatch.setattr(
        handler, "open_gateway", lambda url: (_ for _ in ()).throw(RuntimeError("x"))
    )
    await handler.handle_request({"prompt": "hi"})  # failure
    assert len(wired.cleanups) == 3
