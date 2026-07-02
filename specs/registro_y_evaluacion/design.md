# design.md — Feature 10: registro_y_evaluacion

## Arquitectura

Paquete nuevo y aislado `src/eval/` + extensión mínima a `src/cli.py` (dos
subcomandos). Reusa, sin duplicar: `src/models/dixon_coles.py` (fit/predict),
`src/markets/goals.py` (O/U, BTTS), `src/backtest/metrics.py` (log-loss, Brier,
exactitud, calibración, baselines) y la lógica de fixtures pendientes de
`schedule` (`src/cli.py`). NO se instala nada nuevo.

| Módulo                       | Responsabilidad                                                        | Requisitos |
|------------------------------|-----------------------------------------------------------------------|------------|
| `src/eval/__init__.py`       | Paquete vacío.                                                         | —          |
| `src/eval/prediction_log.py` | Genera predicciones (1X2 + λ + mercados opc.) para fixtures y las anexa al log con upsert determinista. Timestamp inyectado. | R1–R5      |
| `src/eval/evaluate.py`       | Cruza log ↔ resultados reales; métricas 1X2, calibración, Brier de mercado, error de λ; escritura determinista del reporte. | R6–R11     |
| `src/cli.py` (extensión)     | Subcomandos `predict-log` y `evaluate` (patrón existente; previos intactos). | R12, R13 |

Flujo:

```
# Registro (backward = reconstrucción jornada 1; o forward = jornada futura)
fixtures objetivo (schedule pendientes | CSV)
   └─► predict-log --as-of D --timestamp T [--markets]
         load_training_data(silver, as_of=D) ─► fit_dixon_coles  (fecha < D, R3)
         por fixture: predict_match ─► (p_home,p_draw,p_away, λh, λa)
                      [--markets] markets.goals ─► (p_over25, p_btts)
         upsert por (match_id, as_of_date, model_version) ─► data/predictions/log.csv  (R1,R2,R4)

# Evaluación
data/predictions/log.csv  +  data/silver/matches.csv
   └─► evaluate [--from --to] [--markets]
         join por match_id (fallback date+equipos)  ─► evaluables / skipped (R6)
         metrics.evaluate (reusa backtest)          ─► log-loss, Brier, exactitud (R7)
         metrics.calibration                        ─► curva por bins (R8)
         [--markets] Brier O/U2.5, BTTS             ─► (R9)
         RMSE/MAE de λ vs goles reales              ─► (R10)
         report ─► data/reports/evaluacion/{summary.json, per_match.csv, calibration.csv}  (R11)
```

## Contrato del log (R1, R4)

`data/predictions/log.csv`, columnas en orden fijo:

```
created_at, model_version, as_of_date, match_date, match_id, home_code, away_code,
p_home, p_draw, p_away, lambda_home, lambda_away, p_over25, p_btts, neutral
```

- `created_at`: ISO-8601 **inyectado** por argumento `--timestamp` (R2). Nunca
  `datetime.now()`. Misma política anti-reloj que features 5 y 7.
- `model_version`: cadena del modelo usado, p.ej. `"dc-v1"` (Dixon-Coles de
  producción). Permite distinguir reconstrucciones de versiones futuras (v2).
- `as_of_date`: fecha de corte del entrenamiento (R3).
- `match_id`: el mismo identificador del silver (hash estable) para el join (R6).
- Clave de upsert (R4): (`match_id`, `as_of_date`, `model_version`). El archivo se
  reescribe ordenado por (`match_date`, `match_id`, `as_of_date`) → determinista.
- `p_over25`/`p_btts`: vacías si no se pidió `--markets`.

## Generación out-of-sample (R3, R5)

- `load_training_data(silver, as_of=D, ...)` + `fit_dixon_coles` reales; el filtro
  `fecha < as_of_date` de la feature 3 garantiza la anti-fuga (R3). El test muta
  resultados posteriores a `D` y comprueba predicciones idénticas (1e-12).
