---
name: project-feature14-qa
description: QA findings for feature 14 elo_externo_ensemble — aprobado con observaciones; deuda silenciosa en prediction_log; 367 passed
metadata:
  type: project
---

Feature 14 `elo_externo_ensemble` — revisado 2026-06-17. Resultado: APROBADO CON OBSERVACIONES.

**Suite**: 367 passed (337 previos intactos + 30 nuevos), 0 warnings, 0 fallos.

**Hallazgos:**

1. BAJO — Degradación silenciosa en `src/eval/prediction_log.py` línea 480-483: cuando `elo_weight > 0` pero `elo_history` no existe en disco, el ensemble no se aplica y `model_version` queda `dc-v1` sin ninguna advertencia al usuario. El código tiene un comentario pero no emite `warnings.warn`. No produce resultados incorrectos (degrada a DC puro correctamente), pero el usuario podría creer que el ensemble se aplicó.

**Verificaciones críticas superadas:**
- No-regresión w=0: diferencia exactamente 0.00e+00 para los 3 componentes (tol 1e-9 cumplida)
- Anti-fuga: `ratings_as_of` usa `date < as_of_date` (exclusión estricta), confirmado manualmente
- Guard `EloExternoEnBacktestError`: efectivo, levanta con `use_external=True`
- Parser seguro: `pandas.read_html(flavor='lxml')` exclusivamente — sin `etree.fromstring` en código activo
- `simulate` sin `--elo-weight`: confirmado, decisión documentada en design.md y docstring
- 13 subcomandos exactos: conjunto idéntico al esperado en `EXPECTED_SUBCOMMANDS`
- Trazabilidad R1-R9: todos los tests de tasks.md existen y ejecutan correctamente

**Divergencia design.md vs implementación (no es defecto):**
- design.md dice `--elo-weight` en predict usa Elo externo (snapshot live); prediction_log usa `elo_history` as-of. Esto es correcto y por diseño (predict = live, predict-log = medición backtest-compatible). El `_apply_elo_ensemble` en cli.py usa `predict_elo_live`; `_predict_row` en prediction_log.py usa `predict_elo` (elo_history as-of). Ambas rutas son correctas para sus contextos.

**Patrón recurrente de deuda:** segunda vez que una degradación silenciosa sin warning queda documentada en comentario pero sin `warnings.warn` (feature 10 también tenía este patrón).
