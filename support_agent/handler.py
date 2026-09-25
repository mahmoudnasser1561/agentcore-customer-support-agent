"""Request handling: builds the agent for one customer request and returns its answer."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from functools import lru_cache
from typing import Any

from bedrock_agentcore.memory import MemoryClient
from strands import Agent
from strands.models import BedrockModel
from strands_tools.browser import AgentCoreBrowser

from support_agent import logger
from support_agent.browser import stop_browser_sessions_since
from support_agent.config import BROWSER_ID, Settings
from support_agent.gateway import open_gateway
from support_agent.memory import CustomerMemoryHook
from support_agent.prompts import build_system_prompt
from support_agent.tools import calculate_loyalty_discount, search_knowledge_base
from support_agent.tracing import ToolTraceHook

EMPTY_PROMPT_REPLY = "Please tell me how I can help you today."
ERROR_REPLY = "I'm sorry, I ran into a problem handling your request. Please try again in a moment."


@lru_cache(maxsize=4)
def _memory_client(region: str) -> MemoryClient:
    return MemoryClient(region_name=region)


@lru_cache(maxsize=4)
def _model(model_id: str) -> BedrockModel:
    return BedrockModel(model_id=model_id)


async def handle_request(payload: dict[str, Any], settings: Settings | None = None) -> str:
    """Answer one customer message.

    payload keys: ``prompt`` (required), ``customer_id`` and ``session_id`` (optional).
    """
    settings = settings or Settings.from_env()
    # Small margin absorbs clock skew between this host and AWS when cleaning up browser sessions.
    started_at = datetime.now(UTC) - timedelta(seconds=5)
    try:
        prompt = (payload.get("prompt") or "").strip()
        if not prompt:
            return EMPTY_PROMPT_REPLY
        customer_id = payload.get("customer_id") or "anonymous"
        session_id = payload.get("session_id") or str(uuid.uuid4())

        for name in settings.missing():
            logger.warning("%s is not set; the related capability is unavailable", name)

        hooks: list[Any] = [ToolTraceHook(log_inputs=settings.trace_tool_inputs)]
        if settings.memory_id:
            hooks.append(
                CustomerMemoryHook(
                    customer_id, session_id, _memory_client(settings.region), settings.memory_id
                )
            )

        browser = AgentCoreBrowser(
            region=settings.region,
            identifier=BROWSER_ID,
            session_timeout=settings.browser_session_timeout,
        )
        tools: list[Any] = [search_knowledge_base, calculate_loyalty_discount, browser.browser]

        with open_gateway(settings.gateway_url) as gateway:
            tools.extend(gateway.tools)
            agent = Agent(
                model=_model(settings.model_id),
                tools=tools,
                hooks=hooks,
                system_prompt=build_system_prompt(customer_id, gateway.available),
                callback_handler=None,
            )
            response = await agent.invoke_async(prompt)

        return response.message["content"][0]["text"]

    except Exception as exc:  # noqa: BLE001 - the customer always gets a graceful reply
        logger.error("Agent invocation failed: %s", exc, exc_info=True)
        return ERROR_REPLY

    finally:
        stop_browser_sessions_since(settings.region, started_at)
