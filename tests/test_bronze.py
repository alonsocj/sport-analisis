"""R5 — persistencia en capa bronze con particionado determinista."""

from src.ingestion.bronze import bronze_path, param_key, read_bronze, write_bronze


def test_param_key_is_deterministic_and_ordered():
    # Mismo resultado independientemente del orden de inserción.
    assert param_key({"team": 10, "last": 15}) == param_key({"last": 15, "team": 10})
    assert param_key({"last": 15, "team": 10}) == "last=15_team=10"
    assert param_key({}) == "all"


def test_write_bronze_partitioned(tmp_path):
    bronze = tmp_path / "bronze"
    params = {"team": 10, "last": 15}
    payload = {"response": [{"fixture": {"id": 1}}]}

    path = write_bronze(bronze, "fixtures", params, payload, fetched_at="2026-06-07T00:00:00Z")

    # R5: ruta determinista por endpoint + params.
    assert path == bronze_path(bronze, "fixtures", params)
    assert path.parent.name == "fixtures"
    assert path.name == "last=15_team=10.json"

    record = read_bronze(bronze, "fixtures", params)
    assert record["endpoint"] == "fixtures"
    assert record["params"] == params
    assert record["fetched_at"] == "2026-06-07T00:00:00Z"
    assert record["payload"] == payload


def test_read_bronze_missing_returns_none(tmp_path):
    assert read_bronze(tmp_path / "bronze", "fixtures", {"team": 99}) is None
