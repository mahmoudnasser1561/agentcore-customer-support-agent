"""Test setup: no test may reach AWS.

Dummy credentials and an empty AWS config are installed before any boto3 client is created, so even a
mistake in a test cannot pick up real credentials from the developer's machine.
"""

import os
import types

import pytest

os.environ.update(
    {
        "AWS_ACCESS_KEY_ID": "test",
        "AWS_SECRET_ACCESS_KEY": "test",
        "AWS_DEFAULT_REGION": "us-east-1",
        "AWS_CONFIG_FILE": os.devnull,
        "AWS_SHARED_CREDENTIALS_FILE": os.devnull,
        "BYPASS_TOOL_CONSENT": "true",
    }
)


def call_tool(tool_obj, *args, **kwargs):
    """Call the plain function behind a Strands ``@tool``."""
    return getattr(tool_obj, "_tool_func", tool_obj)(*args, **kwargs)


def user_msg(text):
    return {"role": "user", "content": [{"text": text}]}


def assistant_msg(text):
    return {"role": "assistant", "content": [{"text": text}]}


def event_for(messages):
    """Minimal stand-in for a Strands hook event: only ``event.agent.messages`` is used."""
    return types.SimpleNamespace(agent=types.SimpleNamespace(messages=messages))


@pytest.fixture(autouse=True)
def clean_settings_env(monkeypatch):
    for name in ("GATEWAY_URL", "KNOWLEDGE_BASE_ID", "MEMORY_ID", "MODEL_ID", "TRACE_TOOL_INPUTS"):
        monkeypatch.delenv(name, raising=False)
