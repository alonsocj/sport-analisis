"""Capa silver: normalización bronze → silver (R1–R7).

Transforma las respuestas crudas de API-Football (``data/bronze/fixtures/*.json`` y
``data/bronze/fixtures_statistics/*.json``) y el CSV de la fuente pública
(``data/bronze/public_results/results.csv``) en una tabla única de partidos
(``data/silver/matches.csv``): partidos finalizados (R1), estadísticas adjuntas con
posesión como float (R2), filas públicas con stats nulas y descarte tolerante de filas
corruptas (R3), códigos FIFA con alias y
fallback slug determinista (R4), ``match_id`` estable (R5), dedupe entre fuentes con
prioridad ``api_football`` (R6) y esquema/orden de columnas exactos del contrato (R7).

Procesamiento 100% offline: lee disco, no hace red ni usa ``API_FOOTBALL_KEY``.
"""

from __future__ import annotations

import csv
import hashlib
import json
import logging
import re
import unicodedata
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from ..ingestion.ingest import normalize_statistics
from ..ingestion.teams import all_teams

try:
    # R4: si la feature 7 (ingesta_publica) está disponible, su tabla de alias es la
    # fuente de verdad nombre-dataset → código FIFA. Se desarrolla en paralelo, por lo
    # que este módulo DEBE funcionar también sin ella (fallback propio más abajo).
    from ..ingestion.public_data import to_fifa_code as _public_to_fifa_code
except ImportError:  # pragma: no cover — depende de la presencia de la feature 7.
    _public_to_fifa_code = None

logger = logging.getLogger(__name__)


class SilverInputError(RuntimeError):
    """No existe ninguna fuente bronze para construir silver (R7)."""


# Columnas de estadísticas (nullable; los 10 originales desde api_football/fotmob +
# home_xg/away_xg desde fotmob_stats F23) — R2, R7, F23-R3.
STAT_COLUMNS: tuple[str, ...] = (
    "home_corners",
    "away_corners",
    "home_cards",
    "away_cards",
    "home_shots",
    "away_shots",
    "home_shots_on_target",
    "away_shots_on_target",
    "home_possession",
    "away_possession",
    "home_xg",
    "away_xg",
)

# Contrato silver: esquema y ORDEN exactos de columnas (R7, design.md).
SILVER_COLUMNS: tuple[str, ...] = (
    "match_id",
    "date",
    "home_code",
    "away_code",
    "home_team",
    "away_team",
    "home_goals",
    "away_goals",
    "tournament",
    "neutral",
    "source",
) + STAT_COLUMNS

# Tabla de alias propia de fallback (R4): construida dinámicamente desde las 48 de
# ``teams.py`` (nombre canónico → código FIFA). Cubre los 48 códigos por construcción.
_FALLBACK_ALIASES: dict[str, str] = {t.name: t.code for t in all_teams()}

# Código FIFA → nombre canónico (para ``home_team``/``away_team`` en silver).
_CODE_TO_NAME: dict[str, str] = {t.code: t.name for t in all_teams()}


def slugify(name: str) -> str:
    """Código *fallback* determinista para equipos fuera de las 48 (R4).

    Normalización Unicode (NFKD, sin acentos) + minúsculas + no-alfanumérico → ``_``.
    No usa ``hash()`` (varía con ``PYTHONHASHSEED``); no colisiona con códigos FIFA
    (estos son MAYÚSCULAS de 3 letras).
    """
    ascii_name = (
        unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode("ascii")
    )
    return re.sub(r"[^a-z0-9]+", "_", ascii_name.lower()).strip("_")


def resolve_code(name: str) -> str:
    """Nombre de equipo en la fuente → código FIFA de 3 letras o slug fallback (R4)."""
    if _public_to_fifa_code is not None:
        code = _public_to_fifa_code(name)
        if code is not None:
            return code
    code = _FALLBACK_ALIASES.get(name)
    if code is not None:
        return code
    return slugify(name)


def canonical_name(code: str, source_name: str) -> str:
    """Nombre canónico: el de ``teams.py`` si el código es de las 48; si no, el de la fuente (R4)."""
    return _CODE_TO_NAME.get(code, source_name)


