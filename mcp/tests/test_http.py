import csv
import io
import json
from contextlib import asynccontextmanager

import httpx
import pytest

from exploration_mcp.apps import DASHBOARD_URI
from exploration_mcp.results import CSV_URI_TEMPLATE
from exploration_mcp.server import create_agentcore_app, create_app


def rpc(method, params):
    return {
        "jsonrpc": "2.0",
        "id": 1,
        "method": method,
        "params": {
            **params,
            "_meta": {
                "io.modelcontextprotocol/protocolVersion": "2026-07-28",
                "io.modelcontextprotocol/clientInfo": {"name": "test", "version": "1"},
                "io.modelcontextprotocol/clientCapabilities": {},
            },
        },
    }


@asynccontextmanager
async def http_client(parquet, tmp_path):
    app = create_app(data_path=parquet, results_dir=tmp_path / "results")
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://127.0.0.1:8001",
            headers={
                "Accept": "application/json, text/event-stream",
                "MCP-Protocol-Version": "2026-07-28",
            },
        ) as client:
            yield client


async def test_discovery_and_tool_call_return_single_json_without_session(parquet, tmp_path):
    async with http_client(parquet, tmp_path) as client:
        response = await client.post(
            "/mcp", json=rpc("tools/list", {}), headers={"Mcp-Method": "tools/list"}
        )
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("application/json")
        assert {tool["name"] for tool in response.json()["result"]["tools"]} == {
            "describe_dataset",
            "search_transactions",
            "aggregate_transactions",
            "compare_values",
            "show_transaction_dashboard",
        }
        response = await client.post(
            "/mcp",
            json=rpc(
                "tools/call",
                {"name": "compare_values", "arguments": {"baseline": 100, "current": 120}},
            ),
            headers={"Mcp-Method": "tools/call", "Mcp-Name": "compare_values"},
        )
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("application/json")
        assert "mcp-session-id" not in response.headers
        value = response.json()["result"]["structuredContent"]["preview_rows"][0]
        assert value == {"baseline": 100, "current": 120, "difference": 20, "percent_change": 20}
        # An already deployed comparison client reads these original top-level fields.
        structured = response.json()["result"]["structuredContent"]
        assert all(structured[key] == item for key, item in value.items())
        assert json.loads(response.json()["result"]["content"][0]["text"]) == value


async def test_invalid_argument_is_tool_error(parquet, tmp_path):
    async with http_client(parquet, tmp_path) as client:
        response = await client.post(
            "/mcp",
            json=rpc(
                "tools/call",
                {"name": "compare_values", "arguments": {"baseline": "invalid", "current": 120}},
            ),
            headers={"Mcp-Method": "tools/call", "Mcp-Name": "compare_values"},
        )
        assert response.status_code == 200
        assert response.json()["result"]["isError"] is True


async def test_search_keeps_artifact_preview_and_model_content_separate(parquet, tmp_path):
    async with http_client(parquet, tmp_path) as client:
        reply = await client.post(
            "/mcp",
            json=rpc(
                "tools/call",
                {
                    "name": "search_transactions",
                    "arguments": {"limit": 200},
                },
            ),
            headers={"Mcp-Method": "tools/call", "Mcp-Name": "search_transactions"},
        )
        result = reply.json()["result"]
        summary = json.loads(result["content"][0]["text"])
        preview = result["structuredContent"]
        assert len(summary["sample_rows"]) == 3
        assert len(preview["preview_rows"]) == 20
        assert summary["total_count"] == preview["total_count"] == 4143
        assert "preview_rows" not in json.dumps(result["content"])
        artifact = json.loads((tmp_path / "results" / f"{preview['result_id']}.json").read_text())
        assert len(artifact["rows"]) == 200
        assert artifact["truncated"] is True
        reply = await client.post(
            "/mcp",
            json=rpc(
                "tools/call",
                {
                    "name": "aggregate_transactions",
                    "arguments": {"municipality": "品川区", "group_by": "year"},
                },
            ),
            headers={"Mcp-Method": "tools/call", "Mcp-Name": "aggregate_transactions"},
        )
        rows = reply.json()["result"]["structuredContent"]["preview_rows"]
        assert [r["year"] for r in rows] == [2023, 2024, 2025]
        assert sum(r["transaction_count"] for r in rows) == 1190


def test_missing_mcp_data_is_rejected_at_startup(tmp_path):
    with pytest.raises(FileNotFoundError):
        create_app(data_path=tmp_path / "missing.parquet")


@pytest.mark.parametrize(
    "name,arguments",
    [
        ("search_transactions", {"limit": 201}),
        ("aggregate_transactions", {"group_by": "unknown"}),
    ],
)
async def test_query_limits_and_group_allowlist_are_enforced_over_mcp(
    parquet,
    tmp_path,
    name,
    arguments,
):
    async with http_client(parquet, tmp_path) as client:
        reply = await client.post(
            "/mcp",
            json=rpc("tools/call", {"name": name, "arguments": arguments}),
            headers={"Mcp-Method": "tools/call", "Mcp-Name": name},
        )
        assert reply.json()["result"]["isError"] is True


