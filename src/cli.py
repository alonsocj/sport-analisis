"""src/cli.py — CLI del pipeline del Mundial 2026 (Features 6, 4, 5, 10, 11, 13, 14, 15, 24 y 25).

Capa FINA de orquestación sobre las features 7 (``ingesta_publica``), 2
(``feature_store``), 3 (``modelo_resultado``), 4 (``modelos_mercados``), 5
(``backtesting``), 10 (``registro_y_evaluacion``), 11 (``factor_jugadores``),
13 (``simulacion_montecarlo``), 14 (``elo_externo_ensemble``), 15
(``xg_proxy_wikipedia``) y 24 (``corners_market``) y 25 (``count_markets``):
parsea argumentos con ``argparse``, delega en sus APIs públicas, formatea la
salida (texto ``✅`` / ``--json``) y traduce los errores esperables a mensajes
accionables. NO reimplementa lógica de esas capas ni modifica sus módulos
(design.md). Sin dependencias nuevas: solo stdlib.

Flujo de subcomandos: ``ingest-public → build-features → train → predict``
(+ ``schedule`` auxiliar, ``markets`` para mercados de goles, ``backtest`` para
evaluación walk-forward, ``predict-log`` para registro de predicciones, ``evaluate``
para evaluación predicho-vs-ocurrido, ``ingest-goalscorers`` para descarga CC0 de
goleadores, ``scorers`` para probabilidades anytime-scorer por partido,
``simulate`` para la simulación Monte Carlo del torneo completo, ``ingest-elo``
para la ingesta del Elo externo de eloratings.net, ``ingest-wiki-stats`` para
la ingesta de stats de partido desde Wikipedia, ``ingest-roster`` para la
descarga del roster R32 desde fotmob.com, ``ingest-fotmob-stats`` para la
ingesta de stats por partido desde fotmob.com (Feature 23), ``corners`` para
el mercado de corners O/U con shrinkage bayesiano (Feature 24) y ``count-market``
para el mercado genérico de conteo (tarjetas/tiros/SoT) con shrinkage bayesiano
(Feature 25)).

Offline por defecto: no usa ``API_FOOTBALL_KEY`` ni importa ``config``/
``client``/``ingest``; los subcomandos con red real son ``ingest-public``,
``ingest-goalscorers``, ``ingest-elo``, ``ingest-wiki-stats``, ``ingest-roster``
e ``ingest-fotmob-stats`` en ejecución explícita (regla STOP de ``CLAUDE.md``);
el único uso de reloj es el metadato ``fetched_at`` de esas descargas
(nunca lógica predictiva).
"""

from __future__ import annotations

import argparse
import csv
import difflib
import json
import re
import sys
import warnings
from datetime import datetime, timezone
from pathlib import Path

from .features.build import build_all
from .features.silver import SilverInputError
from .ingestion.goalscorers import (
    GoalscorersDownloadError,
    GoalscorersSchemaError,
    bronze_goalscorers_paths,
    ingest_goalscorers,
    DEFAULT_BRONZE_DIR as GOALSCORERS_BRONZE_DIR,
)
from .ingestion.elo_ratings import (
    EloDownloadError,
    EloParseError,
    ingest_elo_ratings,
    DEFAULT_URL as ELO_DEFAULT_URL,
    DEFAULT_TTL_DAYS as ELO_DEFAULT_TTL_DAYS,
    DEFAULT_GOLD_PATH as ELO_DEFAULT_GOLD_PATH,
)
from .ingestion.wiki_stats import (
    WikiFetchError,
    ingest_wiki_stats,
    DEFAULT_TTL_HOURS as WIKI_DEFAULT_TTL_HOURS,
    DEFAULT_BRONZE_DIR as WIKI_DEFAULT_BRONZE_DIR,
)
from .ingestion.roster import (
    RosterFetchError,
    DEFAULT_ROSTERS_CSV as ROSTER_DEFAULT_ROSTERS_CSV,
    DEFAULT_UNAVAILABLE_CSV as ROSTER_DEFAULT_UNAVAILABLE_CSV,
    ingest_roster,
)
from .ingestion.fotmob_stats import (
    StatsFetchError,
    StatsCoverage,
    DEFAULT_BRONZE_DIR as FOTMOB_STATS_DEFAULT_BRONZE_DIR,
    ingest_fotmob_stats,
)
from .ingestion.fotmob_ko import (
    DEFAULT_KNOCKOUTS_DIR as KO_DEFAULT_DIR,
    fetch_bracket,
    ingest_ko,
    write_ko_fixtures,
)
from .ingestion.fotmob_lineup import (
    DEFAULT_BRONZE_DIR as LINEUP_DEFAULT_BRONZE_DIR,
    ingest_lineups,
)
from .features.lineup_strength import (
    build_lineup_strength,
    write_lineup_strength,
)
from .ingestion.public_data import (
    PublicDownloadError,
    PublicSchemaError,
    bronze_public_paths,
    filter_world_cup_matches,
    ingest_public_results,
    parse_results,
    to_fifa_code,
)
from .ingestion.teams import all_teams
from .backtest.report import write_report
from .backtest.walkforward import BacktestConfig
from .markets.goals import (
    DEFAULT_TEAM_LINES,
    DEFAULT_TOTAL_LINES,
    MarketSummary,
    _validate_line,
    market_summary,
)
from .markets.by_half import prob_late_goal, prob_over_half, prob_team_scores
from .models.half_signal import (
    DEFAULT_PRIOR_1T,
    half_lambdas,
    load_half_signal,
    split_lambda,
)
from .models.dixon_coles import (
    DCConfig,
    DEFAULT_PARAMS_PATH_V2,
    NotFittedError,
    SilverNotFoundError,
    UnknownTeamError,
    fit_dixon_coles,
    load_params,
    predict_match,
    save_params,
)

# Defaults de módulo (design.md): rutas de las features 7/2/3 + límite del calendario.
DEFAULT_PARAMS_PATH = Path("data/gold/dixon_coles_params.json")
DEFAULT_PLAYER_FACTOR_PATH = Path("data/gold/player_factor.csv")
DEFAULT_FEATURES_CSV = Path("data/gold/team_features.csv")
DEFAULT_RESULTS_CSV = Path("data/bronze/public_results/results.csv")
DEFAULT_SCHEDULE_LIMIT = 10  # vista compacta de "qué predecir ahora" (design.md, R10)
WC_TOURNAMENT = "FIFA World Cup"
# Feature 34: simulador de un cruce fijo.
DEFAULT_PREDICTIONS_DIR = Path("data/predictions")
DEFAULT_MATCH_SIM_N = 50_000

# Recordatorio del orden del flujo en los mensajes accionables (R12).
_FLOW = "ingest-public → build-features → train → predict"

# Formato de código FIFA: exactamente 3 letras A–Z (R6).
_TEAM_CODE_RE = re.compile(r"^[A-Z]{3}$")


def _error(message: str) -> int:
    """Imprime ``error: {message}`` en stderr y devuelve exit 1 (R6, R7, R11, R12)."""
    print(f"error: {message}", file=sys.stderr)
    return 1


# ---------------------------------------------------------------------------
# ingest-public (R2, R12)
# ---------------------------------------------------------------------------


def cmd_ingest_public(args: argparse.Namespace) -> int:
    """``ingest-public [--from-date]``: ingesta delegada + reporte ``✅`` (R2, R12).

    Único subcomando con red real (regla STOP de ``CLAUDE.md``; en tests la función
    delegada está monkeypatcheada — cero red). ``fetched_at = now(UTC)`` es la ÚNICA
    lectura de reloj de todo el CLI y solo como metadato del sidecar bronze
    (excepción documentada de R13). ``--from-date`` solo recorta la vista informativa
    de consumo; el bronze siempre es completo y no destructivo (R9 de la feature 7).
    """
    fetched_at = datetime.now(timezone.utc).isoformat()
    try:
        report = ingest_public_results(fetched_at)
    except PublicDownloadError as exc:
        return _error(
            f"descarga fallida ({exc}); verifica conectividad/URL y reintenta "
            f"`ingest-public` (es la cabeza del flujo {_FLOW})"
        )
    except PublicSchemaError as exc:
        return _error(
            f"el esquema de la fuente cambió ({exc}); no continúes el flujo y "
            "revisa specs/ingesta_publica"
        )

    csv_path, meta_path = bronze_public_paths()
    matches, _ = parse_results(csv_path.read_text(encoding="utf-8"))
    view = filter_world_cup_matches(matches, from_date=args.from_date)

    print(
        f"✅ Ingesta pública completada: {report.n_rows_total} filas "
        f"({report.n_valid} válidas, {report.n_discarded} descartadas)"
    )
    print(f"✅ Descartes por motivo: {report.discarded_by_reason}")
    print(f"✅ Bronze: {csv_path} + {meta_path}")
    print(
        f"✅ Vista de consumo (48 selecciones, from_date={args.from_date}): "
        f"{len(view)} partidos"
    )
    return 0


# ---------------------------------------------------------------------------
# build-features (R3, R12)
# ---------------------------------------------------------------------------


def cmd_build_features(args: argparse.Namespace) -> int:
    """``build-features --as-of-date``: delega en ``build_all`` + resumen ``✅`` (R3, R7).

    ``--as-of-date`` es obligatorio (sin reloj implícito, R3/R13). Traduce
    ``SilverInputError`` (falta bronze → ``ingest-public``) y ``ValueError`` de
    fecha mal formada a mensajes accionables (R12).

    Extensión feature 11 (R7): si existe el bronze de goleadores, construye también
    ``gold/player_factor.csv``; si no existe, lo omite con aviso (no rompe el flujo
    existente ni los tests previos).
    """
    try:
        summary = build_all(args.as_of_date)
    except SilverInputError as exc:
        return _error(
            f"no hay bronze para construir silver ({exc}); ejecuta primero "
            f"`ingest-public` (flujo: {_FLOW})"
        )
    except ValueError as exc:
        return _error(f"fecha inválida ({exc}); formato esperado YYYY-MM-DD")

    paths = summary["paths"]
    print(
        f"✅ Features construidas: {summary['n_matches_silver']} partidos en silver, "
        f"{summary['n_teams_gold']} equipos en gold"
    )
    print(f"✅ Silver matches: {paths['matches']}")
    print(f"✅ Gold elo_history: {paths['elo_history']}")
    print(f"✅ Gold team_features: {paths['team_features']}")

    # Feature 11 — R7: construir player_factor.csv si existe el bronze de goleadores.
    csv_path, _ = bronze_goalscorers_paths()
    if csv_path.is_file():
        try:
            from .players.normalize import normalize_goalscorer_events
            from .players.factor import build_player_factor
            from .models.dixon_coles import DCConfig

            csv_text = csv_path.read_text(encoding="utf-8")
            events, report = normalize_goalscorer_events(csv_text)
            rates = build_player_factor(events, args.as_of_date)
            print(
                f"✅ Gold player_factor: {len(rates)} entradas "
                f"({DEFAULT_PLAYER_FACTOR_PATH})"
            )
            print(
                f"✅ Goleadores: {report.n_valid} eventos válidos, "
                f"{report.n_discarded} descartados ({report.discarded_by_reason})"
            )
        except Exception as exc:  # noqa: BLE001 — fallo no crítico, no aborta el flujo
            print(
                f"⚠️ No se pudo construir player_factor ({exc}); "
                "el resto del pipeline no se ve afectado.",
                file=sys.stderr,
            )
    else:
        print(
            "⚠️ Bronze de goleadores no encontrado; omitiendo player_factor.csv. "
            "Ejecuta `ingest-goalscorers` para habilitarlo.",
            file=sys.stderr,
        )

    return 0


# ---------------------------------------------------------------------------
# train (R4, R12)
# ---------------------------------------------------------------------------


def cmd_train(args: argparse.Namespace) -> int:
    """``train --as-of-date [--from-date] [--xi] [--model-version] [--importance]``.

    Ajusta y persiste el modelo Dixon-Coles (R4, R5, R6 feature 12).

    ``DCConfig(**kwargs)`` se construye SOLO con los flags proporcionados: en su
    ausencia rigen EXACTAMENTE los defaults de la feature 3 (única fuente de
    verdad, design.md). DONDE no converge: aviso ``⚠️`` visible en stderr SIN
    cambiar el exit code (coherente con R6 de la feature 3: no se aborta).

    Con ``--model-version dc-v2``: persiste en ``dixon_coles_params_v2.json`` SIN pisar
    el v1. Con ``--importance default``: aplica el mapa de importancia v2 (R6 f12).
    """
    kwargs: dict[str, object] = {}
    if args.from_date is not None:
        kwargs["from_date"] = args.from_date
    if args.xi is not None:
        kwargs["xi"] = args.xi
    config = DCConfig(**kwargs)  # type: ignore[arg-type]

    # Selección de versión y mapa de importancia (R6 feature 12)
    model_version: str = getattr(args, "model_version", "dc-v1") or "dc-v1"
    importance_flag: str = getattr(args, "importance", "off") or "off"

    importance_map: dict[str, float] | None = None
    importance_config_label: str = "off"

    if model_version == "dc-v2" and importance_flag == "default":
        # Construir mapa de importancia v2 desde el silver
        from .models.importance import TIER_FACTORS, build_importance_map
        silver_path = Path("data/silver/matches.csv")
        if silver_path.is_file():
            try:
                import pandas as _pd
                _df = _pd.read_csv(silver_path, usecols=["tournament"])
                importance_map = build_importance_map(
                    list(_df["tournament"].astype(str).unique()),
                    tier_factors=TIER_FACTORS,
                )
                importance_config_label = "default"
            except Exception as exc:  # noqa: BLE001
                print(
                    f"⚠️ No se pudo construir el mapa de importancia ({exc}); "
                    "entrenando sin importancia.",
                    file=sys.stderr,
                )

    # Feature 15 R4: construir xg_target_map si --xg-weight > 0
    xg_weight: float = getattr(args, "xg_weight", 0.0) or 0.0
    xg_target_map: dict[tuple[str, str], float] | None = None
    if xg_weight > 0.0:
        try:
            from .xg.proxy import build_xg_table, build_goal_target_series
            import pandas as _pd_xg
            _silver_path = Path("data/silver/matches.csv")
            _bronze_wiki = Path("data/bronze/wikipedia")
            if _silver_path.is_file() and _bronze_wiki.is_dir():
                _xg_table = build_xg_table(_silver_path, _bronze_wiki)
                _gt_series = build_goal_target_series(_silver_path, _xg_table, v=xg_weight)
                xg_target_map = {
                    (str(row["match_id"]), str(row["team_code"])): float(row["goal_target"])
                    for _, row in _gt_series.iterrows()
                }
            else:
                warnings.warn(
                    f"--xg-weight={xg_weight} pero no se encontraron datos de Wikipedia "
                    f"({_bronze_wiki}); entrenando con goles reales (v1).",
                    UserWarning,
                    stacklevel=2,
                )
        except Exception as exc:  # noqa: BLE001
            print(
                f"⚠️ No se pudo construir la serie xG ({exc}); "
                "entrenando con goles reales (v1).",
                file=sys.stderr,
            )

    try:
        params = fit_dixon_coles(
            args.as_of_date,
            config=config,
            importance_map=importance_map,
            xg_target_map=xg_target_map,
        )
    except SilverNotFoundError as exc:
        return _error(
            f"no hay silver ({exc}); ejecuta primero "
            f"`build-features --as-of-date YYYY-MM-DD` (flujo: {_FLOW})"
        )
    except ValueError as exc:
        return _error(f"fecha inválida ({exc}); formato esperado YYYY-MM-DD")

    # Seleccionar ruta de salida según versión (R6 feature 12)
    if model_version == "dc-v2":
        out_path = DEFAULT_PARAMS_PATH_V2
        extra_meta: dict[str, object] = {
            "model_version": "dc-v2",
            "importance_config": importance_config_label,
        }
    else:
        out_path = DEFAULT_PARAMS_PATH
        extra_meta = {}

    path = save_params(params, path=out_path, extra_metadata=extra_meta or None)
    convergencia = params.convergencia
    print(
        f"✅ Modelo Dixon-Coles ajustado: {params.n_matches} partidos, "
        f"{params.n_teams} equipos"
    )
    print(
        f"✅ Convergencia: success={convergencia['success']} "
        f"({convergencia['n_iter']} iteraciones)"
    )
    print(f"✅ Parámetros escritos en {path}")
    if xg_weight > 0.0:
        print(f"✅ xg_weight={xg_weight} (serie objetivo mezclada, Feature 15 R4)")
    if model_version == "dc-v2":
        print(f"✅ model_version=dc-v2  importance={importance_config_label}")
    if not convergencia["success"]:
        print(
            f"⚠️ el optimizador no convergió ({convergencia.get('message', 'sin mensaje')}); "
            "los parámetros se guardaron igualmente (R6 de la feature 3)",
            file=sys.stderr,
        )
    return 0