def make_match_id(source: str, date: str, home_code: str, away_code: str) -> str:
    """``match_id`` determinista y estable entre ejecuciones y procesos (R5).

    Hash corto: ``sha1("source|date|home_code|away_code")[:12]`` vía ``hashlib``
    (nunca ``hash()`` builtin).
    """
    raw = f"{source}|{date}|{home_code}|{away_code}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:12]


def _to_utc_date(iso_datetime: str) -> str:
    """``fixture.date`` ISO-8601 → ``YYYY-MM-DD`` en UTC (R1)."""
    dt = datetime.fromisoformat(iso_datetime.replace("Z", "+00:00"))
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%d")


def _stat_to_float(value: Any) -> float | None:
    """Estadística cruda → float nullable (R2)."""
    if value is None:
        return None
    return float(value)


def _possession_to_float(value: Any) -> float | None:
    """Posesión de API-Football (``"55%"``) → float ``55.0``; ``None`` permanece null (R2)."""
    if value is None:
        return None
    if isinstance(value, str):
        return float(value.strip().rstrip("%"))
    return float(value)


def _statistics_for(bronze_dir: Path, fixture_id: int) -> dict[str, float | None]:
    """Columnas de stats del partido desde ``fixtures_statistics/fixture=<id>.json`` (R2).

    SI no existe el archivo (o es ilegible), todas las columnas quedan nulas y el
    procesamiento continúa sin fallar. El esquema por lado lo define
    ``src/ingestion/ingest.py::normalize_statistics`` (fuente de verdad).
    """
    cols: dict[str, float | None] = {c: None for c in STAT_COLUMNS}
    path = bronze_dir / "fixtures_statistics" / f"fixture={fixture_id}.json"
    if not path.is_file():
        return cols
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("Statistics bronze ilegible, stats nulas: %s (%s)", path, exc)
        return cols
    normalized = normalize_statistics(record.get("payload") or {})
    for side in ("home", "away"):
        stats = normalized.get(side)
        if not stats:
            continue
        cols[f"{side}_corners"] = _stat_to_float(stats.get("corners"))
        cols[f"{side}_cards"] = _stat_to_float(stats.get("cards"))
        cols[f"{side}_shots"] = _stat_to_float(stats.get("shots"))
        cols[f"{side}_shots_on_target"] = _stat_to_float(stats.get("shots_on_target"))
        cols[f"{side}_possession"] = _possession_to_float(stats.get("possession"))
    return cols


def _extract_api_rows(api_files: list[Path], bronze_dir: Path) -> list[dict[str, Any]]:
    """Filas silver desde los envoltorios bronze de API-Football (R1, R2).

    Solo partidos finalizados (``fixture.status.short == "FT"``); el resto se descarta.
    ``neutral`` por defecto ``False`` (API-Football no expone un flag fiable; el dedupe
    con la fuente pública lo corrige cuando existe contraparte, R6). Un archivo JSON
    ilegible se registra y se omite sin abortar el lote.
    """
    rows: list[dict[str, Any]] = []
    discarded = 0
    for path in api_files:
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("Bronze ilegible, se omite: %s (%s)", path, exc)
            continue
        payload = record.get("payload") or {}
        for fx in payload.get("response", []):
            status = (fx.get("fixture") or {}).get("status", {}).get("short")
            if status != "FT":  # R1: partido no finalizado → descarte
                discarded += 1
                continue
            home_name = fx["teams"]["home"]["name"]
            away_name = fx["teams"]["away"]["name"]
            home_code = resolve_code(home_name)
            away_code = resolve_code(away_name)
            row: dict[str, Any] = {
                "date": _to_utc_date(fx["fixture"]["date"]),
                "home_code": home_code,
                "away_code": away_code,
                "home_team": canonical_name(home_code, home_name),
                "away_team": canonical_name(away_code, away_name),
                "home_goals": int(fx["goals"]["home"]),
                "away_goals": int(fx["goals"]["away"]),
                "tournament": (fx.get("league") or {}).get("name"),
                "neutral": False,
                "source": "api_football",
            }
            row.update(_statistics_for(bronze_dir, fx["fixture"]["id"]))
            rows.append(row)
    if discarded:
        logger.info("Fixtures descartados por status != FT: %d (R1)", discarded)
    return rows


