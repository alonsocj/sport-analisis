"""Feature 6 — cli_prediccion (R1–R13).

Tests 100 % offline y deterministas: ``main(argv)`` se invoca EN PROCESO; las
funciones delegadas se monkeypatchean SOBRE ``src.cli`` (``ingest_public_results``,
``bronze_public_paths``, ``build_all``, ``fit_dixon_coles``, ``save_params``) —
cero red, cero entrenamientos reales. ``predict`` usa ``load_params`` y
``predict_match`` REALES sobre un JSON de parámetros sintético en ``tmp_path``
(contrato de la feature 3). Cero ``now()`` en aserciones; salidas con ``capsys``.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import math
import re
import socket
import sys
from pathlib import Path

import pytest

import src.cli as cli
from src.features.silver import SilverInputError
from src.ingestion.public_data import (
    IngestReport,
    PublicDownloadError,
    PublicSchemaError,
)
from src.models.dixon_coles import (
    DCConfig,
    DixonColesParams,
    NotFittedError,
    SilverNotFoundError,
)

FIXTURES = Path(__file__).resolve().parent / "fixtures"
PUBLIC_SAMPLE = (FIXTURES / "public_results_sample.csv").read_text(encoding="utf-8")

AS_OF = "2026-06-01"

RESULTS_HEADER = (
    "date,home_team,away_team,home_score,away_score,tournament,city,country,neutral\n"
)


# ---------------------------------------------------------------------------
# Helpers y fixtures (offline, deterministas)
# ---------------------------------------------------------------------------


def make_params_doc(**overrides) -> dict:
    """JSON sintético con TODAS las claves del contrato de la feature 3 (R11).

    5 equipos de las 48 (ARG/BRA/JPN/MEX/USA); valores fijos a mano → las lambdas
    esperadas se calculan en el test con ``math.exp`` (sin entrenamiento real).
    """
    doc = {
        "as_of_date": AS_OF,
        "from_date": "2018-01-01",
        "xi": 0.65,
        "mu": 0.1,
        "home_advantage": 0.3,
        "rho": -0.08,
        "attack": {"ARG": 0.40, "BRA": -0.10, "JPN": -0.60, "MEX": 0.20, "USA": 0.10},
        "defense": {"ARG": 0.30, "BRA": 0.20, "JPN": -0.50, "MEX": 0.05, "USA": 0.00},
        "n_matches": 240,
        "n_teams": 5,
        "min_matches": 5,
        "reg_lambda": 1.0,
        "low_data_teams": [],
        "convergencia": {
            "success": True,
            "n_iter": 50,
            "message": "ok",
            "neg_log_lik": 100.0,
        },
    }
    doc.update(overrides)
    return doc


def write_params_json(tmp_path: Path, **overrides) -> Path:
    """Persiste el JSON sintético en ``tmp_path`` (para ``load_params`` REAL, R5)."""
    path = tmp_path / "dixon_coles_params.json"
    path.write_text(json.dumps(make_params_doc(**overrides)), encoding="utf-8")
    return path


def make_dc_params(**overrides) -> DixonColesParams:
    """Instancia real del dataclass de la feature 3 (para los fakes de train)."""
    return DixonColesParams(**make_params_doc(**overrides))


def no_gold(tmp_path: Path) -> str:
    """Ruta de features INEXISTENTE: aísla los tests del gold real del repo (R8)."""
    return str(tmp_path / "no_gold" / "team_features.csv")


def write_team_features(tmp_path: Path) -> Path:
    """``team_features.csv`` mínimo: ARG completo, MEX con nulls (→ ``n/d``) (R8)."""
    path = tmp_path / "team_features.csv"
    path.write_text(
        "code,gf_ma15,ga_ma15,elo\nARG,2.1,0.7,2100.5\nMEX,,,1850.0\n",
        encoding="utf-8",
    )
    return path


def write_results_csv(tmp_path: Path, rows: list[str]) -> Path:
    """CSV crudo bronze sintético con el encabezado de la feature 7 (R10)."""
    path = tmp_path / "results.csv"
    path.write_text(RESULTS_HEADER + "".join(r + "\n" for r in rows), encoding="utf-8")
    return path


def fail_if_called(name: str):
    """Centinela: aborta el test si la función vigilada llega a invocarse."""

    def _sentinel(*_args, **_kwargs):
        raise AssertionError(f"{name} NO debe invocarse en este escenario")

    return _sentinel


@pytest.fixture
def bronze_publico(tmp_path, monkeypatch):
    """Bronze público sintético + ingesta delegada monkeypatcheada (cero red, R2).

    El fixture compartido ``public_results_sample.csv`` se escribe en ``tmp_path``;
    ``src.cli.ingest_public_results`` devuelve un ``IngestReport`` sintético y
    ``src.cli.bronze_public_paths`` apunta al CSV temporal (parseo/filtro reales).
    """
    csv_path = tmp_path / "public_results" / "results.csv"
    meta_path = tmp_path / "public_results" / "results.meta.json"
    csv_path.parent.mkdir(parents=True)
    csv_path.write_text(PUBLIC_SAMPLE, encoding="utf-8")
    meta_path.write_text("{}", encoding="utf-8")

    report = IngestReport(
        n_rows_total=17,
        n_valid=13,
        n_discarded=4,
        discarded_by_reason={
            "fecha_invalida": 1,
            "goles_no_numericos": 2,
            "columnas_incompletas": 1,
        },
    )
    calls: list[str] = []

    def fake_ingest(fetched_at, *args, **kwargs):
        calls.append(fetched_at)
        return report

    monkeypatch.setattr(cli, "ingest_public_results", fake_ingest)
    monkeypatch.setattr(cli, "bronze_public_paths", lambda *a, **k: (csv_path, meta_path))
    return {"csv_path": csv_path, "meta_path": meta_path, "calls": calls}


# ---------------------------------------------------------------------------
# R1 — estructura del CLI
# ---------------------------------------------------------------------------


def test_main_sin_subcomando_exit_no_cero(capsys):
    """R1: sin subcomando → uso/ayuda y exit ≠ 0 (SystemExit(2) de argparse)."""
    with pytest.raises(SystemExit) as excinfo:
        cli.main([])
    assert excinfo.value.code != 0
    assert "usage" in capsys.readouterr().err.lower()


def test_subcomando_desconocido_exit_no_cero(capsys):
    """R1: subcomando desconocido → uso/ayuda y exit ≠ 0."""
    with pytest.raises(SystemExit) as excinfo:
        cli.main(["frobnicar"])
    assert excinfo.value.code != 0
    err = capsys.readouterr().err
    assert "usage" in err.lower()
    assert "frobnicar" in err


def test_subcomandos_exactos_con_funcion_propia():
    """R1/R12/R7: exactamente 17 subcomandos registrados, cada uno despachando a su funcion propia.

    Feature 5 añade 'backtest' como septimo subcomando; feature 10 añade 'predict-log' y
    'evaluate'; feature 11 añade 'ingest-goalscorers' y 'scorers'; feature 13 añade 'simulate';
    feature 14 añade 'ingest-elo' (R8 f14); feature 15 añade 'ingest-wiki-stats' (R6 f15);
    feature 21 añade 'ingest-roster' (R4 f21); feature 23 añade 'ingest-fotmob-stats' (R4 f23);
    feature 24 añade 'corners' (R4 f24).
    El conjunto completo es exactamente los 17 subcomandos listados.
    """
    parser = cli.build_parser()
    sub = next(
        a for a in parser._actions if isinstance(a, argparse._SubParsersAction)
    )
    # Igualdad exacta: ni más ni menos de los 18 subcomandos actuales
    assert set(sub.choices) == {
        "ingest-public",
        "build-features",
        "train",
        "predict",
        "schedule",
        "markets",
        "backtest",
        "predict-log",
        "evaluate",
        "ingest-goalscorers",   # Feature 11
        "scorers",              # Feature 11
        "simulate",             # Feature 13
        "ingest-elo",           # Feature 14
        "ingest-wiki-stats",    # Feature 15
        "ingest-roster",        # Feature 21
        "ingest-fotmob-stats",  # Feature 23
        "corners",              # Feature 24
        "count-market",         # Feature 25
    }
    esperadas = {
        "ingest-public": cli.cmd_ingest_public,
        "build-features": cli.cmd_build_features,
        "train": cli.cmd_train,
        "predict": cli.cmd_predict,
        "schedule": cli.cmd_schedule,
        "markets": cli.cmd_markets,
        "backtest": cli.cmd_backtest,
        "predict-log": cli.cmd_predict_log,
        "evaluate": cli.cmd_evaluate,
        "ingest-goalscorers": cli.cmd_ingest_goalscorers,        # Feature 11
        "scorers": cli.cmd_scorers,                              # Feature 11
        "simulate": cli.cmd_simulate,                            # Feature 13
        "ingest-elo": cli.cmd_ingest_elo,                        # Feature 14
        "ingest-wiki-stats": cli.cmd_ingest_wiki_stats,          # Feature 15
        "ingest-roster": cli.cmd_ingest_roster,                  # Feature 21
        "ingest-fotmob-stats": cli.cmd_ingest_fotmob_stats,      # Feature 23
        "corners": cli.cmd_corners,                              # Feature 24
        "count-market": cli.cmd_count_market,                    # Feature 25
    }
    argv_minimos = {
        "ingest-public": ["ingest-public"],
        "build-features": ["build-features", "--as-of-date", AS_OF],
        "train": ["train", "--as-of-date", AS_OF],
        "predict": ["predict", "ARG", "MEX"],
        "schedule": ["schedule"],
        "backtest": ["backtest"],
        "predict-log": ["predict-log", "--as-of", AS_OF, "--timestamp", "2026-06-01T10:00:00Z"],
        "evaluate": ["evaluate"],
        "ingest-goalscorers": ["ingest-goalscorers"],                         # Feature 11
        "scorers": ["scorers", "--home", "ARG", "--away", "MEX"],             # Feature 11
        "ingest-wiki-stats": ["ingest-wiki-stats"],                           # Feature 15
        "ingest-roster": ["ingest-roster"],                                   # Feature 21
        "ingest-fotmob-stats": ["ingest-fotmob-stats"],                       # Feature 23
    }
    for name, argv in argv_minimos.items():
        args = parser.parse_args(argv)
        assert args.func is esperadas[name], name
    assert len(set(esperadas.values())) == 18  # una función POR subcomando (18 total, R3 f25)


# ---------------------------------------------------------------------------
# R2 — ingest-public
# ---------------------------------------------------------------------------


def test_ingest_public_delegada_e_imprime_reporte(bronze_publico, capsys):
    """R2: delega en ingest_public_results e imprime el IngestReport con ✅."""
    rc = cli.main(["ingest-public"])
    out = capsys.readouterr().out
    assert rc == 0
    assert len(bronze_publico["calls"]) == 1  # delegación efectiva (fake: cero red)
    assert "✅" in out
    assert "17 filas" in out and "13 válidas" in out and "4 descartadas" in out
    assert "fecha_invalida" in out and "goles_no_numericos" in out
    assert str(bronze_publico["csv_path"]) in out
    assert str(bronze_publico["meta_path"]) in out
    assert "11 partidos" in out  # vista de consumo de las 48 sin from_date


def test_ingest_public_from_date_filtra_vista(bronze_publico, capsys):
    """R2: --from-date recorta la vista de consumo informativa (no el bronze)."""
    rc = cli.main(["ingest-public", "--from-date", "2025-11-18"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "from_date=2025-11-18" in out
    assert "3 partidos" in out  # solo los >= 2025-11-18 de las 48 en el fixture


# ---------------------------------------------------------------------------
# R3 — build-features
# ---------------------------------------------------------------------------


def test_build_features_llama_build_all_e_imprime_resumen(monkeypatch, capsys):
    """R3: delega en build_all(as_of_date) e imprime resumen + 3 rutas con ✅."""
    summary = {
        "n_matches_silver": 1234,
        "n_teams_gold": 48,
        "paths": {
            "matches": "data/silver/matches.csv",
            "elo_history": "data/gold/elo_history.csv",
            "team_features": "data/gold/team_features.csv",
        },
    }
    calls: list[str] = []

    def fake_build_all(as_of_date, *args, **kwargs):
        calls.append(as_of_date)
        return summary

    monkeypatch.setattr(cli, "build_all", fake_build_all)
    rc = cli.main(["build-features", "--as-of-date", AS_OF])
    out = capsys.readouterr().out
    assert rc == 0
    assert calls == [AS_OF]
    assert "✅" in out
    assert "1234" in out and "48 equipos" in out
    for path in summary["paths"].values():
        assert path in out


def test_build_features_sin_as_of_date_falla(capsys):
    """R3: --as-of-date es obligatorio (sin reloj implícito) → exit ≠ 0."""
    with pytest.raises(SystemExit) as excinfo:
        cli.main(["build-features"])
    assert excinfo.value.code != 0
    assert "--as-of-date" in capsys.readouterr().err


# ---------------------------------------------------------------------------
# R4 — train
# ---------------------------------------------------------------------------


def test_train_ajusta_persiste_e_imprime_resumen(tmp_path, monkeypatch, capsys):
    """R4: fit_dixon_coles + save_params delegados; resumen con ✅ y exit 0."""
    params = make_dc_params()
    fit_calls: list[tuple] = []
    saved: list[DixonColesParams] = []
    out_path = tmp_path / "dixon_coles_params.json"

    def fake_fit(as_of_date, *args, **kwargs):
        fit_calls.append((as_of_date, kwargs.get("config")))
        return params

    def fake_save(p, *args, **kwargs):
        saved.append(p)
        return out_path

    monkeypatch.setattr(cli, "fit_dixon_coles", fake_fit)
    monkeypatch.setattr(cli, "save_params", fake_save)
    rc = cli.main(["train", "--as-of-date", AS_OF])
    captured = capsys.readouterr()
    assert rc == 0
    assert fit_calls[0][0] == AS_OF
    assert saved == [params]  # persistencia delegada en save_params
    assert "240 partidos" in captured.out and "5 equipos" in captured.out
    assert "success=True" in captured.out and "50 iteraciones" in captured.out
    assert str(out_path) in captured.out
    assert captured.err == ""  # convergió: sin aviso


def test_train_pasa_from_date_y_xi_solo_si_se_dan(tmp_path, monkeypatch):
    """R4: DCConfig se construye SOLO con los flags presentes (defaults feature 3)."""
    params = make_dc_params()
    configs: list[DCConfig] = []

    def fake_fit(as_of_date, *args, **kwargs):
        configs.append(kwargs["config"])
        return params

    monkeypatch.setattr(cli, "fit_dixon_coles", fake_fit)
    monkeypatch.setattr(cli, "save_params", lambda p, *a, **k: tmp_path / "p.json")

    assert cli.main(["train", "--as-of-date", AS_OF]) == 0
    assert configs[-1] == DCConfig()  # sin flags → EXACTAMENTE los defaults

    assert (
        cli.main(
            ["train", "--as-of-date", AS_OF, "--from-date", "2010-01-01", "--xi", "0.3"]
        )
        == 0
    )
    assert configs[-1] == DCConfig(from_date="2010-01-01", xi=0.3)

    assert cli.main(["train", "--as-of-date", AS_OF, "--xi", "0.2"]) == 0
    assert configs[-1] == DCConfig(xi=0.2)  # from_date conserva su default


def test_train_no_convergencia_avisa_sin_cambiar_exit(tmp_path, monkeypatch, capsys):
    """R4: convergencia.success=False → aviso visible en stderr, exit 0 igualmente."""
    params = make_dc_params(
        convergencia={
            "success": False,
            "n_iter": 1000,
            "message": "max iter alcanzado",
            "neg_log_lik": 1.0,
        }
    )
    monkeypatch.setattr(cli, "fit_dixon_coles", lambda *a, **k: params)
    monkeypatch.setattr(cli, "save_params", lambda p, *a, **k: tmp_path / "p.json")
    rc = cli.main(["train", "--as-of-date", AS_OF])
    captured = capsys.readouterr()
    assert rc == 0  # no se aborta (coherente con R6 de la feature 3)
    assert "no convergió" in captured.err  # aviso visible y separable del resumen
    assert "success=False" in captured.out


# ---------------------------------------------------------------------------
# R5 — predict: caso feliz sin reentrenar
# ---------------------------------------------------------------------------


def test_predict_caso_feliz_sin_reentrenar(tmp_path, monkeypatch, capsys):
    """R5: carga con load_params REAL (JSON sintético) y NUNCA llama a fit (centinela)."""
    monkeypatch.setattr(cli, "fit_dixon_coles", fail_if_called("fit_dixon_coles"))
    params_path = write_params_json(tmp_path)
    rc = cli.main(
        ["predict", "ARG", "MEX", "--params", str(params_path), "--features", no_gold(tmp_path)]
    )
    out = capsys.readouterr().out
    assert rc == 0
    assert "Argentina (ARG)" in out and "Mexico (MEX)" in out  # nombre + código FIFA
    # lambdas del contrato (h=0: ARG no es anfitriona): exp(mu+att_h−def_a) / exp(mu+att_a−def_h)
    lambda_home = math.exp(0.1 + 0.40 - 0.05)
    lambda_away = math.exp(0.1 + 0.20 - 0.30)
    assert f"{lambda_home:.2f}" in out and f"{lambda_away:.2f}" in out
    assert re.search(r"\d+\.\d%", out)  # 1X2 en porcentaje
    assert len(re.findall(r"\d+-\d+\s+\d+\.\d%", out)) == 5  # top-5 marcadores con su prob
    assert str(params_path) in out and AS_OF in out


# ---------------------------------------------------------------------------
# R6 — validación de códigos de entrada
# ---------------------------------------------------------------------------


def test_predict_normaliza_a_mayusculas(tmp_path, capsys):
    """R6: HOME/AWAY se normalizan a MAYÚSCULAS (strip+upper) antes de validar."""
    params_path = write_params_json(tmp_path)
    rc = cli.main(
        ["predict", "arg", " mex ", "--params", str(params_path), "--features", no_gold(tmp_path)]
    )
    out = capsys.readouterr().out
    assert rc == 0
    assert "Argentina (ARG)" in out and "Mexico (MEX)" in out


def test_predict_codigo_invalido_error_y_sugerencia(tmp_path, monkeypatch, capsys):
    """R6: código fuera de las 48 → exit 1, sugerencia difflib, SIN cargar parámetros."""
    monkeypatch.setattr(cli, "load_params", fail_if_called("load_params"))
    rc = cli.main(["predict", "ARH", "MEX", "--params", str(tmp_path / "params.json")])
    captured = capsys.readouterr()
    assert rc == 1
    assert "error:" in captured.err
    assert "ARH" in captured.err  # código rechazado
    assert "ARG" in captured.err  # sugerencia determinista más cercana
    assert "teams.py" in captured.err  # dónde consultar los 48
    assert "Traceback" not in captured.err

    # formato inválido (≠ 3 letras A–Z) también se rechaza sin tocar disco
    rc = cli.main(["predict", "ARGENTINA", "MEX", "--params", str(tmp_path / "params.json")])
    captured = capsys.readouterr()
    assert rc == 1
    assert "ARGENTINA" in captured.err
    assert "Traceback" not in captured.err


def test_predict_codigos_iguales_error_de_uso(tmp_path, monkeypatch, capsys):
    """R6: HOME == AWAY (tras normalizar) → error de uso claro y exit ≠ 0."""
    monkeypatch.setattr(cli, "load_params", fail_if_called("load_params"))
    rc = cli.main(["predict", "ARG", "arg", "--params", str(tmp_path / "params.json")])
    captured = capsys.readouterr()
    assert rc == 1
    assert "error:" in captured.err
    assert "ARG" in captured.err
    assert "distint" in captured.err  # deben ser selecciones distintas


# ---------------------------------------------------------------------------
# R7 — equipo de las 48 sin parámetros entrenados
# ---------------------------------------------------------------------------


def test_predict_equipo_sin_parametros_mensaje_accionable(tmp_path, capsys):
    """R7: FRA está en las 48 pero NO en attack/defense → UnknownTeamError traducido."""
    params_path = write_params_json(tmp_path)
    rc = cli.main(
        ["predict", "FRA", "MEX", "--params", str(params_path), "--features", no_gold(tmp_path)]
    )
    captured = capsys.readouterr()
    assert rc == 1
    assert "FRA" in captured.err  # el código rechazado
    assert "train" in captured.err and "--from-date" in captured.err  # acción sugerida
    assert "Traceback" not in captured.err


# ---------------------------------------------------------------------------
# R8 — contexto gold opcional
# ---------------------------------------------------------------------------


def test_predict_contexto_gold_presente(tmp_path, capsys):
    """R8: con gold presente muestra elo y forma gf/ga_ma15; nulls → n/d."""
    params_path = write_params_json(tmp_path)
    features = write_team_features(tmp_path)
    rc = cli.main(
        ["predict", "ARG", "MEX", "--params", str(params_path), "--features", str(features)]
    )
    out = capsys.readouterr().out
    assert rc == 0
    assert "2100.5" in out and "2.1" in out and "0.7" in out  # ARG completo
    assert "1850.0" in out  # elo de MEX presente
    assert "n/d" in out  # formas nulas de MEX → n/d


def test_predict_sin_gold_omite_contexto_sin_fallar(tmp_path, capsys):
    """R8: sin gold se omite la sección de contexto sin fallar ni alterar el resto."""
    params_path = write_params_json(tmp_path)
    rc = cli.main(
        ["predict", "ARG", "MEX", "--params", str(params_path), "--features", no_gold(tmp_path)]
    )
    captured = capsys.readouterr()
    assert rc == 0  # exit code intacto
    assert "Contexto" not in captured.out  # sección omitida por completo
    assert "n/d" not in captured.out
    assert captured.err == ""  # sin mensaje de error
    assert "Argentina (ARG)" in captured.out  # el resto de la salida intacto


# ---------------------------------------------------------------------------
# R9 — salida machine-readable --json
# ---------------------------------------------------------------------------


def test_predict_json_documento_unico_y_claves(tmp_path, capsys):
    """R9: stdout = un ÚNICO documento JSON parseable con las claves del contrato."""
    params_path = write_params_json(tmp_path)
    features = write_team_features(tmp_path)
    rc = cli.main(
        [
            "predict",
            "ARG",
            "MEX",
            "--params",
            str(params_path),
            "--features",
            str(features),
            "--json",
        ]
    )
    out = capsys.readouterr().out
    assert rc == 0
    assert "✅" not in out  # sin líneas decorativas mezcladas
    doc = json.loads(out)  # el stdout COMPLETO parsea como un solo documento
    assert doc["home"] == {"code": "ARG", "name": "Argentina"}
    assert doc["away"] == {"code": "MEX", "name": "Mexico"}
    assert doc["as_of_date"] == AS_OF
    assert doc["params_path"] == str(params_path)
    assert doc["lambda_home"] == pytest.approx(math.exp(0.1 + 0.40 - 0.05), abs=1e-12)
    assert doc["lambda_away"] == pytest.approx(math.exp(0.1 + 0.20 - 0.30), abs=1e-12)
    probs = doc["probs"]
    assert set(probs) == {"home", "draw", "away"}
    assert probs["home"] + probs["draw"] + probs["away"] == pytest.approx(1.0, abs=1e-9)
    assert len(doc["top_scores"]) == 5
    assert set(doc["top_scores"][0]) == {"home_goals", "away_goals", "prob"}
    assert "matrix" not in doc  # la matriz conjunta NO se incluye (design.md)
    assert doc["context"]["home"] == {"elo": 2100.5, "gf_ma15": 2.1, "ga_ma15": 0.7}
    assert doc["context"]["away"] == {"elo": 1850.0, "gf_ma15": None, "ga_ma15": None}


def test_predict_json_context_null_sin_gold(tmp_path, capsys):
    """R9: --json sin gold → context: null (el resto del documento intacto)."""
    params_path = write_params_json(tmp_path)
    rc = cli.main(
        [
            "predict",
            "ARG",
            "MEX",
            "--params",
            str(params_path),
            "--features",
            no_gold(tmp_path),
            "--json",
        ]
    )
    out = capsys.readouterr().out
    assert rc == 0
    doc = json.loads(out)
    assert doc["context"] is None
    assert doc["home"]["code"] == "ARG"  # el resto sigue presente


# ---------------------------------------------------------------------------
# R10 — schedule
# ---------------------------------------------------------------------------


def test_schedule_lista_pendientes_orden_y_limite(tmp_path, capsys):
    """R10: pendientes = WC + scores no numéricos; orden (date, home, away); --limit."""
    rows = [
        "2026-06-14,United States,Haiti,NA,NA,FIFA World Cup,Inglewood,United States,FALSE",
        "2026-06-12,Kiribati,Jordan,NA,NA,FIFA World Cup,Toronto,Canada,TRUE",
        "2026-06-11,Mexico,South Africa,NA,NA,FIFA World Cup,Mexico City,Mexico,FALSE",
        "2026-06-11,Canada,Curaçao,NA,NA,FIFA World Cup,Vancouver,Canada,FALSE",
        "1950-07-16,Brazil,Uruguay,1,2,FIFA World Cup,Rio de Janeiro,Brazil,FALSE",
        "2026-06-11,Argentina,Japan,NA,NA,Friendly,Dallas,United States,TRUE",
    ]
    csv_path = write_results_csv(tmp_path, rows)
    rc = cli.main(["schedule", "--results-csv", str(csv_path), "--limit", "3"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "2026-06-11" in out
    assert "Canada (CAN)" in out and "Curaçao (CUW)" in out  # código FIFA vía alias
    assert "Mexico (MEX)" in out and "South Africa (RSA)" in out
    # cronológico ascendente con desempate determinista por home_team
    assert out.index("Canada (CAN)") < out.index("Mexico (MEX)") < out.index("Kiribati")
    assert "Kiribati (" not in out  # alias inexistente → solo el nombre, sin código
    assert "United States" not in out  # 4.º pendiente: recortado por --limit 3
    assert "Brazil" not in out  # jugado (scores numéricos): NO pendiente
    assert "Argentina" not in out  # no es FIFA World Cup


def test_schedule_sin_pendientes_mensaje_y_exit_0(tmp_path, capsys):
    """R10: 0 pendientes → mensaje claro y exit 0 (estado válido, no error)."""
    rows = ["1950-07-16,Brazil,Uruguay,1,2,FIFA World Cup,Rio de Janeiro,Brazil,FALSE"]
    csv_path = write_results_csv(tmp_path, rows)
    rc = cli.main(["schedule", "--results-csv", str(csv_path)])
    captured = capsys.readouterr()
    assert rc == 0
    assert "No hay" in captured.out and "pendientes" in captured.out
    assert captured.err == ""


# ---------------------------------------------------------------------------
# R11 — schedule sin bronze público
# ---------------------------------------------------------------------------


def test_schedule_sin_bronze_error_accionable(tmp_path, capsys):
    """R11: bronze inexistente → stderr accionable (ingest-public antes) y exit ≠ 0."""
    rc = cli.main(["schedule", "--results-csv", str(tmp_path / "missing" / "results.csv")])
    captured = capsys.readouterr()
    assert rc == 1
    assert "error:" in captured.err
    assert "ingest-public" in captured.err  # acción: ejecutar antes la ingesta
    assert "Traceback" not in captured.err


# ---------------------------------------------------------------------------
# R12 — traducción de errores de capas inferiores
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("argv", "objetivo", "excepcion", "pista"),
    [
        pytest.param(
            ["build-features", "--as-of-date", AS_OF],
            "build_all",
            SilverInputError("no hay bronze disponible"),
            "ingest-public",
            id="build-features-silver-input",
        ),
        pytest.param(
            ["build-features", "--as-of-date", "fecha-rota"],
            "build_all",
            ValueError("as_of_date inválida"),
            "YYYY-MM-DD",
            id="build-features-fecha",
        ),
        pytest.param(
            ["train", "--as-of-date", AS_OF],
            "fit_dixon_coles",
            SilverNotFoundError("no existe el silver"),
            "build-features",
            id="train-silver-not-found",
        ),
        pytest.param(
            ["train", "--as-of-date", "fecha-rota"],
            "fit_dixon_coles",
            ValueError("from_date inválida"),
            "YYYY-MM-DD",
            id="train-fecha",
        ),
        pytest.param(
            ["predict", "ARG", "MEX", "--params", "x.json"],
            "load_params",
            NotFittedError("sin parámetros entrenados"),
            "train",
            id="predict-not-fitted",
        ),
        pytest.param(
            ["ingest-public"],
            "ingest_public_results",
            PublicDownloadError(503, "https://example.test/results.csv"),
            "ingest-public",
            id="ingest-download",
        ),
        pytest.param(
            ["ingest-public"],
            "ingest_public_results",
            PublicSchemaError(["date"], ["fecha"]),
            "ingesta_publica",
            id="ingest-schema",
        ),
    ],
)
def test_errores_capas_inferiores_traducidos(
    monkeypatch, capsys, argv, objetivo, excepcion, pista
):
    """R12: cada excepción listada → exit 1, stderr accionable, sin traceback."""

    def _raise(*_args, **_kwargs):
        raise excepcion

    monkeypatch.setattr(cli, objetivo, _raise)
    rc = cli.main(argv)
    captured = capsys.readouterr()
    assert rc == 1
    assert "error:" in captured.err
    assert pista in captured.err  # comando previo del flujo / acción a ejecutar
    assert "Traceback" not in captured.err


def test_excepcion_no_listada_se_propaga(monkeypatch):
    """R12: una excepción NO listada (bug) NO se oculta: se propaga con traceback."""

    class BugInesperado(Exception):
        pass

    def _raise(*_args, **_kwargs):
        raise BugInesperado("bug interno")

    monkeypatch.setattr(cli, "build_all", _raise)
    with pytest.raises(BugInesperado):
        cli.main(["build-features", "--as-of-date", AS_OF])


# ---------------------------------------------------------------------------
# R13 — offline por defecto, sin secretos y sin reloj predictivo
# ---------------------------------------------------------------------------


def test_offline_sin_api_key_ni_red(tmp_path, monkeypatch, capsys):
    """R13: import, ayuda y subcomandos offline funcionan sin API_FOOTBALL_KEY ni red."""
    monkeypatch.delenv("API_FOOTBALL_KEY", raising=False)

    def _no_net(*_args, **_kwargs):
        raise AssertionError("red real prohibida en tests (R13)")

    monkeypatch.setattr(socket, "socket", _no_net)
    monkeypatch.setattr(socket, "create_connection", _no_net)

    # Importar src.cli desde cero (copia bajo otro nombre) no requiere key ni red.
    spec = importlib.util.spec_from_file_location("src._cli_import_check", cli.__file__)
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, spec.name, module)
    spec.loader.exec_module(module)
    assert module.DEFAULT_SCHEDULE_LIMIT == cli.DEFAULT_SCHEDULE_LIMIT

    # Mostrar la ayuda tampoco requiere entorno.
    with pytest.raises(SystemExit) as excinfo:
        cli.main(["--help"])
    assert excinfo.value.code == 0

    # Subcomandos offline: ninguno falla por configuración/entorno (red bloqueada).
    monkeypatch.setattr(
        cli,
        "build_all",
        lambda *a, **k: {
            "n_matches_silver": 1,
            "n_teams_gold": 48,
            "paths": {"matches": "m.csv", "elo_history": "e.csv", "team_features": "t.csv"},
        },
    )
    monkeypatch.setattr(cli, "fit_dixon_coles", lambda *a, **k: make_dc_params())
    monkeypatch.setattr(cli, "save_params", lambda p, *a, **k: tmp_path / "p.json")
    assert cli.main(["build-features", "--as-of-date", AS_OF]) == 0
    assert cli.main(["train", "--as-of-date", AS_OF]) == 0

    params_path = write_params_json(tmp_path)
    assert (
        cli.main(
            [
                "predict",
                "ARG",
                "MEX",
                "--params",
                str(params_path),
                "--features",
                no_gold(tmp_path),
            ]
        )
        == 0
    )

    csv_path = write_results_csv(
        tmp_path,
        ["2026-06-11,Mexico,South Africa,NA,NA,FIFA World Cup,Mexico City,Mexico,FALSE"],
    )
    assert cli.main(["schedule", "--results-csv", str(csv_path)]) == 0
    capsys.readouterr()  # drena la salida (el formato se aserta en sus tests propios)


def test_predict_as_of_date_viene_de_params(tmp_path, capsys):
    """R13: predict reporta el as_of_date de los parámetros cargados, nunca 'hoy'."""
    fecha_params = "2031-12-25"  # fecha sintética claramente distinta de cualquier 'hoy'
    params_path = write_params_json(tmp_path, as_of_date=fecha_params)
    rc = cli.main(
        [
            "predict",
            "ARG",
            "MEX",
            "--params",
            str(params_path),
            "--features",
            no_gold(tmp_path),
            "--json",
        ]
    )
    out = capsys.readouterr().out
    assert rc == 0
    assert json.loads(out)["as_of_date"] == fecha_params

    rc = cli.main(
        ["predict", "ARG", "MEX", "--params", str(params_path), "--features", no_gold(tmp_path)]
    )
    out = capsys.readouterr().out
    assert rc == 0
    assert fecha_params in out  # también en la salida humana
