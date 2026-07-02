# tasks.md — Feature 5: backtesting

Checklist de implementación. Cada R<n> con ≥1 test (el reviewer rechaza si falta).
Secuencia: T1 puede arrancar de inmediato; T2–T6 SOLO tras cerrar la feature 4
(conflicto de archivo en `src/cli.py`, ver design «Secuencia»).

## Implementación

- [x] T1. ENMIENDA feature 3: `_grad_nll_weighted` + `fit_dixon_coles(...,
      use_analytic_jac=True)` con `jac=` en L-BFGS-B; camino numérico conservado
      bajo flag — R12. Tests en `tests/test_dixon_coles_jac.py` (archivo nuevo;
      suite previa intacta).
- [x] T2. `src/backtest/walkforward.py`: `BacktestConfig`, ventanas month/week,
      refits reales, predicciones por ventana, skipped con motivo — R1–R3.
- [x] T3. `src/backtest/metrics.py`: log-loss (sklearn), Brier multiclase propio,
      exactitud, calibración (sklearn, degradación por clase escasa), baselines
      uniforme/marginal — R4–R6.
- [x] T4. `src/backtest/roi.py`: esquema CSV de cuotas, validación/descartes,
      matching, value bets, ROI; ausencia → omisión con aviso — R8.
- [x] T5. `src/backtest/report.py`: `run_backtest`/`run_grid`, summary.json
      (sort_keys, low_data R13), windows.csv, calibration.csv — R7, R9, R13.
- [x] T6. `src/cli.py`: subcomando `backtest` (patrón existente; subcomandos
      previos intactos) — R10. `src/app/tabs/modelo.py`: sección Backtest
      (lee summary.json, tolerante) — R11.

## Tests (mapeo R<n> → test)

| Req | Test |
|-----|------|
| R1  | `test_backtest.py::test_ventanas_month_week_y_rango` |
| R2  | `test_backtest.py::test_anti_fuga_mutar_futuro_no_cambia_predicciones` |
| R3  | `test_backtest.py::test_refits_reales_y_skipped_con_motivo` |
| R4  | `test_backtest.py::test_logloss_brier_exactitud_oraculo_a_mano` |
| R5  | `test_backtest.py::test_calibracion_bins_y_degradacion` |
| R6  | `test_backtest.py::test_baselines_uniforme_y_marginal` |
| R7  | `test_backtest.py::test_grid_ranking_orden_y_solo_con_flag` |
| R8  | `test_backtest.py::test_roi_value_bets_oraculo`, `::test_roi_sin_csv_omitido`, `::test_roi_descartes_malformados` |
| R9  | `test_backtest.py::test_reporte_determinista_mismo_contenido` |
| R10 | `test_cli_backtest.py::test_backtest_exito_y_reporte`, `::test_errores_accionables_exit_codes`, `::test_subcomandos_previos_intactos` |
| R11 | `test_app_backtest_ui.py::test_seccion_backtest_con_summary`, `::test_seccion_backtest_sin_summary` |
| R12 | `test_dixon_coles_jac.py::test_gradiente_vs_numerico`, `::test_optimo_equivalente_jac_on_off`, `::test_convergencia_con_jac` |
| R13 | `test_backtest.py::test_low_data_en_summary_y_aviso_torneo` |

## Cierre

- [x] T7. Suite completa verde (todos los previos + nuevos), `bash init.sh` verde.
- [x] T8. Ejecución real de validación: `python -m src.cli backtest` sobre el
      silver real; pegar resumen en progress/current.md (métricas vs baselines).
- [x] T9. Review (Reviewer): trazabilidad R1–R13 ↔ tests; enmienda R12 con suite
      feature 3 intacta; extensiones mínimas en cli.py/modelo.py.
- [x] T10. Dictamen security-lead (sin red; escritura SOLO en out_dir bajo data/).
- [x] T11. Actualizar `feature_list.json` (5 → done), `progress/current.md`,
      `README.md` (subcomando backtest + esquema CSV de cuotas).
