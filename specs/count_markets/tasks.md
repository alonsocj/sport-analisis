# tasks.md — Feature 25: count_markets

Checklist. Cada R<n> con ≥1 test. Depende de F23 (silver con stats), F24 (córners, patrón),
F22 (detalle KO). Sin libs nuevas. NO toca DC/forma/roster/goals.py/corners.py.

## Implementación

- [ ] T1. `src/markets/counts.py`: `STAT_SPECS` (cards/shots/sot), `count_rates` (shrinkage,
      leak-free), `expected_counts`, `count_over_under` (Poisson), `count_summary` (n_matches) — R1, R2.
- [ ] T2. `src/cli.py`: subcomando `count-market HOME AWAY --stat {cards,shots,sot} [...]`;
      subcomandos previos intactos — R3.
- [ ] T3. `src/app/tabs/knockouts.py`: en el sub-tab Mercados del detalle KO, añadir tarjetas/
      tiros/SoT (O/U); aviso de ruido en tarjetas; degrada sin datos — R4.
- [ ] T4. Tests: `tests/test_count_markets.py`, `tests/test_cli_count.py` (offline) — ver tabla.

## Tests (mapeo R<n> → test)

| Req | Test |
|-----|------|
| R1  | `test_count_markets.py::test_shrinkage_por_stat`, `::test_anti_fuga_as_of`, `::test_stat_ausente_degrada` |
| R2  | `::test_over_under_poisson_suma_uno_por_stat`, `::test_lineas_default_por_stat` |
| R3  | `test_cli_count.py::test_count_market_cards_shots_sot_json`, `::test_subcomandos_exactos_intactos`, `::test_stat_invalido_error` |
| R4  | `test_count_markets.py::test_app_mercados_incluye_stats_o_degrada`, `::test_tarjetas_lleva_aviso_ruido` |
| R5  | transversal (offline, as_of inyectado, degradación, avisos, sin libs nuevas) |

## Cierre

- [ ] T5. Suite completa verde (573 previos + nuevos), `bash init.sh` verde, sin warnings.
- [ ] T6. Review (Reviewer): trazabilidad R1–R5 ↔ tests; shrinkage por stat; anti-fuga;
      degradación; subcomandos intactos + count-market; aviso de ruido en tarjetas.
- [ ] T7. **Validación (LEADER)**: `count-market CAN RSA --stat cards/shots --as-of 2026-06-29` razonable.
- [ ] T8. Actualizar `feature_list.json` (25 → done), `progress/current.md`, `README.md`.
