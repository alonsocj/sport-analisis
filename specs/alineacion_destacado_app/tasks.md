# tasks.md — Feature 31: alineacion_destacado_app

Cada R<n> con ≥1 test. Reusa F28 (bronze lineups), F11 (player_factor), F22 (detalle KO).

## Implementación

- [ ] T1. `fotmob_lineup.py`: `PlayerXI` + `_parse_players` capturan market_value/shirt_number/
      club/age; lectura tolerante — R1.
- [ ] T2. `src/features/lineup_view.py`: `find_lineup_doc`, `pick_crack`, `build_lineup_view`,
      `_norm`, `POS_LABELS` — R2, R3, R4.
- [ ] T3. `knockouts.py`: sub-pestaña "Alineación" en `_render_detalle_ko` — R5.
- [ ] T4. Re-scrape real (STOP): `ingest-lineups` → bronze con campos nuevos — R1.
- [ ] T5. Tests `tests/test_lineup_view.py` (pura) + `tests/test_app_alineacion.py` (AppTest).

## Tests (mapeo R<n> → test)

| Req | Test |
|-----|------|
| R1  | `test_lineup_view.py::test_parse_captura_campos_nuevos` (extractor) |
| R2  | `test_lineup_view.py::test_pick_crack_mayor_valor`, `::test_sin_valor_crack_none` |
| R3  | `test_lineup_view.py::test_goal_share_cruce_sin_acentos` |
| R4  | `test_lineup_view.py::test_build_view_orden_posicion_orientacion`, `::test_sin_doc_none` |
| R5  | `test_app_alineacion.py::test_subpestana_alineacion_presente` |
| R6  | transversal (pura sin red, AppTest sin excepción, sin libs nuevas) |

## Cierre

- [ ] QA R1–R6 trazables, tests verdes, no-regresión detalle KO.
- [ ] Registrar feature 31 done.
