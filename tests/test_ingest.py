"""R2, R3, R4, R9 — orquestación de la ingesta."""

from src.ingestion.client import ApiFootballClient, HttpError
from src.ingestion.ingest import (
    fetch_fixture_statistics,
    fetch_last_fixtures,
    fetch_odds,
    ingest_all,
)
from tests.conftest import FakeResponse, FakeTransport, load_fixture


def _client(tmp_settings, router):
    return ApiFootballClient(tmp_settings, transport=FakeTransport(router=router), sleep=lambda _: None)


def test_fetch_last_15_fixtures(tmp_settings):
    # R2: recupera 15 partidos finalizados y los persiste en bronze (R5).
    client = _client(tmp_settings, {"fixtures": FakeResponse(200, load_fixture("fixtures_last15.json"))})
    fixtures = fetch_last_fixtures(client, team_id=10, last=15, fetched_at="2026-06-07T00:00:00Z")

    assert len(fixtures) == 15
    bronze_file = tmp_settings.BRONZE_DIR / "fixtures" / "last=15_team=10.json"
    assert bronze_file.is_file()


def test_fetch_fixture_statistics(tmp_settings):
    # R3: estadísticas normalizadas por lado (goles, córners, tarjetas, tiros, tiros a puerta, posesión).
    client = _client(tmp_settings, {"fixtures/statistics": FakeResponse(200, load_fixture("statistics.json"))})
    stats = fetch_fixture_statistics(
        client, fixture_id=1000, goals={"home": 2, "away": 1}, fetched_at="2026-06-07T00:00:00Z"
    )

    for side in ("home", "away"):
        for key in ("goals", "corners", "cards", "shots", "shots_on_target", "possession"):
            assert key in stats[side]
    assert stats["home"]["corners"] == 9
    assert stats["home"]["cards"] == 3        # 2 amarillas + 1 roja
    assert stats["home"]["shots_on_target"] == 6
    assert stats["home"]["possession"] == "58%"
    assert stats["home"]["goals"] == 2


def test_fetch_odds(tmp_settings):
    # R4: recupera cuotas cuando existen.
    client = _client(tmp_settings, {"odds": FakeResponse(200, load_fixture("odds.json"))})
    odds = fetch_odds(client, fixture_id=1000, fetched_at="2026-06-07T00:00:00Z")
    assert odds is not None
    assert odds[0]["bookmakers"][0]["name"] == "BookA"


def test_missing_odds_does_not_fail(tmp_settings):
    # R4: sin cuotas → None, sin fallar.
    client = _client(tmp_settings, {"odds": FakeResponse(200, load_fixture("odds_empty.json"))})
    odds = fetch_odds(client, fixture_id=9999, fetched_at="2026-06-07T00:00:00Z")
    assert odds is None


def test_error_in_one_team_continues(tmp_settings):
    # R9: un error en una selección no aborta el lote.
    ok_payload = load_fixture("fixtures_last15.json")

    class TeamAwareTransport:
        def __init__(self):
            self.calls = []

        def __call__(self, method, url, headers, params):
            self.calls.append(params)
            if params.get("team") == 20:        # esta selección falla
                return FakeResponse(404, {})
            return FakeResponse(200, ok_payload)

    client = ApiFootballClient(tmp_settings, transport=TeamAwareTransport(), sleep=lambda _: None)
    summary = ingest_all(client, {"AAA": 10, "BBB": 20, "CCC": 30}, last=15, fetched_at="2026-06-07T00:00:00Z")

    assert set(summary["ok"]) == {"AAA", "CCC"}
    assert len(summary["errores"]) == 1
    assert summary["errores"][0]["code"] == "BBB"
    assert "HttpError" in summary["errores"][0]["error"]
