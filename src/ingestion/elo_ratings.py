"""Ingesta de Elo externo desde eloratings.net a la capa bronze (Feature 14, R1, R2).

Descarga la tabla de Elo de selecciones en formato TSV vía transporte INYECTABLE (R1),
la parsea con ``pandas.read_csv`` (sin ``read_html``: la fuente es TSV, no HTML) (R1, R9),
valida que hay filas con código alpha-2 y Elo numérico o lanza :class:`EloParseError`
ruidosamente (NUNCA DataFrame vacío silencioso), mapea los códigos alpha-2 de eloratings
a códigos FIFA del proyecto usando :data:`ALPHA2_TO_CODE` (R2), persiste el TSV crudo en
``data/bronze/elo/eloratings_<fetched_date>.tsv`` junto con un sidecar ``.meta.json``
(url, fetched_at INYECTADO, sha256) y aplica un TTL configurable (default 7 días): si
existe un bronze del mismo día dentro del TTL no re-descarga (R1).

Fuente real (verificada 2026-06-17):

  URL: ``https://www.eloratings.net/World.tsv``
  Formato: TSV sin cabecera, ~244 filas, separador TAB.
  Columnas (0-indexed): col0=rank_display, col1=rank_display, col2=código_alpha2, col3=Elo(int).
  Los signos menos Unicode U+2212 (``−``) en otras columnas son irrelevantes.

Reglas de seguridad (security-lead 2026-06-17):
- ``pandas.read_csv`` con ``dtype=str`` (no ``read_html``, no ``lxml``, no XXE) (R9).
- ``fetched_at`` SIEMPRE inyectado (sin reloj en lógica pura, R9).
- Escritura solo bajo ``data/``.

Regla STOP de ``CLAUDE.md``: ejecutar la descarga real (sin transporte inyectado)
requiere aprobación previa del usuario.
"""

from __future__ import annotations

import hashlib
import io
import json
import warnings
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Callable

import pandas as pd

# URL pública por defecto (eloratings.net TSV). Parametrizable (R1).
DEFAULT_URL = "https://www.eloratings.net/World.tsv"

# TTL por defecto en días: si el bronze tiene menos de este tiempo, no re-descargar (R1).
DEFAULT_TTL_DAYS = 7

# Número mínimo de filas con código alpha-2 y Elo válidos para considerar el archivo útil.
_MIN_VALID_ROWS = 10

# Contrato del gold: columnas del artefacto external_elo.csv (R3).
EXTERNAL_ELO_COLUMNS: tuple[str, ...] = ("fetched_date", "team_code", "elo")

DEFAULT_BRONZE_DIR = Path("data") / "bronze"
DEFAULT_GOLD_PATH = Path("data") / "gold" / "external_elo.csv"

# Transporte inyectable: url → texto TSV (UTF-8 decodificado) (R1, R9).
EloTransport = Callable[[str], str]

# Mapeo de código alpha-2 de eloratings.net → código FIFA del proyecto (R2).
#
# eloratings.net usa en su mayoría ISO alpha-2 estándar, con excepciones para
# las Home Nations (EN=England, SQ=Scotland, WA=Wales, NI=Northern Ireland) y
# algunos países con notación propia (RS=Serbia, KO=Kosovo, etc.).
# ATENCIÓN: SC en eloratings es Seychelles (Elo≈853), NO Escocia. Escocia=SQ.
# Solo se incluyen los países presentes en DATASET_ALIASES (48 selecciones).
#
# Fuente de la lista: data/silver/matches.csv (tournament='FIFA World Cup', date>=2026-06-11)
# + DATASET_ALIASES de public_data (candidatos históricos del modelo).
ALPHA2_TO_CODE: dict[str, str] = {
    # ISO alpha-2 estándar
    "AR": "ARG",  # Argentina
    "AU": "AUS",  # Australia
    "AT": "AUT",  # Austria
    "BE": "BEL",  # Belgium
    "BA": "BIH",  # Bosnia and Herzegovina
    "BR": "BRA",  # Brazil
    "CA": "CAN",  # Canada
    "CI": "CIV",  # Ivory Coast
    "CD": "COD",  # DR Congo
    "CO": "COL",  # Colombia
    "CV": "CPV",  # Cape Verde
    "HR": "CRO",  # Croatia
    "CW": "CUW",  # Curaçao
    "CZ": "CZE",  # Czech Republic
    "DZ": "ALG",  # Algeria
    "EC": "ECU",  # Ecuador
    "EG": "EGY",  # Egypt
    "FR": "FRA",  # France
    "DE": "GER",  # Germany
    "GH": "GHA",  # Ghana
    "HT": "HAI",  # Haiti
    "IR": "IRN",  # Iran
    "IQ": "IRQ",  # Iraq
    "JO": "JOR",  # Jordan
    "JP": "JPN",  # Japan
    "KR": "KOR",  # South Korea
    "SA": "KSA",  # Saudi Arabia
    "MA": "MAR",  # Morocco
    "MX": "MEX",  # Mexico
    "NL": "NED",  # Netherlands
    "NZ": "NZL",  # New Zealand
    "NO": "NOR",  # Norway
    "PA": "PAN",  # Panama
    "PY": "PAR",  # Paraguay
    "PT": "POR",  # Portugal
    "QA": "QAT",  # Qatar
    "ZA": "RSA",  # South Africa
    "SN": "SEN",  # Senegal
    "ES": "ESP",  # Spain
    "SE": "SWE",  # Sweden
    "CH": "SUI",  # Switzerland
    "TN": "TUN",  # Tunisia
    "TR": "TUR",  # Turkey
    "US": "USA",  # United States
    "UY": "URU",  # Uruguay
    "UZ": "UZB",  # Uzbekistan
    # Home Nations — códigos no-ISO usados por eloratings.net
    "EN": "ENG",  # England
    "SQ": "SCO",  # Scotland (eloratings SQ≈1794; ISO SC=Seychelles≈853, descartado)
}


