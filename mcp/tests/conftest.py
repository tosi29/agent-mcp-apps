import pytest

from exploration_mcp.data import prepare_sample


@pytest.fixture
def parquet(tmp_path):
    path = tmp_path / "synthetic.parquet"
    prepare_sample(path)
    return path
