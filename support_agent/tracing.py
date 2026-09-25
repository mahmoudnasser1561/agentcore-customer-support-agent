"""Structured tool-call tracing.

Emits one JSON line per tool call on the ``support_agent.trace`` logger, so CloudWatch Logs
Insights can answer "which tools ran, how long did they take, and did they succeed?":

    {"event": "tool_call", "tool": "orders-api___get_order",
     "status": "success", "duration_ms": 412}

Tool arguments are logged only when TRACE_TOOL_INPUTS=1 (they can contain customer data).
"""

from __future__ import annotations

import json
import logging
from typing import Any

from strands.hooks import AfterToolCallEvent, HookProvider, HookRegistry

trace_logger = logging.getLogger("support_agent.trace")
MAX_INPUT_CHARS = 200


class ToolTraceHook(HookProvider):
    def __init__(self, log_inputs: bool = False):
        self.log_inputs = log_inputs

    def register_hooks(self, registry: HookRegistry, **kwargs: Any) -> None:
        registry.add_callback(AfterToolCallEvent, self.record)

    def record(self, event: AfterToolCallEvent) -> None:
        result = event.result or {}
        status = result.get("status") or ("error" if event.exception else "unknown")
        entry: dict[str, Any] = {
            "event": "tool_call",
            "tool": event.tool_use.get("name"),
            "status": status,
            "duration_ms": round((event.duration or 0) * 1000),
        }
        if self.log_inputs:
            entry["input"] = json.dumps(event.tool_use.get("input", {}), default=str)[
                :MAX_INPUT_CHARS
            ]
        trace_logger.info(json.dumps(entry))
