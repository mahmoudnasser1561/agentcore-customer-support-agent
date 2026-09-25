"""Cross-session customer memory (AgentCore Memory) as a Strands hook.

Flow per request:
  1. ``inject_context``  - before the model sees the customer's message, recall what we know about
     the customer (facts + preferences) and prepend it as a "Customer Context:" block.
  2. ``persist_turn``    - after the reply, save the customer's ORIGINAL words and the agent's final
     answer as one event. AgentCore extracts long-term records from those events asynchronously.

Memory is an enhancement, never a dependency: every failure is logged and swallowed.
"""

from __future__ import annotations

from typing import Any

from strands.hooks import AfterInvocationEvent, HookProvider, HookRegistry, MessageAddedEvent

from support_agent import logger

CONTEXT_HEADER = "Customer Context:\n"


def namespaces_for(memory_client: Any, memory_id: str) -> dict[str, str]:
    """Map each strategy type to its namespace template, e.g. ``cs/{actorId}/facts``.

    Newer resources expose ``namespaceTemplates``; older ones only the legacy ``namespaces``.
    """
    namespaces: dict[str, str] = {}
    for strategy in memory_client.get_memory_strategies(memory_id):
        templates = strategy.get("namespaceTemplates") or strategy.get("namespaces") or []
        if templates:
            namespaces[strategy["type"]] = templates[0]
    return namespaces


def _plain_text(message: dict) -> str | None:
    """Text of a message if it is plain customer/assistant text (not a tool call or result)."""
    blocks = message.get("content") or []
    if any("toolResult" in b or "toolUse" in b for b in blocks):
        return None
    return next((b["text"] for b in blocks if "text" in b), None)


class CustomerMemoryHook(HookProvider):
    def __init__(self, customer_id: str, session_id: str, memory_client: Any, memory_id: str):
        self.customer_id = customer_id
        self.session_id = session_id
        self.memory_client = memory_client
        self.memory_id = memory_id
        self.namespaces = namespaces_for(memory_client, memory_id)
        self._injected_prefix = ""

    # -- before the model runs -------------------------------------------------------------
    def inject_context(self, event: MessageAddedEvent) -> None:
        messages = event.agent.messages
        if not messages or messages[-1].get("role") != "user":
            return
        message = messages[-1]
        query = _plain_text(message)
        if not query:
            return
        try:
            notes = []
            for strategy_type, template in self.namespaces.items():
                records = self.memory_client.retrieve_memories(
                    memory_id=self.memory_id,
                    namespace=template.format(actorId=self.customer_id),
                    query=query,
                    top_k=5,
                )
                for record in records:
                    text = record.get("content", {}).get("text", "").strip()
                    if text:
                        notes.append(f"[{strategy_type}] {text}")
            if notes:
                self._injected_prefix = CONTEXT_HEADER + "\n".join(notes) + "\n\n"
                message["content"][0]["text"] = self._injected_prefix + query
        except Exception as exc:  # noqa: BLE001
            logger.error("Memory retrieval failed: %s", exc)

    # -- after the reply -------------------------------------------------------------------
    def persist_turn(self, event: AfterInvocationEvent) -> None:
        try:
            customer_text = agent_text = None
            for message in reversed(event.agent.messages):
                text = _plain_text(message)
                if not text:
                    continue
                if message.get("role") == "assistant" and agent_text is None:
                    agent_text = text
                elif message.get("role") == "user" and customer_text is None:
                    customer_text = text
                if customer_text and agent_text:
                    break
            if not (customer_text and agent_text):
                return
            # Store the customer's own words, not the context block we prepended.
            if self._injected_prefix and customer_text.startswith(self._injected_prefix):
                customer_text = customer_text[len(self._injected_prefix) :]
            self.memory_client.create_event(
                memory_id=self.memory_id,
                actor_id=self.customer_id,
                session_id=self.session_id,
                messages=[(customer_text, "USER"), (agent_text, "ASSISTANT")],
            )
        except Exception as exc:  # noqa: BLE001
            logger.error("Memory save failed: %s", exc)

    def register_hooks(self, registry: HookRegistry, **kwargs: Any) -> None:
        registry.add_callback(MessageAddedEvent, self.inject_context)
        registry.add_callback(AfterInvocationEvent, self.persist_turn)