def _is_iso_date(value: Any) -> bool:
    """True si ``value`` es exactamente ``YYYY-MM-DD`` (R3; misma regla que ingesta_publica R5)."""
    try:
        return date.fromisoformat(value).isoformat() == value
    except (TypeError, ValueError):
        return False


def _load_public_rows(bronze_dir: Path) -> list[dict[str, Any]]:
    """Filas silver desde ``public_results/results.csv`` con stats nulas (R3).

    Descarte tolerante (R3, coherente con R5 de ingesta_publica): SI una fila tiene
    goles no numéricos (p. ej. ``'NA'`` del calendario del Mundial 2026) o fecha no
    parseable como ``YYYY-MM-DD``, se descarta, se cuenta (``logging``) y el lote
    continúa sin fallar. Mismas reglas que ``parse_results`` de la feature 7.

    ``city``/``country`` no se materializan en silver (decisión de design.md; bronze
    los conserva).
    """
    path = bronze_dir / "public_results" / "results.csv"
    rows: list[dict[str, Any]] = []
    if not path.is_file():
        return rows
    discarded = 0
    with path.open(encoding="utf-8", newline="") as fh:
        for rec in csv.DictReader(fh):
            try:
                home_goals = int(rec["home_score"])
                away_goals = int(rec["away_score"])
            except (TypeError, ValueError):  # goles no numéricos → descarte (R3)
                discarded += 1
                continue
            if not _is_iso_date(rec["date"]):  # fecha inválida → descarte (R3)
                discarded += 1
                continue
            home_code = resolve_code(rec["home_team"])
            away_code = resolve_code(rec["away_team"])
            row: dict[str, Any] = {
                "date": rec["date"],
                "home_code": home_code,
                "away_code": away_code,
                "home_team": canonical_name(home_code, rec["home_team"]),
                "away_team": canonical_name(away_code, rec["away_team"]),
                "home_goals": home_goals,
                "away_goals": away_goals,
                "tournament": rec["tournament"],
                "neutral": rec["neutral"].strip().upper() == "TRUE",
                "source": "public_csv",
            }
            row.update({c: None for c in STAT_COLUMNS})
            rows.append(row)
    if discarded:
        logger.info(
            "Filas públicas descartadas (goles no numéricos o fecha inválida): %d (R3)",
            discarded,
        )
    return rows


