"""AgentCore entrypoint using the Parameter Store-backed Sakura model."""

import os

from fastapi import FastAPI

from exploration_agent.entrypoints.server import create_app
from exploration_agent.mcp_clients.agentcore import runtime_url
from exploration_agent.model import sakura_factory_from_parameter_store


def create_agentcore_app() -> FastAPI:
    mcp_runtime_arn = os.environ.get("MCP_RUNTIME_ARN")
    if mcp_runtime_arn is not None:
        runtime_url(mcp_runtime_arn)
    return create_app(
        sakura_factory_from_parameter_store(),
        mode="sakura",
        mcp_runtime_arn=mcp_runtime_arn,
        # AgentCore authenticates callers with IAM before forwarding to this server.
        trusted_hosts=["*"],
    )
