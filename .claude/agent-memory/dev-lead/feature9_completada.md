---
name: feature9-app-streamlit-completada
description: Feature 9 app_streamlit + Feature 4 mercados implementadas. 188 tests (1 fallo preexistente).
metadata:
  type: project
---

Feature 9 `app_streamlit` — tareas T4-T7 implementadas (2026-06-09).
Feature 4 `modelos_mercados` — T1-T4 implementadas (2026-06-09).

Archivos de Feature 4 creados/modificados:
- `src/markets/__init__.py`: paquete puro (solo docstring, sin imports).
- `src/markets/goals.py`: funciones puras O/U, BTTS, totales, market_summary, dataclasses.
- `src/cli.py`: subcomando markets añadido (extension aditiva, 6 subcomandos total).
- `src/app/tabs/calendario.py`: cuarta sub-pestaña Mercados en detalle predecible.
- `tests/test_markets.py`: 9 tests R1-R6, R9, R10.
- `tests/test_cli_markets.py`: 5 tests R7.
- `tests/test_app_markets_ui.py`: 2 tests R8.

Suite total: 188 tests, 187 passed, 1 fallo PREEXISTENTE (`test_fit_reporta_convergencia`
en test_dixon_coles_fit.py — fallo numérico del optimizador L-BFGS-B con datos sintéticos
pequeños, no introducido por ninguna feature).

**Why:** Implementacion de la capa de mercados pura sobre el contrato de la feature 3.

**How to apply:** `python -m src.cli markets HOME AWAY [--json] [--lines L1,L2,...]`.
