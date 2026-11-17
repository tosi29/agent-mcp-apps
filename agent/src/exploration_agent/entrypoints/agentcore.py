"""AgentCore entrypoint using the Parameter Store-backed Sakura model."""

import os

from fastapi import FastAPI

from exploration_agent.entrypoints.server import create_app
from exploration_agent.mcp_clients.target import runtime_target
from exploration_agent.model import sakura_factory_from_parameter_store


def create_agentcore_app() -> FastAPI:
    mcp_runtime_arn = os.environ.get("MCP_RUNTIME_ARN")
    return create_app(
        sakura_factory_from_parameter_store(),
        mode="sakura",
        mcp=runtime_target(mcp_runtime_arn) if mcp_runtime_arn is not None else None,
        # AgentCore authenticates callers with IAM before forwarding to this server.
        trusted_hosts=["*"],
    )
