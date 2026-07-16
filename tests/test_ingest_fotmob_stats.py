"""tests/test_ingest_fotmob_stats.py — Tests de ingesta de stats fotmob (Feature 23, R1–R5).

Todos offline: transporte inyectable, JSON sintético embebido en el test, sin red
real, sin reloj (fetched_at inyectado), sleeper=None (sin rate-limit en tests).

Mapeo de trazabilidad:
- test_transporte_inyectable_y_bronze_meta  → R1 (transporte, bronze, meta, sha256)
- test_parse_mapeo_titulos_xg_cards         → R1 (mapeo títulos fotmob, xG float, cards=AM+R)
- test_partido_sin_stats_no_aborta          → R1, R5 (degradación elegante, no aborta)
- test_mapeo_fifa_y_filas                   → R2 (to_fifa_code, filas por date+equipos)
- test_equipo_sin_mapeo_omitido             → R2 (equipo sin mapeo omitido, warn)
- test_cli_ingest_fotmob_stats              → R4 (subcomando CLI, exit 0)
- test_subcomandos_exactos_intactos         → R4 (16 subcomandos exactos)
"""

from __future__ import annotations

import json
import warnings
from pathlib import Path
from unittest.mock import patch

import pytest

from src.ingestion.fotmob_stats import (
    MatchRef,
    RawMatchStats,
    StatsCoverage,
    _bronze_paths,
    _extract_next_data,
    _slug_from_ref,
    fetch_and_persist,
    fetch_match_urls,
    normalize_stats,
    parse_match_stats,
)

# ---------------------------------------------------------------------------
# Constantes y helpers de test
# ---------------------------------------------------------------------------

FETCHED_AT = "2026-06-15T15:00:00+00:00"

# Fixture de la página de match con stats completas (RSA 0-1 CAN verificado)
_MATCH_NEXT_DATA_WITH_STATS: dict = {
    "props": {
        "pageProps": {
            "general": {
                "homeTeam": {"name": "South Africa"},
                "awayTeam": {"name": "Canada"},
                "matchTimeUTC": "2026-06-15T15:00:00.000Z",
            },
            "header": {
                "status": {"finished": True, "started": True, "scoreStr": "0 - 1"}
            },
            "content": {
                "stats": {
                    "Periods": {
                        "All": {
                            "stats": [
                                {
                                    "title": "Top stats",
                                    "stats": [
                                        {
                                            "title": "Ball possession",
                                            "stats": [41, 59],
                                            "type": "possession",
                                        },
                                        {
                                            "title": "Expected goals (xG)",
                                            "stats": [0.13, 1.32],
                                            "type": "number",
                                        },
                                        {
                                            "title": "Total shots",
                                            "stats": [6, 12],
                                            "type": "number",
                                        },
                                        {
                                            "title": "Shots on target",
                                            "stats": [3, 5],
                                            "type": "number",
                                        },
                                        {
                                            "title": "Corners",
                                            "stats": [1, 4],
                                            "type": "number",
                                        },
                                        {
                                            "title": "Yellow cards",
                                            "stats": [2, 1],
                                            "type": "number",
                                        },
                                        {
                                            "title": "Red cards",
                                            "stats": [None, 0],
                                            "type": "number",
                                        },
                                    ],
                                }
                            ]
                        }
                    }
                }
            },
        }
    }
}

# Fixture de la página de la liga con un partido jugado
_LEAGUE_NEXT_DATA: dict = {
    "props": {
        "pageProps": {
            # Ruta real de fotmob: fixtures.allMatches (no matches.allMatches)
            "fixtures": {
                "allMatches": [
                    {
                        "id": "4519287",
                        "pageUrl": "/matches/south-africa-vs-canada/17s1wd#4519287",
                        # home/away son strings directos (NO objetos) en fotmob
                        "home": "South Africa",
                        "away": "Canada",
                        "status": {
                            "utcTime": "2026-06-15T15:00:00.000Z",
                            "finished": True,
                            "started": True,
                            "cancelled": False,
                            "scoreStr": "0 - 1",
                        },
                    },
                    {
                        "id": "4519288",
                        "pageUrl": "/matches/argentina-vs-brazil/xyz123",
                        "home": "Argentina",
                        "away": "Brazil",
                        "status": {
                            "utcTime": "2026-07-01T18:00:00.000Z",
                            "finished": False,  # pendiente → se filtra
                            "started": False,
                            "cancelled": False,
                            "scoreStr": None,
                        },
                    },
                ]
            }
        }
    }
}