# ---------------------------------------------------------------------------
# predict (R5–R9, R12)
# ---------------------------------------------------------------------------


def _validate_team_code(raw: str) -> str:
    """Normaliza (``strip``+``upper``) y valida un código FIFA de las 48 (R6).

    Orden: formato 3 letras A–Z → pertenencia a ``all_teams()``. SI es inválido
    levanta ``ValueError`` con el código rechazado, sugerencias deterministas
    (``difflib`` sobre los 48 ordenados) y dónde consultar la lista completa.
    NUNCA toca disco ni red (la validación ocurre antes de ``load_params``).
    """
    code = raw.strip().upper()
    valid = sorted(team.code for team in all_teams())
    if _TEAM_CODE_RE.match(code) and code in valid:
        return code
    suggestions = difflib.get_close_matches(code, valid, n=3, cutoff=0.4)
    hint = f"; ¿quisiste decir {', '.join(suggestions)}?" if suggestions else ""
    raise ValueError(
        f"código de equipo inválido: {code!r} (recibido {raw!r}); se espera un código "
        f"FIFA de 3 letras de las 48 selecciones{hint}; la lista completa está en "
        "src/ingestion/teams.py"
    )


def _to_float(value: str | None) -> float | None:
    """Celda CSV → float; vacía/ausente/no numérica → ``None`` (R8, defensivo)."""
    if value is None or value.strip() == "":
        return None
    try:
        return float(value)
    except ValueError:
        return None


def _read_team_context(
    path: Path | str, codes: tuple[str, ...]
) -> dict[str, dict[str, float | None]] | None:
    """Contexto gold opcional por código: ``elo``/``gf_ma15``/``ga_ma15`` (R8).

    SI el CSV no existe devuelve ``None`` (la sección se omite por completo, sin
    fallar y sin alterar el exit code). Celda vacía o fila ausente → ``None`` por
    métrica (``n/d`` en texto, ``null`` en JSON).
    """
    csv_path = Path(path)
    if not csv_path.is_file():
        return None
    with csv_path.open(encoding="utf-8", newline="") as handle:
        rows = {row.get("code"): row for row in csv.DictReader(handle)}
    context: dict[str, dict[str, float | None]] = {}
    for code in codes:
        row = rows.get(code) or {}
        context[code] = {
            key: _to_float(row.get(key)) for key in ("elo", "gf_ma15", "ga_ma15")
        }
    return context


def _fmt_nd(value: float | None) -> str:
    """Valor nulo → ``n/d`` en la salida humana (R8)."""
    return "n/d" if value is None else f"{value}"


def cmd_predict(args: argparse.Namespace) -> int:
    """``predict HOME AWAY``: 1X2 + lambdas + top-k SIN reentrenar (R5–R9, R12).

    Valida los códigos ANTES de tocar disco (R6); carga con ``load_params``
    (nunca ``fit_dixon_coles``, R5) y llama a ``predict_match``; traduce
    ``NotFittedError`` (→ ``train``, R12) y ``UnknownTeamError`` (→ reentrenar
    ampliando ``--from-date``, R7). Mercados (feature 4): fuera de alcance.
    """
    try:
        home = _validate_team_code(args.home)
        away = _validate_team_code(args.away)
    except ValueError as exc:
        return _error(str(exc))
    if home == away:
        return _error(
            f"HOME_CODE y AWAY_CODE deben ser selecciones distintas; se recibió "
            f"{home!r} dos veces"
        )

    model_version_predict: str = getattr(args, "model_version", "dc-v1") or "dc-v1"
    try:
        params = load_params(args.params, model_version=model_version_predict)
    except NotFittedError as exc:
        return _error(
            f"no hay parámetros entrenados ({exc}); ejecuta primero "
            f"`train --as-of-date YYYY-MM-DD` (flujo: {_FLOW})"
        )

    # Feature 16: forma_reciente — construir form_factor callable si γ > 0 (R4, R6)
    # Feature 26: --form-xg activa señal xG en la ventana (R3, R4)
    form_weight: float = getattr(args, "form_weight", 0.0) or 0.0
    form_xg: bool = bool(getattr(args, "form_xg", False))
    predict_form_factor = _build_form_factor(form_weight, params.as_of_date, use_xg=form_xg)

    try:
        pred = predict_match(
            params, home, away,
            max_goals=args.max_goals, top_k=args.top_k,
            form_factor=predict_form_factor,
        )
    except UnknownTeamError as exc:
        return _error(
            f"equipo sin parámetros entrenados ({exc}); reentrena ampliando la "
            "ventana: `train --as-of-date YYYY-MM-DD --from-date <fecha más antigua>`"
        )

    # Feature 14 R8: aplicar ensemble Elo si --elo-weight > 0 (default 0.0 = DC puro)
    elo_weight: float = getattr(args, "elo_weight", 0.0) or 0.0
    prob_home, prob_draw, prob_away = _apply_elo_ensemble(
        pred.prob_home, pred.prob_draw, pred.prob_away,
        home, away, elo_weight,
    )

    names = {team.code: team.name for team in all_teams()}
    context = _read_team_context(args.features, (home, away))

    if args.json:
        # R9: un ÚNICO documento JSON parseable en stdout, sin líneas ✅.
        # La matriz conjunta NO se incluye (decisión justificada en design.md).
        doc = {
            "home": {"code": home, "name": names[home]},
            "away": {"code": away, "name": names[away]},
            "as_of_date": params.as_of_date,  # el de los parámetros: cero reloj (R13)
            "params_path": str(args.params),
            "lambda_home": pred.lambda_home,
            "lambda_away": pred.lambda_away,
            "elo_weight": elo_weight,
            "form_weight": form_weight,
            "probs": {
                "home": prob_home,
                "draw": prob_draw,
                "away": prob_away,
            },
            "top_scores": [
                {"home_goals": gx, "away_goals": gy, "prob": prob}
                for gx, gy, prob in pred.top_scores
            ],
            "context": None
            if context is None
            else {"home": context[home], "away": context[away]},
        }
        print(json.dumps(doc, ensure_ascii=False))
        return 0

    print(f"✅ Partido: {names[home]} ({home}) vs {names[away]} ({away})")
    print(f"✅ Parámetros: {args.params} (as_of_date={params.as_of_date})")
    if elo_weight > 0.0:
        print(f"✅ Ensemble DC+Elo activo (elo_weight={elo_weight})")
    if form_weight > 0.0:
        print(f"✅ Forma reciente activa (form_weight={form_weight})")
    print(
        "✅ Probabilidades 1X2: "
        f"local {100 * prob_home:.1f}% | "
        f"empate {100 * prob_draw:.1f}% | "
        f"visita {100 * prob_away:.1f}%"
    )
    print(
        f"✅ Goles esperados: lambda_home={pred.lambda_home:.2f}, "
        f"lambda_away={pred.lambda_away:.2f}"
    )
    print(f"✅ Marcadores más probables (top {len(pred.top_scores)}):")
    for gx, gy, prob in pred.top_scores:
        print(f"   {gx}-{gy}  {100 * prob:.1f}%")
    if context is not None:
        print("✅ Contexto (gold):")
        for code in (home, away):
            vals = context[code]
            print(
                f"   {code}: elo={_fmt_nd(vals['elo'])}, "
                f"gf_ma15={_fmt_nd(vals['gf_ma15'])}, "
                f"ga_ma15={_fmt_nd(vals['ga_ma15'])}"
            )
    return 0


# ---------------------------------------------------------------------------
# schedule (R10, R11)
# ---------------------------------------------------------------------------


def _is_int(value: object) -> bool:
    """True si ``value`` es convertible a ``int`` (marca de partido jugado, R10)."""
    try:
        int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return False
    return True


def _pending_world_cup_rows(csv_path: Path) -> list[dict]:
    """Filas del bronze crudo con partidos del Mundial 2026 AÚN no jugados (R10).

    ``pendiente := tournament == "FIFA World Cup" y algún score no numérico``
    (la marca del dataset; NUNCA el reloj — cero ``now()``, R13). Se lee el CSV
    crudo deliberadamente: la vista de consumo de la feature 7 descarta estas
    filas por ``goles_no_numericos`` (design.md). Filas malformadas se ignoran
    de forma defensiva. Orden ascendente ``(date, home_team, away_team)``.
    """
    with Path(csv_path).open(encoding="utf-8", newline="") as handle:
        rows = []
        for row in csv.DictReader(handle):
            if not row.get("date") or not row.get("home_team") or not row.get("away_team"):
                continue  # fila malformada: defensivo (espíritu tolerante de la feature 7)
            if row.get("tournament") != WC_TOURNAMENT:
                continue
            if _is_int(row.get("home_score")) and _is_int(row.get("away_score")):
                continue  # ya jugado: scores numéricos
            rows.append(row)
    rows.sort(key=lambda r: (r["date"], r["home_team"], r["away_team"]))
    return rows


def _team_label(dataset_name: str) -> str:
    """``"<nombre> (<CODE>)"`` vía ``to_fifa_code``; sin alias → solo el nombre (R10)."""
    code = to_fifa_code(dataset_name)
    return f"{dataset_name} ({code})" if code else dataset_name


def cmd_schedule(args: argparse.Namespace) -> int:
    """``schedule [--limit] [--results-csv]``: próximos partidos WC2026 (R10, R11).

    SI el bronze público no existe → error accionable (ejecutar antes
    ``ingest-public``) y exit 1 (R11). SI no hay pendientes → mensaje claro y
    exit 0 (estado válido, no error).
    """
    csv_path = Path(args.results_csv)
    if not csv_path.is_file():
        return _error(
            f"no existe el bronze público en {csv_path}; ejecuta primero "
            f"`python -m src.cli ingest-public` (flujo: {_FLOW})"
        )
    pending = _pending_world_cup_rows(csv_path)
    if not pending:
        print("✅ No hay partidos del Mundial 2026 pendientes en el bronze público.")
        return 0
    shown = pending[: args.limit]
    print(
        f"✅ Próximos partidos del Mundial 2026 pendientes "
        f"({len(shown)} de {len(pending)}):"
    )
    for row in shown:
        print(
            f"   {row['date']}  {_team_label(row['home_team'])} "
            f"vs {_team_label(row['away_team'])}"
        )
    return 0


# ---------------------------------------------------------------------------
# markets (Feature 4, R7)
# ---------------------------------------------------------------------------


def _parse_lines_arg(raw: str) -> tuple[float, ...]:
    """Parsea un argumento CSV de lineas ``'0.5,1.5,2.5'`` a tuple de floats.

    Aplica ``_validate_line`` a cada valor: si alguno no es k+0.5 lanza
    ``ValueError`` con el mensaje de la capa pura (el parser lo convierte
    a exit 2 via ``parser.error``). No se permiten duplicados ni strings vacios.

    Args:
        raw: Comma-separated string of float values.

    Returns:
        Tuple of validated float lines.

    Raises:
        ValueError: If any line is not of the form k + 0.5.
    """
    parts = [p.strip() for p in raw.split(",") if p.strip()]
    if not parts:
        raise ValueError("--lines no puede estar vacio; usa ej. '0.5,1.5,2.5'")
    result = []
    for part in parts:
        try:
            val = float(part)
        except ValueError:
            raise ValueError(f"valor no numerico en --lines: {part!r}")
        _validate_line(val)
        result.append(val)
    return tuple(result)


def _market_summary_to_dict(summary: MarketSummary) -> dict:
    """Serializa un MarketSummary a dict nativo (floats, sin numpy, para JSON).

    Args:
        summary: MarketSummary to serialize.

    Returns:
        Plain dict ready for json.dumps.
    """
    return {
        "home_code": summary.home_code,
        "away_code": summary.away_code,
        "probs": {
            "home": summary.prob_home,
            "draw": summary.prob_draw,
            "away": summary.prob_away,
        },
        "totals": [
            {"line": ml.line, "over": ml.over, "under": ml.under}
            for ml in summary.totals
        ],
        "btts": {"yes": summary.btts_yes, "no": summary.btts_no},
        "home_totals": [
            {"line": ml.line, "over": ml.over, "under": ml.under}
            for ml in summary.home_totals
        ],
        "away_totals": [
            {"line": ml.line, "over": ml.over, "under": ml.under}
            for ml in summary.away_totals
        ],
    }


# Fracción del 2T atribuible al 76-90 (prior direccional; se afina con el histórico por-bucket).
_LATE_BUCKET_SHARE: float = 0.42
DEFAULT_HALF_SIGNAL_PATH = Path("data/gold/half_signal.csv")


def _by_half_markets_dict(params, home: str, away: str, signal: dict | None = None) -> dict:
    """Mercados por mitad para HOME vs AWAY (Feature 32, R5) repartiendo el λ del modelo.

    Reparte λ_home/λ_away (de ``predict_match``) en 1T/2T. Si ``signal`` (gold
    ``half_signal``) tiene AMBOS equipos → reparto **ajustado por rival** (ataque de A ×
    defensa de B por mitad); si no → reparto por **prior de liga**. Conserva el total.
    """
    pred = predict_match(params, home, away)
    signal = signal or {}
    if home in signal and away in signal:
        l1h, l2h = half_lambdas(pred.lambda_home, signal[home]["att"], signal[away]["def"])
        l1a, l2a = half_lambdas(pred.lambda_away, signal[away]["att"], signal[home]["def"])
        reparto = "ajuste_rival"
    else:
        l1h, l2h = split_lambda(pred.lambda_home, DEFAULT_PRIOR_1T)
        l1a, l2a = split_lambda(pred.lambda_away, DEFAULT_PRIOR_1T)
        reparto = "prior_liga"
    return {
        "reparto": reparto,
        "prior_1t": DEFAULT_PRIOR_1T,
        "ou_1t": {"over_0_5": prob_over_half(l1h, l1a, 0.5), "over_1_5": prob_over_half(l1h, l1a, 1.5)},
        "ou_2t": {"over_0_5": prob_over_half(l2h, l2a, 0.5), "over_1_5": prob_over_half(l2h, l2a, 1.5)},
        "marca_2t": {"home": prob_team_scores(l2h), "away": prob_team_scores(l2a)},
        "gol_76_90": prob_late_goal(l2h, l2a, _LATE_BUCKET_SHARE),
    }


