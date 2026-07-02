---
name: enmienda-hiperparametros-20260611
description: Cambio de defaults de producción DCConfig/BacktestConfig según grid walk-forward feature 5; aprobado usuario 2026-06-11
metadata:
  type: project
---

Defaults de producción actualizados: `xi: 0.65 → 0.35`, `reg_lambda: 1.0 → 0.25`.

**Why:** Grid walk-forward feature 5 (17 configs, 2 510 partidos) mostró que xi=0.35/λ=0.25
da log-loss 0.8641 vs 0.8943 del anterior. El usuario eligió esta config robusta sobre la
esquina mínima 0.2/0.1 (0.8606) por un margen < 0.4 % de diferencia; con xi=0.35 los datos
de 2018 pesan ~6 %, aportando contexto histórico sin sobreponderar el pasado remoto.

**How to apply:** El modelo entrenado en disco (data/gold/dixon_coles_params.json) aún usa los
parámetros anteriores; requiere reentrenamiento con `train --as-of-date YYYY-MM-DD` para
que los parámetros reflejen los nuevos defaults. No hay que cambiar from_date (2018-01-01
se conserva — la evidencia del grid se midió con esa ventana).

Archivos modificados: `src/models/dixon_coles.py` (DCConfig), `src/backtest/walkforward.py`
(BacktestConfig), `specs/modelo_resultado/design.md` (enmienda al final),
`specs/backtesting/design.md` (nota en Decisiones). Tests: ninguno tocado (no había
aserciones hardcodeadas de los valores default 0.65/1.0 en los dataclasses).

Ver [[feature5_backtest_completada]].
