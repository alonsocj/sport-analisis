# tasks.md — Feature 26: forma_xg

Checklist. Cada R<n> con ≥1 test. Depende de F16 (forma), F18 (índice), F23 (silver xG). Sin
libs nuevas. NO toca DC/roster/mercados. Optimización equivalente con use_xg=False.

## Implementación

- [ ] T1. `src/form/window.py`: `MatchInWindow` con `xg_for`/`xg_against`; `index_matches_by_team`
      y `build_window*` leen `home_xg`/`away_xg` (null→None) — R1.
- [ ] T2. `src/form/metrics.py` + `config.py`: `team_form(..., use_xg=False)` con mezcla
      xG/gol por partido (fallback) y mismos pesos; `FormConfig.use_xg` default False — R2, R3.
- [ ] T3. `src/form/factor.py`: `make_form_factor_fn`/`make_form_factory` propagan `use_xg`;
      `use_xg=False` ≡ F16 exacto (1e-9) — R3.
- [ ] T4. `src/cli.py`: flag `--form-xg` en predict/backtest/simulate; subcomandos intactos — R4.
- [ ] T5. Tests `tests/test_form_xg.py` (offline, silver con/sin xG) — ver tabla.

## Tests (mapeo R<n> → test)

| Req | Test |
|-----|------|
| R1  | `::test_ventana_lleva_xg_y_fallback_null` |
| R2  | `::test_metrica_usa_xg_donde_hay_y_gol_donde_no`, `::test_pesos_recencia_se_conservan` |
| R3  | `::test_use_xg_false_equivale_f16_1e9`, `::test_ventana_sin_xg_equivale_goles` |
| R4  | `tests/test_cli_form.py::test_form_xg_flag` (o en test_form_xg), `::test_subcomandos_exactos_intactos` |
| R5  | `::test_backtest_forma_goles_vs_xg_reproducible` |
| R6  | transversal (offline, as_of inyectado, degradación, sin libs nuevas) |

## Cierre

- [ ] T6. Suite completa verde (604 previos + nuevos), `bash init.sh` verde, sin warnings.
- [ ] T7. Review (Reviewer): no-regresión use_xg=False (1e-9); fallback xG→gol; anti-fuga;
      flag --form-xg en los 3 subcomandos; subcomandos intactos.
- [ ] T8. **VALIDACIÓN/VEREDICTO (LEADER)**: backtest WC forma-goles vs forma-xG (mismo γ) →
      reportar Brier/log-loss/exactitud; ¿el xG mejora la forma?
- [ ] T9. Actualizar `feature_list.json` (26 → done + veredicto), `progress/current.md`, `README.md`, `MEMORY.md`.
