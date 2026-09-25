import json
import logging
import types

import main
from support_agent.config import DEFAULT_MODEL_ID, Settings
from support_agent.prompts import build_system_prompt
from support_agent.tracing import ToolTraceHook


# -- prompts --------------------------------------------------------------------------------
def test_prompt_names_the_customer_and_every_backend_tool():
    prompt = build_system_prompt("CUS-2001")
    assert "CUS-2001" in prompt and "temporarily unavailable" not in prompt
    with open("backends/refund_tool_schema.json") as fh:
        for tool in json.load(fh):
            assert f"refunds___{tool['name']}" in prompt, (
                "prompt drifted from the refund tool schema"
            )
    for name in (
        "orders-api___get_order",
        "orders-api___get_customer_orders",
        "orders-api___get_customer",
    ):
        assert name in prompt


def test_degraded_prompt_forbids_guessing():
    prompt = build_system_prompt("CUS-1", gateway_available=False)
    assert "temporarily unavailable" in prompt and "Do not guess" in prompt


# -- config ---------------------------------------------------------------------------------
def test_settings_defaults_and_env_overrides():
    defaults = Settings.from_env({})
    assert (defaults.region, defaults.model_id, defaults.browser_session_timeout) == (
        "us-east-1",
        DEFAULT_MODEL_ID,
        300,
    )
    assert defaults.missing() == ["GATEWAY_URL", "KNOWLEDGE_BASE_ID", "MEMORY_ID"]

    configured = Settings.from_env(
        {
            "AWS_REGION": "eu-west-1",
            "GATEWAY_URL": " https://gw/mcp ",
            "KNOWLEDGE_BASE_ID": "KB1",
            "MEMORY_ID": "M1",
            "MODEL_ID": "m",
            "BROWSER_SESSION_TIMEOUT": "60",
            "TRACE_TOOL_INPUTS": "1",
        }
    )
    assert (configured.region, configured.gateway_url, configured.model_id) == (
        "eu-west-1",
        "https://gw/mcp",
        "m",
    )
    assert (
        configured.browser_session_timeout == 60
        and configured.trace_tool_inputs
        and configured.missing() == []
    )


def test_region_falls_back_to_default_region_variable():
    assert Settings.from_env({"AWS_DEFAULT_REGION": "ap-south-1"}).region == "ap-south-1"


# -- tracing --------------------------------------------------------------------------------
def tool_event(name="orders-api___get_order", status="success", duration=0.4123, arguments=None):
    return types.SimpleNamespace(
        tool_use={"name": name, "input": arguments or {"order_id": "ORD-7001"}},
        result={"status": status},
        exception=None,
        duration=duration,
    )


def test_tool_call_trace_is_one_json_line(caplog):
    with caplog.at_level(logging.INFO, logger="support_agent.trace"):
        ToolTraceHook().record(tool_event())
    entry = json.loads(caplog.records[0].getMessage())
    assert entry == {
        "event": "tool_call",
        "tool": "orders-api___get_order",
        "status": "success",
        "duration_ms": 412,
    }


def test_tool_inputs_are_logged_only_on_request_and_are_truncated(caplog):
    long_args = {"blob": "x" * 1000}
    with caplog.at_level(logging.INFO, logger="support_agent.trace"):
        ToolTraceHook(log_inputs=False).record(tool_event(arguments=long_args))
        ToolTraceHook(log_inputs=True).record(tool_event(arguments=long_args))
    without, with_inputs = (json.loads(r.getMessage()) for r in caplog.records)
    assert "input" not in without
    assert len(with_inputs["input"]) == 200


# -- entrypoint -----------------------------------------------------------------------------
async def test_entrypoint_delegates_to_the_handler(monkeypatch):
    seen = {}

    async def fake_handle(payload):
        seen["payload"] = payload
        return "handled"

    monkeypatch.setattr(main, "handle_request", fake_handle)
    assert await main.invoke({"prompt": "hi"}) == "handled"
    assert seen["payload"] == {"prompt": "hi"}


def test_entrypoint_module_exposes_an_agentcore_app():
    assert type(main.app).__name__ == "BedrockAgentCoreApp"
    assert callable(main.app.run)
