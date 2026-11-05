"""AgentCore entrypoint with explicit fixture or Parameter Store-backed Sakura mode."""

import os

from fastapi import FastAPI

from exploration_agent.entrypoints.server import create_app
from exploration_agent.mcp_clients.agentcore import runtime_url
from exploration_agent.model import build_model_factory


def create_agentcore_app() -> FastAPI:
    mode = os.environ.get("EXPLORER_MODEL_MODE", "fixture")
    mcp_runtime_arn = os.environ.get("MCP_RUNTIME_ARN")
    if mcp_runtime_arn is not None:
        runtime_url(mcp_runtime_arn)
    return create_app(
        build_model_factory(mode, compare=bool(mcp_runtime_arn)),
        mode=mode,
        mcp_runtime_arn=mcp_runtime_arn,
        # AgentCore authenticates callers with IAM before forwarding to this server.
        trusted_hosts=["*"],
    )
