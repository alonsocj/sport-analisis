---
name: project-feature5-qa
description: Feature 5 backtesting QA findings — defects, patterns, trazabilidad gaps found in review
metadata:
  type: project
---

## Feature 5 Backtesting — QA Review (2026-06-09)

**Veredicto: APROBADO CON OBSERVACIONES**

### Hallazgos clave

1. **R10 test vacío (MEDIO)**: `test_backtest_exito_y_reporte` (el test nombrado en tasks.md para R10 success path) tiene cero assertions. Es el primer test en `test_cli_backtest.py` y el desarrollador dejó comentarios explicando la limitación. La cobertura real existe en `test_backtest_exito_con_silver_custom` (que sí hace monkeypatch y asserts), pero no está en el mapeo oficial de tasks.md. La trazabilidad nominalmente apunta a un test sin valor.

2. **R2 gap de boundary (BAJO)**: El test `test_anti_fuga_mutar_futuro_no_cambia_predicciones` muta filas con `date >= '2024-02-01'` (posterior a la ventana). Esto NO detecta si el filtro fuera `<=` en vez de `<` en el límite exacto del inicio de ventana (2024-01-01). La implementación usa `date < as_of_date` (correcto), pero el test no lo verifica directamente. La rama `else` del test es código muerto con `n_per_pair=20`. Esto es una limitación de la spec, no un bug de implementación.

3. **R9 verificación top-level**: El test de determinismo solo verifica que las claves TOP-LEVEL del JSON estén ordenadas. El test no verifica claves anidadas (config, metrics, etc.). La implementación usa `sort_keys=True` que ordena todos los niveles — verificado manualmente. Gap cosmético de cobertura de test.

### Enmienda R12 — OK

- Contrato público intacto: `fit_dixon_coles` añade `use_analytic_jac=True` con default compatible. PARAMS_KEYS no cambió. 31 tests feature 3 verdes sin modificación.
- check_grad usa epsilon=1.49e-8 (sqrt de machine eps), no 1e-5 como podría parecer. Los 4 puntos de prueba incluyen rho positivo/negativo/grande.
- test_optimo_equivalente_jac_on_off: NLL relativo <= 1e-6, params principales <= 1e-4.

### summary.json producción

- Claves top-level y anidadas: todas ordenadas.
- Config: completa (11 campos de BacktestConfig serializados).
- low_data: 27 equipos con attack/defense, low_data_en_torneo=False.
- Modelo vs baselines: log-loss 0.894 (modelo) vs 1.054 (marginal) vs 1.099 (uniforme) — modelo bate ambos baselines.

### Patrón recurrente

El patrón de "test vacío o debilitado para el test nombrado en tasks.md + test real con nombre diferente" aparece también en feature 4 (test_cli.py subset weakening). Es un patrón recurrente del implementador cuando hay dificultad de inyección de paths en CLI sin flag --silver.

**Why:** El CLI no expone --silver como flag (decisión de diseño intencional), por lo que las pruebas de integración con silver customizado requieren monkeypatch, que el primer test no hace.

**How to apply:** En reviews futuras, verificar que el test nombrado en tasks.md R10 tiene assertions reales, no solo que existe y pasa.
