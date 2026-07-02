---
name: feature12-modelo-v2-completada
description: Feature 12 modelo_v2 completada — importance weighting, 23 tests nuevos, 296 total, equivalencia v1 verificada.
metadata:
  type: project
---

Feature 12 `modelo_v2` implementada el 2026-06-17.

**Archivos creados:**
- `src/models/importance.py` — mapa tier→factor, clasificación substring, TIER_FACTORS, IDENTITY_FACTORS, build_importance_map, identity_importance_map.

**Archivos modificados:**
- `src/models/dixon_coles.py` — load_training_data/fit_dixon_coles aceptan importance_map opcional; DEFAULT_PARAMS_PATH_V2; load_params acepta model_version; save_params acepta extra_metadata.
- `src/backtest/walkforward.py` — run() acepta importance_map.
- `src/backtest/report.py` — run_grid() con importance_scales; write_report() con importance_scales.
- `src/eval/prediction_log.py` — log_predictions acepta model_version e importance_map.
- `src/eval/evaluate.py` — evaluate() acepta model_version_filter.
- `src/cli.py` — flags nuevos en train, predict, markets, predict-log, evaluate, backtest.

**Tests creados:**
- `tests/test_dixon_coles_importance.py` (3 tests: R1×2, R3×1)
- `tests/test_modelo_v2.py` (7 tests: R2×3, R4×2, R5×1, R7×1)
- `tests/test_cli_train_v2.py` (13 tests: R6×13)
- Total: 23 tests nuevos, 296 total.

**Principio de no-regresión verificado:**
- test_default_identidad_equivale_v1 pasa con tol 1e-9.
- Los 273 tests previos siguen en verde.

**Flags nuevos por subcomando:**
- `train`: `--model-version {dc-v1,dc-v2}`, `--importance {off,default}`
- `predict`: `--model-version {dc-v1,dc-v2}`
- `markets`: `--model-version {dc-v1,dc-v2}`
- `predict-log`: `--model-version {dc-v1,dc-v2}`, `--importance {off,default}`
- `evaluate`: `--model-version` (filtro por versión)
- `backtest`: `--importance-scales S1,S2,...` (grid v2)

**Decisión clave de clasificación de torneo:**
- TIER_KEYWORDS ordena qualifier ANTES de world_cup para que "FIFA World Cup Qualification" → qualifier (no world_cup). Copa del Mundo "FIFA World Cup" → world_cup por keyword "fifa world cup".

**Deuda técnica:**
- T8 (validación real re-grid + comparación v1 vs v2 con torneo) pendiente de datos reales.
- Subcomando count sigue en 11 (no cambia).

**Why:** Mejorar precisión del modelo Dixon-Coles para el Mundial 2026 incorporando peso por importancia de partido sin romper el comportamiento v1.
