import csv
import io
from pathlib import Path

import pytest

from exploration_mcp.source import prepare_data

SOURCE = Path(__file__).resolve().parents[1] / "source"


@pytest.fixture(scope="session")
def parquet(tmp_path_factory):
    path = tmp_path_factory.mktemp("data") / "transactions.parquet"
    prepare_data(SOURCE, path)
    return path


@pytest.fixture(scope="session")
def source_rows():
    """Independent reading of the committed CSVs, used as expected values."""
    rows = []
    for path in sorted(SOURCE.glob("*.csv")):
        text = path.read_bytes().decode("cp932")
        rows += list(csv.DictReader(io.StringIO(text, newline="")))
    return rows
