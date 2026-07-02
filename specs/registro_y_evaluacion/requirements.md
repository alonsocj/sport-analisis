# requirements.md — Feature 10: registro_y_evaluacion

Objetivo: cerrar el gap "sin registro de predicciones" del pipeline y medir
honestamente **predicho-vs-ocurrido** sobre el slate real del Mundial 2026. Dos
capacidades:

1. **Log de predicciones** append-only y reproducible (timestamp INYECTADO, no
   reloj), que sirve tanto para reconstruir las predicciones de la jornada ya
   jugada (out-of-sample, `--as-of` pre-torneo) como para registrar de forma
   honesta las predicciones de jornadas futuras.
2. **Evaluación** que cruza el log con los resultados reales del silver y reporta
   métricas 1X2 (log-loss, Brier, exactitud), calibración, Brier por mercado
   (O/U 2.5, BTTS) y error de goles esperados (λ vs goles reales).

La **ingesta** de resultados reales NO añade código: se hace con los comandos
existentes `ingest-public` + `build-features` (la fuente CC0 ya trae los 20
marcadores de la jornada 1; el silver descarta filas sin marcador y el refit ya
filtra `fecha < as_of`). Las mejoras al modelo (peso por importancia, refit
intra-torneo), el factor de jugadores y la simulación Monte Carlo quedan
**fuera de alcance** (features 11, 12, 13).

Notación EARS. Cada `R<n>` mapea a ≥1 test en `tests/test_prediction_log.py`,
`tests/test_evaluate.py` o `tests/test_cli_eval.py` (ver `tasks.md`).

---

**R1 — Esquema del log de predicciones.**
El sistema DEBE persistir un log append-only en `data/predictions/log.csv` con
columnas fijas y orden documentado: `created_at`, `model_version`, `as_of_date`,
`match_date`, `match_id`, `home_code`, `away_code`, `p_home`, `p_draw`, `p_away`,
`lambda_home`, `lambda_away`, `p_over25`, `p_btts`, `neutral`. Las probabilidades
`p_home + p_draw + p_away` DEBEN sumar 1 (tolerancia 1e-9). Las columnas de
mercado (`p_over25`, `p_btts`) DEBEN quedar vacías cuando no se piden mercados.

**R2 — Timestamp inyectado, sin reloj.**
CUANDO se genera una entrada de log, el sistema DEBE usar el `created_at` provisto
como argumento (ISO-8601 validado), NUNCA del reloj del sistema. Un test DEBE
verificar que dos generaciones con el mismo timestamp inyectado producen el mismo
`created_at` y que no se lee `datetime.now()`/reloj.

**R3 — Generación out-of-sample por `as_of`.**
CUANDO se generan predicciones con `--as-of D`, el modelo DEBE entrenarse usando
exclusivamente partidos con `fecha < D` (filtro de la feature 3) y predecir los
fixtures objetivo. Un test DEBE verificar la propiedad anti-fuga: alterar o
eliminar resultados con `fecha >= D` NO cambia las predicciones generadas
(tolerancia 1e-12).

**R4 — Append idempotente y orden determinista.**
CUANDO se registra un conjunto cuya clave (`match_id` + `as_of_date` +
`model_version`) ya existe en el log, el sistema DEBE actualizar en sitio (upsert)
sin crear duplicados. El archivo persistido DEBE quedar ordenado de forma
determinista por (`match_date`, `match_id`, `as_of_date`).

**R5 — Predicción de fixtures pendientes.**
El sistema DEBE poder tomar como objetivo los fixtures WC2026 pendientes del bronze
público (reusa la lógica de `schedule`). SI un equipo del fixture no está en el
modelo del refit (fuera del recorte de entrenamiento), ENTONCES ese fixture DEBE
omitirse con motivo `equipo_fuera_de_recorte`, sin abortar el resto.

**R6 — Cruce predicho-vs-ocurrido.**
CUANDO se ejecuta `evaluate`, el sistema DEBE unir el log de predicciones con los
resultados reales del silver por `match_id` (o, si falta, por `match_date` +
equipos normalizados). Los fixtures sin marcador real DEBEN contabilizarse como
`skipped` (pendientes), no como error.

**R7 — Métricas 1X2.**
El sistema DEBE calcular, agregado y por partido, sobre los partidos evaluables:
**log-loss** multiclase, **Brier** multiclase y **exactitud** (argmax con
desempate determinista `1, X, 2`), REUSANDO `src/backtest/metrics.py`. Un test
DEBE verificar los valores contra un oráculo calculado a mano.

**R8 — Calibración.**
El sistema DEBE producir una curva de calibración por bins (reusa la utilidad de
`src/backtest/metrics.py`) sobre la probabilidad asignada al desenlace observado,
con degradación controlada cuando un bin queda escaso.

**R9 — Brier por mercado (opcional).**
DONDE `--markets` esté presente, el sistema DEBE calcular el Brier binario de
**O/U 2.5** (over real = `home_goals + away_goals > 2.5`) y **BTTS** (real =
`home_goals ≥ 1 y away_goals ≥ 1`) contra `p_over25` y `p_btts`. SIN `--markets`,
estas métricas se omiten.

**R10 — Error de goles esperados.**
El sistema DEBE reportar RMSE y MAE entre los goles esperados (`lambda_home`,
`lambda_away`) y los goles reales (`home_goals`, `away_goals`) de los partidos
evaluables.

**R11 — Reporte determinista en disco.**
El sistema DEBE escribir `data/reports/evaluacion/summary.json` (con `sort_keys`),
`per_match.csv` y `calibration.csv`. La misma entrada DEBE producir el mismo
contenido byte a byte (fit determinista; sin reloj). La escritura DEBE limitarse a
rutas bajo `data/`.

**R12 — CLI `predict-log`.**
El sistema DEBE exponer el subcomando `predict-log --as-of <fecha>
--timestamp <iso> [--markets] [--targets schedule|<ruta_csv>]` que genera y
persiste las predicciones. Errores accionables con exit codes (`0` éxito,
`1` error accionable, `2` error de argumentos). Un test DEBE verificar que el
conjunto EXACTO de subcomandos previos permanece intacto (más los nuevos).

**R13 — CLI `evaluate`.**
El sistema DEBE exponer `evaluate [--from <fecha>] [--to <fecha>] [--markets]` que
lee el log y el silver, calcula las métricas, escribe el reporte e imprime una
tabla. SI no existe log → error accionable (ejecutar `predict-log` primero, exit
1). SI no hay partidos evaluables (todo pendiente) → mensaje claro y exit 0.
