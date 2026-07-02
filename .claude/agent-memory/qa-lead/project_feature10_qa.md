---
name: project-feature10-qa
description: QA findings for Feature 10 (registro_y_evaluacion) — R1-R13 trazabilidad, 3 desviaciones declaradas, 227 passed
metadata:
  type: project
---

Feature 10 aprobada con observaciones (2026-06-17). 227 tests passed. 34 tests nuevos.

## Desviaciones declaradas y dictamen

**Desviación A (_assert_under_data eliminada de prediction_log.py):**
- evaluate.py TIENE la guarda en write_report -> aceptable para R11 (reporte de evaluacion).
- prediction_log.py NO tiene guarda en log_predictions(). El --out del CLI no valida que esté bajo data/. Riesgo real pero menor (contexto CLI local, mismo usuario). Aceptado con observación BAJO.

**Desviación B (test R2 grep del fuente):**
- El test R2 tiene DOS partes: (1) grep de 'datetime.now()' en el fuente con ruta RELATIVA, (2) verificación de comportamiento real (mismo timestamp -> mismo created_at).
- La parte 2 es la verificación real de R2 y es correcta.
- La parte 1 es frágil: ruta relativa (falla si CWD != raiz del proyecto), solo detecta dos patrones concretos.
- No es tautológico (el grep busca en el fuente, no en el test), pero es un cheque estático incompleto.
- Aceptado como observación BAJO.

**Desviación C (marginal 1/3 en evaluate.py para calibración R8):**
- compute_calibration usa probs reales del modelo (probs[:, k]), NO las marginales.
- Las marginales 1/3 solo afectarían a make_marginal_probs() que NO se invoca en evaluate.py.
- R8 implementado correctamente. INOCUO.

## Imports no utilizados en tests (linting)
- tests/test_prediction_log.py importa: `inspect`, `textwrap`, `UPSERT_KEY` sin usarlos en el cuerpo.
- No afecta funcionalidad pero viola convenciones de limpieza.

## Patrones de calidad observados
- Oráculo a mano en R7 y R9 con tolerancia 1e-9: MUY BUENO.
- Test R3 anti-fuga real con silver mutado: correcto y robusto.
- Test R4 upsert con timestamps distintos y verificación de orden: correcto.
- test_cli.py actualizado correctamente (9 subcomandos, conjunto exacto).
- Reusor de backtest.metrics y markets.goals sin duplicacion: CORRECTO.

## Patrones recurrentes de calidad negativa
- Imports no utilizados en test files (ya visto en features 4 y 5).
- Rutas relativas en tests (ya declarado en feature 5 con `inspect.getsource()`).