class EloDownloadError(RuntimeError):
    """Descarga real fallida: status HTTP no exitoso (≠ 2xx) (R1)."""

    def __init__(self, status_code: int, url: str) -> None:
        super().__init__(f"HTTP {status_code} al descargar {url}")
        self.status_code = status_code
        self.url = url


class EloParseError(ValueError):
    """TSV descargado no contiene filas de Elo válidas (R1, R9).

    Nunca se devuelve un DataFrame vacío silencioso: este error se lanza
    siempre que el parseo no produce al menos :data:`_MIN_VALID_ROWS` filas
    con código alpha-2 y Elo numérico entero en las columnas col2/col3.
    """


@dataclass
class EloIngestResult:
    """Resultado de la ingesta: rutas persistidas y tabla mapeada (R1, R2)."""

    tsv_path: Path
    meta_path: Path
    n_mapped: int
    n_discarded: int
    from_cache: bool


def _default_transport(url: str, user_agent: str | None = None) -> str:
    """Transporte real con ``requests`` (import perezoso: solo si se usa) (R1).

    Status no exitoso → :class:`EloDownloadError` y nada se persiste.
    ``user_agent`` inyectable; si es ``None`` usa un UA identificable por defecto.

    Args:
        url: URL to download.
        user_agent: Optional User-Agent header value.

    Returns:
        TSV content as UTF-8 decoded string.

    Raises:
        EloDownloadError: If the HTTP status code is not 2xx.
    """
    import requests  # noqa: PLC0415 — import perezoso

    ua = user_agent or "sport-analysis-bot/1.0 (Mundial 2026 pipeline; contact: aalonsocj14@gmail.com)"
    headers = {"User-Agent": ua}
    resp = requests.get(url, timeout=60, headers=headers)
    if not 200 <= resp.status_code < 300:
        raise EloDownloadError(resp.status_code, url)
    return resp.content.decode("utf-8", errors="replace")


def _bronze_paths(
    fetched_date: str,
    bronze_dir: Path = DEFAULT_BRONZE_DIR,
) -> tuple[Path, Path]:
    """Rutas deterministas del bronze: TSV y sidecar meta (R1).

    Args:
        fetched_date: Date string YYYY-MM-DD used as filename suffix.
        bronze_dir: Bronze directory root.

    Returns:
        Tuple of (tsv_path, meta_path).
    """
    base = Path(bronze_dir) / "elo"
    tsv_path = base / f"eloratings_{fetched_date}.tsv"
    meta_path = base / f"eloratings_{fetched_date}.meta.json"
    return tsv_path, meta_path


