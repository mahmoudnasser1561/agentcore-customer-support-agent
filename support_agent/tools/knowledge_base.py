"""Knowledge-base retrieval tool (Bedrock Knowledge Bases, Retrieve API)."""

from __future__ import annotations

from functools import lru_cache

import boto3
from strands import tool

from support_agent import logger
from support_agent.config import Settings

NOT_CONFIGURED = (
    "Knowledge Base is not configured: KNOWLEDGE_BASE_ID is empty or missing. "
    "Set KNOWLEDGE_BASE_ID before attempting a knowledge-base search."
)
NO_RESULTS = "No relevant information was found in the knowledge base."
UNAVAILABLE = "The knowledge base is temporarily unavailable."


@lru_cache(maxsize=4)
def _runtime_client(region: str):
    return boto3.client("bedrock-agent-runtime", region_name=region)


@tool
def search_knowledge_base(query: str) -> str:
    """
    Search the store's product catalogue and support knowledge base. Call this for product
    specifications, return and warranty policies, shipping options, loyalty-programme rules and
    order-status definitions - anything that is company policy or product fact rather than a
    specific customer's data.

    Args:
        query: The question or topic to look up.

    Returns:
        The most relevant passages, separated by "---".
    """
    settings = Settings.from_env()
    if not settings.knowledge_base_id:
        return NOT_CONFIGURED

    try:
        response = _runtime_client(settings.region).retrieve(
            knowledgeBaseId=settings.knowledge_base_id,
            retrievalQuery={"text": query},
        )
    except Exception as exc:  # noqa: BLE001
        logger.error("Knowledge base search failed: %s", exc)
        return UNAVAILABLE

    passages = [r["content"]["text"] for r in response.get("retrievalResults", [])]
    return "\n---\n".join(passages) if passages else NO_RESULTS
