"""tests/test_cli_xg.py — Tests del CLI para la feature 15 xg_proxy_wikipedia (R6, R7).

Todos offline: transporte inyectable, fixtures en memoria, sin red real.

Mapeo trazabilidad (R6 → tests):
- test_ingest_wiki_stats: R6 (subcomando ingest-wiki-stats con transporte inyectado)
- test_xg_weight_en_train: R6 (flag --xg-weight en train)
- test_subcomandos_exactos_intactos: R6 (14 subcomandos exactos, previos intactos)
- test_exit_codes: R6 (exit codes correctos para ingest-wiki-stats)
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from unittest.mock import patch, MagicMock

import pandas as pd
import pytest

import src.cli as cli
from src.ingestion.wiki_stats import WikiStatsResult


# ---------------------------------------------------------------------------
# Fixtures helper
# ---------------------------------------------------------------------------


def _make_wiki_result(has_stats: bool = True, from_cache: bool = False) -> WikiStatsResult:
    """Crea un WikiStatsResult de prueba."""
    return WikiStatsResult(
        slug="test_slug",
        json_path=Path("data/bronze/wikipedia/test_slug.json"),
        meta_path=Path("data/bronze/wikipedia/test_slug.meta.json"),
        has_stats=has_stats,
        from_cache=from_cache,
        n_teams=2 if has_stats else 0,
    )


def _write_silver(tmp_path: Path, rows: list[dict]) -> Path:
    """Escribe un silver mínimo en tmp_path y devuelve la ruta."""
    silver = tmp_path / "silver" / "matches.csv"
    silver.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_csv(silver, index=False)
    return silver


# ---------------------------------------------------------------------------
# R6: test_ingest_wiki_stats
# ---------------------------------------------------------------------------


def test_ingest_wiki_stats_subcomando_csv(tmp_path, capsys, monkeypatch):
    """R6: ingest-wiki-stats --matches <csv> usa transporte inyectado, no red real."""
    # Crear un CSV de matches de prueba
    matches_csv = tmp_path / "matches.csv"
    matches_csv.write_text(
        "slug,match_id,home_code,away_code\n"
        "Match_A,m001,MEX,POL\n"
        "Match_B,m002,ARG,BRA\n",
        encoding="utf-8",
    )

    # Monkeypatchear ingest_wiki_stats para no usar red real
    mock_results = [
        _make_wiki_result(has_stats=True),
        _make_wiki_result(has_stats=False),
    ]

    with patch("src.cli.ingest_wiki_stats", return_value=mock_results):
        rc = cli.main(["ingest-wiki-stats", "--matches", str(matches_csv)])

    assert rc == 0
    out = capsys.readouterr().out
    assert "✅" in out
    assert "2 artículos" in out


def test_ingest_wiki_stats_sin_bronze_publico(tmp_path, monkeypatch):
    """R6: ingest-wiki-stats --matches schedule sin bronze público → exit 1 accionable."""
    # Asegurarse de que el bronze público no existe
    with patch.object(Path, "is_file", return_value=False):
        rc = cli.main(["ingest-wiki-stats", "--matches", "schedule"])

    assert rc == 1


def test_ingest_wiki_stats_csv_inexistente(tmp_path, monkeypatch):
    """R6: CSV inexistente → exit 1 con mensaje accionable."""
    rc = cli.main(["ingest-wiki-stats", "--matches", "/ruta/inexistente.csv"])
    assert rc == 1


def test_ingest_wiki_stats_sin_partidos(tmp_path, capsys, monkeypatch):
    """R6: CSV vacío (sin slugs) → exit 0 con mensaje informativo."""
    # CSV sin filas de datos válidas
    matches_csv = tmp_path / "empty.csv"
    matches_csv.write_text("slug,match_id,home_code,away_code\n", encoding="utf-8")

    rc = cli.main(["ingest-wiki-stats", "--matches", str(matches_csv)])
    assert rc == 0
    out = capsys.readouterr().out
    assert "No hay partidos" in out


def test_ingest_wiki_stats_ttl_flag(tmp_path, monkeypatch):
    """R6: el flag --ttl-hours se pasa correctamente al módulo de ingesta."""
    matches_csv = tmp_path / "matches.csv"
    matches_csv.write_text(
        "slug,match_id,home_code,away_code\nMatch_C,m003,FRA,ESP\n",
        encoding="utf-8",
    )

    captured_kwargs: list[dict] = []

    def _fake_ingest(*args, **kwargs):
        captured_kwargs.append(kwargs)
        return [_make_wiki_result()]

    with patch("src.cli.ingest_wiki_stats", side_effect=_fake_ingest):
        cli.main(["ingest-wiki-stats", "--matches", str(matches_csv), "--ttl-hours", "48"])

    assert len(captured_kwargs) == 1
    assert captured_kwargs[0]["ttl_hours"] == 48


# ---------------------------------------------------------------------------
# R6: test_xg_weight_en_train
# ---------------------------------------------------------------------------


def test_xg_weight_default_cero(tmp_path, capsys, monkeypatch):
    """R6: --xg-weight 0 (default) → xg_target_map=None se pasa a fit_dixon_coles (comportamiento v1)."""
    # Monkeypatchear fit_dixon_coles para verificar que con xg_weight=0.0 se pasa xg_target_map=None
    captured: list[dict] = []

    def _fake_fit(*args, **kwargs):
        captured.append({"xg_target_map": kwargs.get("xg_target_map")})
        # Simular fallo por silver no disponible (no importa, lo que importa es xg_target_map)
        from src.models.dixon_coles import SilverNotFoundError
        raise SilverNotFoundError("silver no disponible (test)")

    with patch("src.cli.fit_dixon_coles", side_effect=_fake_fit):
        rc = cli.main(["train", "--as-of-date", "2025-01-01"])

    # El RC puede ser 1 (no hay silver), pero fit fue llamado con xg_target_map=None
    assert len(captured) == 1
    assert captured[0]["xg_target_map"] is None  # v=0 → sin xG → v1 exacto


def test_xg_weight_flag_en_train_parser():
    """R6: el parser de 'train' acepta --xg-weight y lo almacena en args.xg_weight."""
    parser = cli.build_parser()
    args = parser.parse_args(["train", "--as-of-date", "2025-01-01", "--xg-weight", "0.3"])
    assert hasattr(args, "xg_weight")
    assert args.xg_weight == pytest.approx(0.3)


def test_xg_weight_flag_en_backtest_parser():
    """R6: el parser de 'backtest' acepta --xg-weight."""
    parser = cli.build_parser()
    args = parser.parse_args(["backtest", "--xg-weight", "0.5"])
    assert hasattr(args, "xg_weight")
    assert args.xg_weight == pytest.approx(0.5)


def test_xg_weight_default_es_cero_en_train():
    """R6: --xg-weight por defecto es 0.0 en train → comportamiento v1 exacto."""
    parser = cli.build_parser()
    args = parser.parse_args(["train", "--as-of-date", "2025-01-01"])
    assert args.xg_weight == 0.0


def test_xg_weight_default_es_cero_en_backtest():
    """R6: --xg-weight por defecto es 0.0 en backtest → comportamiento v1 exacto."""
    parser = cli.build_parser()
    args = parser.parse_args(["backtest"])
    assert args.xg_weight == 0.0


# ---------------------------------------------------------------------------
# R6: test_subcomandos_exactos_intactos
# ---------------------------------------------------------------------------


def test_subcomandos_exactos_intactos():
    """R6: exactamente 14 subcomandos; los 13 previos ESTÁN intactos + ingest-wiki-stats."""
    parser = cli.build_parser()
    sub = next(
        a for a in parser._actions if isinstance(a, argparse._SubParsersAction)
    )
    subcommands = set(sub.choices.keys())

    # Los 13 subcomandos previos deben seguir presentes (no-regresión)
    subcomandos_previos = {
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
    }
    assert subcomandos_previos.issubset(subcommands), (
        f"Subcomandos previos perdidos: {subcomandos_previos - subcommands}"
    )

    # El nuevo subcomando está presente
    assert "ingest-wiki-stats" in subcommands

    # Exactamente 18 subcomandos (ni más ni menos) — count-market añadido en Feature 25
    assert len(subcommands) == 18, (
        f"Se esperaban 18 subcomandos, se encontraron {len(subcommands)}: {subcommands}"
    )

    # Cada subcomando despacha a su función (no comparten funciones)
    funciones = set()
    for name, subparser in sub.choices.items():
        func = subparser.get_default("func")
        assert func is not None, f"Subcomando '{name}' sin función registrada"
        funciones.add(id(func))

    assert len(funciones) == 18, "Hay subcomandos compartiendo función (no permitido)"


def test_ingest_wiki_stats_funcion_correcta():
    """R6: ingest-wiki-stats despacha a cmd_ingest_wiki_stats."""
    parser = cli.build_parser()
    args = parser.parse_args(["ingest-wiki-stats"])
    assert args.func is cli.cmd_ingest_wiki_stats


# ---------------------------------------------------------------------------
# R6: test_exit_codes
# ---------------------------------------------------------------------------


def test_exit_code_0_ingest_wiki_sin_partidos(tmp_path, capsys):
    """R6: exit 0 cuando no hay partidos para ingestar (estado válido, no error)."""
    matches_csv = tmp_path / "empty.csv"
    matches_csv.write_text("slug,match_id,home_code,away_code\n", encoding="utf-8")

    rc = cli.main(["ingest-wiki-stats", "--matches", str(matches_csv)])
    assert rc == 0


def test_exit_code_1_csv_inexistente():
    """R6: exit 1 cuando el CSV de matches no existe."""
    rc = cli.main(["ingest-wiki-stats", "--matches", "/no/existe/matches.csv"])
    assert rc == 1


def test_exit_code_0_ingest_wiki_con_resultados(tmp_path, capsys):
    """R6: exit 0 cuando la ingesta completa correctamente."""
    matches_csv = tmp_path / "matches.csv"
    matches_csv.write_text(
        "slug,match_id,home_code,away_code\nMatch_D,m004,ENG,GER\n",
        encoding="utf-8",
    )
    mock_result = _make_wiki_result(has_stats=True)

    with patch("src.cli.ingest_wiki_stats", return_value=[mock_result]):
        rc = cli.main(["ingest-wiki-stats", "--matches", str(matches_csv)])

    assert rc == 0
    out = capsys.readouterr().out
    assert "✅" in out


def test_ingest_wiki_stats_cobertura_en_salida(tmp_path, capsys):
    """R6: la salida incluye el porcentaje de cobertura."""
    matches_csv = tmp_path / "matches.csv"
    matches_csv.write_text(
        "slug,match_id,home_code,away_code\n"
        "M1,m1,MEX,POL\n"
        "M2,m2,ARG,BRA\n",
        encoding="utf-8",
    )

    mock_results = [
        _make_wiki_result(has_stats=True),
        _make_wiki_result(has_stats=False),
    ]

    with patch("src.cli.ingest_wiki_stats", return_value=mock_results):
        rc = cli.main(["ingest-wiki-stats", "--matches", str(matches_csv)])

    assert rc == 0
    out = capsys.readouterr().out
    # La salida debe incluir info de cobertura (50.0% en este caso)
    assert "Cobertura" in out or "cobertura" in out.lower() or "50" in out


# ---------------------------------------------------------------------------
# OBS-2: degradación elegante cuando --xg-weight > 0 sin bronze de Wikipedia
# ---------------------------------------------------------------------------


def test_xg_weight_sin_bronze_wikipedia_avisa_y_continua(tmp_path, monkeypatch):
    """OBS-2: --xg-weight 0.5 sin bronze Wikipedia → UserWarning + entrena igual (v1)."""
    captured_xg_maps: list = []

    def _fake_fit(*args, **kwargs):
        captured_xg_maps.append(kwargs.get("xg_target_map"))
        from src.models.dixon_coles import SilverNotFoundError
        raise SilverNotFoundError("silver no disponible (test)")

    # Asegurar que ninguna ruta de datos exista (ni silver, ni bronze Wikipedia)
    monkeypatch.chdir(tmp_path)

    with patch("src.cli.fit_dixon_coles", side_effect=_fake_fit):
        with pytest.warns(UserWarning, match="no se encontraron datos de Wikipedia"):
            rc = cli.main(["train", "--as-of-date", "2025-01-01", "--xg-weight", "0.5"])

    # El path de degradación: fit_dixon_coles recibió xg_target_map=None (comportamiento v1)
    assert len(captured_xg_maps) == 1
    assert captured_xg_maps[0] is None  # sin xG → comportamiento idéntico a v1

    # El exit code puede ser 1 (no hay silver), pero NO aborta por ausencia de Wikipedia
    assert rc == 1