def _parse_elo_tsv(tsv_text: str) -> pd.DataFrame:
    """Parsea el TSV de eloratings.net con ``pandas.read_csv`` (R1, R9).

    El TSV no tiene cabecera. Solo se usan col2 (código alpha-2) y col3 (Elo int).
    Se usa ``dtype=str`` para evitar problemas con signos menos Unicode (U+2212)
    en las columnas de variación que no se procesan.

    Args:
        tsv_text: Raw TSV string (sin cabecera, separador TAB).

    Returns:
        DataFrame con columnas ``alpha2`` (str) y ``elo`` (int), filas válidas.

    Raises:
        EloParseError: Si no hay suficientes filas con código y Elo válidos.
    """
    try:
        df_raw = pd.read_csv(
            io.StringIO(tsv_text),
            sep="\t",
            header=None,
            dtype=str,
            on_bad_lines="skip",
        )
    except Exception as exc:
        raise EloParseError(
            f"No se pudo parsear el TSV de eloratings con pandas.read_csv: {exc}"
        ) from exc

    if df_raw.shape[1] < 4:
        raise EloParseError(
            f"El TSV tiene menos de 4 columnas ({df_raw.shape[1]}); "
            "se esperan al menos col0=rank, col1=rank, col2=alpha2, col3=elo. "
            "Verificar que la URL apunta al TSV correcto (World.tsv)."
        )

    # Extraer col2 (alpha-2) y col3 (Elo)
    df = df_raw[[2, 3]].copy()
    df.columns = ["alpha2", "elo_raw"]

    # Limpiar y convertir: alpha-2 limpio, Elo numérico entero
    df["alpha2"] = df["alpha2"].astype(str).str.strip()
    df["elo"] = pd.to_numeric(df["elo_raw"], errors="coerce")

    # Descartar filas con alpha2 vacío, NaN en Elo, o Elo no entero
    df = df.dropna(subset=["elo"])
    df = df[df["alpha2"].str.len() > 0]
    df["elo"] = df["elo"].astype(int)
    df = df[["alpha2", "elo"]].reset_index(drop=True)

    if len(df) < _MIN_VALID_ROWS:
        raise EloParseError(
            f"El TSV produjo solo {len(df)} filas válidas (mínimo {_MIN_VALID_ROWS}). "
            "Verificar que la fuente TSV no está vacía o corrupta."
        )

    return df


def _map_to_codes(df: pd.DataFrame) -> tuple[list[dict], list[str]]:
    """Mapea códigos alpha-2 de eloratings al código FIFA del proyecto (R2).

    Usa :data:`ALPHA2_TO_CODE`. Alpha-2 sin entrada → descartados con motivo,
    sin abortar. Reporta cuántos de los 48 del DATASET_ALIASES quedan cubiertos.

    Args:
        df: DataFrame con columnas ``alpha2`` (str) y ``elo`` (int).

    Returns:
        Tuple de (filas mapeadas como list[dict], lista de alpha-2 descartados).
    """
    mapped: list[dict] = []
    discarded: list[str] = []
    for _, row in df.iterrows():
        alpha2 = str(row["alpha2"])
        code = ALPHA2_TO_CODE.get(alpha2)
        if code is None:
            discarded.append(alpha2)
        else:
            mapped.append({"team_code": code, "elo": int(row["elo"])})
    return mapped, discarded


def _cache_is_valid(
    fetched_date: str,
    bronze_dir: Path,
    ttl_days: int,
) -> bool:
    """Verifica si existe un bronze reciente dentro del TTL (R1).

    Compara la fecha del archivo existente con la ``fetched_date`` proporcionada.
    Si existe un archivo TSV con fecha dentro de ``ttl_days`` días antes de
    ``fetched_date`` (inclusive), el cache es válido.

    Args:
        fetched_date: Current date string YYYY-MM-DD (injected, no clock).
        bronze_dir: Bronze directory root.
        ttl_days: TTL in days.

    Returns:
        True if a valid cached TSV file exists within TTL.
    """
    elo_dir = Path(bronze_dir) / "elo"
    if not elo_dir.is_dir():
        return False
    current = date.fromisoformat(fetched_date)
    cutoff = current - timedelta(days=ttl_days)
    for tsv_file in elo_dir.glob("eloratings_*.tsv"):
        stem = tsv_file.stem  # "eloratings_YYYY-MM-DD"
        try:
            file_date = date.fromisoformat(stem.replace("eloratings_", ""))
        except ValueError:
            continue
        if cutoff <= file_date <= current:
            return True
    return False


def write_bronze_elo(
    tsv_text: str,
    fetched_date: str,
    url: str,
    fetched_at: str,
    bronze_dir: Path = DEFAULT_BRONZE_DIR,
) -> tuple[Path, Path]:
    """Persiste el TSV crudo y el sidecar de metadatos en bronze (R1).

    Args:
        tsv_text: Raw TSV content.
        fetched_date: Date string YYYY-MM-DD for the filename.
        url: Source URL (included in metadata).
        fetched_at: ISO-8601 timestamp (INJECTED, no clock) for metadata.
        bronze_dir: Bronze directory root.

    Returns:
        Tuple of (tsv_path, meta_path).
    """
    tsv_path, meta_path = _bronze_paths(fetched_date, bronze_dir)
    tsv_path.parent.mkdir(parents=True, exist_ok=True)

    raw = tsv_text.encode("utf-8")
    tsv_path.write_bytes(raw)

    meta = {
        "url": url,
        "fetched_at": fetched_at,
        "sha256": hashlib.sha256(raw).hexdigest(),
    }
    meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    return tsv_path, meta_path


