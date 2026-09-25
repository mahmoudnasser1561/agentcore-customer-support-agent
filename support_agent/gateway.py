"""Connection to the AgentCore Gateway (Model Context Protocol over streamable HTTP).

``open_gateway`` never raises for connectivity problems. It logs the failure, reports
``available=False`` and lets the caller carry on with the agent's local tools, so an outage of the
order/refund systems degrades the conversation instead of breaking it.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass, field
from typing import Any

from mcp.client.streamable_http import streamable_http_client
from strands.tools.mcp.mcp_client import MCPClient

from support_agent import logger


@dataclass
class GatewayConnection:
    tools: list[Any] = field(default_factory=list)
    available: bool = False


@contextmanager
def open_gateway(url: str) -> Iterator[GatewayConnection]:
    connection = GatewayConnection()
    if not url:
        logger.warning("GATEWAY_URL is not set; order and refund tools are unavailable")
        yield connection
        return

    client = MCPClient(lambda: streamable_http_client(url))
    # ExitStack so a failure while *starting* the client is handled like a failure while listing
    # tools, and the client is always closed afterwards.
    with ExitStack() as stack:
        try:
            stack.enter_context(client)
            connection.tools = list(client.list_tools_sync())
            connection.available = True
            logger.info("Gateway connected successfully. Loaded %d tools.", len(connection.tools))
        except TimeoutError:
            logger.exception("Gateway tool loading timed out")
        except ConnectionError:
            logger.exception("Gateway connection failed")
        except Exception as exc:  # noqa: BLE001
            logger.exception("Gateway tool loading failed: %s", exc)
        yield connection
