# requirements.md — Feature 5: backtesting

Objetivo: evaluar honestamente el modelo Dixon-Coles con un **backtest walk-forward
sin fuga temporal** sobre el histórico silver: métricas (log-loss, Brier,
exactitud), curvas de calibración y comparación contra baselines; búsqueda
opcional de hiperparámetros (ξ, reg_lambda); **ROI opcional** contra un CSV de
cuotas provisto por el usuario (no hay cuotas en disco y su ingesta queda fuera de
alcance). Incluye dos cierres de deuda de la feature 3: **gradiente analítico**
para L-BFGS-B (los refits repetidos del walk-forward lo exigen) y visibilidad del
**artefacto low-data** ('isle_of_man'). Resultados por CLI (`backtest`) + reporte
en disco + sección `Backtest` en la pestaña Modelo de la app (hueco reservado por
la feature 9). Primer uso de **scikit-learn** en el proyecto (ya instalado).

Notación EARS. Cada `R<n>` mapea a ≥1 test en `tests/test_backtest.py`,
`tests/test_dixon_coles_jac.py`, `tests/test_cli_backtest.py` o
`tests/test_app_backtest_ui.py` (ver `tasks.md`).

---

**R1 — Walk-forward sin reloj y parametrizable.**
El sistema DEBE particionar el histórico silver en ventanas de evaluación
cronológicas consecutivas dentro de un rango `[from_date, to_date]` parametrizable
(defaults: `from_date = "2024-01-01"`, `to_date` = fecha máxima del dataset), con
frecuencia de refit parametrizable (default: mensual). Ninguna fecha DEBE provenir
del reloj del sistema: solo del dataset y de los argumentos.

**R2 — Anti-fuga temporal estricta.**
Para cada ventana, el modelo DEBE entrenarse exclusivamente con partidos de fecha
**estrictamente anterior** al inicio de la ventana (`as_of_date` = día de inicio;
el filtro de entrenamiento de la feature 3 ya es `fecha < as_of_date`), y predecir
solo partidos dentro de la ventana. Un test DEBE verificar la propiedad: alterar o
eliminar partidos POSTERIORES a una ventana NO cambia las predicciones de esa
ventana (tolerancia 1e-12).

**R3 — Refits reales por ventana.**
Cada refit DEBE usar `fit_dixon_coles` real (sin mocks) con la configuración
vigente (ξ, reg_lambda, min_matches). SI una ventana no tiene partidos evaluables
(equipos fuera del recorte de entrenamiento → `UnknownTeamError`), ENTONCES esos
partidos DEBEN omitirse contabilizados como `skipped` (con motivo) sin abortar.

**R4 — Métricas 1X2.**
El sistema DEBE calcular, agregado y por ventana: **log-loss** multiclase
(`sklearn.metrics.log_loss` con `labels` fijos `["1","X","2"]`), **Brier
multiclase** (suma de cuadrados contra one-hot, fórmula documentada en el design) y
**exactitud** (argmax con desempate determinista orden `1, X, 2`). Los conteos
(`n_matches`, `n_skipped`) DEBEN acompañar cada métrica.

**R5 — Calibración.**
El sistema DEBE producir datos de curva de fiabilidad por desenlace (1, X, 2) con
`sklearn.calibration.calibration_curve` (bins parametrizables, default 10,
estrategia `quantile`), exportados en el reporte (R9). SI un desenlace tiene menos
muestras que bins, ENTONCES el sistema DEBE reducir bins o marcar la curva como no
computable sin abortar.

**R6 — Baselines.**
El sistema DEBE reportar las mismas métricas de R4 para dos baselines calculados
con la MISMA partición walk-forward: (a) **uniforme** (1/3, 1/3, 1/3) y
(b) **frecuencias marginales** de los desenlaces del conjunto de entrenamiento de
cada ventana. El reporte DEBE permitir comparar modelo vs baselines directamente.