def _load_fotmob_stats_index(
    bronze_dir: Path,
) -> dict[tuple[str, frozenset], dict]:
    """Carga el índice de stats fotmob desde el bronze para el merge silver (F23, R3).

    Lee todos los ``.json`` (no ``.meta.json``) en ``bronze_dir/fotmob_stats/``,
    mapea nombres de equipo a códigos FIFA y devuelve un dict por
    ``(date, frozenset({home_code, away_code}))`` → entry con orientación fotmob.

    La clave usa frozenset para ser robusta a diferencias de orientación entre
    fotmob y el silver (BUG2): no importa qué lado llame "home" cada fuente.

    SI ``fotmob_stats/`` no existe → devuelve ``{}`` (no-op, no-regresión, R3).
    Partidos sin stats (has_stats=False) o sin mapeo FIFA → se omiten con logging.

    Args:
        bronze_dir: Directorio bronze base (padre de ``fotmob_stats/``).

    Returns:
        Dict ``(date, frozenset)`` → ``{"fotmob_home_code": str, "fotmob_away_code": str,
        "home": {stat_key: val}, "away": {...}}``.
    """
    stats_dir = bronze_dir / "fotmob_stats"
    if not stats_dir.is_dir():
        return {}

    # Import perezoso: evita dependencia circular si fotmob_stats importa silver (no ocurre,
    # pero buena práctica). Import seguro aquí porque el módulo ya existe en este punto.
    from ..ingestion.fotmob_stats import _fotmob_stats_to_fifa_code  # noqa: PLC0415

    index: dict[tuple[str, str, str], dict[str, dict]] = {}
    for path in sorted(stats_dir.glob("*.json")):
        if path.name.endswith(".meta.json"):
            continue
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning(
                "Bronze fotmob_stats ilegible, omitiendo: %s (%s)", path, exc
            )
            continue
        if not doc.get("has_stats"):
            continue
        home_name = doc.get("home_name", "")
        away_name = doc.get("away_name", "")
        home_code = _fotmob_stats_to_fifa_code(home_name)
        away_code = _fotmob_stats_to_fifa_code(away_name)
        if not home_code:
            logger.warning(
                "Bronze fotmob_stats: equipo local '%s' sin mapeo FIFA (%s)", home_name, path
            )
            continue
        if not away_code:
            logger.warning(
                "Bronze fotmob_stats: equipo visitante '%s' sin mapeo FIFA (%s)", away_name, path
            )
            continue
        date = doc.get("date", "")
        if not date:
            continue
        pair = frozenset({home_code, away_code})
        entry = {
            "fotmob_home_code": home_code,
            "fotmob_away_code": away_code,
            "home": doc.get("home") or {},
            "away": doc.get("away") or {},
        }
        # Clave frozenset (robusta a inversión home/away, BUG2) + tolerancia de ±1 día
        # (BUG3): fotmob usa fecha UTC y martj42 fecha local; los kickoffs nocturnos
        # caen un día distinto. Se registra la fecha exacta y, con setdefault, los
        # vecinos ±1 día (sin pisar un match exacto de otro partido del mismo par).
        from datetime import datetime as _dt, timedelta as _td  # noqa: PLC0415

        index[(date, pair)] = entry  # exacta tiene prioridad
        try:
            base = _dt.strptime(date, "%Y-%m-%d")
            for delta in (-1, 1):
                neighbor = (base + _td(days=delta)).strftime("%Y-%m-%d")
                index.setdefault((neighbor, pair), entry)
        except ValueError:
            pass
    return index


def _apply_fotmob_stats(
    df: pd.DataFrame,
    fotmob_index: dict[tuple[str, frozenset], dict],
) -> None:
    """Aplica el merge de stats fotmob al silver DataFrame in-place (F23, R3).

    Puebla ``home/away_{corners,cards,shots,shots_on_target,possession}`` donde
    actualmente son null (no sobreescribe stats de api_football), y
    ``home_xg/away_xg`` (siempre desde fotmob; default null si no hay match).

    El merge es robusto a inversión home/away entre fotmob y el silver (BUG2):
    la clave es ``(date, frozenset({home_code, away_code}))``; si la orientación
    de fotmob es opuesta a la del silver, las stats se intercambian al asignar.

    La operación es in-place. ``df`` debe tener índice 0..n-1 (post reset_index).

    Args:
        df: Silver DataFrame con STAT_COLUMNS ya presentes (null por defecto).
        fotmob_index: Índice ``(date, frozenset)`` → entry con orientación fotmob.
    """
    if not fotmob_index:
        return

    _stat_cols = ("corners", "cards", "shots", "shots_on_target", "possession")

    for i, row in df.iterrows():
        key = (row["date"], frozenset({row["home_code"], row["away_code"]}))
        if key not in fotmob_index:
            continue

        entry = fotmob_index[key]
        fm_home_code = entry["fotmob_home_code"]

        # Detectar inversión: si el home de fotmob coincide con el home del silver → normal.
        # Si difieren → fotmob tiene los equipos al revés → swap de stats.
        if fm_home_code == row["home_code"]:
            h_stats: dict = entry["home"]
            a_stats: dict = entry["away"]
        else:
            h_stats = entry["away"]   # lado fotmob "away" es el home del silver
            a_stats = entry["home"]   # lado fotmob "home" es el away del silver

        # Stat cols: rellenar solo donde silver es null
        for col in _stat_cols:
            for side, stats in (("home", h_stats), ("away", a_stats)):
                s_col = f"{side}_{col}"
                val = stats.get(col)
                if val is not None and pd.isna(df.at[i, s_col]):
                    df.at[i, s_col] = float(val)

        # xG: siempre de fotmob (columna nueva F23; permanece NaN si no hay valor)
        h_xg = h_stats.get("xg")
        a_xg = a_stats.get("xg")
        if h_xg is not None:
            df.at[i, "home_xg"] = float(h_xg)
        if a_xg is not None:
            df.at[i, "away_xg"] = float(a_xg)


