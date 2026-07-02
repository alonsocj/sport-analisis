---
name: feature16-forma-reciente-completada
description: Feature 16 forma_reciente completada — multiplicador exp(γ·z) sobre λ DC, 45 tests nuevos, 458 total, 14 subcomandos CLI intactos.
metadata:
  type: project
---

Feature 16 `forma_reciente` implementada y cerrada.

**Why:** Ajuste post-predicción de λ_home/λ_away según forma reciente de cada equipo. Multiplicador exp(γ·z) sobre el Dixon-Coles existente sin re-entrenar.

**Archivos creados:**
- `src/form/__init__.py`, `config.py`, `window.py`, `metrics.py`, `factor.py`
- `tests/test_forma_reciente.py` (R1, R2 — 15 tests)
- `tests/test_form_factor.py` (R3, R4, R5 — 18 tests)
- `tests/test_cli_form.py` (R6 — 12 tests)

**Archivos modificados:**
- `src/models/dixon_coles.py` — `predict_match(form_factor=None)`
- `src/simulation/montecarlo.py` — `run_simulation(form_factor=None)`, `precompute_match_params`, `_compute_single_match_params`, `simulate_elimination_match`, `_simulate_one`
- `src/backtest/walkforward.py` — `run(form_factory=None)`
- `src/backtest/report.py` — `write_report(form_factory=None)`, `run_backtest(form_factory=None)`
- `src/cli.py` — `--form-weight G` en predict/backtest/simulate; helper `_build_form_factor`

**Gates verificados:**
- NO-REGRESIÓN (γ=0 → factor=1.0, tol 1e-9): PASS
- Anti-fuga (date < as_of strict): PASS
- Degradación (ventana vacía → factor 1.0, equipo sin Elo → q=1.0): PASS
- Subcomandos intactos (exactamente 14): PASS
- Suite completa: 458 passed

**How to apply:** Próximas features con ajuste post-predicción siguen el mismo patrón de callable opcional inyectado como parámetro.
