# design.md — Feature 5: backtesting

## Arquitectura

Usa el paquete ya andamiado `src/backtest/` + enmienda quirúrgica a
`src/models/dixon_coles.py` (jac analítico) + extensiones mínimas a `src/cli.py`
(subcomando) y `src/app/tabs/modelo.py` (sección Backtest). Primer consumo de
scikit-learn (`sklearn.metrics.log_loss`, `sklearn.calibration.calibration_curve`)
— ya en requirements.txt, sin instalación nueva.

| Módulo                         | Responsabilidad                                                  | Requisitos |
|--------------------------------|-------------------------------------------------------------------|------------|
| `src/backtest/__init__.py`     | Ya existe (vacío); queda sin imports.                            | R1 |
| `src/backtest/walkforward.py`  | Ventanas cronológicas, refits, predicciones por ventana, skipped. | R1–R3 |
| `src/backtest/metrics.py`      | log-loss/Brier/exactitud, calibración, baselines (funciones puras). | R4–R6 |
| `src/backtest/roi.py`          | Carga/validación CSV de cuotas, matching, value bets, ROI.        | R8 |
| `src/backtest/report.py`       | Ensamblado y escritura determinista de summary.json/windows.csv/calibration.csv; grid runner. | R7, R9, R13 |
| `src/models/dixon_coles.py`    | ENMIENDA: `_grad_nll_weighted` + `jac=` en L-BFGS-B.              | R12 |
| `src/cli.py` (extensión)       | Subcomando `backtest`.                                            | R10 |
| `src/app/tabs/modelo.py` (ext.)| Sección Backtest (lee summary.json si existe).                    | R11 |

Flujo:

```
data/silver/matches.csv ──► walkforward.run(cfg)
   por ventana w:  train = partidos < w.start ──► fit_dixon_coles(as_of=w.start)
                   eval  = partidos en [w.start, w.end) ──► predict_match
                   (UnknownTeamError → skipped con motivo)
   ──► WindowResult(preds, reales, skipped)
metrics.evaluate(results) ──► modelo vs baselines + calibración
roi.evaluate(results, odds_csv?) ──► ROI (opcional)
report.write(out_dir) ──► summary.json + windows.csv + calibration.csv
                                   │
CLI backtest ──────────────────────┘        app/tabs/modelo.py lee summary.json
```

## Walk-forward (R1–R3)

- `@dataclass(frozen=True) BacktestConfig`: `from_date, to_date, refit_every
  ("month"|"week"), xi, reg_lambda, min_matches, bins, value_threshold, out_dir,
  odds_csv`.
- Ventanas: cortes en límites de mes/semana ISO calculados con `datetime.date`
  aritmético sobre las FECHAS DEL DATASET/argumentos (cero `today()`).
- Entrenamiento por ventana: `load_training_data(silver, as_of=w.start, ...)` +
  `fit_dixon_coles` reales (R3). El filtro `< as_of_date` de la feature 3 ya
  garantiza la exclusión estricta (R2); el test de la propiedad anti-fuga muta
  partidos posteriores y compara predicciones (1e-12).
- Partido evaluable: ambos equipos en `attack`/`defense` del refit de SU ventana;
  si no → `skipped` con motivo `equipo_fuera_de_recorte`.
- Coste: ~30 refits (mensual desde 2024) × fit con jac analítico (R12). El jac se
  implementa ANTES de correr el backtest completo (ver Secuencia).

## Métricas (R4–R6)

- Vectores: `y_true ∈ {"1","X","2"}`, `probs` matriz n×3 en orden fijo
  `OUTCOME_ORDER = ("1", "X", "2")`.
- log-loss: `sklearn.metrics.log_loss(y_true, probs, labels=list(OUTCOME_ORDER))`.
- **Brier multiclase** (documentado aquí, R4):
  `BS = (1/n) · Σ_i Σ_k (p_ik − o_ik)²` con `o_ik` one-hot del desenlace real
  (rango 0–2; 0 = perfecto). Implementación propia de 3 líneas con numpy (sklearn
  solo trae el caso binario).
- Exactitud: `argmax` por fila con desempate determinista por orden de
  `OUTCOME_ORDER` (numpy `argmax` ya toma el primer máximo — coincide).
- Baselines (R6): uniforme = matriz constante 1/3; marginal = frecuencias de
  desenlaces del train de cada ventana (vector por ventana, aplicado a sus
  partidos). Mismas funciones de métricas para los tres (modelo, uniforme,
  marginal).
- Calibración (R5): `calibration_curve(y_bin_k, probs[:, k], n_bins=bins,
  strategy="quantile")` por desenlace k; si `n_muestras_clase < bins` → reduce a
  `max(2, n_muestras_clase)` o marca `computable=False` (sin abortar).

## ROI opcional (R8)

- Esquema CSV (documentado para el usuario): cabecera exacta
  `date,home_code,away_code,odds_home,odds_draw,odds_away`; decimales europeos
  (> 1.0); matching por `(date, home_code, away_code)` contra los partidos
  evaluados.
- Value bet: para cada desenlace k, apuesta plana de 1 unidad SI
  `prob_modelo_k × cuota_k > 1 + umbral` (default 0.05; máx. una apuesta por
  desenlace y partido — pueden ser varias por partido si varias tienen value).
- ROI = (retorno − stake) / stake. Reporta `n_bets, n_wins, stake, retorno, roi,
  n_descartes_cuotas, n_sin_match`.
- Sin CSV (default actual: no hay cuotas en disco) → sección omitida + aviso. La
  INGESTA de cuotas queda explícitamente fuera de alcance (decisión usuario
  2026-06-09: cero llamadas API).

## Grid opcional (R7)