def cmd_markets(args: argparse.Namespace) -> int:
    """``markets HOME AWAY [--json] [--lines L1,L2,...]``: mercados de goles (Feature 4, R7).

    Valida los codigos ANTES de tocar disco (igual que ``predict``); carga con
    ``load_params`` (nunca reentrenar); llama a ``market_summary`` UNA vez y
    formatea la salida. Traduce ``NotFittedError`` → mensaje ``train``, exit 1;
    ``UnknownTeamError`` → mensaje claro, exit 1.
    """
    try:
        home = _validate_team_code(args.home)
        away = _validate_team_code(args.away)
    except ValueError as exc:
        return _error(str(exc))
    if home == away:
        return _error(
            f"HOME_CODE y AWAY_CODE deben ser selecciones distintas; se recibio "
            f"{home!r} dos veces"
        )

    model_version_markets: str = getattr(args, "model_version", "dc-v1") or "dc-v1"
    try:
        params = load_params(args.params, model_version=model_version_markets)
    except NotFittedError as exc:
        return _error(
            f"no hay parametros entrenados ({exc}); ejecuta primero "
            f"`train --as-of-date YYYY-MM-DD` (flujo: {_FLOW})"
        )

    # Parsear --lines si se proporcionan (validacion ya hecha en _parse_lines_arg)
    total_lines = args.total_lines if args.total_lines is not None else DEFAULT_TOTAL_LINES

    try:
        summary = market_summary(params, home, away, total_lines=total_lines)
    except UnknownTeamError as exc:
        return _error(
            f"equipo sin parametros entrenados ({exc}); reentrena ampliando la "
            "ventana: `train --as-of-date YYYY-MM-DD --from-date <fecha mas antigua>`"
        )

    if args.json:
        # Salida JSON parseable (R7)
        doc = _market_summary_to_dict(summary)
        if getattr(args, "by_half", False):  # Feature 32, R5/R6: aditivo, OFF = idéntico
            _sig = load_half_signal(getattr(args, "half_signal", None) or DEFAULT_HALF_SIGNAL_PATH)
            doc["by_half"] = _by_half_markets_dict(params, home, away, signal=_sig)
        print(json.dumps(doc, ensure_ascii=False))
        return 0

    # Salida humana con porcentajes a 1 decimal (R7)
    names = {team.code: team.name for team in all_teams()}
    print(f"✅ Partido: {names[home]} ({home}) vs {names[away]} ({away})")
    print(f"✅ Parametros: {args.params} (as_of_date={params.as_of_date})")
    print(
        "✅ Probabilidades 1X2: "
        f"local {100 * summary.prob_home:.1f}% | "
        f"empate {100 * summary.prob_draw:.1f}% | "
        f"visita {100 * summary.prob_away:.1f}%"
    )
    print("✅ Over/Under (goles totales):")
    for ml in summary.totals:
        print(
            f"   O{ml.line:.1f}: over {100 * ml.over:.1f}%  |  "
            f"under {100 * ml.under:.1f}%"
        )
    print(
        f"✅ BTTS (ambos marcan): si {100 * summary.btts_yes:.1f}%  |  "
        f"no {100 * summary.btts_no:.1f}%"
    )
    print(f"✅ Totales {names[home]} ({home}):")
    for ml in summary.home_totals:
        print(
            f"   O{ml.line:.1f}: over {100 * ml.over:.1f}%  |  "
            f"under {100 * ml.under:.1f}%"
        )
    print(f"✅ Totales {names[away]} ({away}):")
    for ml in summary.away_totals:
        print(
            f"   O{ml.line:.1f}: over {100 * ml.over:.1f}%  |  "
            f"under {100 * ml.under:.1f}%"
        )
    if getattr(args, "by_half", False):  # Feature 32, R5/R6: aditivo, OFF = idéntico
        _sig = load_half_signal(getattr(args, "half_signal", None) or DEFAULT_HALF_SIGNAL_PATH)
        bh = _by_half_markets_dict(params, home, away, signal=_sig)
        _rep = "ajuste por rival" if bh["reparto"] == "ajuste_rival" else "prior de liga"
        print(f"✅ Por mitad (reparto: {_rep}):")
        print(
            f"   1T over0.5 {100 * bh['ou_1t']['over_0_5']:.1f}%  |  "
            f"2T over0.5 {100 * bh['ou_2t']['over_0_5']:.1f}%"
        )
        print(
            f"   Marca en 2T: {names[home]} {100 * bh['marca_2t']['home']:.1f}%  |  "
            f"{names[away]} {100 * bh['marca_2t']['away']:.1f}%"
        )
        print(f"   Gol en 76-90: {100 * bh['gol_76_90']:.1f}%")
    return 0


# ---------------------------------------------------------------------------
# backtest (Feature 5, R10)
# ---------------------------------------------------------------------------

DEFAULT_BACKTEST_OUT = Path("data/reports/backtest")
DEFAULT_BACKTEST_SILVER = Path("data/silver/matches.csv")
DEFAULT_LOG_PATH = Path("data/predictions/log.csv")
DEFAULT_EVAL_OUT = Path("data/reports/evaluacion")


def cmd_backtest(args: argparse.Namespace) -> int:
    """``backtest [opciones]``: backtest walk-forward Dixon-Coles (Feature 5, R10).

    Delega en ``write_report`` de la capa backtest. Éxito → tabla compacta modelo vs
    baselines + ``✅`` con la ruta del reporte, exit 0. Silver ausente → ``error:``
    accionable y exit 1. Sin reloj (cero ``now()``).
    """
    from .backtest.walkforward import DEFAULT_SILVER_PATH
    from .models.dixon_coles import SilverNotFoundError

    silver_path = Path(args.silver if hasattr(args, "silver") and args.silver else DEFAULT_BACKTEST_SILVER)
    out_dir = Path(args.out) if args.out else DEFAULT_BACKTEST_OUT
    odds_csv = Path(args.odds) if args.odds else None

    cfg = BacktestConfig(
        from_date=args.from_date if args.from_date else "2024-01-01",
        to_date=args.to_date if args.to_date else None,
        refit_every=args.refit_every,
        out_dir=out_dir,
        odds_csv=odds_csv,
        silver_path=silver_path,
    )

    if not silver_path.is_file():
        return _error(
            f"no existe el silver en {silver_path}; ejecuta primero "
            "`build-features --as-of-date YYYY-MM-DD` (o `ingest-public` si falta el bronze)"
        )

    # R4 feature 12: escala de importancia para el grid
    importance_scales_raw: str | None = getattr(args, "importance_scales", None)
    importance_scales: list[float] | None = None
    if importance_scales_raw:
        try:
            importance_scales = [float(v.strip()) for v in importance_scales_raw.split(",") if v.strip()]
        except ValueError:
            return _error("--importance-scales debe ser una lista CSV de números, ej. '0.5,1.0,1.5'")

    # Feature 16: forma_reciente — construir form_factory para backtest walk-forward (R5, R6)
    # Feature 26: --form-xg activa señal xG en el factory (R3, R4)
    backtest_form_weight: float = getattr(args, "form_weight", 0.0) or 0.0
    backtest_form_xg: bool = bool(getattr(args, "form_xg", False))
    backtest_form_factory = None
    if backtest_form_weight > 0.0:
        try:
            import pandas as _pd_bf
            from .form import make_form_factory, DEFAULT_FORM_CONFIG as _BF_CFG
            from .ingestion.teams import all_teams as _bt_all_teams

            _bf_elo_path = Path("data/gold/external_elo.csv")
            _bf_matches = _pd_bf.read_csv(silver_path) if silver_path.is_file() else _pd_bf.DataFrame()
            _bf_elo = _pd_bf.read_csv(_bf_elo_path) if _bf_elo_path.is_file() else None
            _bf_teams = [t.code for t in _bt_all_teams()]

            if not _bf_matches.empty:
                backtest_form_factory = make_form_factory(
                    _bf_matches, _bf_elo, backtest_form_weight, _bf_teams, use_xg=backtest_form_xg
                )
        except Exception as exc_bf:  # noqa: BLE001
            print(
                f"⚠️ No se pudo construir el factory de forma ({exc_bf}); "
                "backtesting sin forma reciente.",
                file=sys.stderr,
            )

    try:
        summary = write_report(
            cfg,
            run_grid_flag=args.grid,
            importance_scales=importance_scales,
            form_factory=backtest_form_factory,
        )
    except SilverNotFoundError as exc:
        return _error(
            f"silver no disponible ({exc}); ejecuta primero "
            "`build-features --as-of-date YYYY-MM-DD` o `ingest-public`"
        )
    except ValueError as exc:
        return _error(str(exc))

    # Resumen humano: modelo vs baselines (R10)
    metrics = summary.get("metrics", {})
    n = metrics.get("model", {}).get("n_matches", 0)
    n_skip = metrics.get("model", {}).get("n_skipped", 0)
    as_of = summary.get("as_of", "?")

    print(f"✅ Backtest walk-forward completado ({n} partidos evaluados, {n_skip} omitidos)")
    print(f"   as_of={as_of}  refit_every={cfg.refit_every}")
    print("")
    header = f"{'Modelo':<12}  {'log-loss':>9}  {'Brier':>8}  {'Exactitud':>10}"
    print(header)
    print("-" * len(header))
    for name, key in [("Modelo", "model"), ("Uniforme", "uniform"), ("Marginal", "marginal")]:
        m = metrics.get(key, {})
        ll = m.get("log_loss", float("nan"))
        brier = m.get("brier", float("nan"))
        acc = m.get("accuracy", float("nan"))
        print(f"{name:<12}  {ll:>9.4f}  {brier:>8.4f}  {100 * acc:>9.2f}%")

    if summary.get("roi"):
        roi = summary["roi"]
        print("")
        print(
            f"   ROI: {roi['n_bets']} apuestas, {roi['n_wins']} aciertos, "
            f"stake={roi['stake']:.1f}, retorno={roi['retorno']:.2f}, "
            f"ROI={100 * roi['roi']:.2f}%"
        )

    if summary.get("low_data", {}).get("low_data_en_torneo"):
        torneo_low = [t["code"] for t in summary["low_data"]["teams"] if t["code"] in {
            c for c in [tt["code"] for tt in summary["low_data"]["teams"]]
        }]
        print(
            f"\n⚠️  low_data incluye selecciones del torneo "
            f"(ver summary.json → low_data)"
        )

    print(f"\n✅ Reporte escrito en {out_dir}/")
    return 0


# ---------------------------------------------------------------------------
# predict-log (Feature 10, R12)
# ---------------------------------------------------------------------------


def cmd_predict_log(args: argparse.Namespace) -> int:
    """``predict-log --as-of <fecha> --timestamp <iso> [--markets] [--targets ...]``.

    Genera y persiste las predicciones en ``data/predictions/log.csv``. El modelo se
    entrena al vuelo con ``fit_dixon_coles(as_of_date)``. Timestamp inyectado: NUNCA
    ``datetime.now()`` (R2 de la feature 10). Exit 0 éxito, 1 error accionable, 2
    error de argumentos (argparse).

    Args:
        args: Parsed CLI arguments.

    Returns:
        Exit code (0, 1 or 2).
    """
    from .eval.prediction_log import (
        DEFAULT_LOG_PATH as _DEF_LOG,
        fixtures_from_csv,
        fixtures_from_schedule,
        log_predictions,
    )

    as_of = args.as_of
    timestamp = args.timestamp
    include_markets: bool = args.markets
    targets: str = args.targets
    results_csv = Path(args.results_csv) if args.results_csv else Path(str(DEFAULT_RESULTS_CSV))
    log_path = Path(args.out) if args.out else _DEF_LOG
    silver_path = Path(args.silver) if hasattr(args, "silver") and args.silver else Path("data/silver/matches.csv")
    # R5/R6 feature 12: versión del modelo e importancia para predict-log
    pl_model_version: str = getattr(args, "model_version", "dc-v1") or "dc-v1"
    pl_importance_flag: str = getattr(args, "importance", "off") or "off"

    # Cargar fixtures objetivo
    if targets == "schedule":
        try:
            fixtures = fixtures_from_schedule(results_csv)
        except FileNotFoundError as exc:
            return _error(str(exc))
    else:
        # Ruta a CSV de fixtures
        target_path = Path(targets)
        if not target_path.is_file():
            return _error(
                f"no existe el CSV de fixtures en {target_path}; "
                "usa --targets schedule o provee una ruta válida"
            )
        try:
            fixtures = fixtures_from_csv(target_path)
        except ValueError as exc:
            return _error(str(exc))

    if not fixtures:
        print("✅ No hay fixtures objetivo; log sin cambios.")
        return 0

    # Construir importance_map si dc-v2 con importancia activada (R5 f12)
    pl_importance_map: dict[str, float] | None = None
    if pl_model_version == "dc-v2" and pl_importance_flag == "default":
        from .models.importance import TIER_FACTORS, build_importance_map as _bim
        if silver_path.is_file():
            try:
                import pandas as _pd2
                _df2 = _pd2.read_csv(silver_path, usecols=["tournament"])
                pl_importance_map = _bim(
                    list(_df2["tournament"].astype(str).unique()),
                    tier_factors=TIER_FACTORS,
                )
            except Exception as exc2:  # noqa: BLE001
                print(
                    f"⚠️ No se pudo construir mapa de importancia ({exc2}); "
                    "predict-log sin importancia.",
                    file=sys.stderr,
                )

    # Seleccionar la config del modelo (versión)
    from .models.dixon_coles import DCConfig as _DCConfig
    pl_dc_config = _DCConfig()

    # Feature 14 R8: peso del ensemble Elo para predict-log
    pl_elo_weight: float = getattr(args, "elo_weight", 0.0) or 0.0

    try:
        result = log_predictions(
            as_of_date=as_of,
            created_at=timestamp,
            fixtures=fixtures,
            include_markets=include_markets,
            silver_path=silver_path,
            log_path=log_path,
            config=pl_dc_config,
            model_version=pl_model_version,
            importance_map=pl_importance_map,
            elo_weight=pl_elo_weight,
        )
    except FileNotFoundError as exc:
        return _error(
            f"no existe el silver ({exc}); ejecuta primero "
            f"`build-features --as-of-date YYYY-MM-DD` (flujo: {_FLOW})"
        )
    except ValueError as exc:
        return _error(str(exc))

    n_logged = result["n_logged"]
    n_skipped = result["n_skipped"]
    print(
        f"✅ predict-log: {n_logged} predicciones registradas, "
        f"{n_skipped} fixtures omitidos (equipo fuera de recorte)"
    )
    print(f"✅ Log escrito en {log_path} (as_of={as_of})")
    if result["skipped"]:
        for sk in result["skipped"]:
            print(f"   ⚠️  omitido: {sk['match_id']} — {sk['reason']}", file=sys.stderr)
    return 0


# ---------------------------------------------------------------------------
# evaluate (Feature 10, R13)
# ---------------------------------------------------------------------------


def cmd_evaluate(args: argparse.Namespace) -> int:
    """``evaluate [--from <fecha>] [--to <fecha>] [--markets] [--log ...] [--silver ...] [--out ...]``.

    Lee el log y el silver, calcula métricas 1X2, calibración, Brier de mercado
    y error de lambda, escribe el reporte e imprime una tabla resumen.
    Sin log → exit 1 accionable. Sin evaluables → mensaje claro y exit 0 (R13).

    Args:
        args: Parsed CLI arguments.

    Returns:
        Exit code (0 or 1).
    """
    from .eval.evaluate import DEFAULT_LOG_PATH as _DEF_LOG, DEFAULT_REPORT_DIR, evaluate

    log_path = Path(args.log) if args.log else _DEF_LOG
    silver_path = Path(args.silver) if args.silver else Path("data/silver/matches.csv")
    out_dir = Path(args.out) if args.out else DEFAULT_REPORT_DIR
    from_date: str | None = args.from_date
    to_date: str | None = args.to_date
    include_markets: bool = args.markets
    # R7 feature 12: filtro de versión del modelo
    eval_model_version: str | None = getattr(args, "model_version", None) or None

    try:
        result = evaluate(
            log_path=log_path,
            silver_path=silver_path,
            out_dir=out_dir,
            from_date=from_date,
            to_date=to_date,
            include_markets=include_markets,
            model_version_filter=eval_model_version,
        )
    except FileNotFoundError as exc:
        # Sin log → exit 1 accionable (R13)
        if "log de predicciones" in str(exc):
            return _error(
                f"no existe el log de predicciones ({exc}); ejecuta primero "
                "`predict-log --as-of YYYY-MM-DD --timestamp <iso>`"
            )
        return _error(str(exc))
    except ValueError as exc:
        return _error(str(exc))

    # Sin evaluables: mensaje claro y exit 0 (R13)
    if result.get("all_skipped"):
        n_skip = result.get("n_skipped", 0)
        print(
            f"✅ Evaluación completada: 0 partidos evaluables "
            f"({n_skip} pendientes/sin marcador). "
            "Ejecuta `ingest-public` + `build-features` para actualizar los resultados."
        )
        return 0

    # Imprimir tabla de resultados
    m = result.get("metrics", {}) or {}
    n_eval = result.get("n_evaluable", 0)
    n_skip = result.get("n_skipped", 0)

    print(f"✅ Evaluación: {n_eval} partidos evaluados, {n_skip} omitidos (pendientes)")
    print("")
    header = f"{'Métrica':<14}  {'Valor':>10}"
    print(header)
    print("-" * len(header))
    print(f"{'log-loss':<14}  {m.get('log_loss', float('nan')):>10.4f}")
    print(f"{'Brier':<14}  {m.get('brier', float('nan')):>10.4f}")
    print(f"{'Exactitud':<14}  {100 * m.get('accuracy', float('nan')):>9.2f}%")

    le = result.get("lambda_error") or {}
    if le:
        print("")
        print(f"✅ Error λ (goles esperados vs reales): RMSE={le.get('rmse', float('nan')):.4f}  MAE={le.get('mae', float('nan')):.4f}")

    mm = result.get("market_metrics")
    if mm:
        print("")
        print(
            f"✅ Brier mercados: O/U2.5={mm.get('brier_over25', float('nan')):.4f}  "
            f"BTTS={mm.get('brier_btts', float('nan')):.4f}"
        )

    report = result.get("report", {})
    if report:
        print(f"\n✅ Reporte escrito en {out_dir}/")

    return 0


