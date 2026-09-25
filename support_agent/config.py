"""Runtime configuration.

Everything that identifies a cloud resource comes from environment variables, so the same
code runs against any account and no resource id is ever committed.

    AWS_REGION             region of every AWS call (default us-east-1)
    GATEWAY_URL            MCP endpoint of the AgentCore Gateway (ends in /mcp)
    KNOWLEDGE_BASE_ID      Bedrock knowledge base used for RAG
    MEMORY_ID              AgentCore Memory resource used for cross-session memory
    MODEL_ID               Bedrock model / inference profile id
    BROWSER_SESSION_TIMEOUT  seconds before an idle browser session is reclaimed
    TRACE_TOOL_INPUTS      "1" to include (truncated) tool arguments in tool-call trace logs
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass

DEFAULT_REGION = "us-east-1"
DEFAULT_MODEL_ID = "global.amazon.nova-2-lite-v1:0"
BROWSER_ID = "aws.browser.v1"


@dataclass(frozen=True)
class Settings:
    region: str = DEFAULT_REGION
    gateway_url: str = ""
    knowledge_base_id: str = ""
    memory_id: str = ""
    model_id: str = DEFAULT_MODEL_ID
    browser_session_timeout: int = 300
    trace_tool_inputs: bool = False

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> Settings:
        env = os.environ if env is None else env
        return cls(
            region=env.get("AWS_REGION") or env.get("AWS_DEFAULT_REGION") or DEFAULT_REGION,
            gateway_url=env.get("GATEWAY_URL", "").strip(),
            knowledge_base_id=env.get("KNOWLEDGE_BASE_ID", "").strip(),
            memory_id=env.get("MEMORY_ID", "").strip(),
            model_id=env.get("MODEL_ID", DEFAULT_MODEL_ID).strip() or DEFAULT_MODEL_ID,
            browser_session_timeout=int(env.get("BROWSER_SESSION_TIMEOUT", "300")),
            trace_tool_inputs=env.get("TRACE_TOOL_INPUTS", "0") == "1",
        )

    def missing(self) -> list[str]:
        """Names of the optional-but-recommended settings that are not set."""
        pairs = [
            ("GATEWAY_URL", self.gateway_url),
            ("KNOWLEDGE_BASE_ID", self.knowledge_base_id),
            ("MEMORY_ID", self.memory_id),
        ]
        return [name for name, value in pairs if not value]
