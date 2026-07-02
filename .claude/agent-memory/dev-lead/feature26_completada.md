---
name: feature26-forma-xg-completada
description: Feature 26 forma_xg implementada: xG-diff en ventana de forma, interruptor use_xg, flag --form-xg CLI, 18 tests nuevos, 622 total.
metadata:
  type: project
---

Feature 26 `forma_xg` implementada (2026-06-28) por IMPLEMENTER. PENDIENTE validación LEADER (T8: backtest veredicto).

**Archivos modificados:**
- `src/form/window.py`: `MatchInWindow` + `xg_for`/`xg_against` (None=default), `_make_record` acepta home_xg/away_xg, `index_matches_by_team` lee columnas con fallback NaN→None
- `src/form/metrics.py`: `team_form(..., use_xg=False)` — xG-diff por partido donde hay, gol-diff fallback; resultado en `gd_w` (reusar campo existente)
- `src/form/factor.py`: `make_form_factor_fn(..., use_xg=False)` y `make_form_factory(..., use_xg=False)` propagan flag a `team_form`
- `src/cli.py`: `_build_form_factor(form_weight, as_of, use_xg=False)` + flag `--form-xg` en predict/backtest/simulate
- `tests/test_cli_form.py`: 2 monkeypatches actualizados a `lambda gamma, as_of, use_xg=False: ...`
- `tests/test_form_xg.py`: 18 tests nuevos (R1–R6)
- `feature_list.json`: corregido JSON duplicado preexistente (bloque `}\n  ]\n}` duplicado al final)

**Suite:** 622 passed (604 previos + 18 nuevos). `bash init.sh` verde.

**Decisiones:**
- `gd_w` reutilizado para señal xG (no campo nuevo en FormMetrics) — interfaz estable
- `use_xg` como param explícito, NOT en FormConfig (es flag por-llamada, no config permanente)
- Mezcla por partido: xG donde ambos not-None, gol-diff otherwise — maximiza cobertura WC

**LEADER backtest veredicto (R5/T8):**
```bash
# Sin xG (baseline goles):
.venv/bin/python -m src.cli backtest --from-date 2026-06-11 --to-date 2026-06-28 --form-weight 0.2

# Con xG:
.venv/bin/python -m src.cli backtest --from-date 2026-06-11 --to-date 2026-06-28 --form-weight 0.2 --form-xg
```

**Why:** Cobertura parcial (solo WC2026 en ventana tiene xG) — efecto limitado en ventana mixta (~3/8 partidos).

**How to apply:** Feature 26 cerrada en código; LEADER decide si adoptar --form-xg como default basado en veredicto.
