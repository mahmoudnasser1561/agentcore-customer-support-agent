"""Cleanup for AgentCore Browser sessions.

The strands ``AgentCoreBrowser`` tool opens a remote browser session but never stops it (its
``close_platform`` has no sessions to close), so a session would stay billable until it times out.
After every request we stop any session that was started during that request.
"""

from __future__ import annotations

from datetime import datetime

import boto3

from support_agent import logger
from support_agent.config import BROWSER_ID


def stop_browser_sessions_since(region: str, since: datetime, browser_id: str = BROWSER_ID) -> int:
    """Stop READY browser sessions created at or after ``since``. Returns how many were stopped."""
    stopped = 0
    try:
        client = boto3.client("bedrock-agentcore", region_name=region)
        sessions = client.list_browser_sessions(browserIdentifier=browser_id, status="READY")
        for session in sessions.get("items", []):
            if session["createdAt"] >= since:
                client.stop_browser_session(
                    browserIdentifier=browser_id, sessionId=session["sessionId"]
                )
                stopped += 1
    except Exception as exc:  # noqa: BLE001 - cleanup must never break the request
        logger.error("Browser session cleanup failed: %s", exc)
    return stopped
