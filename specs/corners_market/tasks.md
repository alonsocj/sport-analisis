# tasks.md — Feature 24: corners_market

Checklist. Cada R<n> con ≥1 test. Depende de F23 (silver con córners), F4 (patrón markets),
F22 (detalle KO). Sin libs nuevas. NO toca el modelo DC, forma, roster.

## Implementación

- [ ] T1. `src/markets/corners.py`: `CornersConfig`, `team_corner_rates` (shrinkage, leak-free),
      `expected_corners`, `corners_over_under` (Poisson), `corners_summary` (con n_matches) — R1, R2, R3.
- [ ] T2. `src/cli.py`: subcomando `corners HOME AWAY [--as-of] [--lines] [--json]`; subcomandos
      previos intactos — R4.
- [ ] T3. `src/app/tabs/knockouts.py`: en el sub-tab Mercados del detalle KO, añadir sección
      córners O/U (total+equipo) con aviso de muestra; degrada sin datos — R5.
- [ ] T4. Tests: `tests/test_corners_market.py`, `tests/test_cli_corners.py` (offline, silver fixture) — ver tabla.

## Tests (mapeo R<n> → test)

| Req | Test |
|-----|------|
| R1  | `test_corners_market.py::test_shrinkage_tira_a_global_con_n_bajo`, `::test_anti_fuga_as_of`, `::test_equipo_sin_datos_prior_global` |
| R2  | `::test_expected_corners_combina_ataque_defensa` |
| R3  | `::test_over_under_poisson_suma_uno`, `::test_lineas_por_equipo` |
| R4  | `test_cli_corners.py::test_corners_basico_y_json`, `::test_subcomandos_exactos_intactos` |
| R5  | `test_corners_market.py::test_app_mercados_incluye_corners_o_degrada` (o en el test del detalle KO) |
| R6  | transversal (offline, as_of inyectado, degradación, aviso muestra chica, sin libs nuevas) |

## Cierre

- [ ] T5. Suite completa verde (558 previos + nuevos), `bash init.sh` verde, sin warnings.
- [ ] T6. Review (Reviewer): trazabilidad R1–R6 ↔ tests; shrinkage; anti-fuga; degradación;
      subcomandos intactos + corners; aviso de muestra chica presente.
- [ ] T7. **Validación (LEADER)**: `corners CAN RSA --as-of 2026-06-28` razonable; revisar que
      con n=3 el resultado tira a la media global.
- [ ] T8. Actualizar `feature_list.json` (24 → done), `progress/current.md`, `README.md`.
