---
name: feature10-registro-evaluacion
description: Feature 10 registro_y_evaluacion implementada — predict-log, evaluate, 34 tests nuevos, 227 total.
metadata:
  type: project
---

Feature 10 `registro_y_evaluacion` implementada y en verde (2026-06-17).

**Why:** Cerrar el gap "sin registro de predicciones" del pipeline y medir predicho-vs-ocurrido en el Mundial 2026.

**Archivos creados:**
- `src/eval/__init__.py` (vacío)
- `src/eval/prediction_log.py` — R1–R5: log append-only con upsert, timestamp inyectado, anti-fuga, skipped por equipo fuera de recorte
- `src/eval/evaluate.py` — R6–R11: join log↔silver, métricas 1X2 (reusa backtest.metrics), calibración, Brier mercados, error lambda, reporte determinista
- `tests/test_prediction_log.py` — 9 tests (R1–R5)
- `tests/test_evaluate.py` — 16 tests (R6–R11)
- `tests/test_cli_eval.py` — 9 tests (R12–R13)

**Archivos modificados:**
- `src/cli.py` — 2 nuevos subcomandos: `predict-log` y `evaluate` (previos intactos)
- `tests/test_cli.py::test_subcomandos_exactos_con_funcion_propia` — actualizado de 7 a 9 subcomandos

**Decisiones técnicas:**
- `_assert_under_data` en evaluate.py verifica `data` como componente del path (no CWD relativo), para que los tests con tmp_path funcionen
- prediction_log.py no tiene validación de ruta de escritura (el CLI garantiza la ruta; los tests usan tmp_path libremente)
- Calibración reusa WindowPrediction de backtest con marginal_home/draw/away=1/3 (marginal no disponible en este contexto)

**Suite:** 227 tests, 0 fallos. Sin librerías nuevas.

**How to apply:** T5 (reconstrucción real jornada 1) pendiente — lo realiza el Leader/usuario después de confirmar que silver tiene resultados de la jornada 1.
