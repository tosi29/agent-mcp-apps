"""AgentCore entrypoint with explicit fixture or Parameter Store-backed Sakura mode."""

import logging
import os
from pathlib import Path

from fastapi import FastAPI

from exploration_agent.data import DataExplorer
from exploration_agent.fixture_model import FixtureModel
from exploration_agent.parameter_store import build_sakura_model_from_parameter_store
from exploration_agent.server import create_app


def create_agentcore_app() -> FastAPI:
    logging.disable(logging.CRITICAL)
    parquet = Path(os.environ.get("EXPLORER_DATA_PATH", "data/synthetic.parquet"))
    results = Path(os.environ.get("EXPLORER_RESULTS_DIR", "/tmp/results"))
    # Finish data validation before /ping can trigger V2's startup snapshot.
    # DuckDB connections are closed here and recreated by each tool operation.
    DataExplorer(parquet).describe()
    mode = os.environ.get("EXPLORER_MODEL_MODE", "fixture")
    if mode not in {"fixture", "sakura"}:
        raise ValueError("EXPLORER_MODEL_MODEはfixtureまたはsakuraを指定してください")
    if mode == "sakura" and not os.environ.get("SAKURA_API_KEY_PARAMETER_NAME", "").strip():
        raise ValueError("SAKURA_API_KEY_PARAMETER_NAMEを指定してください")
    if mode == "fixture" and os.environ.get("SAKURA_API_KEY_PARAMETER_NAME"):
        raise ValueError("パラメータを使う場合はEXPLORER_MODEL_MODE=sakuraを指定してください")
    return create_app(
        build_sakura_model_from_parameter_store if mode == "sakura" else FixtureModel,
        parquet,
        results,
        mode=mode,
        # AgentCore authenticates callers with IAM before forwarding to this server.
        trusted_hosts=["*"],
    )