# ---------------------------------------------------------------------------
# ingest-goalscorers (Feature 11, R1, R7)
# ---------------------------------------------------------------------------


def cmd_ingest_goalscorers(args: argparse.Namespace) -> int:
    """``ingest-goalscorers``: descarga CC0 goleadores a bronze (Feature 11, R1, R7).

    Segundo subcomando con red real (patrón de ``ingest-public``; regla STOP de
    ``CLAUDE.md``; en tests la función delegada está monkeypatcheada — cero red).
    ``fetched_at = now(UTC)`` es la única lectura de reloj, como metadato del sidecar
    bronze (excepción documentada). El bronze se sobreescribe en cada descarga.

    Args:
        args: Parsed CLI arguments.

    Returns:
        Exit code 0 (success) or 1 (error).
    """
    fetched_at = datetime.now(timezone.utc).isoformat()
    try:
        csv_path, meta_path = ingest_goalscorers(fetched_at)
    except GoalscorersDownloadError as exc:
        return _error(
            f"descarga fallida ({exc}); verifica conectividad/URL y reintenta "
            "`ingest-goalscorers`"
        )
    except GoalscorersSchemaError as exc:
        return _error(
            f"el esquema de la fuente cambió ({exc}); no continúes el flujo y "
            "revisa specs/factor_jugadores"
        )

    import json as _json

    meta = _json.loads(meta_path.read_text(encoding="utf-8"))
    print(
        f"✅ Ingesta goleadores completada: {meta['n_rows']} filas "
        f"(sha256={meta['sha256'][:12]}…)"
    )
    print(f"✅ Bronze: {csv_path} + {meta_path}")
    return 0


# ---------------------------------------------------------------------------
# scorers (Feature 11, R4, R5, R7)
# ---------------------------------------------------------------------------


def _load_roster_csv(roster_path: str) -> dict[str, list[str]]:
    """Carga el CSV de roster ``team_code,scorer`` → dict[team_code, list[scorer]] (R5).

    Args:
        roster_path: Path to the roster CSV file.

    Returns:
        Dict mapping team_code to list of scorer names.
    """
    roster: dict[str, list[str]] = {}
    path = Path(roster_path)
    if not path.is_file():
        raise FileNotFoundError(f"no existe el roster CSV en {roster_path}")
    with path.open(encoding="utf-8", newline="") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            code = (row.get("team_code") or "").strip()
            scorer = (row.get("scorer") or "").strip()
            if code and scorer:
                roster.setdefault(code, []).append(scorer)
    return roster


def cmd_scorers(args: argparse.Namespace) -> int:
    """``scorers --home <cod> --away <cod> [--as-of] [--top-k N] [--roster <csv>]``.

    Calcula y muestra las probabilidades anytime-scorer por partido usando la λ del
    modelo Dixon-Coles y las cuotas históricas de goleadores. Si se provee ``--roster``,
    aplica el multiplicador de ataque (R5). Errores accionables con exit codes 0/1/2 (R7).

    Supuesto documentado (R4): cuota histórica de goles ≈ participación ofensiva;
    no distingue titular/suplente/lesionado (requeriría API).

    Args:
        args: Parsed CLI arguments.

    Returns:
        Exit code 0 (success), 1 (domain error), or 2 (argparse error).
    """
    try:
        home = _validate_team_code(args.home)
        away = _validate_team_code(args.away)
    except ValueError as exc:
        return _error(str(exc))
    if home == away:
        return _error(
            f"HOME_CODE y AWAY_CODE deben ser selecciones distintas; se recibió "
            f"{home!r} dos veces"
        )

    # Cargar parámetros del modelo
    try:
        params = load_params(args.params)
    except NotFittedError as exc:
        return _error(
            f"no hay parámetros entrenados ({exc}); ejecuta primero "
            f"`train --as-of-date YYYY-MM-DD` (flujo: {_FLOW})"
        )

    # Determinar as_of para el factor de jugadores
    as_of_date: str = args.as_of if args.as_of else params.as_of_date

    # Cargar factor de jugadores: intentar gold precalculado; si no, construir al vuelo
    from .players.factor import (
        build_player_rates,
        compute_anytime_scorers,
        attack_multiplier,
        load_player_factor,
        DEFAULT_GOLD_PATH as _GOLD_PATH,
    )
    from .players.normalize import normalize_goalscorer_events

    try:
        rates = load_player_factor(Path(args.player_factor))
    except FileNotFoundError:
        # Construir al vuelo desde el bronze si existe
        csv_path, _ = bronze_goalscorers_paths()
        if not csv_path.is_file():
            return _error(
                f"no existe el artefacto de jugadores en {args.player_factor} ni el "
                "bronze de goleadores; ejecuta `ingest-goalscorers` + "
                "`build-features --as-of-date YYYY-MM-DD`"
            )
        csv_text = csv_path.read_text(encoding="utf-8")
        events, _ = normalize_goalscorer_events(csv_text)
        from .models.dixon_coles import DCConfig
        rates = build_player_rates(events, as_of_date, DCConfig.xi)

    # Predecir el partido para obtener las lambdas de equipo
    try:
        pred = predict_match(params, home, away)
    except UnknownTeamError as exc:
        return _error(
            f"equipo sin parámetros entrenados ({exc}); reentrena ampliando la "
            "ventana: `train --as-of-date YYYY-MM-DD --from-date <fecha más antigua>`"
        )

    # Cargar roster si se proporcionó (R5)
    roster_data: dict[str, list[str]] | None = None
    if args.roster:
        try:
            roster_data = _load_roster_csv(args.roster)
        except FileNotFoundError as exc:
            return _error(str(exc))

    top_k: int = args.top_k
    names = {team.code: team.name for team in all_teams()}

    print(
        f"✅ Anytime-scorer: {names[home]} ({home}) vs {names[away]} ({away}) "
        f"[as_of={as_of_date}]"
    )
    print(
        "   Supuesto: cuota histórica de goles ≈ participación ofensiva; "
        "sin datos de alineación/lesionados (R4)."
    )
    print()

    for team_code, lambda_team, team_label in [
        (home, pred.lambda_home, f"{names[home]} ({home})"),
        (away, pred.lambda_away, f"{names[away]} ({away})"),
    ]:
        roster_team = roster_data.get(team_code) if roster_data else None
        mult = attack_multiplier(rates, team_code, roster_team)
        effective_lambda = lambda_team * mult
        scorers = compute_anytime_scorers(rates, effective_lambda, team_code, top_k=top_k)

        print(
            f"  {team_label}  λ_equipo={lambda_team:.3f}"
            + (f"  × roster={mult:.3f}" if roster_data else "")
            + f"  λ_efectivo={effective_lambda:.3f}"
        )
        if scorers:
            for s in scorers:
                print(
                    f"    {s.scorer:<30s}  share={s.share:.3f}  "
                    f"λ={s.lambda_player:.3f}  P(marca)={100 * s.prob_score:.1f}%"
                )
        else:
            print("    (sin datos históricos de goleadores para este equipo)")
        print()

    return 0


# ---------------------------------------------------------------------------
# simulate (Feature 13, R8, R9)
# ---------------------------------------------------------------------------

DEFAULT_SIMULATE_OUT = Path("data/reports/simulacion")


def cmd_simulate(args: argparse.Namespace) -> int:
    """``simulate [--n 10000] [--seed 42] [--as-of <fecha>] [--model-version dc-v1|dc-v2] [--roster <csv>] [--out <dir>]``.

    Simulación Monte Carlo del Mundial 2026 completo (Feature 13, R8, R9).
    Delega en ``src.simulation.montecarlo.run_simulation`` y ``src.simulation.report``.
    Usa dc-v1 por defecto; soporta ``--model-version dc-v2`` si existe el JSON.
    Con ``--roster``, aplica el multiplicador de ataque del factor jugadores (R9).
    Sin roster ni player_factor → modelo base intacto.
    Exit 0 éxito, 1 error de dominio (modelo no entrenado, estructura inválida, etc.).

    Nota: el ensemble Elo (``--elo-weight``) NO está disponible en ``simulate``.
    La simulación trabaja a nivel de marcador (scorelines); el ensemble es a nivel
    de probabilidad 1X2. Integrar ambos exigiría muestrear el desenlace 1X2 ensamblado
    y luego un marcador condicional — diseño fuera de alcance (Feature 14 design.md,
    decisión 2026-06-17). Extensión futura documentada.

    Args:
        args: Parsed CLI arguments.

    Returns:
        Exit code 0 (success) or 1 (domain error).
    """
    from .simulation.montecarlo import (
        GroupStructureError,
        load_wc2026_fixtures,
        load_roster_multipliers,
        run_simulation,
        MIN_N_SIMULATIONS,
    )
    from .simulation.report import write_simulation_report, DEFAULT_REPORT_DIR

    # Validar n
    n = args.n_simulations
    if n < MIN_N_SIMULATIONS:
        return _error(
            f"--n debe ser >= {MIN_N_SIMULATIONS}; se recibió {n}."
        )

    # Cargar modelo
    model_version: str = getattr(args, "model_version", "dc-v1") or "dc-v1"
    try:
        params = load_params(DEFAULT_PARAMS_PATH, model_version=model_version)
    except NotFittedError as exc:
        return _error(
            f"no hay parámetros entrenados para {model_version} ({exc}); "
            f"ejecuta primero `train --as-of-date YYYY-MM-DD [--model-version {model_version}]` "
            f"(flujo: {_FLOW})"
        )

    # Cargar fixtures del Mundial 2026
    as_of: str | None = getattr(args, "as_of", None)
    try:
        fixtures = load_wc2026_fixtures(as_of=as_of)
    except FileNotFoundError as exc:
        return _error(
            f"no se encontraron fixtures del Mundial 2026 ({exc}); "
            "ejecuta primero `ingest-public` + `build-features`"
        )

    # Aplicar roster/multiplicadores (R9)
    roster_multipliers: dict[str, float] | None = None
    roster_path: str | None = getattr(args, "roster", None)
    if roster_path is not None:
        try:
            roster_multipliers = load_roster_multipliers(
                roster_path,
                player_factor_path=DEFAULT_PLAYER_FACTOR_PATH,
            )
            if not roster_multipliers:
                print(
                    "⚠️ Roster proporcionado pero no se encontró player_factor.csv; "
                    "simulando con modelo base (R9).",
                    file=sys.stderr,
                )
        except Exception as exc:  # noqa: BLE001 — fallo no crítico
            print(
                f"⚠️ No se pudo cargar el roster ({exc}); "
                "simulando con modelo base (R9).",
                file=sys.stderr,
            )
            roster_multipliers = None

    # Feature 16: forma_reciente — construir form_factor para simulate (R6)
    # Feature 26: --form-xg activa señal xG en simulate (R3, R4)
    sim_form_weight: float = getattr(args, "form_weight", 0.0) or 0.0
    sim_form_xg: bool = bool(getattr(args, "form_xg", False))
    sim_form_factor = _build_form_factor(sim_form_weight, as_of or params.as_of_date, use_xg=sim_form_xg)

    # Correr simulación
    seed: int = args.seed
    try:
        result = run_simulation(
            fixtures=fixtures,
            params=params,
            n=n,
            seed=seed,
            roster_multipliers=roster_multipliers,
            form_factor=sim_form_factor,
        )
    except GroupStructureError as exc:
        return _error(
            f"error en la estructura de grupos del Mundial 2026 ({exc}); "
            "verifica que el silver/bronze tenga los 72 fixtures correctos."
        )
    except ValueError as exc:
        return _error(str(exc))

    # Escribir reporte
    out_dir = Path(args.out) if args.out else DEFAULT_SIMULATE_OUT
    try:
        json_path, csv_path = write_simulation_report(result, out_dir=out_dir)
    except ValueError as exc:
        return _error(f"error al escribir el reporte ({exc})")

    # Mostrar top-N por P(título)
    top_n: int = getattr(args, "top_n", 10)
    teams_sorted = sorted(
        result.probabilities.keys(),
        key=lambda t: (-result.probabilities[t].get("champion", 0.0), t),
    )[:top_n]

    print(f"✅ Simulación Monte Carlo completada: {n} simulaciones (seed={seed})")
    print(f"✅ Modelo: {model_version}")
    if roster_multipliers:
        n_teams_with_multiplier = sum(1 for v in roster_multipliers.values() if v != 1.0)
        print(f"✅ Roster: {n_teams_with_multiplier} equipos con multiplicador de ataque (R9)")
    print(f"\n   Top-{top_n} por P(título):")
    print(f"   {'Equipo':<6}  {'P(título)':>10}  {'P(Final)':>9}  {'P(Semis)':>9}  {'P(Cuartos)':>11}  {'P(R16)':>7}")
    print(f"   {'-'*6}  {'-'*10}  {'-'*9}  {'-'*9}  {'-'*11}  {'-'*7}")
    for team in teams_sorted:
        probs = result.probabilities[team]
        print(
            f"   {team:<6}  "
            f"{100 * probs.get('champion', 0.0):>9.1f}%  "
            f"{100 * probs.get('final', 0.0):>8.1f}%  "
            f"{100 * probs.get('sf', 0.0):>8.1f}%  "
            f"{100 * probs.get('qf', 0.0):>10.1f}%  "
            f"{100 * probs.get('r16', 0.0):>6.1f}%"
        )

    print(f"\n✅ Reporte escrito en {out_dir}/")
    print(f"   {json_path}")
    print(f"   {csv_path}")
    return 0


# ---------------------------------------------------------------------------
# simulate-match (Feature 34, R7): Monte Carlo de un cruce fijo
# ---------------------------------------------------------------------------

_FIXTURE_SIM_MAP: dict[str, tuple[str, str]] = {
    "r2": ("r2_fixtures.csv", "final_sim.csv"),
    "r3p": ("r3p_fixtures.csv", "r3p_sim.csv"),
}


def _read_first_fixture(path: Path) -> tuple[str, str] | None:
    """Lee el primer cruce resuelto (home_code, away_code) de un CSV de fixtures."""
    if not path.is_file():
        return None
    with path.open(encoding="utf-8", newline="") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            home = (row.get("home_code") or "").strip()
            away = (row.get("away_code") or "").strip()
            if home and away:
                return home, away
    return None


