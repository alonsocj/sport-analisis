# tasks.md — Feature 10: registro_y_evaluacion

Checklist de implementación. Cada R<n> con ≥1 test (el reviewer rechaza si falta).
Secuencia: T0 (ingesta operativa) → T1 → T2 → T3 → T4 → T5 → cierre.

## Implementación

- [ ] T0. **Ingesta operativa** (sin código nuevo): `python -m src.cli
      ingest-public` + `python -m src.cli build-features` para traer los 20
      resultados reales de la jornada 1 (CC0) a `silver/gold`. Verificar que el
      silver pasa de fecha máx. 2026-06-08 a incluir 2026-06-11..16. NO consume
      cuota (fuente CC0).
- [ ] T1. `src/eval/__init__.py` (vacío) + `src/eval/prediction_log.py`: esquema
      del log, generación 1X2+λ (+mercados opc.), timestamp inyectado, upsert
      determinista, objetivos `schedule|CSV`, skipped por equipo fuera de recorte
      — R1–R5.
- [ ] T2. `src/eval/evaluate.py`: join log↔silver, métricas 1X2 (reusa
      `backtest.metrics`), calibración, Brier de mercado, error de λ, reporte
      determinista — R6–R11.
- [ ] T3. `src/cli.py` (extensión): subcomandos `predict-log` y `evaluate`
      (patrón existente; previos intactos, aserción de conjunto exacto) — R12, R13.
- [ ] T4. Tests `tests/test_prediction_log.py`, `tests/test_evaluate.py`,
      `tests/test_cli_eval.py` (offline, fixtures; sin red) — ver tabla.
- [ ] T5. **Reconstrucción real jornada 1**: `predict-log --as-of 2026-06-11
      --timestamp <iso>` (20 fixtures) → `evaluate --markets`; pegar métricas en
      `progress/current.md`.

## Tests (mapeo R<n> → test)

| Req | Test |
|-----|------|
| R1  | `test_prediction_log.py::test_esquema_columnas_y_probs_suman_uno` |
| R2  | `test_prediction_log.py::test_timestamp_inyectado_sin_reloj` |
| R3  | `test_prediction_log.py::test_anti_fuga_as_of_mutar_futuro_no_cambia` |
| R4  | `test_prediction_log.py::test_upsert_sin_duplicados_y_orden_determinista` |
| R5  | `test_prediction_log.py::test_objetivos_pendientes_y_skipped_equipo_fuera` |
| R6  | `test_evaluate.py::test_join_match_id_y_skipped_pendientes` |
| R7  | `test_evaluate.py::test_logloss_brier_exactitud_oraculo` |
| R8  | `test_evaluate.py::test_calibracion_bins_y_degradacion` |
| R9  | `test_evaluate.py::test_brier_mercados_over25_y_btts` |
| R10 | `test_evaluate.py::test_rmse_mae_lambda_vs_goles` |
| R11 | `test_evaluate.py::test_reporte_determinista_solo_bajo_data` |
| R12 | `test_cli_eval.py::test_predict_log_exito`, `::test_subcomandos_exactos_intactos`, `::test_predict_log_exit_codes` |
| R13 | `test_cli_eval.py::test_evaluate_exito_y_reporte`, `::test_evaluate_sin_log_error`, `::test_evaluate_sin_evaluables_exit0` |

## Cierre

- [ ] T6. Suite completa verde (previos + nuevos), `bash init.sh` verde.
- [ ] T7. Review (Reviewer): trazabilidad R1–R13 ↔ tests; sin red; escritura solo
      bajo `data/`; reusa `backtest.metrics`/`markets.goals` sin duplicar.
- [ ] T8. Dictamen security-lead (sin red; timestamp inyectado; escritura confinada).
- [ ] T9. Actualizar `feature_list.json` (10 → done; promover 11 → pending),
      `progress/current.md`, `README.md` (subcomandos `predict-log`, `evaluate` +
      esquema del log).