# Fixture de match SIN stats (solo estructura vacía en Periods)
_MATCH_NEXT_DATA_NO_STATS: dict = {
    "props": {
        "pageProps": {
            "general": {
                "homeTeam": {"name": "South Africa"},
                "awayTeam": {"name": "Canada"},
                "matchTimeUTC": "2026-06-15T15:00:00.000Z",
            },
            "content": {
                "stats": {
                    "Periods": {
                        "All": {
                            "stats": []  # lista vacía → no hay stats
                        }
                    }
                }
            },
        }
    }
}


def _make_html(next_data: dict) -> str:
    """Envuelve next_data en el HTML mínimo de fotmob."""
    payload = json.dumps(next_data)
    return (
        f"<html><head>"
        f'<script id="__NEXT_DATA__" type="application/json">{payload}</script>'
        f"</head><body></body></html>"
    )


def _make_match_ref(
    match_id: str = "4519287",
    page_url: str = "/matches/south-africa-vs-canada/17s1wd",
    home_team: str = "South Africa",
    away_team: str = "Canada",
    date: str = "2026-06-15",
) -> MatchRef:
    return MatchRef(
        match_id=match_id,
        page_url=page_url,
        home_team=home_team,
        away_team=away_team,
        date=date,
    )


# ---------------------------------------------------------------------------
# R1: test_transporte_inyectable_y_bronze_meta
# ---------------------------------------------------------------------------


def test_transporte_inyectable_y_bronze_meta(tmp_path):
    """R1: el transporte inyectable descarga el HTML; bronze + meta persisten con sha256."""
    match_ref = _make_match_ref()
    html = _make_html(_MATCH_NEXT_DATA_WITH_STATS)
    transport = lambda url: html  # noqa: E731

    raw = fetch_and_persist(
        transport=transport,
        match_ref=match_ref,
        fetched_at=FETCHED_AT,
        out_dir=tmp_path,
        sleeper=None,
    )

    # Resultado básico
    assert isinstance(raw, RawMatchStats)
    assert raw.has_stats is True
    assert raw.home_name == "South Africa"
    assert raw.away_name == "Canada"
    assert raw.date == "2026-06-15"

    # Bronze persiste
    slug = _slug_from_ref(match_ref)
    json_path, meta_path = _bronze_paths(slug, tmp_path)
    assert json_path.is_file(), "Falta el JSON de bronze"
    assert meta_path.is_file(), "Falta el sidecar .meta.json"

    doc = json.loads(json_path.read_text(encoding="utf-8"))
    assert doc["match_id"] == "4519287"
    assert doc["has_stats"] is True
    assert doc["home_name"] == "South Africa"
    assert doc["date"] == "2026-06-15"
    assert "home" in doc and "away" in doc

    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    assert meta["fetched_at"] == FETCHED_AT
    assert "sha256" in meta
    assert len(meta["sha256"]) == 64  # sha256 hexdigest = 64 chars
    assert meta["has_stats"] is True


def test_fetch_match_urls_filtra_jugados(tmp_path):
    """R1: fetch_match_urls devuelve solo partidos con status.finished=True.

    Verifica que:
    - la ruta correcta es fixtures.allMatches (no matches.allMatches)
    - home/away son strings directos (no objetos)
    - el partido pending (finished=False) se filtra
    - MatchRef.date se popula desde status.utcTime[:10] (BUG1)
    """
    html = _make_html(_LEAGUE_NEXT_DATA)
    transport = lambda url: html  # noqa: E731

    refs = fetch_match_urls(transport=transport, league_id=77)

    # Solo el partido RSA-CAN tiene status.finished=True → 1 resultado
    assert len(refs) == 1
    ref = refs[0]
    assert ref.match_id == "4519287"
    assert "/matches/south-africa-vs-canada/" in ref.page_url
    # home/away son strings directos, no objetos
    assert ref.home_team == "South Africa"
    assert ref.away_team == "Canada"
    # Fecha propagada desde status.utcTime (BUG1 fix)
    assert ref.date == "2026-06-15"


def test_fetch_match_urls_estructura_ausente_devuelve_lista_vacia():
    """R1: si la estructura fixtures.allMatches no existe → devuelve [] sin lanzar."""
    html = _make_html({"props": {"pageProps": {}}})
    transport = lambda url: html  # noqa: E731

    refs = fetch_match_urls(transport=transport)
    assert refs == []