**R7 — Búsqueda opcional de hiperparámetros.**
DONDE se invoque con la opción de grid (`--grid`), el sistema DEBE evaluar el
producto cartesiano de listas parametrizables de ξ y reg_lambda (defaults:
ξ ∈ {0.5, 0.65, 0.8}, reg_lambda ∈ {0.5, 1.0, 2.0}) con el MISMO protocolo
walk-forward, ordenar el ranking por log-loss ascendente (desempate Brier) y
reportarlo. Sin `--grid`, NO DEBE ejecutarse ninguna búsqueda (solo la
configuración vigente).

**R8 — ROI opcional contra cuotas del usuario.**
DONDE se proporcione un CSV de cuotas con el esquema documentado
(`date,home_code,away_code,odds_home,odds_draw,odds_away`, decimales europeos
> 1.0), el sistema DEBE calcular ROI de apuesta plana con criterio de value
(`prob_modelo × cuota > 1 + umbral`, umbral parametrizable default 0.05) sobre los
partidos casados por `(date, home_code, away_code)`, reportando: apuestas, aciertos,
stake total, retorno y ROI. SI el CSV no existe o ningún partido casa, ENTONCES la
sección ROI DEBE omitirse con un aviso claro, sin fallo. Filas de cuotas
malformadas (cuota ≤ 1.0, fecha inválida) DEBEN descartarse con conteo de
descartes.

**R9 — Reporte determinista en disco.**
El sistema DEBE escribir el reporte en un directorio parametrizable (default
`data/reports/backtest/`): `summary.json` (configuración, métricas agregadas,
baselines, low-data, ROI si aplica, ranking si aplica) y `windows.csv` (métricas
por ventana) y `calibration.csv`. Mismas entradas y argumentos → mismo contenido
(sin reloj, sin RNG); el JSON DEBE ser estable (claves ordenadas).

**R10 — CLI: subcomando `backtest`.**
El sistema DEBE añadir a `src/cli.py` el subcomando `python -m src.cli backtest
[--from-date F] [--to-date T] [--refit-every {month,week}] [--grid]
[--odds RUTA] [--out DIR]`. Éxito → resumen humano (log-loss/Brier/exactitud modelo
vs baselines, 1 línea por baseline) + `✅` con la ruta del reporte + exit `0`.
Silver ausente → `error:` accionable (`build-features`/`ingest-public`) en stderr y
exit `1`; argparse → exit `2`. Los subcomandos existentes NO DEBEN cambiar.

**R11 — App: sección Backtest en la pestaña Modelo.**
La pestaña Modelo DEBE mostrar una sección `Backtest` que, SI existe
`summary.json` en la ruta default, presenta las métricas clave (modelo vs
baselines, fecha `as_of` del reporte y n de partidos); SI no existe, muestra una
indicación de cómo generarlo (`python -m src.cli backtest`) sin fallar.

**R12 — Enmienda feature 3: gradiente analítico.**
`fit_dixon_coles` DEBE usar gradiente analítico de la NLL ponderada (incluida la
penalización ridge) en L-BFGS-B. Un test DEBE verificar el gradiente contra
aproximación numérica (`scipy.optimize.check_grad` o diferencias centrales,
tolerancia relativa documentada) en un dataset sintético; otro DEBE verificar que
el óptimo alcanzado en el fixture de la feature 3 coincide con el de la versión
numérica (tolerancia en parámetros o en NLL). La suite previa de la feature 3 DEBE
seguir verde sin modificar sus tests; el contrato público (firmas, JSON de params)
NO DEBE cambiar.

**R13 — Visibilidad del artefacto low-data.**
El `summary.json` DEBE incluir la lista de equipos `low_data` del entrenamiento
final (los de `params.low_data_teams`) con sus `attack`/`defense`, y un campo de
aviso booleano si alguna de las 48 selecciones del torneo está en esa lista. El
caso 'isle_of_man' (ataque inflado por pocos partidos) DEBE quedar documentado en
el design con la decisión tomada (mostrar, no recortar: el recorte de fuerzas es
no-objetivo).
