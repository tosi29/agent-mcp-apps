"""AgentCore entrypoint for the initial API-free deployment."""

import logging
import os
from pathlib import Path

from fastapi import FastAPI

from exploration_agent.data import DataExplorer
from exploration_agent.fixture_model import FixtureModel
from exploration_agent.server import create_app


def create_agentcore_app() -> FastAPI:
    logging.disable(logging.CRITICAL)
    parquet = Path(os.environ.get("EXPLORER_DATA_PATH", "data/synthetic.parquet"))
    results = Path(os.environ.get("EXPLORER_RESULTS_DIR", "/tmp/results"))
    # Finish data validation before /ping can trigger V2's startup snapshot.
    # DuckDB connections are closed here and recreated by each tool operation.
    DataExplorer(parquet).describe()
    return create_app(
        FixtureModel,
        parquet,
        results,
        mode="fixture",
        # AgentCore authenticates callers with IAM before forwarding to this server.
        trusted_hosts=["*"],
    )