def test_bronze_fecha_usa_matchref_si_parse_falla(tmp_path):
    """R1 (BUG1): si parse_match_stats no puede extraer la fecha, se usa match_ref.date.

    Escenario: HTML sin 'matchTimeUTC' en general → parse retorna date=''.
    El bronze debe quedar con la fecha propagada desde la league page (MatchRef.date).
    """
    # HTML con estructura de match válida pero SIN matchTimeUTC → date='' en parse
    next_data_sin_fecha: dict = {
        "props": {
            "pageProps": {
                "general": {
                    "homeTeam": {"name": "South Africa"},
                    "awayTeam": {"name": "Canada"},
                    # matchTimeUTC AUSENTE → parse_match_stats devuelve date=""
                },
                "content": {
                    "stats": {
                        "Periods": {
                            "All": {"stats": []}  # sin stats: has_stats=False, pero bronze persiste
                        }
                    }
                },
            }
        }
    }
    html = _make_html(next_data_sin_fecha)
    transport = lambda url: html  # noqa: E731

    # match_ref con date ya propagada desde la league page
    match_ref = _make_match_ref(date="2026-06-15")

    import warnings
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", UserWarning)
        raw = fetch_and_persist(
            transport=transport,
            match_ref=match_ref,
            fetched_at=FETCHED_AT,
            out_dir=tmp_path,
            sleeper=None,
        )

    # La fecha en el RawMatchStats debe venir de match_ref (no de parse_match_stats)
    assert raw.date == "2026-06-15", f"Se esperaba '2026-06-15', se obtuvo '{raw.date}'"

    # El bronze JSON también debe tener la fecha correcta
    slug = _slug_from_ref(match_ref)
    json_path, _ = _bronze_paths(slug, tmp_path)
    assert json_path.is_file()
    doc = json.loads(json_path.read_text(encoding="utf-8"))
    assert doc["date"] == "2026-06-15", f"bronze.date='{doc['date']}'; debería ser '2026-06-15'"


# ---------------------------------------------------------------------------
# R1: test_parse_mapeo_titulos_xg_cards
# ---------------------------------------------------------------------------


def test_parse_mapeo_titulos_xg_cards():
    """R1: parse_match_stats mapea correctamente xG (float) y cards = amarillas+rojas."""
    html = _make_html(_MATCH_NEXT_DATA_WITH_STATS)
    result = parse_match_stats(html)

    # Estructura de retorno
    assert "home" in result and "away" in result
    assert "teams" in result and "date" in result

    # Nombres
    assert result["teams"] == ("South Africa", "Canada")
    assert result["date"] == "2026-06-15"

    home = result["home"]
    away = result["away"]

    # xG float exacto (oráculo del ejemplo RSA vs CAN)
    assert home["xg"] == pytest.approx(0.13, rel=1e-6)
    assert away["xg"] == pytest.approx(1.32, rel=1e-6)

    # Cards = amarillas + rojas (RSA: 2+0=2, CAN: 1+0=1; red=None→0)
    assert home["cards"] == pytest.approx(2.0)
    assert away["cards"] == pytest.approx(1.0)

    # Otras stats
    assert home["possession"] == pytest.approx(41.0)
    assert away["possession"] == pytest.approx(59.0)
    assert home["shots"] == pytest.approx(6.0)
    assert away["shots"] == pytest.approx(12.0)
    assert home["shots_on_target"] == pytest.approx(3.0)
    assert away["shots_on_target"] == pytest.approx(5.0)
    assert home["corners"] == pytest.approx(1.0)
    assert away["corners"] == pytest.approx(4.0)


def test_parse_mapeo_cards_null_a_cero():
    """R1: Red cards con null → 0 en la suma de cards (R5 degradación)."""
    data = {
        "props": {
            "pageProps": {
                "general": {
                    "homeTeam": {"name": "Spain"},
                    "awayTeam": {"name": "France"},
                    "matchTimeUTC": "2026-06-20T18:00:00.000Z",
                },
                "content": {
                    "stats": {
                        "Periods": {
                            "All": {
                                "stats": [
                                    {
                                        "title": "Cards",
                                        "stats": [
                                            {"title": "Yellow cards", "stats": [3, 2], "type": "number"},
                                            {
                                                "title": "Red cards",
                                                "stats": [None, None],
                                                "type": "number",
                                            },
                                        ],
                                    }
                                ]
                            }
                        }
                    }
                },
            }
        }
    }
    html = _make_html(data)
    result = parse_match_stats(html)
    # null → 0; cards = 3+0=3, 2+0=2
    assert result["home"]["cards"] == pytest.approx(3.0)
    assert result["away"]["cards"] == pytest.approx(2.0)


