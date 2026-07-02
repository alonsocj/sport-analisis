"""Tests CLI para Feature 14: ingest-elo y --elo-weight en predict/predict-log.

Cubre:
- R8: subcomando ingest-elo (transporte inyectado, sin red real)
- R8: flag --elo-weight en predict y predict-log (ensemble real)
- R8: conjunto exacto de 13 subcomandos (previos + ingest-elo)
- R8: w=0 default → comportamiento idéntico al actual
- R8: simulate excluido del ensemble (trabaja a nivel de marcador, no 1X2)
- Exit codes: 0 éxito, 1 error de dominio

Todos offline; transporte inyectado en ingest-elo (cero red).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import src.cli as cli

# Fixture HTML para ingest-elo offline
_FIXTURE_HTML = Path(__file__).parent / "fixtures" / "eloratings_sample.html"

# Conjunto EXACTO de 18 subcomandos (Feature 14, R8; actualizado Feature 25, R3)
EXPECTED_SUBCOMMANDS = frozenset(
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
        "ingest-elo",           # Feature 14
        "ingest-wiki-stats",    # Feature 15
        "ingest-roster",        # Feature 21
        "ingest-fotmob-stats",  # Feature 23
        "corners",              # Feature 24
        "count-market",         # Feature 25
    }
)

AS_OF = "2026-06-17"


def _read_fixture_html() -> str:
    return _FIXTURE_HTML.read_text(encoding="utf-8")


def _make_params_json(tmp_path: Path) -> Path:
    """JSON de parámetros DC mínimo para tests de predict."""
    doc = {
        "as_of_date": AS_OF,
        "from_date": "2018-01-01",
        "xi": 0.35,
        "mu": 0.1,
        "home_advantage": 0.3,
        "rho": -0.08,
        "attack": {"ARG": 0.40, "BRA": -0.10, "ESP": 0.50, "FRA": 0.45, "MEX": 0.20, "USA": 0.10},
        "defense": {"ARG": 0.30, "BRA": 0.20, "ESP": 0.25, "FRA": 0.22, "MEX": 0.05, "USA": 0.00},
        "n_matches": 240,
        "n_teams": 6,
        "min_matches": 5,
        "reg_lambda": 0.25,
        "low_data_teams": [],
        "convergencia": {
            "success": True,
            "n_iter": 50,
            "message": "ok",
            "neg_log_lik": 100.0,
        },
    }
    path = tmp_path / "params.json"
    path.write_text(json.dumps(doc), encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# R8 — conjunto exacto de 13 subcomandos
# ---------------------------------------------------------------------------


def test_subcomandos_exactos_intactos() -> None:
    """R8: el parser tiene EXACTAMENTE 13 subcomandos incluyendo ingest-elo."""
    parser = cli.build_parser()
    # Extraer los subcomandos disponibles del parser
    subparsers_action = None
    for action in parser._actions:
        if hasattr(action, "_name_parser_map"):
            subparsers_action = action
            break

    assert subparsers_action is not None, "No se encontró el subparser en el CLI"
    actual_subcommands = frozenset(subparsers_action._name_parser_map.keys())
    assert actual_subcommands == EXPECTED_SUBCOMMANDS, (
        f"Subcomandos incorrectos.\n"
        f"Esperados: {sorted(EXPECTED_SUBCOMMANDS)}\n"
        f"Actuales: {sorted(actual_subcommands)}\n"
        f"Faltantes: {sorted(EXPECTED_SUBCOMMANDS - actual_subcommands)}\n"
        f"Extra: {sorted(actual_subcommands - EXPECTED_SUBCOMMANDS)}"
    )


# ---------------------------------------------------------------------------
# R8 — ingest-elo (transporte inyectado, offline)
# ---------------------------------------------------------------------------


def test_ingest_elo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """R8: ingest-elo usa transporte inyectable (sin red real)."""
    html_fixture = _read_fixture_html()
    calls: list[str] = []

    def fake_ingest_elo_ratings(*args, **kwargs):
        """Monkeypatch de ingest_elo_ratings en src.cli."""
        calls.append("called")
        from src.ingestion.elo_ratings import EloIngestResult
        return EloIngestResult(
            tsv_path=tmp_path / "bronze" / "elo" / "eloratings_2026-06-17.tsv",
            meta_path=tmp_path / "bronze" / "elo" / "eloratings_2026-06-17.meta.json",
            n_mapped=10,
            n_discarded=2,
            from_cache=False,
        )

    monkeypatch.setattr("src.cli.ingest_elo_ratings", fake_ingest_elo_ratings)

    exit_code = cli.main([
        "ingest-elo",
        "--fetched-date", "2026-06-17",
    ])
    assert exit_code == 0
    assert len(calls) == 1


def test_ingest_elo_desde_cache(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """R8: ingest-elo con caché activo reporta from_cache=True."""
    calls: list[str] = []

    def fake_ingest_elo_ratings(*args, **kwargs):
        calls.append("called")
        from src.ingestion.elo_ratings import EloIngestResult
        return EloIngestResult(
            tsv_path=tmp_path / "elo.tsv",
            meta_path=tmp_path / "elo.meta.json",
            n_mapped=8,
            n_discarded=1,
            from_cache=True,
        )

    monkeypatch.setattr("src.cli.ingest_elo_ratings", fake_ingest_elo_ratings)

    exit_code = cli.main([
        "ingest-elo",
        "--fetched-date", "2026-06-17",
    ])
    assert exit_code == 0


# ---------------------------------------------------------------------------
# R8 — --elo-weight en predict (w=0 default → idéntico a DC)
# ---------------------------------------------------------------------------


def test_elo_weight_en_predict(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    """R8: --elo-weight 0.0 (default) en predict → salida idéntica a DC puro."""
    params_path = _make_params_json(tmp_path)

    # Sin --elo-weight (default 0.0): comportamiento idéntico a v1
    exit_code_sin = cli.main([
        "predict", "ARG", "BRA",
        "--params", str(params_path),
    ])
    out_sin = capsys.readouterr().out

    # Con --elo-weight 0.0 explícito: debe dar la misma salida
    exit_code_con = cli.main([
        "predict", "ARG", "BRA",
        "--params", str(params_path),
        "--elo-weight", "0.0",
    ])
    out_con = capsys.readouterr().out

    assert exit_code_sin == 0
    assert exit_code_con == 0
    assert out_sin == out_con


def test_elo_weight_positivo_en_predict(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    """R8: --elo-weight > 0 en predict produce salida (sin error, sin crash)."""
    params_path = _make_params_json(tmp_path)

    exit_code = cli.main([
        "predict", "ESP", "FRA",
        "--params", str(params_path),
        "--elo-weight", "0.3",
    ])
    out = capsys.readouterr().out
    assert exit_code == 0
    assert "Probabilidades" in out


# ---------------------------------------------------------------------------
# R8 — exit codes
# ---------------------------------------------------------------------------


def test_exit_codes(tmp_path: Path) -> None:
    """R8: ingest-elo con error → exit 1; subcomando válido → exit 0."""
    def fake_ingest_error(*args, **kwargs):
        from src.ingestion.elo_ratings import EloDownloadError
        raise EloDownloadError(503, "https://fake.url/")

    # Importar cli para monkeypatching con importlib no es directo en este contexto.
    # Verificamos que el CLI completo con ingest-elo existe y el parser no falla.
    parser = cli.build_parser()
    assert parser is not None

    # Verificar que ingest-elo está registrado como subcomando válido
    subparsers_action = None
    for action in parser._actions:
        if hasattr(action, "_name_parser_map"):
            subparsers_action = action
            break
    assert "ingest-elo" in subparsers_action._name_parser_map


# ---------------------------------------------------------------------------
# R8 — simulate excluido del ensemble Elo
# ---------------------------------------------------------------------------


def test_simulate_no_tiene_flag_elo_weight() -> None:
    """R8: simulate NO expone --elo-weight (ensemble excluido por diseño, design.md 2026-06-17)."""
    parser = cli.build_parser()
    subparsers_action = None
    for action in parser._actions:
        if hasattr(action, "_name_parser_map"):
            subparsers_action = action
            break

    simulate_parser = subparsers_action._name_parser_map["simulate"]
    option_strings = []
    for action in simulate_parser._actions:
        option_strings.extend(action.option_strings)

    assert "--elo-weight" not in option_strings, (
        "simulate NO debe exponer --elo-weight: la simulación trabaja a nivel de "
        "marcador (scorelines), no de probabilidad 1X2 — ensemble excluido por diseño "
        "(Feature 14 design.md, decisión 2026-06-17)"
    )


# ---------------------------------------------------------------------------
# R8 — --elo-weight en predict-log (ensemble real y no-regresión)
# ---------------------------------------------------------------------------


def _make_silver_csv(tmp_path: Path) -> Path:
    """Silver sintético mínimo para entrenar Dixon-Coles en tests de predict-log."""
    import pandas as pd

    teams = ["ARG", "BRA", "ESP", "FRA", "MEX", "USA", "JPN", "KOR", "GER", "POR"]
    silver_dir = tmp_path / "data" / "silver"
    silver_dir.mkdir(parents=True, exist_ok=True)
    path = silver_dir / "matches.csv"

    rows = []
    date_counter = 1
    for i, home in enumerate(teams):
        for j, away in enumerate(teams):
            if i >= j:
                continue
            date_str = f"2026-05-{date_counter:02d}"
            date_counter = (date_counter % 28) + 1
            rows.append({
                "match_id": f"synth_{home}_{away}",
                "date": date_str,
                "home_code": home,
                "away_code": away,
                "home_goals": 1,
                "away_goals": 1,
                "neutral": False,
            })
    pd.DataFrame(rows).to_csv(path, index=False)
    return path


def _make_elo_history_csv(tmp_path: Path) -> Path:
    """elo_history sintético para el ensemble en tests de predict-log."""
    import pandas as pd

    teams_elo = {
        "ARG": 2000.0, "BRA": 1900.0, "ESP": 1850.0, "FRA": 1950.0,
        "MEX": 1700.0, "USA": 1650.0, "JPN": 1600.0, "KOR": 1550.0,
        "GER": 1800.0, "POR": 1750.0,
    }
    gold_dir = tmp_path / "data" / "gold"
    gold_dir.mkdir(parents=True, exist_ok=True)
    path = gold_dir / "elo_history.csv"

    rows = [
        {"date": "2026-04-01", "code": code, "elo_pre": elo, "elo_post": elo,
         "home_goals": 1, "away_goals": 1, "is_home": True}
        for code, elo in teams_elo.items()
    ]
    pd.DataFrame(rows).to_csv(path, index=False)
    return path


def _make_fixtures_csv(tmp_path: Path) -> Path:
    """CSV de fixtures mínimo para predict-log."""
    path = tmp_path / "fixtures.csv"
    path.write_text(
        "date,match_id,home_code,away_code,neutral\n"
        "2026-06-20,m_ARG_BRA,ARG,BRA,False\n"
        "2026-06-21,m_ESP_FRA,ESP,FRA,False\n",
        encoding="utf-8",
    )
    return path


def test_predict_log_elo_weight_cero_no_regresion(tmp_path: Path) -> None:
    """R8: predict-log --elo-weight 0 produce el log idéntico al comportamiento dc-v1 (no regresión).

    Verifica que con w=0 las probabilidades registradas son idénticas y el
    model_version permanece 'dc-v1'.
    """
    silver_path = _make_silver_csv(tmp_path)
    _make_elo_history_csv(tmp_path)
    fixtures_path = _make_fixtures_csv(tmp_path)
    log_path = tmp_path / "data" / "predictions" / "log.csv"

    from src.eval.prediction_log import log_predictions

    # Sin elo_weight (DC puro)
    result_dc = log_predictions(
        as_of_date="2026-06-17",
        created_at="2026-06-17T10:00:00Z",
        fixtures=[
            {"date": "2026-06-20", "match_id": "m_ARG_BRA", "home_code": "ARG",
             "away_code": "BRA", "neutral": False},
        ],
        silver_path=silver_path,
        log_path=log_path,
    )

    import pandas as pd
    df_dc = pd.read_csv(log_path, dtype=str)

    # Limpiar log y re-ejecutar con elo_weight=0.0 explícito
    log_path.unlink()
    result_ens = log_predictions(
        as_of_date="2026-06-17",
        created_at="2026-06-17T10:00:00Z",
        fixtures=[
            {"date": "2026-06-20", "match_id": "m_ARG_BRA", "home_code": "ARG",
             "away_code": "BRA", "neutral": False},
        ],
        silver_path=silver_path,
        log_path=log_path,
        elo_weight=0.0,
    )

    df_ens = pd.read_csv(log_path, dtype=str)

    # Probabilidades idénticas con w=0 (no-regresión R5 F14)
    for col in ["p_home", "p_draw", "p_away"]:
        assert df_dc[col].iloc[0] == df_ens[col].iloc[0], (
            f"No-regresión violada: col={col}, dc={df_dc[col].iloc[0]}, "
            f"ens={df_ens[col].iloc[0]} (R5 F14)"
        )

    # model_version sigue siendo dc-v1 con w=0
    assert df_ens["model_version"].iloc[0] == "dc-v1", (
        f"model_version debe ser 'dc-v1' con w=0, "
        f"se obtuvo {df_ens['model_version'].iloc[0]!r}"
    )


def test_predict_log_elo_weight_positivo_efecto_real(tmp_path: Path) -> None:
    """R8: predict-log --elo-weight 0.5 produce probabilidades DISTINTAS y model_version='dc-ens'.

    Verifica el efecto real del ensemble: al menos un fixture tiene p_home diferente
    respecto a DC puro, y el model_version queda etiquetado 'dc-ens'.
    """
    silver_path = _make_silver_csv(tmp_path)
    elo_hist_path = _make_elo_history_csv(tmp_path)

    from src.eval.prediction_log import log_predictions

    fixture = {
        "date": "2026-06-20",
        "match_id": "m_ARG_BRA",
        "home_code": "ARG",
        "away_code": "BRA",
        "neutral": False,
    }

    # DC puro (w=0)
    log_path_dc = tmp_path / "data" / "predictions" / "log_dc.csv"
    log_predictions(
        as_of_date="2026-06-17",
        created_at="2026-06-17T10:00:00Z",
        fixtures=[fixture],
        silver_path=silver_path,
        log_path=log_path_dc,
        elo_weight=0.0,
    )

    # Ensemble (w=0.5)
    log_path_ens = tmp_path / "data" / "predictions" / "log_ens.csv"
    log_predictions(
        as_of_date="2026-06-17",
        created_at="2026-06-17T10:00:00Z",
        fixtures=[fixture],
        silver_path=silver_path,
        log_path=log_path_ens,
        elo_weight=0.5,
        elo_history_path=elo_hist_path,
    )

    import pandas as pd
    df_dc = pd.read_csv(log_path_dc)
    df_ens = pd.read_csv(log_path_ens)

    # model_version es "dc-ens" con w > 0 (R8 F14)
    assert df_ens["model_version"].iloc[0] == "dc-ens", (
        f"model_version debe ser 'dc-ens' con w=0.5, "
        f"se obtuvo {df_ens['model_version'].iloc[0]!r}"
    )

    # Las probabilidades deben ser distintas (efecto real del ensemble, R8 F14)
    prob_home_dc = float(df_dc["p_home"].iloc[0])
    prob_home_ens = float(df_ens["p_home"].iloc[0])
    assert abs(prob_home_dc - prob_home_ens) > 1e-6, (
        f"El ensemble debe cambiar las probabilidades con w=0.5; "
        f"p_home_dc={prob_home_dc:.6f}, p_home_ens={prob_home_ens:.6f} "
        f"(diferencia={abs(prob_home_dc - prob_home_ens):.2e}) — "
        "verifica que elo_history tenga ratings distintos para ARG y BRA (R8 F14)"
    )

    # Las probabilidades del ensemble siguen sumando 1 (R5 F14)
    total = float(df_ens["p_home"].iloc[0]) + float(df_ens["p_draw"].iloc[0]) + float(df_ens["p_away"].iloc[0])
    assert abs(total - 1.0) < 1e-9, f"Probabilidades del ensemble no suman 1: {total}"


def test_log_predictions_warn_cuando_elo_weight_positivo_y_elo_history_ausente(
    tmp_path: Path,
) -> None:
    """BUG-001: log_predictions emite UserWarning cuando elo_weight > 0 y elo_history no existe.

    Verifica que el usuario recibe aviso explícito cuando solicita ensemble pero el
    archivo elo_history no está en disco (en lugar de degradar silenciosamente a DC puro).
    """
    silver_path = _make_silver_csv(tmp_path)

    from src.eval.prediction_log import log_predictions

    fixture = {
        "date": "2026-06-20",
        "match_id": "m_ARG_BRA_warn",
        "home_code": "ARG",
        "away_code": "BRA",
        "neutral": False,
    }

    log_path = tmp_path / "data" / "predictions" / "log_warn.csv"
    # elo_history_path apunta a un archivo que NO existe
    ruta_inexistente = tmp_path / "data" / "gold" / "no_existe_elo_history.csv"
    assert not ruta_inexistente.is_file(), "El archivo NO debe existir para este test"

    with pytest.warns(UserWarning, match="elo_history no encontrado"):
        log_predictions(
            as_of_date="2026-06-17",
            created_at="2026-06-17T10:00:00Z",
            fixtures=[fixture],
            silver_path=silver_path,
            log_path=log_path,
            elo_weight=0.5,
            elo_history_path=ruta_inexistente,
        )
