import logging

import pytest

from support_agent import gateway
from support_agent.gateway import open_gateway


class FakeClient:
    def __init__(self, on_enter=None, on_list=None):
        self.on_enter, self.on_list, self.exited = on_enter, on_list, False

    def __enter__(self):
        if self.on_enter:
            raise self.on_enter
        return self

    def __exit__(self, *exc):
        self.exited = True

    def list_tools_sync(self):
        if self.on_list:
            raise self.on_list
        return ["t1", "t2", "t3"]


@pytest.fixture
def use_client(monkeypatch):
    def install(client):
        monkeypatch.setattr(gateway, "MCPClient", lambda *_a, **_k: client)
        return client

    return install


def test_healthy_gateway_loads_tools_and_logs_the_count(use_client, caplog):
    client = use_client(FakeClient())
    with (
        caplog.at_level(logging.INFO, logger="support_agent"),
        open_gateway("https://gw.example/mcp") as conn,
    ):
        assert conn.available and conn.tools == ["t1", "t2", "t3"]
    assert "Gateway connected successfully. Loaded 3 tools." in caplog.text
    assert client.exited


@pytest.mark.parametrize(
    "client_kwargs, message",
    [
        ({"on_list": TimeoutError("slow")}, "Gateway tool loading timed out"),
        ({"on_enter": ConnectionError("refused")}, "Gateway connection failed"),
        ({"on_list": RuntimeError("boom")}, "Gateway tool loading failed: boom"),
    ],
    ids=["timeout", "connection", "other"],
)
def test_failures_are_logged_with_traceback_and_degrade(use_client, caplog, client_kwargs, message):
    client = use_client(FakeClient(**client_kwargs))
    with (
        caplog.at_level(logging.INFO, logger="support_agent"),
        open_gateway("https://gw.example/mcp") as conn,
    ):
        assert not conn.available and conn.tools == []
    record = next(r for r in caplog.records if message in r.getMessage())
    assert record.exc_info, "the failure must be logged with its traceback"
    if "on_enter" not in client_kwargs:
        assert client.exited, "a started client must be closed even when listing tools fails"


def test_missing_url_is_reported_without_touching_the_network(monkeypatch, caplog):
    monkeypatch.setattr(
        gateway, "MCPClient", lambda *a, **k: pytest.fail("client must not be created")
    )
    with caplog.at_level(logging.WARNING, logger="support_agent"), open_gateway("") as conn:
        assert not conn.available
    assert "GATEWAY_URL is not set" in caplog.text


def test_real_client_against_an_unreachable_url_degrades_instead_of_crashing(caplog):
    """No stubs: the real MCP client cannot resolve this host, and the agent must carry on."""
    with (
        caplog.at_level(logging.INFO, logger="support_agent"),
        open_gateway("https://gateway.invalid/mcp") as conn,
    ):
        assert not conn.available and conn.tools == []
    assert any("Gateway" in r.getMessage() and r.exc_info for r in caplog.records)
