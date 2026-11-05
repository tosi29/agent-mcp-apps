from types import SimpleNamespace

import pytest
from ag_ui.core import RunAgentInput
from ag_ui_strands.agent import _extract_tool_result_data
from test_server import run_input

from exploration_agent.agent import managed_agent
from exploration_agent.entrypoints.agui import agui_events
from exploration_agent.fixture_model import FixtureModel
from exploration_agent.mcp_clients import docs as docs_mcp
from exploration_agent.mcp_clients.docs import (
    DOCS_SERVERS,
    MAX_DOCS_CALLS_PER_RUN,
    MAX_RESULT_CHARS,
    TOOL_TIMEOUT,
    TRUNCATED_NOTICE,
    DocsMCPHook,
    DocsServer,
    build_docs_clients,
)
from exploration_agent.tools.echo import echo_text


def use_servers(monkeypatch, *servers):
    monkeypatch.setenv("DOCS_MCP_ENABLED", "true")
    monkeypatch.setattr(docs_mcp, "DOCS_SERVERS", servers)


def agent_args(clients):
    return {"model": FixtureModel(), "tools": [echo_text, *clients], "callback_handler": None}


def before(name, tool=None):
    return SimpleNamespace(tool_use={"name": name}, cancel_tool=False, selected_tool=tool)


def test_endpoints_and_tools_are_fixed():
    assert {server.url for server in DOCS_SERVERS} == {
        "https://knowledge-mcp.global.api.aws",
        "https://learn.microsoft.com/api/mcp",
    }
    # Returns agent instructions rather than documentation.
    assert "aws___retrieve_skill" not in docs_mcp.DOCS_TOOL_NAMES


@pytest.mark.parametrize("value", [None, "", "false", "1"])
def test_disabled_without_explicit_true(monkeypatch, value):
    if value is None:
        monkeypatch.delenv("DOCS_MCP_ENABLED", raising=False)
    else:
        monkeypatch.setenv("DOCS_MCP_ENABLED", value)
    assert build_docs_clients() == []


async def test_only_allowed_tools_load_and_connection_closes_after_run(monkeypatch, mcp_url):
    use_servers(monkeypatch, DocsServer("local", mcp_url, ("describe_dataset",)))
    clients = build_docs_clients()
    async with managed_agent(**agent_args(clients)) as agent:
        assert set(agent.tool_registry.registry) == {"echo_text", "describe_dataset"}
        assert clients[0]._is_session_active()
    assert not clients[0]._is_session_active()


async def test_unreachable_server_is_skipped(monkeypatch, mcp_url):
    use_servers(
        monkeypatch,
        DocsServer("down", "http://127.0.0.1:9/mcp", ("search_transactions",)),
        DocsServer("local", mcp_url, ("describe_dataset",)),
    )
    async with managed_agent(**agent_args(build_docs_clients())) as agent:
        assert set(agent.tool_registry.registry) == {"echo_text", "describe_dataset"}


async def test_failed_tool_listing_is_skipped_and_closed(monkeypatch, mcp_url):
    use_servers(monkeypatch, DocsServer("local", mcp_url, ("describe_dataset",)))
    client = build_docs_clients()[0]

    def fail(*args, **kwargs):
        raise RuntimeError("listing failed")

    monkeypatch.setattr(client, "list_tools_sync", fail)
    async with managed_agent(**agent_args([client])) as agent:
        assert set(agent.tool_registry.registry) == {"echo_text"}
    assert not client._is_session_active()


async def test_agui_run_finishes_with_docs_clients_through_the_adapter(monkeypatch, mcp_url):
    use_servers(monkeypatch, DocsServer("local", mcp_url, ("describe_dataset",)))
    clients = []
    build = docs_mcp.build_docs_clients

    def record():
        clients.extend(build())
        return clients

    monkeypatch.setattr("exploration_agent.agent.build_docs_clients", record)
    events = [
        event.type.value
        async for event in agui_events(RunAgentInput.model_validate(run_input()), FixtureModel())
    ]
    assert events[0] == "RUN_STARTED"
    assert events[-1] == "RUN_FINISHED"
    assert clients
    assert not clients[0]._is_session_active()


def test_call_budget_is_shared_across_servers_and_ignores_other_tools():
    hook = DocsMCPHook()
    names = ["aws___search_documentation", "microsoft_docs_search"]
    for index in range(MAX_DOCS_CALLS_PER_RUN):
        tool = SimpleNamespace(timeout=None)
        event = before(names[index % 2], tool)
        hook.before_tool(event)
        assert event.cancel_tool is False
        assert tool.timeout == TOOL_TIMEOUT
    over = before(names[0])
    hook.before_tool(over)
    assert isinstance(over.cancel_tool, str)
    other = before("search_transactions")
    hook.before_tool(other)
    assert other.cancel_tool is False


def test_result_is_bounded_marked_untrusted_and_text_only():
    result = {
        "status": "success",
        "toolUseId": "1",
        "content": [
            {"text": "a" * (MAX_RESULT_CHARS - 2)},
            {"image": {"format": "png", "source": {"bytes": b"x"}}},
            {"text": "bcd"},
        ],
        "structuredContent": {"raw": "x"},
        "metadata": {"raw": "x"},
    }
    event = SimpleNamespace(tool_use={"name": "microsoft_docs_fetch"}, result=result)
    DocsMCPHook().after_tool(event)
    assert "structuredContent" not in result
    assert "metadata" not in result
    # A single block: the AG-UI adapter forwards and replays only the last text block.
    body = "a" * (MAX_RESULT_CHARS - 2) + "\nb"
    assert result["content"] == [{"text": f"{body}\n{TRUNCATED_NOTICE}"}]
    assert _extract_tool_result_data(result["content"]) == result["content"][0]["text"]


def test_other_tool_results_are_untouched():
    result = {"status": "success", "toolUseId": "1", "content": [{"text": "x"}], "metadata": {}}
    event = SimpleNamespace(tool_use={"name": "search_transactions"}, result=result)
    DocsMCPHook().after_tool(event)
    assert result["content"] == [{"text": "x"}]
    assert result["metadata"] == {}
