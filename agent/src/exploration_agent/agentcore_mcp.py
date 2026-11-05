"""Request-scoped, SigV4-signed MCP transport for one Tokyo AgentCore runtime."""

import asyncio
import re
from contextlib import asynccontextmanager
from urllib.parse import quote
from uuid import uuid4

import boto3
import httpx2
from botocore.auth import SigV4Auth
from botocore.awsrequest import AWSRequest
from mcp.client.streamable_http import streamable_http_client
from strands.tools.mcp import MCPClient

REGION = "ap-northeast-1"
RUNTIME_ARN = re.compile(
    r"arn:aws:bedrock-agentcore:ap-northeast-1:[0-9]{12}:runtime/"
    r"[A-Za-z][A-Za-z0-9_]{0,47}-[A-Za-z0-9]{10}"
)


def runtime_url(arn: str) -> str:
    if not RUNTIME_ARN.fullmatch(arn):
        raise ValueError("MCP Runtime ARNには東京のAgentCore Runtime ARNを指定してください")
    return (
        f"https://bedrock-agentcore.{REGION}.amazonaws.com/runtimes/"
        f"{quote(arn, safe='')}/invocations?qualifier=DEFAULT"
    )


class RuntimeAuth(httpx2.Auth):
    """Refresh credentials per HTTP request; never capture them in startup snapshots."""

    requires_request_body = True

    def __init__(self):
        self.session_id = str(uuid4())

    def _signed_headers(self, request: httpx2.Request) -> dict[str, str]:
        credentials = boto3.Session().get_credentials()
        if credentials is None:
            raise ValueError("MCP接続用のAWS認証情報を取得できません")
        signed = AWSRequest(
            method=request.method,
            url=str(request.url),
            data=request.content,
            headers=dict(request.headers),
        )
        SigV4Auth(credentials.get_frozen_credentials(), "bedrock-agentcore", REGION).add_auth(
            signed
        )
        return dict(signed.headers)

    async def async_auth_flow(self, request):
        request.headers["Mcp-Session-Id"] = self.session_id
        request.headers.update(await asyncio.to_thread(self._signed_headers, request))
        response = yield request
        if session_id := response.headers.get("Mcp-Session-Id"):
            self.session_id = session_id


@asynccontextmanager
async def runtime_transport(arn: str):
    url = runtime_url(arn)
    async with httpx2.AsyncClient(
        auth=RuntimeAuth(),
        timeout=httpx2.Timeout(60, connect=10),
        follow_redirects=False,
    ) as client:
        async with streamable_http_client(
            url, http_client=client, terminate_on_close=False
        ) as streams:
            yield streams


def runtime_client(arn: str, *, allowed_tools: list[str]) -> MCPClient:
    # Validate before creating a worker or resolving credentials.
    runtime_url(arn)
    return MCPClient(
        lambda: runtime_transport(arn),
        startup_timeout=60,
        tool_filters={"allowed": allowed_tools},
    )
