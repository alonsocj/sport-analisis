# tasks.md — Feature 28: jugadores_xi_fotmob

Cada R<n> con ≥1 test. Red real sólo en ejecución explícita (STOP); tests con fixtures.
Depende de F27 (bracket), F21 (patrón roster). Sin libs nuevas.

## Implementación

- [ ] T1. `src/ingestion/fotmob_lineup.py`: `PlayerXI`, `parse_match_lineup`,
      `fetch_and_persist_lineup`, `ingest_lineups` (usa `fetch_bracket`) — R1, R2.
- [ ] T2. `src/features/lineup_strength.py`: `build_lineup_strength`,
      `write_lineup_strength` (xi/att/def_rating, split por posición) — R3, R4.
- [ ] T3. `src/cli.py`: `ingest-lineups`, `build-lineup-strength`; previos intactos — R5.
- [ ] T4. Ejecución real (STOP): scrape XI de octavos (jugados+por jugar) → bronze;
      build-lineup-strength → gold — R2, R3.
- [ ] T5. Tests: `tests/test_fotmob_lineup.py`, `tests/test_lineup_strength.py` — ver tabla.

## Tests (mapeo R<n> → test)

| Req | Test |
|-----|------|
| R1  | `test_fotmob_lineup.py::test_parse_xi_ratings`, `::test_sin_lineup_no_aborta` |
| R2  | `test_fotmob_lineup.py::test_persiste_bronze_meta` |
| R3  | `test_lineup_strength.py::test_fuerza_xi_att_def`, `::test_jugador_sin_rating_omitido` |
| R4  | `test_lineup_strength.py::test_sin_bronze_no_rompe` |
| R5  | `test_fotmob_lineup.py::test_subcomandos_exactos` |
| R6  | transversal (sin red, fetched_at inyectado, sin libs nuevas) |

## Cierre

- [ ] QA R1–R6 trazables, tests verdes, no-regresión.
- [ ] Registrar feature 28 done con cobertura medida (n partidos, n equipos con XI).
