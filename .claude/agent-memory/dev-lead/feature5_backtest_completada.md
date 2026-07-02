---
name: feature5-backtest-completada
description: Feature 5 backtesting completada — T2-T6, 20 tests nuevos, 211 total, backtest real OK.
metadata:
  type: project
---

Feature 5 backtesting T2-T6 implementada y verde (2026-06-09).

**Por qué:** Evaluación honesta del modelo Dixon-Coles con walk-forward sin fuga temporal.

**Archivos creados:**
- `src/backtest/walkforward.py` — BacktestConfig, ventanas month/week, refits reales, skipped (R1-R3)
- `src/backtest/metrics.py` — log-loss/Brier/exactitud/calibración/baselines (R4-R6)
- `src/backtest/roi.py` — CSV de cuotas, value bets, ROI (R8)
- `src/backtest/report.py` — run_backtest/run_grid, summary.json/windows.csv/calibration.csv (R7,R9,R13)
- `tests/test_backtest.py` — 13 tests cubriendo R1-R9, R13
- `tests/test_cli_backtest.py` — 6 tests cubriendo R10
- `tests/test_app_backtest_ui.py` — 2 tests cubriendo R11

**Archivos modificados:**
- `src/cli.py` — añadido subcomando `backtest` (7 subcomandos total)
- `src/app/tabs/modelo.py` — sección Backtest con st.metric si existe summary.json
- `tests/test_cli.py` — test_subcomandos_exactos actualizado de 6 → 7

**Decisión técnica crítica:** sklearn.metrics.log_loss espera columnas en orden léxico
sorted(labels). Para OUTCOME_ORDER=("1","X","2"), sorted=("1","2","X"), hay que
reordenar las columnas antes de pasar a sklearn. Ver `_SKL_COL_MAP` en metrics.py.

**Resultado del backtest real (data/silver/matches.csv, 2024-01-01, mensual):**
- 2510 partidos evaluados, 7 omitidos, 30 refits, 7.5 segundos
- Modelo: log-loss=0.8943, Brier=0.5264, exactitud=59.16%
- Uniforme: log-loss=1.0986, Brier=0.6667, exactitud=47.41%
- Marginal: log-loss=1.0540, Brier=0.6358, exactitud=47.41%
- low_data_en_torneo=False (27 equipos low_data pero ninguno de las 48 del torneo)

**How to apply:** La próxima feature puede usar BacktestConfig y write_report directamente.
Referencia: [[streamlit_apptest_pattern]] para tests UI.