def write_gold_external_elo(
    mapped_rows: list[dict],
    fetched_date: str,
    gold_path: Path = DEFAULT_GOLD_PATH,
) -> Path:
    """Persiste el artefacto gold ``external_elo.csv`` determinista (R3).

    Columnas: ``fetched_date, team_code, elo``. Ordenado por ``team_code``
    (mismo input → mismo contenido byte a byte). Escritura solo bajo ``data/``.

    Args:
        mapped_rows: List of dicts with keys ``team_code`` and ``elo``.
        fetched_date: Date string YYYY-MM-DD for the ``fetched_date`` column.
        gold_path: Output path for the gold CSV.

    Returns:
        Resolved output path.
    """
    gold_path = Path(gold_path)
    gold_path.parent.mkdir(parents=True, exist_ok=True)

    rows = [
        {"fetched_date": fetched_date, "team_code": r["team_code"], "elo": r["elo"]}
        for r in mapped_rows
    ]
    # Ordenar por team_code para determinismo (R3)
    rows.sort(key=lambda r: r["team_code"])

    df = pd.DataFrame(rows, columns=list(EXTERNAL_ELO_COLUMNS))
    df.to_csv(gold_path, index=False, encoding="utf-8")
    return gold_path


def ingest_elo_ratings(
    fetched_at: str,
    fetched_date: str,
    transport: EloTransport | None = None,
    url: str = DEFAULT_URL,
    bronze_dir: Path = DEFAULT_BRONZE_DIR,
    gold_path: Path = DEFAULT_GOLD_PATH,
    ttl_days: int = DEFAULT_TTL_DAYS,
    user_agent: str | None = None,
) -> EloIngestResult:
    """Orquesta la ingesta: caché → fetch → parse → map → bronze + gold (R1, R2, R3).

    ``fetched_at`` y ``fetched_date`` se inyectan (sin reloj en lógica pura, R9).
    Sin transporte inyectado usa el real (descarga efectiva solo con OK del usuario,
    regla STOP de ``CLAUDE.md``).

    Args:
        fetched_at: ISO-8601 timestamp (injected; no clock in pure logic).
        fetched_date: Date YYYY-MM-DD (injected; used for filenames and gold column).
        transport: Callable url→tsv_text; if None uses real HTTP transport.
        url: Source URL (default: eloratings.net/World.tsv).
        bronze_dir: Bronze directory root.
        gold_path: Gold output CSV path.
        ttl_days: Cache TTL in days; if bronze < TTL days old, skip re-download.
        user_agent: Optional UA string for the real transport.

    Returns:
        EloIngestResult with paths and mapping statistics.
    """
    from_cache = False

    # Caché TTL: si existe bronze reciente, no re-descargar (R1)
    if _cache_is_valid(fetched_date, bronze_dir, ttl_days):
        from_cache = True
        # Leer el bronze existente más reciente dentro del TTL
        elo_dir = Path(bronze_dir) / "elo"
        current = date.fromisoformat(fetched_date)
        cutoff = current - timedelta(days=ttl_days)
        candidates = []
        for tsv_file in elo_dir.glob("eloratings_*.tsv"):
            stem = tsv_file.stem
            try:
                file_date = date.fromisoformat(stem.replace("eloratings_", ""))
            except ValueError:
                continue
            if cutoff <= file_date <= current:
                candidates.append((file_date, tsv_file))
        candidates.sort(reverse=True)
        tsv_path = candidates[0][1]
        meta_path = tsv_path.with_suffix(".meta.json")
        tsv_text = tsv_path.read_text(encoding="utf-8", errors="replace")
    else:
        # Descarga efectiva via transporte
        actual_transport: EloTransport
        if transport is not None:
            actual_transport = transport
        else:
            def actual_transport(u: str) -> str:
                return _default_transport(u, user_agent=user_agent)

        tsv_text = actual_transport(url)
        tsv_path, meta_path = write_bronze_elo(tsv_text, fetched_date, url, fetched_at, bronze_dir)

    # Parseo TSV con pandas.read_csv (R1, R9 — no lxml, no XXE)
    df = _parse_elo_tsv(tsv_text)

    # Mapeo a códigos FIFA (R2)
    mapped_rows, discarded = _map_to_codes(df)

    # Log de descartes (R2: sin abortar)
    if discarded:
        warnings.warn(
            f"Alpha-2 sin mapeo FIFA descartadas ({len(discarded)}): "
            f"{discarded[:10]}{'...' if len(discarded) > 10 else ''}",
            UserWarning,
            stacklevel=2,
        )

    # Persistir gold (R3)
    write_gold_external_elo(mapped_rows, fetched_date, gold_path)

    return EloIngestResult(
        tsv_path=tsv_path,
        meta_path=meta_path,
        n_mapped=len(mapped_rows),
        n_discarded=len(discarded),
        from_cache=from_cache,
    )
