from strands.hooks import AfterInvocationEvent, HookRegistry, MessageAddedEvent

from support_agent.memory import CONTEXT_HEADER, CustomerMemoryHook, namespaces_for
from tests.conftest import assistant_msg, event_for, user_msg


class FakeMemory:
    def __init__(self, strategies=None, records=None, fail=False):
        self.strategies = strategies or [
            {"type": "SEMANTIC", "namespaceTemplates": ["cs/{actorId}/facts"]},
            {"type": "USER_PREFERENCE", "namespaces": ["cs/{actorId}/prefs"]},
        ]
        self.records, self.fail = records or {}, fail
        self.queries, self.events = [], []

    def get_memory_strategies(self, memory_id):
        return self.strategies

    def retrieve_memories(self, memory_id, namespace, query, top_k):
        self.queries.append((namespace, query, top_k))
        if self.fail:
            raise RuntimeError("memory down")
        return self.records.get(namespace, [])

    def create_event(self, **kwargs):
        self.events.append(kwargs)


def rec(text):
    return {"content": {"text": text}}


def hook_with(memory):
    return CustomerMemoryHook("CUS-1", "s1", memory, "MEM")


# -- namespaces -----------------------------------------------------------------------------
def test_namespaces_prefer_templates_then_legacy_then_skip():
    both = [
        {
            "type": "SEMANTIC",
            "namespaceTemplates": ["new/{actorId}"],
            "namespaces": ["old/{actorId}"],
        }
    ]
    only_templates = [{"type": "SEMANTIC", "namespaceTemplates": ["new/{actorId}"]}]
    only_legacy = [{"type": "USER_PREFERENCE", "namespaces": ["old/{actorId}"]}]
    neither = [{"type": "SEMANTIC"}, {"type": "USER_PREFERENCE", "namespaceTemplates": []}]

    assert namespaces_for(FakeMemory(strategies=both), "M") == {"SEMANTIC": "new/{actorId}"}
    assert namespaces_for(FakeMemory(strategies=only_templates), "M") == {
        "SEMANTIC": "new/{actorId}"
    }
    assert namespaces_for(FakeMemory(strategies=only_legacy), "M") == {
        "USER_PREFERENCE": "old/{actorId}"
    }
    assert namespaces_for(FakeMemory(strategies=neither), "M") == {}


# -- retrieval ------------------------------------------------------------------------------
def test_inject_context_tags_by_strategy_and_prepends():
    memory = FakeMemory(
        records={
            "cs/CUS-1/facts": [rec("Name is Maya"), rec("   ")],
            "cs/CUS-1/prefs": [rec("Prefers concise replies")],
        }
    )
    messages = [user_msg("Do you remember me?")]
    hook_with(memory).inject_context(event_for(messages))

    assert messages[0]["content"][0]["text"] == (
        CONTEXT_HEADER
        + "[SEMANTIC] Name is Maya\n[USER_PREFERENCE] Prefers concise replies\n\nDo you remember me?"
    )
    assert memory.queries == [
        ("cs/CUS-1/facts", "Do you remember me?", 5),
        ("cs/CUS-1/prefs", "Do you remember me?", 5),
    ]


def test_inject_context_ignores_tool_results_assistant_messages_and_empty_history():
    memory = FakeMemory()
    hook = hook_with(memory)
    tool_result = [
        {
            "role": "user",
            "content": [{"toolResult": {"toolUseId": "t", "content": [{"text": "x"}]}}],
        }
    ]
    hook.inject_context(event_for(tool_result))
    hook.inject_context(event_for([assistant_msg("hi")]))
    hook.inject_context(event_for([]))
    assert memory.queries == []


def test_inject_context_leaves_message_alone_when_nothing_is_remembered_or_memory_fails():
    empty = [user_msg("hello")]
    hook_with(FakeMemory()).inject_context(event_for(empty))
    assert empty[0]["content"][0]["text"] == "hello"

    failing = [user_msg("hello")]
    hook_with(FakeMemory(fail=True)).inject_context(event_for(failing))
    assert failing[0]["content"][0]["text"] == "hello"


# -- persistence ----------------------------------------------------------------------------
def test_persist_turn_saves_original_question_and_final_answer():
    memory = FakeMemory(records={"cs/CUS-1/facts": [rec("Name is Maya")]})
    hook = hook_with(memory)
    messages = [user_msg("Do you remember me?")]
    hook.inject_context(event_for(messages))  # prepends the context block
    messages += [
        {
            "role": "assistant",
            "content": [
                {"text": "Let me check."},
                {"toolUse": {"toolUseId": "t1", "name": "x", "input": {}}},
            ],
        },
        {
            "role": "user",
            "content": [{"toolResult": {"toolUseId": "t1", "content": [{"text": "ok"}]}}],
        },
        assistant_msg("Yes, Maya!"),
    ]
    hook.persist_turn(event_for(messages))

    saved = memory.events[0]
    assert (saved["memory_id"], saved["actor_id"], saved["session_id"]) == ("MEM", "CUS-1", "s1")
    assert saved["messages"] == [("Do you remember me?", "USER"), ("Yes, Maya!", "ASSISTANT")]


def test_persist_turn_skips_incomplete_turns_and_swallows_errors():
    memory = FakeMemory()
    hook = hook_with(memory)
    hook.persist_turn(event_for([user_msg("only a question")]))
    hook.persist_turn(event_for([]))
    assert memory.events == []

    memory.create_event = lambda **kw: (_ for _ in ()).throw(RuntimeError("write failed"))
    hook.persist_turn(event_for([user_msg("q"), assistant_msg("a")]))  # must not raise


def test_hook_registers_on_both_events():
    registry = HookRegistry()
    registry.add_hook(hook_with(FakeMemory()))
    assert {MessageAddedEvent, AfterInvocationEvent} <= set(registry._registered_callbacks)
