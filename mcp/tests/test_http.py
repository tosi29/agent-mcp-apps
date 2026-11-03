from contextlib import asynccontextmanager

import httpx

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
async def http_client():
    app = create_app()
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


async def test_discovery_and_tool_call_return_single_json_without_session():
    async with http_client() as client:
        response = await client.post(
            "/mcp", json=rpc("tools/list", {}), headers={"Mcp-Method": "tools/list"}
        )
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("application/json")
        assert [tool["name"] for tool in response.json()["result"]["tools"]] == ["compare_values"]
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
        value = response.json()["result"]["structuredContent"]
        assert value == {"baseline": 100, "current": 120, "difference": 20, "percent_change": 20}


async def test_invalid_argument_is_tool_error():
    async with http_client() as client:
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


async def test_untrusted_origin_host_and_oversized_request_are_rejected():
    async with http_client() as client:
        body = rpc("tools/list", {})
        assert (
            await client.post("/mcp", json=body, headers={"Origin": "https://untrusted.invalid"})
        ).status_code == 403
        assert (
            await client.post("/mcp", json=body, headers={"Host": "untrusted.invalid"})
        ).status_code == 421
        assert (await client.post("/mcp", content="x" * (128 * 1024 + 1))).status_code == 413


async def test_agentcore_entrypoint_accepts_internal_host_and_platform_session_but_not_origin():
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
            assert response.json()["result"]["structuredContent"]["percent_change"] == 20
            assert (
                await client.post(
                    "/mcp", json=rpc("tools/list", {}), headers={"Origin": "https://example.com"}
                )
            ).status_code == 403
            assert (await client.post("/mcp", content="x" * (128 * 1024 + 1))).status_code == 413
