"""AgentCore Runtime entrypoint.

Deploy:  agentcore deploy   (see docs/deployment.md)
Local:   python main.py     (serves on :8080; POST /invocations)
"""

import logging
import os

from bedrock_agentcore.runtime import BedrockAgentCoreApp

from support_agent import LOGGER_NAME
from support_agent.handler import handle_request

# The browser tool asks for interactive consent by default; a headless runtime cannot answer.
os.environ.setdefault("BYPASS_TOOL_CONSENT", "true")

logging.basicConfig(level=logging.WARNING, format="%(levelname)s:%(name)s:%(message)s")
logging.getLogger(LOGGER_NAME).setLevel(logging.INFO)

app = BedrockAgentCoreApp()


@app.entrypoint
async def invoke(payload, context=None):
    """Handle one customer message.

    Payload: ``{"prompt": str, "customer_id": str (optional), "session_id": str (optional)}``
    """
    return await handle_request(payload)


if __name__ == "__main__":
    app.run()
