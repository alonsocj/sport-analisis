---
name: feature14-elo-externo-ensemble
description: Feature 14 elo_externo_ensemble implementada — ensemble DC+Elo, 27 tests nuevos, 364 total, 13 subcomandos CLI
metadata:
  type: project
---

Feature 14 `elo_externo_ensemble` implementada y suite completa verde (364 passed).

**Archivos creados:**
- `src/ingestion/elo_ratings.py` — descarga eloratings.net (transporte inyectable), parser seguro lxml (pandas.read_html flavor="lxml"), validación columnas o EloParseError, mapeo DATASET_ALIASES, bronze+meta, caché TTL 7d
- `src/elo_ext/__init__.py` — paquete vacío
- `src/elo_ext/model.py` — sub-modelo Elo→1X2, fórmula expected_score, parámetro empate d, fuente as-of (elo_history) vs externo (live), guard EloExternoEnBacktestError
- `src/elo_ext/ensemble.py` — ensemble (1-w)·pDC + w·pElo, renormalizado; ajuste w/d por backtest walk-forward (rejilla W_GRID × D_GRID)
- `tests/fixtures/eloratings_sample.html` — fixture HTML offline para tests
- `tests/test_ingest_elo.py` — 8 tests (R1, R2, R3, R9)
- `tests/test_elo_model.py` — 13 tests (R3, R4, R5, R6, R7)
- `tests/test_cli_elo.py` — 6 tests (R8)

**Archivos modificados:**
- `src/cli.py` — cmd_ingest_elo, _apply_elo_ensemble, --elo-weight en predict/predict-log/simulate, subcomando ingest-elo; 12→13 subcomandos
- `tests/test_cli.py` — actualizado a 13 subcomandos
- `tests/test_cli_eval.py` — actualizado a 13 subcomandos
- `tests/test_cli_scorers.py` — actualizado a 13 subcomandos
- `tests/test_cli_simulate.py` — actualizado a 13 subcomandos

**Decisiones clave:**
- Parser seguro: pandas.read_html(flavor="lxml") — nunca etree.fromstring sobre HTML crudo
- Anti-fuga R7: predict_elo_backtest levanta EloExternoEnBacktestError si use_external=True
- Equivalencia v1: w=0.0 devuelve p_DC exactas (tol 1e-9), verificado con test
- Fórmula draw: p_draw = d·(1−|2E−1|), banda proporcional al equilibrio
- w=0.0 default en predict/predict-log/simulate → comportamiento idéntico a v1

**Why:** El Elo externo (eloratings) solo tiene snapshot actual, no series históricas, por eso no es backtesteable sin fuga. El ensemble a nivel de probabilidad (no refit) garantiza w=0 = v1 exacto.

**How to apply:** Para backtest de ensemble usar always `predict_elo_backtest(..., use_external=False)`. Para predicción live usar `predict_elo_live(...)` o `--elo-weight > 0` en CLI.

13 subcomandos CLI: ingest-public, build-features, train, predict, schedule, markets, backtest, predict-log, evaluate, ingest-goalscorers, scorers, simulate, ingest-elo.

Pendientes T8 (validación real con red, requiere OK del usuario), T9 (dictamen security-lead del código), T10 (actualizar feature_list.json).
