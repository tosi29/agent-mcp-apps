"""Start the separate MCP project for integration tests; no model/AWS API calls."""

import os
import socket
import subprocess
import time
from pathlib import Path

import pytest


@pytest.fixture(scope="session")
def mcp_service(tmp_path_factory, unused_tcp_port_factory):
    root = Path(__file__).resolve().parents[2] / "mcp"
    python = root / ".venv/bin/python"
    assert python.exists(), "Run uv sync --locked in mcp/ before agent integration tests"
    directory = tmp_path_factory.mktemp("mcp-service")
    parquet = directory / "synthetic.parquet"
    results = directory / "results"
    env = {**os.environ, "PYTHONPATH": str(root / "src")}
    subprocess.run(
        [str(python), "-m", "exploration_mcp.server", "--data", str(parquet), "prepare-sample"],
        check=True,
        env=env,
        stdout=subprocess.DEVNULL,
    )
    port = unused_tcp_port_factory()
    process = subprocess.Popen(
        [
            str(python),
            "-m",
            "exploration_mcp.server",
            "--port",
            str(port),
            "--data",
            str(parquet),
            "--results",
            str(results),
        ],
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        for _ in range(100):
            assert process.poll() is None, "MCP server exited during startup"
            try:
                with socket.create_connection(("127.0.0.1", port), timeout=0.2):
                    break
            except OSError:
                pass
            time.sleep(0.05)
        else:
            pytest.fail("MCP server did not start")
        yield {"url": f"http://127.0.0.1:{port}/mcp", "results": results}
    finally:
        process.terminate()
        process.wait(timeout=5)


@pytest.fixture
def mcp_url(mcp_service):
    return mcp_service["url"]


@pytest.fixture
def mcp_results(mcp_service):
    return mcp_service["results"]
