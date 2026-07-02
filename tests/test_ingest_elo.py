"""Tests de ingesta de Elo externo — Feature 14, R1, R2, R9.

Cubre:
- R1: transporte inyectable, meta con url/fetched_at/sha256, caché TTL
- R2: mapeo de códigos alpha-2 a códigos FIFA, descarte sin abortar
- R3: gold determinista (mismo input → mismo contenido byte a byte)
- R9: parser TSV seguro (sin lxml/red real), fetched_at inyectado, escritura bajo data/

Todos los tests son offline (sin red). El TSV se lee desde la fixture
``tests/fixtures/eloratings_world_sample.tsv``.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pandas as pd
import pytest

# Fixture TSV real guardada (offline, R9)
FIXTURE_TSV = Path(__file__).parent / "fixtures" / "eloratings_world_sample.tsv"


def _read_fixture() -> str:
    return FIXTURE_TSV.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# R1 — transporte inyectable, meta, caché TTL
# ---------------------------------------------------------------------------


def test_descarga_transporte_inyectable_y_meta(tmp_path: Path) -> None:
    """R1: transporte inyectable url→tsv; sidecar meta contiene url, fetched_at, sha256."""
    from src.ingestion.elo_ratings import (
        ingest_elo_ratings,
        DEFAULT_TTL_DAYS,
    )

    tsv_fixture = _read_fixture()
    called_with: list[str] = []

    def fake_transport(url: str) -> str:
        called_with.append(url)
        return tsv_fixture

    gold_path = tmp_path / "gold" / "external_elo.csv"
    # La fixture TSV real tiene alpha-2 sin mapeo → UserWarning de descarte (R2)
    with pytest.warns(UserWarning, match="sin mapeo FIFA"):
        result = ingest_elo_ratings(
            fetched_at="2026-06-17T12:00:00+00:00",
            fetched_date="2026-06-17",
            transport=fake_transport,
            url="https://fake.eloratings.test/World.tsv",
            bronze_dir=tmp_path / "bronze",
            gold_path=gold_path,
            ttl_days=DEFAULT_TTL_DAYS,
        )

    # El transporte fue llamado con la URL correcta
    assert called_with == ["https://fake.eloratings.test/World.tsv"]

    # El TSV se persistió en bronze
    assert result.tsv_path.is_file()
    assert result.tsv_path.suffix == ".tsv"
    assert "eloratings_2026-06-17" in result.tsv_path.name

    # El meta existe y tiene las claves requeridas
    assert result.meta_path.is_file()
    meta = json.loads(result.meta_path.read_text(encoding="utf-8"))
    assert meta["url"] == "https://fake.eloratings.test/World.tsv"
    assert meta["fetched_at"] == "2026-06-17T12:00:00+00:00"
    assert "sha256" in meta

    # sha256 coincide con el contenido real
    expected_sha = hashlib.sha256(tsv_fixture.encode("utf-8")).hexdigest()
    assert meta["sha256"] == expected_sha

    # No vino del caché
    assert not result.from_cache


def test_tsv_invalido_falla_ruidoso_sin_columnas(tmp_path: Path) -> None:
    """R1/R9: TSV sin columnas suficientes → EloParseError ruidoso (nunca silencioso)."""
    from src.ingestion.elo_ratings import ingest_elo_ratings, EloParseError

    tsv_sin_columnas = "A\tB\n1\t2\n"

    with pytest.raises(EloParseError, match="menos de 4 columnas"):
        ingest_elo_ratings(
            fetched_at="2026-06-17T12:00:00+00:00",
            fetched_date="2026-06-17",
            transport=lambda _url: tsv_sin_columnas,
            url="https://fake.test/",
            bronze_dir=tmp_path / "bronze",
            gold_path=tmp_path / "gold" / "external_elo.csv",
        )


def test_tsv_invalido_falla_ruidoso_sin_elos_validos(tmp_path: Path) -> None:
    """R1/R9: TSV con 4 columnas pero sin Elo numérico → EloParseError (validación ruidosa)."""
    from src.ingestion.elo_ratings import ingest_elo_ratings, EloParseError

    # TSV con 4 columnas pero sin Elo numérico válido en col3
    tsv_malo = "1\t1\tXX\tabc\n2\t2\tYY\txyz\n"

    with pytest.raises(EloParseError, match="filas válidas"):
        ingest_elo_ratings(
            fetched_at="2026-06-17T12:00:00+00:00",
            fetched_date="2026-06-17",
            transport=lambda _url: tsv_malo,
            url="https://fake.test/",
            bronze_dir=tmp_path / "bronze",
            gold_path=tmp_path / "gold" / "external_elo.csv",
        )


def test_cache_ttl_no_redescarga(tmp_path: Path) -> None:
    """R1: si existe bronze TSV del mismo día (dentro del TTL), no re-descarga."""
    from src.ingestion.elo_ratings import ingest_elo_ratings, write_bronze_elo

    tsv_fixture = _read_fixture()
    call_count = [0]

    # Escribir un bronze existente para la fecha
    write_bronze_elo(
        tsv_text=tsv_fixture,
        fetched_date="2026-06-17",
        url="https://original.url/",
        fetched_at="2026-06-17T08:00:00+00:00",
        bronze_dir=tmp_path / "bronze",
    )

    def counting_transport(url: str) -> str:
        call_count[0] += 1
        return tsv_fixture

    gold_path = tmp_path / "gold" / "external_elo.csv"
    with pytest.warns(UserWarning, match="sin mapeo FIFA"):
        result = ingest_elo_ratings(
            fetched_at="2026-06-17T14:00:00+00:00",
            fetched_date="2026-06-17",
            transport=counting_transport,
            url="https://new.url/",
            bronze_dir=tmp_path / "bronze",
            gold_path=gold_path,
            ttl_days=7,
        )

    # No llamó al transporte: usó el cache
    assert call_count[0] == 0
    assert result.from_cache is True


def test_ttl_expirado_redescarga(tmp_path: Path) -> None:
    """R1: bronze más antiguo que TTL → re-descarga."""
    from src.ingestion.elo_ratings import ingest_elo_ratings, write_bronze_elo

    tsv_fixture = _read_fixture()
    call_count = [0]

    # Bronze con fecha de hace 10 días (> TTL de 7 días)
    write_bronze_elo(
        tsv_text=tsv_fixture,
        fetched_date="2026-06-07",  # 10 días antes de 2026-06-17
        url="https://original.url/",
        fetched_at="2026-06-07T08:00:00+00:00",
        bronze_dir=tmp_path / "bronze",
    )

    def counting_transport(url: str) -> str:
        call_count[0] += 1
        return tsv_fixture

    gold_path = tmp_path / "gold" / "external_elo.csv"
    with pytest.warns(UserWarning, match="sin mapeo FIFA"):
        ingest_elo_ratings(
            fetched_at="2026-06-17T14:00:00+00:00",
            fetched_date="2026-06-17",
            transport=counting_transport,
            url="https://new.url/",
            bronze_dir=tmp_path / "bronze",
            gold_path=gold_path,
            ttl_days=7,
        )

    # Llamó al transporte porque el bronze expiró
    assert call_count[0] == 1


# ---------------------------------------------------------------------------
# R2 — mapeo de alpha-2 a códigos FIFA del proyecto
# ---------------------------------------------------------------------------


def test_mapeo_codigos_y_descarte_sin_mapeo(tmp_path: Path) -> None:
    """R2: mapeo correcto a códigos FIFA; alpha-2 sin mapeo descartados sin abortar."""
    from src.ingestion.elo_ratings import ingest_elo_ratings
    from src.ingestion.public_data import DATASET_ALIASES

    tsv_fixture = _read_fixture()
    gold_path = tmp_path / "gold" / "external_elo.csv"

    # La fixture TSV real tiene alpha-2 sin mapeo → UserWarning (R2)
    with pytest.warns(UserWarning, match="sin mapeo FIFA"):
        result = ingest_elo_ratings(
            fetched_at="2026-06-17T12:00:00+00:00",
            fetched_date="2026-06-17",
            transport=lambda _url: tsv_fixture,
            url="https://fake.test/",
            bronze_dir=tmp_path / "bronze",
            gold_path=gold_path,
        )

    # Todos los equipos del DATASET_ALIASES deben estar mapeados desde el TSV real
    assert result.n_mapped == 48
    # Los alpha-2 sin entrada en ALPHA2_TO_CODE son descartados
    assert result.n_discarded > 0

    # El gold existe y tiene las columnas correctas
    assert gold_path.is_file()
    df = pd.read_csv(gold_path)
    assert list(df.columns) == ["fetched_date", "team_code", "elo"]

    # Todos los códigos en el gold son válidos (pertenecen a DATASET_ALIASES)
    valid_codes = set(DATASET_ALIASES.values())
    assert all(code in valid_codes for code in df["team_code"])

    # El gold está ordenado por team_code (determinismo R3)
    assert list(df["team_code"]) == sorted(df["team_code"])

    # fetched_date en el gold
    assert all(df["fetched_date"] == "2026-06-17")


def test_wc_2026_selecciones_cubiertas(tmp_path: Path) -> None:
    """R2: los 40 equipos clasificados al WC 2026 están presentes en el gold."""
    from src.ingestion.elo_ratings import ingest_elo_ratings

    tsv_fixture = _read_fixture()
    gold_path = tmp_path / "gold" / "external_elo.csv"

    with pytest.warns(UserWarning, match="sin mapeo FIFA"):
        ingest_elo_ratings(
            fetched_at="2026-06-17T12:00:00+00:00",
            fetched_date="2026-06-17",
            transport=lambda _url: tsv_fixture,
            url="https://fake.test/",
            bronze_dir=tmp_path / "bronze",
            gold_path=gold_path,
        )

    df = pd.read_csv(gold_path)
    mapped_codes = set(df["team_code"])

    # 40 selecciones del WC 2026 según data/silver/matches.csv
    wc_2026_codes = {
        "ALG", "ARG", "AUS", "AUT", "BEL", "BIH", "BRA", "CAN", "CPV", "CUW",
        "CZE", "ECU", "EGY", "FRA", "GER", "HAI", "IRN", "IRQ", "CIV", "JPN",
        "JOR", "MEX", "MAR", "NED", "NZL", "NOR", "PAR", "QAT", "KSA", "SCO",
        "SEN", "RSA", "KOR", "ESP", "SWE", "SUI", "TUN", "TUR", "USA", "URU",
    }
    missing = wc_2026_codes - mapped_codes
    assert not missing, f"Selecciones WC 2026 ausentes del gold: {missing}"


def test_elo_valores_enteros_positivos(tmp_path: Path) -> None:
    """R2: los valores Elo en el gold son enteros positivos plausibles (>500)."""
    from src.ingestion.elo_ratings import ingest_elo_ratings

    tsv_fixture = _read_fixture()
    gold_path = tmp_path / "gold" / "external_elo.csv"

    with pytest.warns(UserWarning, match="sin mapeo FIFA"):
        ingest_elo_ratings(
            fetched_at="2026-06-17T12:00:00+00:00",
            fetched_date="2026-06-17",
            transport=lambda _url: tsv_fixture,
            url="https://fake.test/",
            bronze_dir=tmp_path / "bronze",
            gold_path=gold_path,
        )

    df = pd.read_csv(gold_path)
    assert (df["elo"] > 500).all(), "Elo inusualmente bajo (<= 500)"
    assert (df["elo"] < 3000).all(), "Elo inusualmente alto (>= 3000)"


def test_sco_mapea_desde_sq_no_desde_sc(tmp_path: Path) -> None:
    """R2/bug-fix: SCO obtiene el Elo de SQ (~1794) y NO el del minnow SC (~853).

    eloratings.net usa SQ para Scotland (Elo real) y SC para Seychelles (minnow).
    El mismapeo SC→SCO asignaba Elo 853 a Scotland — absurdo para una selección WC.
    """
    from src.ingestion.elo_ratings import ingest_elo_ratings

    tsv_fixture = _read_fixture()
    gold_path = tmp_path / "gold" / "external_elo.csv"

    with pytest.warns(UserWarning, match="sin mapeo FIFA"):
        ingest_elo_ratings(
            fetched_at="2026-06-17T12:00:00+00:00",
            fetched_date="2026-06-17",
            transport=lambda _url: tsv_fixture,
            url="https://fake.test/",
            bronze_dir=tmp_path / "bronze",
            gold_path=gold_path,
        )

    df = pd.read_csv(gold_path)
    sco_rows = df[df["team_code"] == "SCO"]

    # SCO debe estar presente exactamente una vez
    assert len(sco_rows) == 1, f"SCO debe aparecer 1 vez en el gold, encontrado: {len(sco_rows)}"

    sco_elo = int(sco_rows.iloc[0]["elo"])
    # SQ=1794 en la fixture; SC=853 sería el valor incorrecto del minnow
    assert sco_elo > 1500, (
        f"SCO tiene Elo {sco_elo} — parece el minnow SC (~853) y no Scotland real (SQ~1794). "
        "Verificar que ALPHA2_TO_CODE mapea 'SQ' → 'SCO' y no 'SC' → 'SCO'."
    )
    # Verificar valor exacto contra la fixture (SQ=1794)
    assert sco_elo == 1794, f"SCO debería ser 1794 (SQ en fixture), obtenido: {sco_elo}"


def test_ninguna_seleccion_wc2026_elo_menor_1000(tmp_path: Path) -> None:
    """R2/sanity: ninguna selección del WC 2026 presente en gold tiene Elo < 1000.

    Test de cordura para cazar mismapeos futuros: un Elo < 1000 para cualquier
    participante del Mundial indica que se está leyendo un equipo minnow incorrecto.
    """
    from src.ingestion.elo_ratings import ingest_elo_ratings

    tsv_fixture = _read_fixture()
    gold_path = tmp_path / "gold" / "external_elo.csv"

    with pytest.warns(UserWarning, match="sin mapeo FIFA"):
        ingest_elo_ratings(
            fetched_at="2026-06-17T12:00:00+00:00",
            fetched_date="2026-06-17",
            transport=lambda _url: tsv_fixture,
            url="https://fake.test/",
            bronze_dir=tmp_path / "bronze",
            gold_path=gold_path,
        )

    df = pd.read_csv(gold_path)

    # Selecciones clasificadas al WC 2026 que deberían estar en el gold
    wc_2026_codes = {
        "ALG", "ARG", "AUS", "AUT", "BEL", "BIH", "BRA", "CAN", "CPV", "CUW",
        "CZE", "ECU", "EGY", "FRA", "GER", "HAI", "IRN", "IRQ", "CIV", "JPN",
        "JOR", "MEX", "MAR", "NED", "NZL", "NOR", "PAR", "QAT", "KSA", "SCO",
        "SEN", "RSA", "KOR", "ESP", "SWE", "SUI", "TUN", "TUR", "USA", "URU",
    }
    df_wc = df[df["team_code"].isin(wc_2026_codes)]
    low_elo = df_wc[df_wc["elo"] < 1000]

    assert low_elo.empty, (
        f"Selecciones WC 2026 con Elo < 1000 (posible mismapeo a minnow): "
        f"{low_elo[['team_code', 'elo']].to_dict('records')}"
    )


# ---------------------------------------------------------------------------
# R3 — gold determinista
# ---------------------------------------------------------------------------


def test_gold_determinista_misma_entrada(tmp_path: Path) -> None:
    """R3: misma entrada → mismo contenido gold byte a byte."""
    from src.ingestion.elo_ratings import ingest_elo_ratings

    tsv_fixture = _read_fixture()
    gold_path_1 = tmp_path / "gold1" / "external_elo.csv"
    gold_path_2 = tmp_path / "gold2" / "external_elo.csv"

    with pytest.warns(UserWarning, match="sin mapeo FIFA"):
        ingest_elo_ratings(
            fetched_at="2026-06-17T12:00:00+00:00",
            fetched_date="2026-06-17",
            transport=lambda _url: tsv_fixture,
            url="https://fake.test/",
            bronze_dir=tmp_path / "bronze1",
            gold_path=gold_path_1,
        )
    with pytest.warns(UserWarning, match="sin mapeo FIFA"):
        ingest_elo_ratings(
            fetched_at="2026-06-17T12:00:00+00:00",
            fetched_date="2026-06-17",
            transport=lambda _url: tsv_fixture,
            url="https://fake.test/",
            bronze_dir=tmp_path / "bronze2",
            gold_path=gold_path_2,
        )

    assert gold_path_1.read_bytes() == gold_path_2.read_bytes()


# ---------------------------------------------------------------------------
# R9 — seguridad / sin red real
# ---------------------------------------------------------------------------


def test_no_red_real_en_tests() -> None:
    """R9: el módulo importa sin red real (import puro, sin llamada HTTP)."""
    # Si el import levanta o hace red, el test falla
    import src.ingestion.elo_ratings  # noqa: F401


def test_alpha2_to_code_cubre_dataset_aliases() -> None:
    """R2/R9: ALPHA2_TO_CODE cubre todos los códigos de DATASET_ALIASES."""
    from src.ingestion.elo_ratings import ALPHA2_TO_CODE
    from src.ingestion.public_data import DATASET_ALIASES

    mapped_project_codes = set(ALPHA2_TO_CODE.values())
    all_alias_codes = set(DATASET_ALIASES.values())
    missing = all_alias_codes - mapped_project_codes
    assert not missing, (
        f"Códigos de DATASET_ALIASES sin entrada en ALPHA2_TO_CODE: {missing}"
    )
