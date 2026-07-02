# tasks.md — Feature 21: roster_fotmob

Checklist. Cada R<n> con ≥1 test. Red real solo en ejecución explícita (regla STOP); tests
con transporte inyectado + fixtures. Depende de F11 (scorers/player_factor), F20 (panel),
ingestion.teams (to_fifa_code). Sin libs nuevas (`requests` ya está).

## Implementación

- [ ] T1. `src/ingestion/roster.py`: `fetch_playoff_match_urls`, `fetch_match_lineup`
      (transporte inyectable, bronze+meta con `fetched_at` inyectado, rate-limit, UA, caché,
      saltar partido en error de red), `normalize_rosters` (to_fifa_code, disponibles vs no
      disponibles, cobertura) — R1, R2.
- [ ] T2. `src/cli.py`: subcomando `ingest-roster` (red real, transporte real; patrón
      ingest-wiki-stats); subcomandos previos intactos — R4.
- [ ] T3. `src/app/tabs/knockouts.py`: el panel de goleadores (F20) filtra no disponibles y
      renormaliza si hay roster; nota de bajas; sin roster → comportamiento F20 — R3.
- [ ] T4. Tests: `tests/test_ingest_roster.py`, `tests/test_roster_normalize.py`,
      `tests/test_app_knockouts_roster.py` (offline, fixtures `__NEXT_DATA__`) — ver tabla.

## Tests (mapeo R<n> → test)

| Req | Test |
|-----|------|
| R1  | `test_ingest_roster.py::test_transporte_inyectable_y_bronze_meta`, `::test_partido_sin_lineup_no_aborta`, `::test_error_red_salta_partido` |
| R2  | `test_roster_normalize.py::test_mapeo_fifa_y_disponibles_vs_no`, `::test_roster_csv_schema_compatible_con_flag`, `::test_equipo_sin_mapeo_descartado` |
| R3  | `test_app_knockouts_roster.py::test_filtra_no_disponibles_y_renormaliza`, `::test_sin_roster_igual_a_f20`, `::test_nota_bajas_presente` |
| R4  | `test_ingest_roster.py::test_cli_ingest_roster`, `::test_subcomandos_exactos_intactos` |
| R5  | transversal (sin red en tests, `fetched_at` inyectado, degradación, escritura bajo data/, sin libs nuevas) |

## Cierre

- [ ] T5. Suite completa verde (494 previos + nuevos), `bash init.sh` verde, sin warnings.
- [ ] T6. Review (Reviewer): trazabilidad R1–R5 ↔ tests; transporte inyectado/sin red en
      tests; roster compatible con `--roster`; degradación; subcomandos intactos + ingest-roster.
- [ ] T7. Dictamen security-lead (UA, rate-limit, caché, solo GET público, sin secrets).
- [ ] T8. **VALIDACIÓN REAL (con OK usuario)**: `ingest-roster` (red, fotmob) sobre R32 →
      reportar cobertura + ejemplo (RSA sin Zwane) + scorers con/sin roster.
- [ ] T9. Actualizar `feature_list.json` (21 → done), `progress/current.md`, `README.md`, `MEMORY.md`.