def build_silver(bronze_dir: Path | str) -> pd.DataFrame:
    """Construye el DataFrame silver desde las fuentes bronze (R1–R7).

    - SI falta una de las dos fuentes → continúa con la disponible (R7).
    - SI no existe ninguna → ``SilverInputError`` con mensaje claro (R7).
    - Dedupe por ``(date, home_code, away_code)``: sobrevive la fila ``api_football``
      tomando ``neutral`` y ``tournament`` del registro público cuando existe (R6).
    - ``match_id`` se calcula tras el dedupe, sobre la fila superviviente (R5).
    - Orden de filas determinista: ``(date, match_id)`` ascendente (R7).
    """
    bronze_dir = Path(bronze_dir)
    fixtures_dir = bronze_dir / "fixtures"
    api_files = sorted(fixtures_dir.glob("*.json")) if fixtures_dir.is_dir() else []
    public_path = bronze_dir / "public_results" / "results.csv"
    if not api_files and not public_path.is_file():
        raise SilverInputError(
            f"Sin fuentes bronze en {bronze_dir}: se esperaba fixtures/*.json "
            "y/o public_results/results.csv (R7)"
        )

    api_rows = _extract_api_rows(api_files, bronze_dir)
    public_rows = _load_public_rows(bronze_dir)

    # Índice público por clave de partido; duplicados intra-fuente colapsan a la primera
    # aparición (orden determinista de lectura).
    public_by_key: dict[tuple[str, str, str], dict[str, Any]] = {}
    for row in public_rows:
        public_by_key.setdefault((row["date"], row["home_code"], row["away_code"]), row)

    merged: dict[tuple[str, str, str], dict[str, Any]] = {}
    for row in api_rows:
        key = (row["date"], row["home_code"], row["away_code"])
        if key in merged:
            continue
        public_match = public_by_key.get(key)
        if public_match is not None:  # R6: neutral/tournament del registro público
            row["neutral"] = public_match["neutral"]
            row["tournament"] = public_match["tournament"]
        merged[key] = row
    for key, row in public_by_key.items():
        merged.setdefault(key, row)

    rows: list[dict[str, Any]] = []
    for row in merged.values():
        row["match_id"] = make_match_id(
            row["source"], row["date"], row["home_code"], row["away_code"]
        )
        rows.append(row)

    df = pd.DataFrame(rows, columns=list(SILVER_COLUMNS))
    df["home_goals"] = df["home_goals"].astype(int)
    df["away_goals"] = df["away_goals"].astype(int)
    df["neutral"] = df["neutral"].astype(bool)
    for col in STAT_COLUMNS:
        df[col] = df[col].astype(float)
    df = df.sort_values(["date", "match_id"], kind="mergesort").reset_index(drop=True)

    # F23 (R3): merge de stats fotmob por (date, home_code, away_code).
    # Si no existe el bronze fotmob_stats → no-op (silver idéntico al actual).
    fotmob_index = _load_fotmob_stats_index(bronze_dir)
    if fotmob_index:
        _apply_fotmob_stats(df, fotmob_index)

    return df


def write_silver(df: pd.DataFrame, silver_dir: Path | str) -> Path:
    """Escribe ``matches.csv`` con el esquema/orden del contrato; null → celda vacía (R7)."""
    silver_dir = Path(silver_dir)
    silver_dir.mkdir(parents=True, exist_ok=True)
    path = silver_dir / "matches.csv"
    df[list(SILVER_COLUMNS)].to_csv(path, index=False)
    return path