async def test_app_discovery_resource_and_model_fallback(parquet, tmp_path):
    async with http_client(parquet, tmp_path) as client:
        tools = (
            await client.post(
                "/mcp", json=rpc("tools/list", {}), headers={"Mcp-Method": "tools/list"}
            )
        ).json()["result"]["tools"]
        app_tool = next(tool for tool in tools if tool["name"] == "show_transaction_dashboard")
        assert app_tool["_meta"]["ui"]["resourceUri"] == DASHBOARD_URI
        resource = (
            await client.post(
                "/mcp",
                json=rpc("resources/read", {"uri": DASHBOARD_URI}),
                headers={"Mcp-Method": "resources/read", "Mcp-Name": DASHBOARD_URI},
            )
        ).json()["result"]["contents"][0]
        assert resource["mimeType"] == "text/html;profile=mcp-app"
        assert "取引データのダッシュボード" in resource["text"]
        assert "/* APP_SCRIPT */" not in resource["text"]
        assert "<script src=" not in resource["text"]
        assert resource["_meta"]["ui"]["csp"]["connectDomains"] == []
        # No Apps capability advertisement: the ordinary textual answer must still work.
        result = (
            await client.post(
                "/mcp",
                json=rpc(
                    "tools/call",
                    {
                        "name": "show_transaction_dashboard",
                        "arguments": {"group_by": "quarter", "municipality": "品川区"},
                    },
                ),
                headers={"Mcp-Method": "tools/call", "Mcp-Name": "show_transaction_dashboard"},
            )
        ).json()["result"]
        summary = json.loads(result["content"][0]["text"])
        assert summary["total_count"] == 4
        assert len(summary["sample_rows"]) == 3
        assert result["structuredContent"] == summary
        assert len(result["_meta"]["preview"]["preview_rows"]) == 4
        assert result["_meta"]["preview"]["group_by"] == "quarter"
        assert "preview_rows" not in result["content"][0]["text"]


async def test_untrusted_origin_host_and_oversized_request_are_rejected(parquet, tmp_path):
    async with http_client(parquet, tmp_path) as client:
        body = rpc("tools/list", {})
        assert (
            await client.post("/mcp", json=body, headers={"Origin": "https://untrusted.invalid"})
        ).status_code == 403
        assert (
            await client.post("/mcp", json=body, headers={"Host": "untrusted.invalid"})
        ).status_code == 421
        assert (await client.post("/mcp", content="x" * (128 * 1024 + 1))).status_code == 413


async def test_agentcore_entrypoint_accepts_internal_host_and_platform_session_but_not_origin(
    parquet, tmp_path, monkeypatch
):
    monkeypatch.setenv("MCP_DATA_PATH", str(parquet))
    monkeypatch.setenv("MCP_RESULTS_DIR", str(tmp_path / "results"))
    app = create_agentcore_app()
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://runtime.internal:8000",
            headers={
                "Accept": "application/json, text/event-stream",
                "Mcp-Session-Id": "platform-session-01234567890123456789",
                "MCP-Protocol-Version": "2026-07-28",
                "Mcp-Method": "tools/call",
                "Mcp-Name": "compare_values",
            },
        ) as client:
            assert (await client.get("/ping")).json() == {"status": "Healthy"}
            response = await client.post(
                "/mcp",
                json=rpc(
                    "tools/call",
                    {"name": "compare_values", "arguments": {"baseline": 100, "current": 120}},
                ),
            )
            assert response.status_code == 200
            assert response.headers["content-type"].startswith("application/json")
            assert (
                response.json()["result"]["structuredContent"]["preview_rows"][0]["percent_change"]
                == 20
            )
            assert (
                await client.post(
                    "/mcp", json=rpc("tools/list", {}), headers={"Origin": "https://example.com"}
                )
            ).status_code == 403
            assert (await client.post("/mcp", content="x" * (128 * 1024 + 1))).status_code == 413


async def test_result_tools_link_csv_resource_readable_on_same_server(parquet, tmp_path):
    async with http_client(parquet, tmp_path) as client:
        templates = (
            await client.post(
                "/mcp",
                json=rpc("resources/templates/list", {}),
                headers={"Mcp-Method": "resources/templates/list"},
            )
        ).json()["result"]["resourceTemplates"]
        assert [t["uriTemplate"] for t in templates] == [CSV_URI_TEMPLATE]
        for name, arguments, count in [
            ("search_transactions", {"limit": 200}, 200),
            ("aggregate_transactions", {"group_by": "year", "municipality": "新宿区"}, 3),
            ("compare_values", {"baseline": 100, "current": 120}, 1),
            ("show_transaction_dashboard", {"group_by": "municipality"}, 3),
        ]:
            result = (
                await client.post(
                    "/mcp",
                    json=rpc("tools/call", {"name": name, "arguments": arguments}),
                    headers={"Mcp-Method": "tools/call", "Mcp-Name": name},
                )
            ).json()["result"]
            # The model's text stays first; the link carries no rows, only a reference.
            text, link = result["content"]
            assert text["type"] == "text"
            assert link["type"] == "resource_link"
            assert link["mimeType"] == "text/csv"
            assert "rows" not in json.dumps(link)
            contents = (
                await client.post(
                    "/mcp",
                    json=rpc("resources/read", {"uri": link["uri"]}),
                    headers={"Mcp-Method": "resources/read", "Mcp-Name": link["uri"]},
                )
            ).json()["result"]["contents"]
            assert contents[0]["mimeType"] == "text/csv"
            rows = list(csv.DictReader(io.StringIO(contents[0]["text"], newline="")))
            assert len(rows) == count
        assert rows[0].keys() >= {"municipality", "transaction_count", "average_price_yen"}


@pytest.mark.parametrize(
    "uri", ["exploration://results/" + "0" * 32 + ".csv", "exploration://results/../x.csv"]
)
async def test_unknown_or_malformed_csv_resource_is_not_found(parquet, tmp_path, uri):
    async with http_client(parquet, tmp_path) as client:
        error = (
            await client.post(
                "/mcp",
                json=rpc("resources/read", {"uri": uri}),
                headers={"Mcp-Method": "resources/read", "Mcp-Name": uri},
            )
        ).json()["error"]
        assert error["code"] == -32602
        assert str(tmp_path) not in error["message"]