`report.run_grid(cfg, xis, lambdas)`: re-ejecuta el walk-forward por combinación
(reutilizando las MISMAS ventanas y los mismos partidos evaluables), ranking por
`(log_loss, brier)` ascendente. Solo bajo `--grid` (coste alto). El resultado se
añade a `summary.json` (`grid_ranking`) y la mejor config se imprime; NO se
modifica el entrenamiento de producción automáticamente (el usuario decide
reentrenar con la ganadora — `train` no cambia).

## Reporte determinista (R9, R13)

- `summary.json`: `json.dumps(..., sort_keys=True, ensure_ascii=False, indent=2)`;
  floats redondeados a 6 decimales (estabilidad de diff); incluye `config`
  completa, `as_of` = `to_date` efectivo (del dataset/args, no del reloj),
  `low_data` (de `params.low_data_teams` del refit FINAL, con attack/defense, y
  `low_data_en_torneo: bool` si interseca las 48 — R13, caso 'isle_of_man':
  decisión = VISIBILIZAR, no recortar fuerzas).
- `windows.csv` y `calibration.csv` con `csv.writer` (orden de filas determinista:
  cronológico / por desenlace y bin).
- `out_dir.mkdir(parents=True, exist_ok=True)`; escribe SOLO dentro de `out_dir`
  (en `data/`, gitignored).

## Enmienda feature 3: jac analítico (R12)

- `_grad_nll_weighted(theta, ...) -> np.ndarray` junto a `nll_weighted`:
  derivadas cerradas de la NLL Poisson ponderada con corrección τ en las 4 celdas
  bajas y término ridge (`+2·λ·θ_fuerzas`). La derivada de τ respecto a
  λ_home/λ_away/ρ existe en forma cerrada (τ es polinómica en esos términos);
  se documenta en docstring.
- `fit_dixon_coles(..., use_analytic_jac: bool = True)`: pasa `jac=` a
  `scipy.optimize.minimize`; `False` conserva el camino numérico (comparación en
  tests y vía de escape). Firma extendida con default → contrato público intacto;
  `maxfun` actual se conserva.
- Tests nuevos en `tests/test_dixon_coles_jac.py` (archivo NUEVO; los tests
  existentes de la feature 3 NO se tocan): (a) `check_grad`/diferencias centrales
  en dataset sintético, tolerancia relativa ≤ 1e-5; (b) óptimo equivalente
  jac-analítico vs numérico en el fixture (NLL final, tolerancia 1e-6 relativa;
  o params con 1e-4); (c) convergencia True.
- Enmienda documentada aquí (mismo mecanismo que las dos enmiendas post-release de
  la sesión: el design de la feature original remite a esta sección).

## CLI (R10) y App (R11)

- Subcomando `backtest` con el patrón de subparsers existente. `--refit-every`
  con `choices=("month","week")`. Salida humana: tabla compacta modelo vs
  baselines + ruta del reporte con `✅`. Errores: silver ausente → `error:` +
  comando previo (`ingest-public`/`build-features`), exit 1.
- App: en `modelo.py`, tras la dispersión: `st.subheader("Backtest")`; si existe
  `data/reports/backtest/summary.json` → métricas clave con `st.metric` (modelo vs
  uniforme/marginal) + n y as_of del reporte; si no → `st.caption` con el comando.
  Lectura tolerante (JSON inválido → aviso, sin crash).

## Secuencia de implementación (coordinación con feature 4)

1. **Ya**: T-JAC (enmienda R12) — archivo `src/models/dixon_coles.py` + test nuevo;
   ningún solape con la feature 4 (que tiene prohibido src/models/).
2. **Tras cerrar feature 4**: resto (src/backtest/, CLI, app) — `src/cli.py` lo
   está editando la feature 4 en este momento; se secuencia para evitar conflicto.

## Decisiones y justificación

- **Refit mensual default** → equilibrio honestidad/coste (~30 refits desde 2024);
  `--refit-every week` disponible para estudios finos.
- **`from_date=2024-01-01` default** → ventana de evaluación con ~2.5 años: ciclos
  de clasificación completos y muestras suficientes para calibración por bins.
- **Baselines uniforme + marginal** → mínimos honestos: si el modelo no bate la
  marginal, no aporta; baselines más fuertes (Elo logístico) = extensión futura.
- **Brier propio (3 líneas)** → sklearn no trae multiclase; la fórmula está fijada
  en el design y protegida por el test de oráculo.
- **Grid NO automático** → cambiar hiperparámetros de producción es decisión del
  usuario (el reporte informa; `train` queda intacto).
- **Defaults de `BacktestConfig` siguen a producción** (enmienda 2026-06-11): `xi=0.35,
  reg_lambda=0.25`, co-óptimos del grid walk-forward de esta feature (ver enmienda en
  `specs/modelo_resultado/design.md`).
- **ROI por CSV de usuario** → no hay cuotas en disco y la regla STOP impide
  llamadas reales; el esquema documentado deja el enchufe listo.
- **jac analítico con flag de escape** → riesgo controlado: equivalencia probada
  por test, camino numérico conservado, firma retrocompatible.
- **Visibilizar low-data, no recortar** → recortar fuerzas alteraría el modelo
  entrenado (fuera de alcance); el aviso en summary + app da la transparencia que
  pedía la deuda ('isle_of_man').

## No-objetivos (explícitos)

- Ingesta de cuotas (API u otra fuente) — el CSV lo aporta el usuario.
- Cambiar defaults de producción de ξ/reg_lambda automáticamente tras `--grid`.
- Baselines adicionales (Elo logístico, mercado), staking no-plano (Kelly).
- Recorte/shrinkage de fuerzas low-data.
- Paralelización de refits (si el coste duele, extensión futura).