- Objetivos (`--targets`): por defecto los fixtures WC2026 pendientes del bronze
  público (reusa `_pending_world_cup_rows`/`_team_label` de `schedule`); o un CSV
  de fixtures provisto. Equipo fuera del recorte → `skipped`
  `equipo_fuera_de_recorte` (R5), nunca aborta.
- **Reconstrucción jornada 1**: `predict-log --as-of 2026-06-11
  --timestamp <iso>` entrena con datos `< 2026-06-11` (silver llega a 2026-06-08,
  todos los partidos de jornada 1 son ≥ 2026-06-11 → out-of-sample limpio) y
  predice los 20 fixtures jugados. El fit L-BFGS-B parte de init fijo → mismas
  probabilidades en reejecución (R11 determinismo).

## Evaluación y métricas (R6–R11)

- **Join (R6)**: por `match_id`; si el log carece de él (CSV externo), fallback a
  `match_date` + códigos/nombres normalizados. Marcador real ausente → `skipped`.
- **1X2 (R7)**: `metrics.evaluate` del backtest sobre `y_true ∈ {"1","X","2"}` y
  matriz `probs` n×3 en orden `("1","X","2")`. Desenlace real desde
  `home_goals`/`away_goals`. Oráculo a mano en el test.
- **Calibración (R8)**: utilidad de bins del backtest sobre la prob del desenlace
  observado; degradación cuando un bin queda escaso (igual que feature 5).
- **Mercados (R9)**: `over_real = (hg+ag) > 2.5`; `btts_real = hg≥1 y ag≥1`. Brier
  binario `mean((p − o)²)`.
- **Error de λ (R10)**: `RMSE`/`MAE` de `(lambda_home, lambda_away)` vs
  `(home_goals, away_goals)` apilados.
- **Reporte (R11)**: `summary.json` con `sort_keys=True` (agregados 1X2,
  calibración resumida, mercados si aplica, error λ, conteos evaluable/skipped),
  `per_match.csv` (una fila por partido: probs, desenlace, contribución a métricas)
  y `calibration.csv`. Escritura solo bajo `data/reports/evaluacion/`. Determinista
  byte a byte.

## CLI (R12, R13)

- `predict-log --as-of <fecha> --timestamp <iso> [--markets] [--targets
  schedule|<ruta_csv>] [--results-csv <bronze>] [--out <log>]`. Sin params de
  producción entrenables → entrena al vuelo con `as_of`. Exit `0/1/2`. La aserción
  de subcomandos del proyecto se endurece al conjunto EXACTO previo + los dos
  nuevos (patrón de la feature 4).
- `evaluate [--from <fecha>] [--to <fecha>] [--markets] [--log <ruta>]
  [--silver <ruta>] [--out <dir>]`. Sin log → exit 1 accionable; sin evaluables →
  exit 0 con mensaje. Imprime tabla resumen (modelo vs, opcional, baselines del
  backtest para contexto).

## Decisiones y justificación

- **Log append-only con upsert vs sobrescritura total**: append-only preserva el
  histórico de jornadas; el upsert por clave evita duplicados al reejecutar una
  misma jornada. Orden determinista hace el archivo apto para diff/control.
- **Reconstrucción por `--as-of` único (2026-06-11) para v1**: evalúa "lo que dijo
  v1 antes del torneo". El refit por-jornada (incorporar resultados previos) es
  comportamiento de la feature 12 (modelo_v2), no de v1; mantenerlo fuera aquí
  preserva la honestidad del diagnóstico de v1.
- **Reusar `backtest.metrics`**: misma definición de log-loss/Brier/calibración
  que el backtest histórico → comparables directamente. Cero duplicación.
- **Sin red ni API**: la ingesta de actuales usa los comandos existentes; los
  tests corren offline con fixtures. Escritura confinada a `data/`.

## Fuera de alcance (explícito)

Pestaña de evaluación en la app Streamlit (futuro opcional); mejoras al modelo
(features 11–13); ROI/cuotas (cubierto por feature 5). Córners/tarjetas siguen
excluidos (decisión usuario).