def cmd_simulate_match(args: argparse.Namespace) -> int:
    """``simulate-match``: Monte Carlo de un cruce fijo (Final / 3er puesto) (Feature 34, R7).

    Resuelve los equipos desde ``--fixture {r2,r3p}`` (lee el CSV de knockouts) o desde
    ``--home/--away``. Aplica forma (``--gamma``) y, opcionalmente, la amortiguación
    ``--dead-rubber`` (3er puesto, R3). Persiste el resultado agregado y lo imprime.
    Exit 0 éxito, 1 error de dominio.
    """
    from .simulation.match_sim import simulate_fixture, write_sim_result
    from .simulation.montecarlo import MIN_N_SIMULATIONS
    from .models.dead_rubber import DeadRubber

    n = args.n_simulations
    if n < MIN_N_SIMULATIONS:
        return _error(f"--n debe ser >= {MIN_N_SIMULATIONS}; se recibió {n}.")

    # Cargar parámetros entrenados
    params_path = getattr(args, "params", None) or str(DEFAULT_PARAMS_PATH)
    try:
        params = load_params(params_path)
    except NotFittedError as exc:
        return _error(
            f"no hay parámetros entrenados ({exc}); ejecuta primero "
            f"`train --as-of-date YYYY-MM-DD` (flujo: {_FLOW})"
        )

    # Resolver el cruce (--fixture tiene prioridad sobre --home/--away)
    fixture: str | None = getattr(args, "fixture", None)
    default_out: Path
    if fixture:
        fx_file, out_name = _FIXTURE_SIM_MAP[fixture]
        fx_path = KO_DEFAULT_DIR / fx_file
        pair = _read_first_fixture(fx_path)
        if pair is None:
            return _error(
                f"no hay un cruce resuelto en {fx_path}; ejecuta `ingest-ko` "
                "tras las semifinales para fijar Final y 3er puesto."
            )
        home, away = pair
        default_out = DEFAULT_PREDICTIONS_DIR / out_name
    else:
        home = getattr(args, "home", None)
        away = getattr(args, "away", None)
        if not home or not away:
            return _error("indica --fixture {r2,r3p} o ambos --home y --away.")
        default_out = DEFAULT_PREDICTIONS_DIR / f"{home}_{away}_sim.csv"

    # Factor de forma (γ=0 → OFF, sin tocar disco)
    gamma: float = getattr(args, "gamma", 0.0) or 0.0
    form_xg: bool = bool(getattr(args, "form_xg", False))
    form_factor = _build_form_factor(gamma, params.as_of_date, use_xg=form_xg)

    # Amortiguación del 3er puesto (R3)
    dead = DeadRubber() if getattr(args, "dead_rubber", False) else None

    res = simulate_fixture(
        home, away, params, n=n, seed=args.seed,
        form_factor=form_factor, dead_rubber=dead,
    )

    out = Path(getattr(args, "out", None) or default_out)
    write_sim_result(res, out)

    # Salida legible
    fav, fav_p = (res.home, res.p_home) if res.p_home >= res.p_away else (res.away, res.p_away)
    mh, ma = res.modal_score
    print(f"✅ simulate-match {res.home} vs {res.away} — n={n}, seed={args.seed}"
          + ("  [dead-rubber ON]" if dead else ""))
    print(f"   P(gana {res.home}) = {100*res.p_home:.1f}%   "
          f"P(gana {res.away}) = {100*res.p_away:.1f}%   (favorito: {fav} {100*fav_p:.1f}%)")
    print(f"   Camino: 90' {100*res.p_reg:.1f}%  ·  prórroga {100*res.p_et:.1f}%  ·  penales {100*res.p_pens:.1f}%")
    print(f"   Marcador modal 90': {res.home} {mh}-{ma} {res.away}   E[goles]={res.e_goals:.2f}")
    print("   Top marcadores 90': " + "  ".join(f"{h}-{a} ({100*p:.1f}%)" for (h, a), p in res.top_scores))
    print(f"   Mercados: O1.5 {100*res.markets['over_1.5']:.0f}%  O2.5 {100*res.markets['over_2.5']:.0f}%  "
          f"O3.5 {100*res.markets['over_3.5']:.0f}%  BTTS {100*res.markets['btts']:.0f}%")
    print(f"✅ Artefacto → {out}")
    return 0


# ---------------------------------------------------------------------------
# ingest-elo (Feature 14, R8)
# ---------------------------------------------------------------------------


def cmd_ingest_elo(args: argparse.Namespace) -> int:
    """``ingest-elo [--url] [--ttl-days 7] [--fetched-date] [--out]``: ingesta Elo externo.

    Tercer subcomando con red real (eloratings.net, CC0; regla STOP de ``CLAUDE.md``).
    ``fetched_at = now(UTC)`` es la única lectura de reloj, solo para el metadato
    bronze (excepción documentada). ``fetched_date`` inyectable para tests y
    reproducibilidad; si no se proporciona se usa la fecha UTC actual.

    El transporte real se usa sin inyección (red efectiva); en tests se monkeypatchea
    ``src.cli.ingest_elo_ratings`` directamente (sin tocar la red).

    Args:
        args: Parsed CLI arguments.

    Returns:
        Exit code 0 (success) or 1 (domain error).
    """
    from datetime import datetime, timezone, date

    fetched_at = datetime.now(timezone.utc).isoformat()
    # fetched_date inyectable (para tests y reproducibilidad); default: hoy UTC
    fetched_date: str = getattr(args, "fetched_date", None) or date.today().isoformat()
    url: str = getattr(args, "url", None) or ELO_DEFAULT_URL
    ttl_days: int = getattr(args, "ttl_days", ELO_DEFAULT_TTL_DAYS)
    out_path = Path(getattr(args, "out", None) or str(ELO_DEFAULT_GOLD_PATH))
    from .ingestion.elo_ratings import DEFAULT_BRONZE_DIR

    try:
        result = ingest_elo_ratings(
            fetched_at=fetched_at,
            fetched_date=fetched_date,
            transport=None,  # red real en producción; tests monkeypatchean esta función
            url=url,
            bronze_dir=DEFAULT_BRONZE_DIR,
            gold_path=out_path,
            ttl_days=ttl_days,
        )
    except EloDownloadError as exc:
        return _error(
            f"descarga de eloratings fallida ({exc}); verifica conectividad/URL y "
            "reintenta `ingest-elo` (requiere aprobación, regla STOP de CLAUDE.md)"
        )
    except EloParseError as exc:
        return _error(
            f"el formato de eloratings.net cambió ({exc}); "
            "revisa specs/elo_externo_ensemble/design.md"
        )

    cache_msg = " (desde caché, no se re-descargó)" if result.from_cache else ""
    print(
        f"✅ Elo externo ingestado{cache_msg}: "
        f"{result.n_mapped} selecciones mapeadas, {result.n_discarded} descartadas"
    )
    print(f"✅ Bronze: {result.tsv_path} + {result.meta_path}")
    print(f"✅ Gold: {out_path}")
    return 0


# ---------------------------------------------------------------------------
# Helper de forma reciente para predict/backtest/simulate (Feature 16, R6)
# ---------------------------------------------------------------------------


def _build_form_factor(
    form_weight: float,
    as_of: str,
    use_xg: bool = False,
) -> "Callable[[str, str], tuple[float, float]] | None":
    """Construye el callable form_factor(home, away) → (mult_home, mult_away) (R4, R6).

    Con ``form_weight=0`` devuelve ``None`` (no-regresión exacta, cero overhead).
    Con ``form_weight>0`` carga silver y Elo desde disco y llama a
    ``make_form_factor_fn``; si los datos no están disponibles emite advertencia
    y devuelve ``None`` (degradación suave, no aborta, R7).

    Feature 26 (forma_xg): ``use_xg=True`` activa la señal xG en la ventana (R3).
    Default False → F16 exacto (tol 1e-9).

    Args:
        form_weight: γ ∈ [0, 1]. 0 → returns None (v1 exact).
        as_of: Cutoff date (YYYY-MM-DD) for anti-fuga (R4).
        use_xg: If True, pass use_xg=True to make_form_factor_fn (F26, R3).

    Returns:
        Callable or None.
    """
    if form_weight == 0.0:
        return None

    try:
        import pandas as _pd
        from .form import make_form_factor_fn, DEFAULT_FORM_CONFIG
        from .ingestion.teams import all_teams as _all_teams

        _silver_path = Path("data/silver/matches.csv")
        _elo_path = Path("data/gold/external_elo.csv")
        _matches_df = _pd.read_csv(_silver_path) if _silver_path.is_file() else _pd.DataFrame()
        _elo_df = _pd.read_csv(_elo_path) if _elo_path.is_file() else None
        _teams_48 = [t.code for t in _all_teams()]

        if _matches_df.empty:
            import warnings as _w
            _w.warn(
                f"--form-weight={form_weight} pero no hay silver en {_silver_path}; "
                "usando predicción v1 (form_factor=None).",
                UserWarning,
                stacklevel=3,
            )
            return None

        return make_form_factor_fn(_matches_df, as_of, _elo_df, form_weight, _teams_48, use_xg=use_xg)
    except Exception as exc:  # noqa: BLE001 — fallo no crítico
        import sys
        print(
            f"⚠️ No se pudo construir el factor de forma ({exc}); "
            "usando predicción v1.",
            file=sys.stderr,
        )
        return None


# ---------------------------------------------------------------------------
# Helper de ensemble para predict/predict-log/simulate (Feature 14, R8)
# ---------------------------------------------------------------------------


def _apply_elo_ensemble(
    prob_home: float,
    prob_draw: float,
    prob_away: float,
    home_code: str,
    away_code: str,
    elo_weight: float,
    neutral: bool = False,
) -> tuple[float, float, float]:
    """Aplica el ensemble DC + Elo con el peso dado (R8, R5).

    Con ``elo_weight=0.0`` devuelve las probabilidades originales EXACTAS (no-regresión
    v1, tol 1e-9). Con ``elo_weight>0`` usa el Elo externo (gold external_elo.csv)
    si existe; si no existe el gold, usa el rating inicial 1500 para ambos equipos
    y emite una advertencia (no aborta).

    Args:
        prob_home: DC home win probability.
        prob_draw: DC draw probability.
        prob_away: DC away win probability.
        home_code: FIFA code of home team.
        away_code: FIFA code of away team.
        elo_weight: Blend weight w ∈ [0, 1].
        neutral: True for neutral venue.

    Returns:
        Tuple (prob_home, prob_draw, prob_away) possibly blended with Elo.
    """
    if elo_weight == 0.0:
        return prob_home, prob_draw, prob_away

    from .elo_ext.model import predict_elo_live, EloModelParams
    from .elo_ext.ensemble import ensemble

    # Usar Elo externo (snapshot live, R7 — solo en predicción, nunca backtest)
    p_elo = predict_elo_live(
        home_code=home_code,
        away_code=away_code,
        neutral=neutral,
    )
    p_ens = ensemble(
        (prob_home, prob_draw, prob_away),
        p_elo,
        w=elo_weight,
    )
    return p_ens.prob_home, p_ens.prob_draw, p_ens.prob_away


# ---------------------------------------------------------------------------
# ingest-wiki-stats (Feature 15, R1, R6)
# ---------------------------------------------------------------------------


def cmd_ingest_wiki_stats(args: argparse.Namespace) -> int:
    """``ingest-wiki-stats [--matches schedule|<csv>] [--ttl-hours 24] [--out]``.

    Ingesta stats de partido desde la MediaWiki API de Wikipedia a bronze
    (Feature 15, R1, R6). Cuarto subcomando con red real — regla STOP de CLAUDE.md.
    ``fetched_at = now(UTC)`` es la única lectura de reloj, solo como metadato bronze.
    El transporte real se usa sin inyección; en tests se monkeypatchea directamente.

    Con ``--matches schedule`` (default): carga los fixtures del Mundial 2026 desde el
    bronze público y construye los slugs de Wikipedia automáticamente.
    Con ``--matches <csv>``: carga un CSV con columnas slug,match_id,home_code,away_code.

    Args:
        args: Parsed CLI arguments.

    Returns:
        Exit code 0 (success) or 1 (domain error).
    """
    fetched_at = datetime.now(timezone.utc).isoformat()
    bronze_dir = Path(args.out) if args.out else Path("data") / "bronze"
    ttl_hours: int = args.ttl_hours

    # Cargar la lista de partidos a ingestar (R6)
    matches_arg: str = args.matches

    matches: list[dict] = []
    if matches_arg == "schedule":
        # Leer fixtures pendientes del bronze público
        results_csv = DEFAULT_RESULTS_CSV
        if not results_csv.is_file():
            return _error(
                f"no existe el bronze público en {results_csv}; ejecuta primero "
                "`ingest-public` (flujo: ingest-public → build-features → train → predict)"
            )
        pending = _pending_world_cup_rows(results_csv)
        for row in pending:
            home_name = row.get("home_team", "")
            away_name = row.get("away_team", "")
            home_code = to_fifa_code(home_name) or ""
            away_code = to_fifa_code(away_name) or ""
            match_date = row.get("date", "").replace("-", "_")
            slug = f"{match_date}_{home_code}_vs_{away_code}"
            matches.append({
                "slug": slug,
                "match_id": f"{row.get('date', '')}_{home_code}_{away_code}",
                "home_code": home_code,
                "away_code": away_code,
            })
    else:
        # CSV inyectado por el usuario: slug,match_id,home_code,away_code
        csv_path = Path(matches_arg)
        if not csv_path.is_file():
            return _error(
                f"no existe el CSV de partidos en {csv_path}; "
                "usa --matches schedule o provee una ruta válida"
            )
        with csv_path.open(encoding="utf-8", newline="") as fh:
            for row in csv.DictReader(fh):
                slug = (row.get("slug") or "").strip()
                if slug:
                    matches.append({
                        "slug": slug,
                        "match_id": (row.get("match_id") or "").strip() or None,
                        "home_code": (row.get("home_code") or "").strip() or None,
                        "away_code": (row.get("away_code") or "").strip() or None,
                    })

    if not matches:
        print("✅ No hay partidos para ingestar.")
        return 0

    try:
        results = ingest_wiki_stats(
            matches=matches,
            fetched_at=fetched_at,
            transport=None,  # red real en producción; tests monkeypatchean
            bronze_dir=bronze_dir,
            ttl_hours=ttl_hours,
        )
    except WikiFetchError as exc:
        return _error(
            f"error al obtener stats de Wikipedia ({exc}); "
            "verifica conectividad y reintenta `ingest-wiki-stats`"
        )

    n_ok = sum(1 for r in results if r.has_stats)
    n_cache = sum(1 for r in results if r.from_cache)
    n_no_stats = sum(1 for r in results if not r.has_stats)
    coverage_pct = 100.0 * n_ok / len(results) if results else 0.0

    print(
        f"✅ ingest-wiki-stats: {len(results)} artículos procesados "
        f"({n_ok} con stats, {n_no_stats} sin stats, {n_cache} desde caché)"
    )
    print(f"✅ Cobertura: {coverage_pct:.1f}%")
    print(f"✅ Bronze: {bronze_dir / 'wikipedia'}/")
    return 0


# ---------------------------------------------------------------------------
# ingest-roster (Feature 21, R4)
# ---------------------------------------------------------------------------


def cmd_ingest_roster(args: argparse.Namespace) -> int:
    """``ingest-roster [--league-id 77] [--ttl-hours] [--out]``: ingesta roster fotmob.

    Quinto subcomando con red real (fotmob.com, público; regla STOP de CLAUDE.md).
    ``fetched_at = now(UTC)`` es la única lectura de reloj, solo para el metadato
    bronze (excepción documentada). El transporte real se usa sin inyección; en
    tests se monkeypatchea ``src.cli.ingest_roster`` directamente.
    """
    fetched_at = datetime.now(timezone.utc).isoformat()
    league_id: int = getattr(args, "league_id", 77) or 77
    out_dir = Path(getattr(args, "out", None) or "data/bronze/rosters")

    try:
        raw_lineups, coverage = ingest_roster(
            fetched_at=fetched_at,
            league_id=league_id,
            transport=None,  # red real; tests monkeypatchean ingest_roster
            bronze_dir=out_dir,
        )
    except Exception as exc:  # noqa: BLE001
        return _error(
            f"ingest-roster falló ({exc}); verifica conectividad con fotmob.com "
            "y reintenta (regla STOP de CLAUDE.md)"
        )

    print(
        f"✅ ingest-roster: {coverage.n_matches} partidos procesados, "
        f"{coverage.n_with_lineup} con lineup"
    )
    print(
        f"✅ Equipos: {coverage.n_teams_mapped} mapeados a FIFA, "
        f"{coverage.n_teams_discarded} descartados"
    )
    print(f"✅ Rosters: {ROSTER_DEFAULT_ROSTERS_CSV}")
    print(f"✅ Bajas: {ROSTER_DEFAULT_UNAVAILABLE_CSV}")
    return 0


# ---------------------------------------------------------------------------
# ingest-fotmob-stats (Feature 23, R4)
# ---------------------------------------------------------------------------


def cmd_ingest_fotmob_stats(args: argparse.Namespace) -> int:
    """``ingest-fotmob-stats [--league-id 77] [--out DIR]``: ingesta stats por partido fotmob.

    Sexto subcomando con red real (fotmob.com, público; regla STOP de CLAUDE.md).
    ``fetched_at = now(UTC)`` es la única lectura de reloj, solo para el metadato
    bronze (excepción documentada). El transporte real se usa sin inyección; en
    tests se monkeypatchea ``src.cli.ingest_fotmob_stats`` directamente.

    Persiste bronze ``data/bronze/fotmob_stats/<slug>.json`` + meta por partido.
    Informa cobertura (partidos con stats / equipos mapeados).

    Args:
        args: Parsed CLI arguments.

    Returns:
        Exit code 0 (success) or 1 (error).
    """
    fetched_at = datetime.now(timezone.utc).isoformat()
    league_id: int = getattr(args, "league_id", 77) or 77
    out_dir = Path(getattr(args, "out", None) or str(FOTMOB_STATS_DEFAULT_BRONZE_DIR))

    try:
        raw_list, coverage = ingest_fotmob_stats(
            fetched_at=fetched_at,
            league_id=league_id,
            transport=None,  # red real en producción; tests monkeypatchean ingest_fotmob_stats
            bronze_dir=out_dir,
        )
    except Exception as exc:  # noqa: BLE001
        return _error(
            f"ingest-fotmob-stats falló ({exc}); verifica conectividad con fotmob.com "
            "y reintenta (regla STOP de CLAUDE.md)"
        )

    print(
        f"✅ ingest-fotmob-stats: {coverage.n_matches} partidos procesados, "
        f"{coverage.n_with_stats} con stats"
    )
    print(
        f"✅ Equipos: {coverage.n_teams_mapped} mapeados a FIFA, "
        f"{coverage.n_teams_discarded} descartados"
    )
    print(f"✅ Bronze: {out_dir}/")
    return 0