# ---------------------------------------------------------------------------
# R1, R5: test_partido_sin_stats_no_aborta
# ---------------------------------------------------------------------------


def test_partido_sin_stats_no_aborta(tmp_path):
    """R1 (R5): un partido con Periods.All.stats vacío no aborta; has_stats=False."""
    match_ref = _make_match_ref()
    html = _make_html(_MATCH_NEXT_DATA_NO_STATS)
    transport = lambda url: html  # noqa: E731

    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        raw = fetch_and_persist(
            transport=transport,
            match_ref=match_ref,
            fetched_at=FETCHED_AT,
            out_dir=tmp_path,
            sleeper=None,
        )

    assert isinstance(raw, RawMatchStats)
    assert raw.has_stats is False
    # Bronze persiste igualmente con has_stats=False
    slug = _slug_from_ref(match_ref)
    json_path, meta_path = _bronze_paths(slug, tmp_path)
    assert json_path.is_file()
    doc = json.loads(json_path.read_text(encoding="utf-8"))
    assert doc["has_stats"] is False


def test_error_transporte_salta_partido(tmp_path):
    """R1 (R5): error en el transporte → warn, no lanza, RawMatchStats con has_stats=False."""
    match_ref = _make_match_ref()

    def _failing_transport(url: str) -> str:
        raise ConnectionError("timeout")

    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        raw = fetch_and_persist(
            transport=_failing_transport,
            match_ref=match_ref,
            fetched_at=FETCHED_AT,
            out_dir=tmp_path,
            sleeper=None,
        )

    assert isinstance(raw, RawMatchStats)
    assert raw.has_stats is False
    assert len(w) >= 1
    assert any("transporte" in str(warning.message).lower() for warning in w)
    # Bronze NO se escribe si el transporte falla antes de obtener HTML
    slug = _slug_from_ref(match_ref)
    json_path, _ = _bronze_paths(slug, tmp_path)
    assert not json_path.is_file()


# ---------------------------------------------------------------------------
# R2: test_mapeo_fifa_y_filas
# ---------------------------------------------------------------------------


def test_mapeo_fifa_y_filas():
    """R2: normalize_stats produce filas con códigos FIFA y las stats correctas."""
    match_ref = _make_match_ref()
    raw = RawMatchStats(
        match_ref=match_ref,
        has_stats=True,
        home_name="South Africa",
        away_name="Canada",
        date="2026-06-15",
        home={"possession": 41.0, "xg": 0.13, "shots": 6.0, "shots_on_target": 3.0,
              "corners": 1.0, "cards": 2.0},
        away={"possession": 59.0, "xg": 1.32, "shots": 12.0, "shots_on_target": 5.0,
              "corners": 4.0, "cards": 1.0},
    )

    rows, coverage = normalize_stats([raw])

    assert len(rows) == 1
    row = rows[0]
    assert row["date"] == "2026-06-15"
    assert row["home_code"] == "RSA"
    assert row["away_code"] == "CAN"
    assert row["home_xg"] == pytest.approx(0.13)
    assert row["away_xg"] == pytest.approx(1.32)
    assert row["home_shots"] == pytest.approx(6.0)
    assert row["away_shots"] == pytest.approx(12.0)
    assert row["home_cards"] == pytest.approx(2.0)

    assert coverage.n_matches == 1
    assert coverage.n_with_stats == 1
    assert coverage.n_teams_mapped == 2
    assert coverage.n_teams_discarded == 0


def test_mapeo_fifa_alias_fotmob():
    """R2: alias FOTMOB_STATS_ALIASES permite mapear 'Korea Republic' → KOR."""
    from src.ingestion.fotmob_stats import _fotmob_stats_to_fifa_code

    assert _fotmob_stats_to_fifa_code("Korea Republic") == "KOR"
    assert _fotmob_stats_to_fifa_code("South Korea") == "KOR"
    assert _fotmob_stats_to_fifa_code("South Africa") == "RSA"
    assert _fotmob_stats_to_fifa_code("Canada") == "CAN"
    assert _fotmob_stats_to_fifa_code("EQUIPO_DESCONOCIDO_XYZ") is None


# ---------------------------------------------------------------------------
# R2: test_equipo_sin_mapeo_omitido
# ---------------------------------------------------------------------------


