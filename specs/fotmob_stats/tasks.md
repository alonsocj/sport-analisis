# tasks.md — Feature 23: fotmob_stats

Checklist. Cada R<n> con ≥1 test. Red real solo en ejecución explícita (STOP); tests con
transporte inyectado + fixtures. Depende de F2 (silver), ingestion.teams, F21 (patrón roster).
Sin libs nuevas (`requests` ya está). Solo ingesta + población silver (NO mercados).

## Implementación

- [ ] T1. `src/ingestion/fotmob_stats.py`: `fetch_match_urls` (liga 77, partidos jugados),
      `parse_match_stats` (mapeo títulos fotmob → claves proyecto, incl. xG y cards=AM+R),
      `fetch_and_persist` (bronze+meta, fetched_at inyectado, rate-limit, saltar en error),
      `normalize_stats` (to_fifa_code, filas por date+equipos, cobertura) — R1, R2.
- [ ] T2. `src/features/silver.py`: merge de stats fotmob por `(date,home_code,away_code)` →
      poblar columnas avanzadas + añadir `home_xg/away_xg`; bronze ausente → silver idéntico
      (no-regresión) — R3.
- [ ] T3. `src/cli.py`: subcomando `ingest-fotmob-stats`; subcomandos previos intactos — R4.
- [ ] T4. Tests: `tests/test_ingest_fotmob_stats.py`, `tests/test_silver_fotmob_stats.py`
      (offline, fixtures `__NEXT_DATA__`) — ver tabla.

## Tests (mapeo R<n> → test)

| Req | Test |
|-----|------|
| R1  | `test_ingest_fotmob_stats.py::test_transporte_inyectable_y_bronze_meta`, `::test_parse_mapeo_titulos_xg_cards`, `::test_partido_sin_stats_no_aborta` |
| R2  | `test_ingest_fotmob_stats.py::test_mapeo_fifa_y_filas`, `::test_equipo_sin_mapeo_omitido` |
| R3  | `test_silver_fotmob_stats.py::test_merge_pobla_columnas`, `::test_sin_bronze_silver_identico_no_regresion`, `::test_xg_columnas_anadidas` |
| R4  | `test_ingest_fotmob_stats.py::test_cli_ingest_fotmob_stats`, `::test_subcomandos_exactos_intactos` |
| R5  | transversal (sin red en tests, fetched_at inyectado, degradación, escritura bajo data/, sin libs nuevas) |

## Cierre

- [ ] T5. Suite completa verde (532 previos + nuevos), `bash init.sh` verde, sin warnings.
- [ ] T6. Review (Reviewer): trazabilidad R1–R5 ↔ tests; transporte inyectado; merge por
      date+equipos; no-regresión sin bronze; subcomandos intactos + ingest-fotmob-stats.
- [ ] T7. Dictamen security-lead (UA, rate-limit, solo GET público, sin secrets).
- [ ] T8. **VALIDACIÓN REAL (con OK usuario)**: `ingest-fotmob-stats` (red) sobre WC2026 jugados
      + `build-features` → reportar cobertura y un ejemplo (RSA 0-1 CAN: shots 6/12, córners
      1/4, xG 0.13/1.32) ya en el silver.
- [ ] T9. Actualizar `feature_list.json` (23 → done), `progress/current.md`, `README.md`, `MEMORY.md`.