# ---------------------------------------------------------------------------
# ingest-ko / build-ko-fixtures (Feature 27, R1/R3/R6)
# ---------------------------------------------------------------------------


def cmd_ingest_ko(args: argparse.Namespace) -> int:
    """``ingest-ko [--league-id 77] [--out DIR] [--knockouts-dir DIR]``.

    Séptimo subcomando con red real (fotmob.com; regla STOP de CLAUDE.md): descarga el
    bracket del playoff, escribe ``r16_fixtures.csv``/``r8_fixtures.csv`` y persiste
    marcador + stats de los partidos KO jugados en el bronze de fotmob_stats. En tests se
    monkeypatchea ``src.cli.ingest_ko``.
    """
    import time  # noqa: PLC0415

    fetched_at = datetime.now(timezone.utc).isoformat()
    league_id: int = getattr(args, "league_id", 77) or 77
    out_dir = Path(getattr(args, "out", None) or str(FOTMOB_STATS_DEFAULT_BRONZE_DIR))
    ko_dir = Path(getattr(args, "knockouts_dir", None) or str(KO_DEFAULT_DIR))

    try:
        result = ingest_ko(
            fetched_at=fetched_at,
            league_id=league_id,
            transport=None,  # red real; tests monkeypatchean ingest_ko
            bronze_dir=out_dir,
            knockouts_dir=ko_dir,
            sleeper=time.sleep,
        )
    except Exception as exc:  # noqa: BLE001
        return _error(
            f"ingest-ko falló ({exc}); verifica conectividad con fotmob.com "
            "y reintenta (regla STOP de CLAUDE.md)"
        )

    print(
        f"✅ ingest-ko: bracket con {result.n_matches_bracket} partidos, "
        f"{result.n_finished} jugados, {result.n_persisted} persistidos con marcador"
    )
    for stage, path in result.fixtures_written.items():
        print(f"✅ Fixtures {stage}: {path}")
    print(f"✅ Bronze: {out_dir}/")
    return 0


def cmd_build_ko_fixtures(args: argparse.Namespace) -> int:
    """``build-ko-fixtures [--league-id 77] [--knockouts-dir DIR]``.

    Sólo escribe los CSV de fixtures (octavos/cuartos) desde el bracket, sin persistir
    stats. Red real (regla STOP). En tests se monkeypatchea ``src.cli.fetch_bracket``.
    """
    from .ingestion.fotmob_stats import _default_transport  # noqa: PLC0415

    league_id: int = getattr(args, "league_id", 77) or 77
    ko_dir = Path(getattr(args, "knockouts_dir", None) or str(KO_DEFAULT_DIR))
    try:
        bracket = fetch_bracket(_default_transport(), league_id=league_id)
        written = write_ko_fixtures(bracket, ko_dir)
    except Exception as exc:  # noqa: BLE001
        return _error(f"build-ko-fixtures falló ({exc}); verifica conectividad (STOP)")

    for stage, path in written.items():
        print(f"✅ Fixtures {stage}: {path}")
    return 0


# ---------------------------------------------------------------------------
# ingest-lineups / build-lineup-strength (Feature 28, R5)
# ---------------------------------------------------------------------------


def cmd_ingest_lineups(args: argparse.Namespace) -> int:
    """``ingest-lineups [--league-id 77] [--out DIR]``: scrape XI + ratings desde fotmob.

    Red real (regla STOP). En tests se monkeypatchea ``src.cli.ingest_lineups``.
    """
    import time  # noqa: PLC0415

    fetched_at = datetime.now(timezone.utc).isoformat()
    league_id: int = getattr(args, "league_id", 77) or 77
    out_dir = Path(getattr(args, "out", None) or str(LINEUP_DEFAULT_BRONZE_DIR))
    try:
        result = ingest_lineups(
            fetched_at=fetched_at, league_id=league_id, transport=None,
            bronze_dir=out_dir, sleeper=time.sleep,
        )
    except Exception as exc:  # noqa: BLE001
        return _error(f"ingest-lineups falló ({exc}); verifica conectividad (STOP)")
    print(f"✅ ingest-lineups: {result.n_matches} partidos, {result.n_with_lineup} con XI")
    print(f"✅ Bronze: {out_dir}/")
    return 0


def cmd_build_lineup_strength(args: argparse.Namespace) -> int:
    """``build-lineup-strength [--bronze-dir DIR] [--gold-dir DIR]``: deriva fuerza-XI (offline)."""
    bronze_dir = Path(getattr(args, "bronze_dir", None) or "data/bronze")
    gold_dir = Path(getattr(args, "gold_dir", None) or "data/gold")
    df = build_lineup_strength(bronze_dir)
    path = write_lineup_strength(df, gold_dir)
    print(f"✅ build-lineup-strength: {len(df)} filas (equipo,partido) → {path}")
    return 0


# ---------------------------------------------------------------------------
# corners (Feature 24, R4)
# ---------------------------------------------------------------------------


def cmd_corners(args: argparse.Namespace) -> int:
    """``corners HOME AWAY [--as-of FECHA] [--lines L1,...] [--silver PATH] [--json]``.

    Mercado de corners O/U con modelo de tasa Poisson y shrinkage bayesiano
    (Feature 24, R4). 100% offline: no requiere modelo entrenado ni red.
    Lee el silver (home/away_corners, date < as_of) para estimar tasas por equipo
    con shrinkage k hacia la media global. La salida incluye un aviso honesto
    sobre la muestra (n partidos; muestra chica => prior global, R6).

    Args:
        args: Parsed CLI arguments.

    Returns:
        Exit code 0 (success) or 1 (domain error).
    """
    import pandas as _pd

    from .markets.corners import CornersConfig, corners_summary

    try:
        home = _validate_team_code(args.home)
        away = _validate_team_code(args.away)
    except ValueError as exc:
        return _error(str(exc))
    if home == away:
        return _error(
            f"HOME_CODE y AWAY_CODE deben ser selecciones distintas; se recibio "
            f"{home!r} dos veces"
        )

    silver_path = Path(args.silver) if args.silver else DEFAULT_BACKTEST_SILVER
    if not silver_path.is_file():
        return _error(
            f"no existe el silver en {silver_path}; ejecuta primero "
            "`build-features --as-of-date YYYY-MM-DD`"
        )

    try:
        matches = _pd.read_csv(silver_path)
    except Exception as exc:  # noqa: BLE001
        return _error(f"no se pudo leer el silver ({exc})")

    # as_of: inyectado o sentinel para "usar todos los datos disponibles"
    as_of: str = args.as_of if args.as_of else "2099-12-31"

    # Lineas O/U: custom o default del modelo (8.5, 9.5, 10.5, 11.5)
    lines_arg = args.lines
    default_lines: tuple[float, ...] = tuple(lines_arg) if lines_arg is not None else (8.5, 9.5, 10.5, 11.5)

    config = CornersConfig(k=5, default_lines=default_lines)

    try:
        summary = corners_summary(matches, home, away, as_of, config)
    except Exception as exc:  # noqa: BLE001
        return _error(f"error calculando corners ({exc})")

    names = {team.code: team.name for team in all_teams()}

    aviso = (
        f"base = {summary.n_matches_home} partidos {home} / "
        f"{summary.n_matches_away} partidos {away}; "
        f"shrinkage k={summary.k} (muestra chica -> prior global "
        f"mu={summary.mu_global:.1f} corneres/equipo)"
    )

    if args.json:
        doc = {
            "home": {"code": home, "name": names[home]},
            "away": {"code": away, "name": names[away]},
            "as_of": as_of,
            "mu_global": summary.mu_global,
            "lambda_home": summary.lambda_home,
            "lambda_away": summary.lambda_away,
            "lambda_total": summary.lambda_total,
            "n_matches_home": summary.n_matches_home,
            "n_matches_away": summary.n_matches_away,
            "k": summary.k,
            "aviso": aviso,
            "total_ou": [
                {"line": ou.line, "over": ou.over, "under": ou.under}
                for ou in summary.total_ou
            ],
            "home_ou": [
                {"line": ou.line, "over": ou.over, "under": ou.under}
                for ou in summary.home_ou
            ],
            "away_ou": [
                {"line": ou.line, "over": ou.over, "under": ou.under}
                for ou in summary.away_ou
            ],
        }
        print(json.dumps(doc, ensure_ascii=False))
        return 0

    print(f"✅ Corners (O/U): {names[home]} ({home}) vs {names[away]} ({away})")
    print(f"✅ {aviso}")
    print(
        f"✅ Corneres esperados: lambda_home={summary.lambda_home:.2f}, "
        f"lambda_away={summary.lambda_away:.2f}, lambda_total={summary.lambda_total:.2f}"
    )
    print("✅ Over/Under (corneres totales):")
    for ou in summary.total_ou:
        print(
            f"   O{ou.line:.1f}: over {100 * ou.over:.1f}%  |  "
            f"under {100 * ou.under:.1f}%"
        )
    print(f"✅ Corneres {names[home]} ({home}):")
    for ou in summary.home_ou:
        print(
            f"   O{ou.line:.1f}: over {100 * ou.over:.1f}%  |  "
            f"under {100 * ou.under:.1f}%"
        )
    print(f"✅ Corneres {names[away]} ({away}):")
    for ou in summary.away_ou:
        print(
            f"   O{ou.line:.1f}: over {100 * ou.over:.1f}%  |  "
            f"under {100 * ou.under:.1f}%"
        )
    return 0


# ---------------------------------------------------------------------------
# count-market (Feature 25, R3)
# ---------------------------------------------------------------------------


def cmd_count_market(args: argparse.Namespace) -> int:
    """``count-market HOME AWAY --stat {cards,shots,sot} [--as-of FECHA] [--lines] [--silver] [--json]``.

    Mercado de conteo O/U (tarjetas/tiros/SoT) con modelo de tasa Poisson y
    shrinkage bayesiano (Feature 25, R3). 100 % offline: no requiere modelo
    entrenado ni red. Lee el silver (home/away_{stat}, date < as_of) para
    estimar tasas por equipo con shrinkage k hacia la media global. La salida
    incluye un aviso honesto sobre la muestra y, para tarjetas, sobre el ruido
    introducido por la no-disponibilidad de datos de arbitro (R4 de F25).

    --stat invalido es rechazado por argparse con exit code 2 (error de uso).

    Args:
        args: Parsed CLI arguments.

    Returns:
        Exit code 0 (success) or 1 (domain error).
    """
    import pandas as _pd

    from .markets.counts import STAT_SPECS, CountConfig, count_summary

    try:
        home = _validate_team_code(args.home)
        away = _validate_team_code(args.away)
    except ValueError as exc:
        return _error(str(exc))
    if home == away:
        return _error(
            f"HOME_CODE y AWAY_CODE deben ser selecciones distintas; se recibio "
            f"{home!r} dos veces"
        )

    stat: str = args.stat
    if stat not in STAT_SPECS:
        # Defensa adicional (argparse con choices ya lo captura antes)
        valid = ", ".join(sorted(STAT_SPECS))
        return _error(f"--stat {stat!r} no reconocido; valores validos: {valid}")

    silver_path = Path(args.silver) if args.silver else DEFAULT_BACKTEST_SILVER
    if not silver_path.is_file():
        return _error(
            f"no existe el silver en {silver_path}; ejecuta primero "
            "`build-features --as-of-date YYYY-MM-DD`"
        )

    try:
        matches = _pd.read_csv(silver_path)
    except Exception as exc:  # noqa: BLE001
        return _error(f"no se pudo leer el silver ({exc})")

    # as_of: inyectado o sentinel para "usar todos los datos disponibles"
    as_of: str = args.as_of if args.as_of else "2099-12-31"

    # Lineas O/U: custom o default del modelo para esta stat
    spec = STAT_SPECS[stat]
    lines_arg = args.lines
    default_lines: tuple[float, ...] = (
        tuple(lines_arg) if lines_arg is not None else spec.lines_default
    )

    config = CountConfig(k=5, lines=default_lines)

    try:
        summary = count_summary(matches, home, away, as_of, stat, config)
    except Exception as exc:  # noqa: BLE001
        return _error(f"error calculando {spec.label} ({exc})")

    names = {team.code: team.name for team in all_teams()}

    aviso = (
        f"base = {summary.n_matches_home} partidos {home} / "
        f"{summary.n_matches_away} partidos {away}; "
        f"shrinkage k={summary.k} (muestra chica -> prior global "
        f"mu={summary.mu_global:.1f} {spec.label.lower()}/equipo)"
    )

    if args.json:
        doc = {
            "home": {"code": home, "name": names[home]},
            "away": {"code": away, "name": names[away]},
            "stat": stat,
            "label": spec.label,
            "noisy_note": spec.noisy_note,
            "as_of": as_of,
            "mu_global": summary.mu_global,
            "lambda_home": summary.lambda_home,
            "lambda_away": summary.lambda_away,
            "lambda_total": summary.lambda_total,
            "n_matches_home": summary.n_matches_home,
            "n_matches_away": summary.n_matches_away,
            "k": summary.k,
            "aviso": aviso,
            "total_ou": [
                {"line": ou.line, "over": ou.over, "under": ou.under}
                for ou in summary.total_ou
            ],
            "home_ou": [
                {"line": ou.line, "over": ou.over, "under": ou.under}
                for ou in summary.home_ou
            ],
            "away_ou": [
                {"line": ou.line, "over": ou.over, "under": ou.under}
                for ou in summary.away_ou
            ],
        }
        print(json.dumps(doc, ensure_ascii=False))
        return 0

    print(f"✅ {spec.label} (O/U): {names[home]} ({home}) vs {names[away]} ({away})")
    if spec.noisy_note:
        print(f"⚠️  {spec.noisy_note}")
    print(f"✅ {aviso}")
    print(
        f"✅ {spec.label} esperadas: lambda_home={summary.lambda_home:.2f}, "
        f"lambda_away={summary.lambda_away:.2f}, lambda_total={summary.lambda_total:.2f}"
    )
    print(f"✅ Over/Under ({spec.label.lower()} totales):")
    for ou in summary.total_ou:
        print(
            f"   O{ou.line:.1f}: over {100 * ou.over:.1f}%  |  "
            f"under {100 * ou.under:.1f}%"
        )
    print(f"✅ {spec.label} {names[home]} ({home}):")
    for ou in summary.home_ou:
        print(
            f"   O{ou.line:.1f}: over {100 * ou.over:.1f}%  |  "
            f"under {100 * ou.under:.1f}%"
        )
    print(f"✅ {spec.label} {names[away]} ({away}):")
    for ou in summary.away_ou:
        print(
            f"   O{ou.line:.1f}: over {100 * ou.over:.1f}%  |  "
            f"under {100 * ou.under:.1f}%"
        )
    return 0


