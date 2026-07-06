# tasks.md — Feature 27: ingesta_r16_fotmob

Checklist. Cada R<n> con ≥1 test. Red real solo en ejecución explícita (STOP); tests con
transporte inyectado + fixtures `__NEXT_DATA__`. Depende de F2 (silver), F21 (roster),
F23 (fotmob_stats). Sin libs nuevas (`requests` ya está).

## Implementación

- [ ] T1. `src/ingestion/fotmob_ko.py`: `KoMatch`, `parse_playoff_bracket`, `fetch_bracket`,
      `write_ko_fixtures` (r16 + r8) — R1, R6.
- [ ] T2. `src/ingestion/fotmob_stats.py`: capturar `home_goals`/`away_goals` en el parser y
      persistir en el JSON; lectura tolerante a JSON viejo — R2, R3.
- [ ] T3. `src/features/silver.py`: segundo paso que materializa filas KO desde el índice
      fotmob (marcador no nulo, sin fila martj42), `source="fotmob"`; enriquecimiento de grupos
      intacto (no-regresión) — R4, R5.
- [ ] T4. `src/cli.py`: subcomandos `ingest-ko` y `build-ko-fixtures`; previos intactos — R1,R6.
- [ ] T5. Ejecución real (STOP, aprobada): scrape bracket + 18 KO → bronze; `build_all` → gold;
      escribir `r16_fixtures.csv` / `r8_fixtures.csv` — R3, R7.
- [ ] T6. Tests (offline, fixtures) — ver tabla.

## Tests (mapeo R<n> → test)

| Req | Test |
|-----|------|
| R1  | `test_ingest_r16_fotmob.py::test_parse_bracket_rondas_y_marcadores`, `::test_ronda_ausente_no_falla` |
| R2  | `test_ingest_r16_fotmob.py::test_extractor_captura_goles`, `::test_json_viejo_sin_goles_tolerante` |
| R3  | `test_ingest_r16_fotmob.py::test_ko_sin_stats_persiste_con_marcador` |
| R4  | `test_silver_ko_materializa.py::test_materializa_filas_ko`, `::test_grupos_no_regresion` |
| R5  | `test_silver_ko_materializa.py::test_ko_con_fila_existente_no_duplica` |
| R6  | `test_ingest_r16_fotmob.py::test_write_r16_r8_fixtures_esquema`, `::test_tbd_no_fuerza_codigo` |
| R7  | `test_silver_ko_materializa.py::test_build_all_incluye_ko` |
| R8  | transversal (sin red en tests, fetched_at inyectado, degradación, sin libs nuevas) |

## Cierre

- [ ] QA: R1–R8 trazables, tests verdes, no-regresión silver de grupos (mutación).
- [ ] Security: sin red en tests, escritura bajo data/, sin libs nuevas, sin secretos.
- [ ] Registrar `feature 27` done en `feature_list.json` con nota de resultados medidos.