def test_equipo_sin_mapeo_omitido():
    """R2: equipo sin mapeo FIFA → partido omitido con warnings.warn, no aborta."""
    match_ref = _make_match_ref(home_team="Unknown FC", away_team="Canada")
    raw = RawMatchStats(
        match_ref=match_ref,
        has_stats=True,
        home_name="Unknown FC",  # sin mapeo FIFA
        away_name="Canada",
        date="2026-06-15",
        home={"shots": 5.0},
        away={"shots": 8.0},
    )

    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        rows, coverage = normalize_stats([raw])

    assert rows == []  # partido omitido
    assert coverage.n_teams_discarded == 1
    assert coverage.n_teams_mapped == 0
    assert len(w) >= 1
    assert any("mapeo" in str(warning.message).lower() for warning in w)


def test_normalize_stats_omite_sin_stats():
    """R2: partidos con has_stats=False se omiten en normalize_stats."""
    match_ref = _make_match_ref()
    raw = RawMatchStats(
        match_ref=match_ref,
        has_stats=False,
        home_name="South Africa",
        away_name="Canada",
    )
    rows, coverage = normalize_stats([raw])
    assert rows == []
    assert coverage.n_with_stats == 0
    assert coverage.n_teams_mapped == 0


# ---------------------------------------------------------------------------
# R4: test_cli_ingest_fotmob_stats
# ---------------------------------------------------------------------------


def test_cli_ingest_fotmob_stats(tmp_path):
    """R4: subcomando ingest-fotmob-stats retorna exit 0 con monkeypatch de ingest_fotmob_stats."""
    from src.cli import main

    fake_coverage = StatsCoverage(
        n_matches=3,
        n_with_stats=3,
        n_teams_mapped=6,
        n_teams_discarded=0,
    )

    with patch("src.cli.ingest_fotmob_stats", return_value=([], fake_coverage)):
        exit_code = main(["ingest-fotmob-stats"])

    assert exit_code == 0


def test_cli_ingest_fotmob_stats_fallo_devuelve_1():
    """R4: si ingest_fotmob_stats lanza excepción, el subcomando devuelve exit 1."""
    from src.cli import main

    with patch("src.cli.ingest_fotmob_stats", side_effect=RuntimeError("sin red")):
        exit_code = main(["ingest-fotmob-stats"])

    assert exit_code == 1


def test_cli_ingest_fotmob_stats_args_personalizados(tmp_path):
    """R4: --league-id y --out se pasan correctamente a ingest_fotmob_stats."""
    from src.cli import main

    fake_coverage = StatsCoverage(
        n_matches=1, n_with_stats=1, n_teams_mapped=2, n_teams_discarded=0
    )
    captured_kwargs: dict = {}

    def fake_ingest(**kwargs) -> tuple:
        captured_kwargs.update(kwargs)
        return ([], fake_coverage)

    with patch("src.cli.ingest_fotmob_stats", side_effect=lambda **kw: fake_ingest(**kw)):
        # Invocamos con --league-id y --out personalizados
        exit_code = main(["ingest-fotmob-stats", "--league-id", "77", "--out", str(tmp_path)])

    assert exit_code == 0


# ---------------------------------------------------------------------------
# R4: test_subcomandos_exactos_intactos
# ---------------------------------------------------------------------------

EXPECTED_SUBCOMMANDS_F23 = frozenset(
    {
        "ingest-public",
        "build-features",
        "train",
        "predict",
        "schedule",
        "markets",
        "backtest",
        "predict-log",
        "evaluate",
        "ingest-goalscorers",
        "scorers",
        "simulate",
        "ingest-elo",
        "ingest-wiki-stats",
        "ingest-roster",
        "ingest-fotmob-stats",  # Feature 23
        "corners",              # Feature 24
        "count-market",         # Feature 25
        "ingest-ko",            # Feature 27
        "build-ko-fixtures",    # Feature 27
        "ingest-lineups",       # Feature 28
        "build-lineup-strength",# Feature 28
        "simulate-match",       # Feature 34
    }
)


def test_subcomandos_exactos_intactos():
    """El parser tiene EXACTAMENTE 20 subcomandos; los previos intactos + ingest-ko/build-ko-fixtures (F27)."""
    from src.cli import build_parser

    parser = build_parser()
    subparsers_action = None
    for action in parser._actions:
        if hasattr(action, "_name_parser_map"):
            subparsers_action = action
            break

    assert subparsers_action is not None, "No se encontraron subparsers en el parser"
    actual = frozenset(subparsers_action._name_parser_map.keys())
    assert actual == EXPECTED_SUBCOMMANDS_F23, (
        f"Diferencia: extra={actual - EXPECTED_SUBCOMMANDS_F23}, "
        f"faltantes={EXPECTED_SUBCOMMANDS_F23 - actual}"
    )