# ---------------------------------------------------------------------------
# Parser y punto de entrada (R1)
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    """Parser con EXACTAMENTE 18 subcomandos, cada uno con su función propia (R1, R7, R10, R12, R13, R8 f14, R6 f15, R4 f21, R4 f23, R4 f24, R3 f25)."""
    parser = argparse.ArgumentParser(
        prog="python -m src.cli",
        description=(
            "CLI del pipeline del Mundial 2026: "
            "ingest-public → build-features → train → predict (+ schedule, markets, "
            "backtest, predict-log, evaluate, ingest-goalscorers, scorers, simulate, "
            "ingest-elo, ingest-wiki-stats, ingest-roster, ingest-fotmob-stats, corners, "
            "count-market)."
        ),
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser(
        "ingest-public",
        help="Descarga la fuente pública a bronze (ÚNICO subcomando con red real).",
    )
    p.add_argument(
        "--from-date",
        default=None,
        help="YYYY-MM-DD; recorta solo la vista informativa de consumo (R2).",
    )
    p.set_defaults(func=cmd_ingest_public)

    p = sub.add_parser(
        "build-features", help="Construye silver y gold (offline) vía build_all."
    )
    p.add_argument(
        "--as-of-date",
        required=True,
        help="YYYY-MM-DD inyectada (obligatoria; sin reloj implícito, R3).",
    )
    p.set_defaults(func=cmd_build_features)

    p = sub.add_parser(
        "train", help="Ajusta el modelo Dixon-Coles desde silver y persiste el JSON."
    )
    p.add_argument(
        "--as-of-date", required=True, help="YYYY-MM-DD inyectada (anti-leakage, R4)."
    )
    p.add_argument(
        "--from-date",
        default=None,
        help="YYYY-MM-DD; si se omite rige el default de DCConfig (feature 3).",
    )
    p.add_argument(
        "--xi",
        type=float,
        default=None,
        help="Decaimiento temporal/año; si se omite rige el default de DCConfig.",
    )
    p.add_argument(
        "--model-version",
        default="dc-v1",
        choices=("dc-v1", "dc-v2"),
        dest="model_version",
        help=(
            "Versión del modelo a persistir: 'dc-v1' (default, sin importancia) o "
            "'dc-v2' (con importancia, escribe dixon_coles_params_v2.json) (R6 feature 12)."
        ),
    )
    p.add_argument(
        "--importance",
        default="off",
        choices=("off", "default"),
        dest="importance",
        help=(
            "'off' (default, identidad = comportamiento v1) o "
            "'default' (mapa de importancia v2 desde importance.py) (R6 feature 12)."
        ),
    )
    p.add_argument(
        "--xg-weight",
        type=float,
        default=0.0,
        dest="xg_weight",
        metavar="V",
        help=(
            "Peso del proxy xG en la serie objetivo (0.0–1.0; default 0.0 = goles reales). "
            "v=0 reproduce v1 EXACTAMENTE (R4 feature 15). Requiere bronze Wikipedia."
        ),
    )
    p.set_defaults(func=cmd_train)

    p = sub.add_parser(
        "predict",
        help="Predice un partido del Mundial 2026 (1X2 + lambdas + top-k) sin reentrenar.",
    )
    p.add_argument("home", metavar="HOME_CODE", help="Código FIFA del local (3 letras).")
    p.add_argument("away", metavar="AWAY_CODE", help="Código FIFA del visitante (3 letras).")
    p.add_argument("--top-k", type=int, default=5, help="Marcadores a mostrar (default 5).")
    p.add_argument(
        "--max-goals", type=int, default=10, help="Soporte de goles de la matriz (default 10)."
    )
    p.add_argument(
        "--params",
        default=str(DEFAULT_PARAMS_PATH),
        help="Ruta del JSON de parámetros entrenados (R5).",
    )
    p.add_argument(
        "--features",
        default=str(DEFAULT_FEATURES_CSV),
        help="Ruta del gold team_features.csv para el contexto opcional (R8).",
    )
    p.add_argument(
        "--json",
        action="store_true",
        help="Salida machine-readable: un único documento JSON en stdout (R9).",
    )
    p.add_argument(
        "--model-version",
        default="dc-v1",
        choices=("dc-v1", "dc-v2"),
        dest="model_version",
        help=(
            "Versión del modelo: 'dc-v1' (default) o 'dc-v2' "
            "(carga dixon_coles_params_v2.json) (R6 feature 12)."
        ),
    )
    p.add_argument(
        "--elo-weight",
        type=float,
        default=0.0,
        dest="elo_weight",
        metavar="W",
        help=(
            "Peso del sub-modelo Elo en el ensemble (0.0–1.0; default 0.0 = DC puro). "
            "w=0 reproduce v1 EXACTAMENTE (R5 feature 14)."
        ),
    )
    p.add_argument(
        "--form-weight",
        type=float,
        default=0.0,
        dest="form_weight",
        metavar="G",
        help=(
            "Peso γ del factor de forma reciente (0.0–1.0; default 0.0 = OFF). "
            "γ=0 reproduce v1 EXACTAMENTE sin reentrenar (R4 feature 16)."
        ),
    )
    p.add_argument(
        "--form-xg",
        action="store_true",
        default=False,
        dest="form_xg",
        help=(
            "Activa señal xG en la ventana de forma (Feature 26, R3). "
            "Requiere silver con columnas home_xg/away_xg (F23). "
            "Default OFF → equivalencia exacta F16 (tol 1e-9)."
        ),
    )
    p.set_defaults(func=cmd_predict)

    p = sub.add_parser(
        "schedule", help="Lista los partidos del Mundial 2026 aún no jugados (bronze)."
    )
    p.add_argument(
        "--limit",
        type=int,
        default=DEFAULT_SCHEDULE_LIMIT,
        help=f"Máximo de partidos a mostrar (default {DEFAULT_SCHEDULE_LIMIT}).",
    )
    p.add_argument(
        "--results-csv",
        default=str(DEFAULT_RESULTS_CSV),
        help="Ruta del CSV crudo bronze de la feature 7 (R10).",
    )
    p.set_defaults(func=cmd_schedule)

    p = sub.add_parser(
        "markets",
        help=(
            "Calcula mercados de goles (over/under, BTTS, totales) para un partido "
            "(Feature 4, R7)."
        ),
    )
    p.add_argument("home", metavar="HOME_CODE", help="Código FIFA del local (3 letras).")
    p.add_argument("away", metavar="AWAY_CODE", help="Código FIFA del visitante (3 letras).")
    p.add_argument(
        "--params",
        default=str(DEFAULT_PARAMS_PATH),
        help="Ruta del JSON de parámetros entrenados.",
    )
    p.add_argument(
        "--json",
        action="store_true",
        help="Salida machine-readable: un único documento JSON en stdout.",
    )
    p.add_argument(
        "--by-half",
        action="store_true",
        dest="by_half",
        help=(
            "Añade mercados por mitad (O/U 1T/2T, marca en 2T, gol 76-90) repartiendo "
            "el λ del modelo. Sin este flag la salida es idéntica a la previa (Feature 32)."
        ),
    )
    p.add_argument(
        "--lines",
        dest="total_lines",
        default=None,
        type=_parse_lines_arg,
        metavar="L1,L2,...",
        help=(
            "Líneas k+0.5 para el mercado de totales (CSV). "
            f"Default: {','.join(str(l) for l in DEFAULT_TOTAL_LINES)}."
        ),
    )
    p.add_argument(
        "--model-version",
        default="dc-v1",
        choices=("dc-v1", "dc-v2"),
        dest="model_version",
        help=(
            "Versión del modelo: 'dc-v1' (default) o 'dc-v2' "
            "(carga dixon_coles_params_v2.json) (R6 feature 12)."
        ),
    )
    p.set_defaults(func=cmd_markets)

    p = sub.add_parser(
        "backtest",
        help=(
            "Backtest walk-forward del modelo Dixon-Coles sobre el silver histórico "
            "(Feature 5, R10)."
        ),
    )
    p.add_argument(
        "--from-date",
        default=None,
        help="YYYY-MM-DD; inicio del rango de evaluación (default: 2024-01-01).",
    )
    p.add_argument(
        "--to-date",
        default=None,
        help="YYYY-MM-DD; fin del rango de evaluación (default: máxima fecha del dataset).",
    )
    p.add_argument(
        "--refit-every",
        default="month",
        choices=("month", "week"),
        help="Frecuencia de refit: 'month' (default) o 'week'.",
    )
    p.add_argument(
        "--grid",
        action="store_true",
        default=False,
        help="Activa la búsqueda de hiperparámetros (ξ × reg_lambda); coste alto (R7).",
    )
    p.add_argument(
        "--odds",
        default=None,
        metavar="RUTA",
        help=(
            "Ruta al CSV de cuotas del usuario "
            "(esquema: date,home_code,away_code,odds_home,odds_draw,odds_away; R8)."
        ),
    )
    p.add_argument(
        "--out",
        default=None,
        metavar="DIR",
        help=f"Directorio de salida del reporte (default: {DEFAULT_BACKTEST_OUT}).",
    )
    p.add_argument(
        "--importance-scales",
        default=None,
        dest="importance_scales",
        metavar="S1,S2,...",
        help=(
            "Escalas de importancia para el grid v2 (CSV de floats, ej. '0.5,1.0,1.5'). "
            "Solo activo con --grid. Requiere columna 'tournament' en el silver (R4 feature 12)."
        ),
    )
    p.add_argument(
        "--xg-weight",
        type=float,
        default=0.0,
        dest="xg_weight",
        metavar="V",
        help=(
            "Peso del proxy xG en la serie objetivo del backtest (0.0–1.0; default 0.0). "
            "v=0 comportamiento idéntico a v1 (R4 feature 15). Requiere bronze Wikipedia."
        ),
    )
    p.add_argument(
        "--form-weight",
        type=float,
        default=0.0,
        dest="form_weight",
        metavar="G",
        help=(
            "Peso γ del factor de forma reciente aplicado en cada ventana del backtest "
            "(0.0–1.0; default 0.0 = OFF). γ=0 reproduce v1 EXACTAMENTE (R5 feature 16)."
        ),
    )
    p.add_argument(
        "--form-xg",
        action="store_true",
        default=False,
        dest="form_xg",
        help=(
            "Activa señal xG en la ventana de forma para el backtest (Feature 26, R3). "
            "Default OFF → equivalencia exacta F16 (tol 1e-9)."
        ),
    )
    p.set_defaults(func=cmd_backtest)

    # -----------------------------------------------------------------------
    # predict-log (Feature 10, R12)
    # -----------------------------------------------------------------------
    p = sub.add_parser(
        "predict-log",
        help=(
            "Genera y persiste predicciones en data/predictions/log.csv "
            "(Feature 10, R12)."
        ),
    )
    p.add_argument(
        "--as-of",
        required=True,
        dest="as_of",
        help="YYYY-MM-DD; fecha de corte del entrenamiento (anti-fuga, R3).",
    )
    p.add_argument(
        "--timestamp",
        required=True,
        help="ISO-8601; created_at inyectado para todas las filas (NUNCA reloj, R2).",
    )
    p.add_argument(
        "--markets",
        action="store_true",
        default=False,
        help="Calcula y registra p_over25 y p_btts (R1).",
    )
    p.add_argument(
        "--targets",
        default="schedule",
        metavar="schedule|<ruta_csv>",
        help=(
            "'schedule': fixtures WC2026 pendientes del bronze (default); "
            "o ruta a un CSV de fixtures con columnas date,match_id,home_code,away_code."
        ),
    )
    p.add_argument(
        "--results-csv",
        default=str(DEFAULT_RESULTS_CSV),
        help="Bronze público (para --targets schedule). Default: data/bronze/public_results/results.csv.",
    )
    p.add_argument(
        "--silver",
        default=None,
        help="Ruta al silver matches.csv (default: data/silver/matches.csv).",
    )
    p.add_argument(
        "--out",
        default=None,
        help=f"Ruta del log CSV de salida (default: {DEFAULT_LOG_PATH}).",
    )
    p.add_argument(
        "--model-version",
        default="dc-v1",
        choices=("dc-v1", "dc-v2"),
        dest="model_version",
        help=(
            "Versión del modelo a registrar en el log: 'dc-v1' (default) o 'dc-v2' "
            "(refit intra-torneo con importancia, R5 feature 12)."
        ),
    )
    p.add_argument(
        "--importance",
        default="off",
        choices=("off", "default"),
        dest="importance",
        help=(
            "'off' (default = v1) o 'default' (mapa importancia v2) "
            "(R5 feature 12)."
        ),
    )
    p.add_argument(
        "--elo-weight",
        type=float,
        default=0.0,
        dest="elo_weight",
        metavar="W",
        help=(
            "Peso del sub-modelo Elo en el ensemble (0.0–1.0; default 0.0 = DC puro). "
            "w=0 no cambia comportamiento (R5 feature 14)."
        ),
    )
    p.set_defaults(func=cmd_predict_log)

    # -----------------------------------------------------------------------
    # evaluate (Feature 10, R13)
    # -----------------------------------------------------------------------
    p = sub.add_parser(
        "evaluate",
        help=(
            "Evalúa predicciones vs resultados reales y escribe el reporte "
            "(Feature 10, R13)."
        ),
    )
    p.add_argument(
        "--from",
        default=None,
        dest="from_date",
        metavar="FECHA",
        help="YYYY-MM-DD; límite inferior inclusivo sobre match_date.",
    )
    p.add_argument(
        "--to",
        default=None,
        dest="to_date",
        metavar="FECHA",
        help="YYYY-MM-DD; límite superior inclusivo sobre match_date.",
    )
    p.add_argument(
        "--markets",
        action="store_true",
        default=False,
        help="Calcula Brier de O/U 2.5 y BTTS (R9).",
    )
    p.add_argument(
        "--log",
        default=None,
        help=f"Ruta del log de predicciones (default: {DEFAULT_LOG_PATH}).",
    )
    p.add_argument(
        "--silver",
        default=None,
        help="Ruta del silver matches.csv (default: data/silver/matches.csv).",
    )
    p.add_argument(
        "--out",
        default=None,
        help=f"Directorio de salida del reporte (default: {DEFAULT_EVAL_OUT}).",
    )
    p.add_argument(
        "--model-version",
        default=None,
        dest="model_version",
        metavar="{dc-v1,dc-v2}",
        help=(
            "Filtra el log por esta versión del modelo (R7 feature 12). "
            "Omitir → evalúa todas las versiones. "
            "Usar 'dc-v1' o 'dc-v2' para comparar versiones sobre los mismos partidos."
        ),
    )
    p.set_defaults(func=cmd_evaluate)

    # -----------------------------------------------------------------------
    # ingest-goalscorers (Feature 11, R1, R7)
    # -----------------------------------------------------------------------
    p = sub.add_parser(
        "ingest-goalscorers",
        help=(
            "Descarga la fuente CC0 de goleadores a bronze (Feature 11, R1). "
            "Segundo subcomando con red real — regla STOP."
        ),
    )
    p.set_defaults(func=cmd_ingest_goalscorers)

    # -----------------------------------------------------------------------
    # scorers (Feature 11, R4, R5, R7)
    # -----------------------------------------------------------------------
    p = sub.add_parser(
        "scorers",
        help=(
            "Probabilidades anytime-scorer por partido usando Dixon-Coles + "
            "cuotas históricas de goleadores (Feature 11, R4, R5, R7)."
        ),
    )
    p.add_argument("--home", required=True, metavar="COD", help="Código FIFA del local (3 letras).")
    p.add_argument("--away", required=True, metavar="COD", help="Código FIFA del visitante (3 letras).")
    p.add_argument(
        "--as-of",
        default=None,
        dest="as_of",
        metavar="FECHA",
        help="YYYY-MM-DD; fecha de corte del factor (default: as_of_date del modelo).",
    )
    p.add_argument(
        "--top-k",
        type=int,
        default=5,
        dest="top_k",
        help="Jugadores a mostrar por equipo (default: 5).",
    )
    p.add_argument(
        "--roster",
        default=None,
        metavar="CSV",
        help="CSV con columnas team_code,scorer de jugadores disponibles (R5).",
    )
    p.add_argument(
        "--params",
        default=str(DEFAULT_PARAMS_PATH),
        help="Ruta del JSON de parámetros entrenados (R7).",
    )
    p.add_argument(
        "--player-factor",
        default=str(DEFAULT_PLAYER_FACTOR_PATH),
        dest="player_factor",
        help=f"Ruta del gold player_factor.csv (default: {DEFAULT_PLAYER_FACTOR_PATH}).",
    )
    p.set_defaults(func=cmd_scorers)

    # -----------------------------------------------------------------------
    # simulate (Feature 13, R8, R9)
    # -----------------------------------------------------------------------
    p = sub.add_parser(
        "simulate",
        help=(
            "Simulación Monte Carlo del Mundial 2026 completo: P(título), P(Final), "
            "P(Semis), P(Cuartos), P(R16), P(avanzar de grupo) por selección (Feature 13, R8)."
        ),
    )
    p.add_argument(
        "--n",
        type=int,
        default=10_000,
        dest="n_simulations",
        help="Número de simulaciones Monte Carlo (default 10000, mínimo 1000, R6).",
    )
    p.add_argument(
        "--seed",
        type=int,
        default=42,
        help="Seed del RNG para reproducibilidad (default 42, inyectada nunca del reloj, R3).",
    )
    p.add_argument(
        "--as-of",
        default=None,
        dest="as_of",
        metavar="FECHA",
        help=(
            "YYYY-MM-DD; anti-leakage: partidos posteriores a esta fecha se "
            "tratan como pendientes (R2)."
        ),
    )
    p.add_argument(
        "--model-version",
        default="dc-v1",
        choices=("dc-v1", "dc-v2"),
        dest="model_version",
        help=(
            "Versión del modelo Dixon-Coles a usar: 'dc-v1' (default) o 'dc-v2'. "
            "(R8)."
        ),
    )
    p.add_argument(
        "--roster",
        default=None,
        metavar="CSV",
        help=(
            "CSV con columnas team_code,scorer; activa el multiplicador de ataque "
            "del factor jugadores (R9)."
        ),
    )
    p.add_argument(
        "--out",
        default=None,
        metavar="DIR",
        help="Directorio de salida del reporte (default: data/reports/simulacion).",
    )
    p.add_argument(
        "--top-n",
        type=int,
        default=10,
        dest="top_n",
        help="Número de equipos a mostrar en el ranking por P(título) (default 10).",
    )
    p.add_argument(
        "--form-weight",
        type=float,
        default=0.0,
        dest="form_weight",
        metavar="G",
        help=(
            "Peso γ del factor de forma reciente en la simulación (0.0–1.0; default 0.0 = OFF). "
            "γ=0 reproduce v1 EXACTAMENTE sin reentrenar (R4 feature 16)."
        ),
    )
    p.add_argument(
        "--form-xg",
        action="store_true",
        default=False,
        dest="form_xg",
        help=(
            "Activa señal xG en la ventana de forma para la simulación (Feature 26, R3). "
            "Default OFF → equivalencia exacta F16 (tol 1e-9)."
        ),
    )
    p.set_defaults(func=cmd_simulate)

    # -----------------------------------------------------------------------
    # ingest-elo (Feature 14, R8)
    # -----------------------------------------------------------------------
    p = sub.add_parser(
        "ingest-elo",
        help=(
            "Descarga el Elo externo de eloratings.net a bronze y gold "
            "(Feature 14, R8). Tercer subcomando con red real — regla STOP."
        ),
    )
    p.add_argument(
        "--url",
        default=None,
        metavar="URL",
        help=f"URL de eloratings.net (default: {ELO_DEFAULT_URL}).",
    )
    p.add_argument(
        "--ttl-days",
        type=int,
        default=ELO_DEFAULT_TTL_DAYS,
        dest="ttl_days",
        help=(
            f"TTL en días para la caché bronze (default {ELO_DEFAULT_TTL_DAYS}). "
            "Si existe un bronze más reciente que este umbral, no re-descarga."
        ),
    )
    p.add_argument(
        "--fetched-date",
        default=None,
        dest="fetched_date",
        metavar="YYYY-MM-DD",
        help=(
            "Fecha de la descarga (INYECTADA; útil para tests y reproducibilidad). "
            "Si se omite, usa la fecha UTC actual."
        ),
    )
    p.add_argument(
        "--out",
        default=None,
        metavar="RUTA",
        help=f"Ruta del gold external_elo.csv (default: {ELO_DEFAULT_GOLD_PATH}).",
    )
    p.set_defaults(func=cmd_ingest_elo)

    # -----------------------------------------------------------------------
    # ingest-wiki-stats (Feature 15, R1, R6)
    # -----------------------------------------------------------------------
    p = sub.add_parser(
        "ingest-wiki-stats",
        help=(
            "Obtiene stats de partido (tiros, SoT, posesión) desde Wikipedia vía "
            "MediaWiki Action API y los persiste en bronze (Feature 15, R1, R6). "
            "Cuarto subcomando con red real — regla STOP."
        ),
    )
    p.add_argument(
        "--matches",
        default="schedule",
        metavar="schedule|<csv>",
        help=(
            "'schedule': fixtures WC2026 pendientes del bronze (default); "
            "o ruta a un CSV con columnas slug,match_id,home_code,away_code."
        ),
    )
    p.add_argument(
        "--ttl-hours",
        type=int,
        default=WIKI_DEFAULT_TTL_HOURS,
        dest="ttl_hours",
        help=(
            f"TTL en horas para la caché bronze (default {WIKI_DEFAULT_TTL_HOURS}). "
            "Si el bronze es más reciente que este umbral, no re-descarga."
        ),
    )
    p.add_argument(
        "--out",
        default=None,
        metavar="DIR",
        help="Directorio bronze de salida (default: data/bronze). Los JSONs se escriben en <DIR>/wikipedia/.",
    )
    p.set_defaults(func=cmd_ingest_wiki_stats)

    # -----------------------------------------------------------------------
    # ingest-roster (Feature 21, R4)
    # -----------------------------------------------------------------------
    p = sub.add_parser(
        "ingest-roster",
        help=(
            "Descarga el roster R32 (disponibilidad de jugadores) desde fotmob "
            "(Feature 21, R4). Quinto subcomando con red real — regla STOP."
        ),
    )
    p.add_argument(
        "--league-id",
        type=int,
        default=77,
        dest="league_id",
        help="ID de la liga fotmob (default: 77 = Mundial 2026).",
    )
    p.add_argument(
        "--out",
        default=None,
        metavar="DIR",
        help="Directorio bronze de salida (default: data/bronze/rosters).",
    )
    p.set_defaults(func=cmd_ingest_roster)

    # -----------------------------------------------------------------------
    # ingest-fotmob-stats (Feature 23, R4)
    # -----------------------------------------------------------------------
    p = sub.add_parser(
        "ingest-fotmob-stats",
        help=(
            "Descarga stats por partido (xG, tiros, córners, tarjetas, posesión) "
            "desde fotmob para los encuentros WC2026 jugados y persiste en bronze "
            "(Feature 23, R4). Sexto subcomando con red real — regla STOP."
        ),
    )
    p.add_argument(
        "--league-id",
        type=int,
        default=77,
        dest="league_id",
        help="ID de la liga fotmob (default: 77 = Mundial 2026).",
    )
    p.add_argument(
        "--out",
        default=None,
        metavar="DIR",
        help=(
            "Directorio bronze de salida "
            f"(default: {FOTMOB_STATS_DEFAULT_BRONZE_DIR})."
        ),
    )
    p.set_defaults(func=cmd_ingest_fotmob_stats)

    # -----------------------------------------------------------------------
    # ingest-ko (Feature 27, R1/R3/R6)
    # -----------------------------------------------------------------------
    p = sub.add_parser(
        "ingest-ko",
        help=(
            "Descarga el bracket de eliminatorias desde fotmob, escribe "
            "r16_fixtures.csv/r8_fixtures.csv y persiste marcador+stats de los KO "
            "jugados en bronze (Feature 27). Red real — regla STOP."
        ),
    )
    p.add_argument(
        "--league-id", type=int, default=77, dest="league_id",
        help="ID de la liga fotmob (default: 77 = Mundial 2026).",
    )
    p.add_argument(
        "--out", default=None, metavar="DIR",
        help=f"Directorio bronze fotmob_stats (default: {FOTMOB_STATS_DEFAULT_BRONZE_DIR}).",
    )
    p.add_argument(
        "--knockouts-dir", default=None, dest="knockouts_dir", metavar="DIR",
        help=f"Directorio de fixtures KO (default: {KO_DEFAULT_DIR}).",
    )
    p.set_defaults(func=cmd_ingest_ko)

    # -----------------------------------------------------------------------
    # build-ko-fixtures (Feature 27, R6)
    # -----------------------------------------------------------------------
    p = sub.add_parser(
        "build-ko-fixtures",
        help=(
            "Escribe r16_fixtures.csv/r8_fixtures.csv desde el bracket fotmob, sin "
            "persistir stats (Feature 27, R6). Red real — regla STOP."
        ),
    )
    p.add_argument(
        "--league-id", type=int, default=77, dest="league_id",
        help="ID de la liga fotmob (default: 77 = Mundial 2026).",
    )
    p.add_argument(
        "--knockouts-dir", default=None, dest="knockouts_dir", metavar="DIR",
        help=f"Directorio de fixtures KO (default: {KO_DEFAULT_DIR}).",
    )
    p.set_defaults(func=cmd_build_ko_fixtures)

    # -----------------------------------------------------------------------
    # ingest-lineups (Feature 28, R5)
    # -----------------------------------------------------------------------
    p = sub.add_parser(
        "ingest-lineups",
        help=(
            "Descarga alineaciones (XI confirmado/predicho) + ratings por jugador desde "
            "fotmob y persiste en bronze (Feature 28). Red real — regla STOP."
        ),
    )
    p.add_argument("--league-id", type=int, default=77, dest="league_id",
                   help="ID de la liga fotmob (default: 77).")
    p.add_argument("--out", default=None, metavar="DIR",
                   help=f"Directorio bronze lineups (default: {LINEUP_DEFAULT_BRONZE_DIR}).")
    p.set_defaults(func=cmd_ingest_lineups)

    # -----------------------------------------------------------------------
    # build-lineup-strength (Feature 28, R5)
    # -----------------------------------------------------------------------
    p = sub.add_parser(
        "build-lineup-strength",
        help=(
            "Deriva la fuerza de alineación por (partido, equipo) desde el bronze de "
            "lineups (Feature 28, offline). Sin red."
        ),
    )
    p.add_argument("--bronze-dir", default=None, dest="bronze_dir", metavar="DIR",
                   help="Directorio bronze base (default: data/bronze).")
    p.add_argument("--gold-dir", default=None, dest="gold_dir", metavar="DIR",
                   help="Directorio gold (default: data/gold).")
    p.set_defaults(func=cmd_build_lineup_strength)

    # -----------------------------------------------------------------------
    # corners (Feature 24, R4)
    # -----------------------------------------------------------------------
    p = sub.add_parser(
        "corners",
        help=(
            "Calcula mercado de corners O/U usando tasa Poisson con shrinkage "
            "bayesiano (Feature 24, R4). Offline: no requiere modelo entrenado."
        ),
    )
    p.add_argument("home", metavar="HOME_CODE", help="Codigo FIFA del local (3 letras).")
    p.add_argument("away", metavar="AWAY_CODE", help="Codigo FIFA del visitante (3 letras).")
    p.add_argument(
        "--as-of",
        default=None,
        dest="as_of",
        metavar="FECHA",
        help=(
            "YYYY-MM-DD; fecha de corte anti-fuga (solo partidos date < as_of). "
            "Default: usa todos los datos disponibles del silver."
        ),
    )
    p.add_argument(
        "--lines",
        dest="lines",
        default=None,
        type=_parse_lines_arg,
        metavar="L1,L2,...",
        help=(
            "Lineas k+0.5 para el mercado de corners (CSV de floats). "
            "Default: 8.5,9.5,10.5,11.5."
        ),
    )
    p.add_argument(
        "--silver",
        default=None,
        metavar="PATH",
        help=(
            "Ruta al silver matches.csv con columnas home/away_corners "
            f"(default: {DEFAULT_BACKTEST_SILVER})."
        ),
    )
    p.add_argument(
        "--json",
        action="store_true",
        help="Salida machine-readable: un unico documento JSON en stdout.",
    )
    p.set_defaults(func=cmd_corners)

    # -----------------------------------------------------------------------
    # count-market (Feature 25, R3)
    # -----------------------------------------------------------------------
    p = sub.add_parser(
        "count-market",
        help=(
            "Calcula mercado de conteo O/U (tarjetas/tiros/SoT) usando tasa Poisson "
            "con shrinkage bayesiano (Feature 25, R3). Offline: no requiere modelo "
            "entrenado. --stat invalido falla con exit code 2."
        ),
    )
    p.add_argument("home", metavar="HOME_CODE", help="Codigo FIFA del local (3 letras).")
    p.add_argument("away", metavar="AWAY_CODE", help="Codigo FIFA del visitante (3 letras).")
    p.add_argument(
        "--stat",
        required=True,
        choices=("cards", "shots", "sot"),
        metavar="{cards,shots,sot}",
        help=(
            "Estadistica a modelar: 'cards' (tarjetas), 'shots' (tiros), "
            "'sot' (tiros a puerta/SoT). Requerido."
        ),
    )
    p.add_argument(
        "--as-of",
        default=None,
        dest="as_of",
        metavar="FECHA",
        help=(
            "YYYY-MM-DD; fecha de corte anti-fuga (solo partidos date < as_of). "
            "Default: usa todos los datos disponibles del silver."
        ),
    )
    p.add_argument(
        "--lines",
        dest="lines",
        default=None,
        type=_parse_lines_arg,
        metavar="L1,L2,...",
        help=(
            "Lineas k+0.5 para el mercado (CSV de floats). "
            "Default segun stat: cards=2.5,3.5,4.5; shots=20.5,24.5,28.5; sot=6.5,8.5,10.5."
        ),
    )
    p.add_argument(
        "--silver",
        default=None,
        metavar="PATH",
        help=(
            "Ruta al silver matches.csv con columnas home/away_{stat} "
            f"(default: {DEFAULT_BACKTEST_SILVER})."
        ),
    )
    p.add_argument(
        "--json",
        action="store_true",
        help="Salida machine-readable: un unico documento JSON en stdout.",
    )
    p.set_defaults(func=cmd_count_market)

    # -----------------------------------------------------------------------
    # simulate-match (Feature 34, R7): Monte Carlo de un cruce fijo (Final / 3er puesto)
    # -----------------------------------------------------------------------
    p = sub.add_parser(
        "simulate-match",
        help=(
            "Simulación Monte Carlo de UN enfrentamiento fijo (Final o 3er puesto): "
            "P(ganador), marcador modal, reparto 90'/prórroga/penales y mercados "
            "(Feature 34, R4). --dead-rubber amortigua el 3er puesto (R3)."
        ),
    )
    p.add_argument(
        "--fixture",
        choices=("r2", "r3p"),
        default=None,
        help="Lee el cruce del CSV: 'r2' (Final) o 'r3p' (3er puesto). Alterna con --home/--away.",
    )
    p.add_argument("--home", default=None, metavar="CODE", help="Código FIFA del local (si no se usa --fixture).")
    p.add_argument("--away", default=None, metavar="CODE", help="Código FIFA del visitante (si no se usa --fixture).")
    p.add_argument("--n", type=int, default=DEFAULT_MATCH_SIM_N, dest="n_simulations",
                   help=f"Número de simulaciones (default {DEFAULT_MATCH_SIM_N}, mínimo 1000).")
    p.add_argument("--seed", type=int, default=42, help="Seed del RNG (default 42, inyectada).")
    p.add_argument("--params", default=str(DEFAULT_PARAMS_PATH), metavar="PATH",
                   help=f"JSON de parámetros Dixon-Coles (default {DEFAULT_PARAMS_PATH}).")
    p.add_argument("--gamma", type=float, default=0.0, dest="gamma", metavar="G",
                   help="Peso γ del factor de forma (0.0–1.0; default 0.0 = OFF). WC2026 KO usa 0.2.")
    p.add_argument("--form-xg", action="store_true", default=False, dest="form_xg",
                   help="Activa señal xG en la ventana de forma (Feature 26).")
    p.add_argument("--dead-rubber", action="store_true", default=False, dest="dead_rubber",
                   help="Activa la amortiguación de motivación del 3er puesto (Feature 34, R3).")
    p.add_argument("--out", default=None, metavar="PATH",
                   help="Ruta del artefacto CSV (default data/predictions/{final,r3p}_sim.csv).")
    p.set_defaults(func=cmd_simulate_match)

    return parser


def main(argv: list[str] | None = None) -> int:
    """Punto de entrada testeable: parsea ``argv`` y despacha al subcomando (R1).

    Errores de uso de ``argparse`` (sin subcomando, subcomando desconocido, flag
    requerido ausente) salen con ``SystemExit(2)`` SIN capturar (política de exit
    codes de design.md); los errores de dominio devuelven 1 vía ``_error``.
    """
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":  # pragma: no cover — invocación de módulo (R1)
    raise SystemExit(main())
