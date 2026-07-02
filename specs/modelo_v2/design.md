# design.md — Feature 12: modelo_v2

## Arquitectura

Enmienda quirúrgica a `src/models/dixon_coles.py` (peso de importancia en el
weighting) + nuevo `src/models/importance.py` (mapa tier → factor) + extensiones a
`src/backtest/` (dimensión de grid) y `src/cli.py` (train/backtest con versión e
importancia). Reusa el harness de la feature 10 para la comparación. SIN librería
nueva.

| Módulo                          | Responsabilidad                                                  | Requisitos |
|---------------------------------|------------------------------------------------------------------|------------|
| `src/models/importance.py`      | Clasificación `tournament` → tier → factor; mapa inyectable; default identidad. | R1, R2 |
| `src/models/dixon_coles.py` (ext.) | `load_training_data`/`fit` aceptan factor de importancia: `w = decay × importance`. Default 1.0 = v1. | R1, R3 |
| `src/backtest/` (ext.)          | Grid sobre (ξ, reg_lambda, escala importancia); comparación v1 vs v2. | R4, R7 |
| `src/cli.py` (ext.)             | `train --model-version {dc-v1,dc-v2} --importance {off,default}`; `backtest` con dimensión importancia. | R5, R6 |

Flujo:

```
silver ─► load_training_data(as_of, importance_map) ─► w = decay × importance   (R1,R3)
        ─► fit_dixon_coles ─► params (model_version dc-v2)  ─► gold/dixon_coles_params_v2.json (R6)
backtest grid (ξ, λ, escala importancia) incl. torneo ─► mejor v2 vs v1          (R4,R7)
predict-log --as-of <jornada> --model-version dc-v2 (rolling)  ─► feature 10 log  (R5)
evaluate (feature 10) ─► v1 vs v2 sobre el slate del torneo                       (R7)
```

## Importancia (R1, R2)

- `importance.py`: `TIER_FACTORS` por defecto (v2 propuesto, justificado):
  - `friendly` → 0.5 (lineups experimentales, ruido alto)
  - clasificatorios / Nations League / cualificación continental → 1.0
  - finales continentales (Euro, Copa América, etc.) → 1.25
  - Copa Mundial → 1.5
  - fallback torneos no mapeados → 1.0 (documentado).
  Valores INYECTABLES; el grid (R4) calibra una **escala** global sobre estos.
- Combinación: `w_i = exp(−ξ·Δaños) × importance(tournament_i)`. El default de la
  config v1 fija todas las importancias a 1.0 → `w` idéntico a v1 (R1 equivalencia).
- Clasificación robusta por substring/normalización del campo `tournament`
  (mismo dato que ya usa la app/calendario), con tabla explícita en el módulo.

## Refit intra-torneo (R5)

- No requiere subcomando nuevo: se realiza con `predict-log --as-of <inicio_jornada>
  --model-version dc-v2` (feature 10) para cada jornada, entrenando con
  `fecha < inicio_jornada`. El filtro de la feature 3 garantiza la anti-fuga.
- v1 = snapshot único pre-torneo (`--as-of 2026-06-11`, importancia off);
  v2 = rolling por jornada con importancia on. `evaluate` compara ambos
  `model_version` sobre los mismos partidos.

## Persistencia y CLI (R6)

- `train --model-version dc-v2 --as-of <fecha> [--importance default|off]` escribe
  `data/gold/dixon_coles_params_v2.json` sin tocar el v1. `load_params` acepta ruta/
  versión. `predict`/`markets`/`scorers` pueden seleccionar versión (default dc-v1
  para no romper comportamiento previo).
- `backtest` gana flags de grid de importancia; reporte añade columna de config.

## Decisiones y justificación

- **Default identidad**: cero regresión; los 193+ tests previos y el backtest
  0.8641 siguen válidos. v2 se activa explícitamente.
- **Escala calibrada por grid, no a ojo**: los factores por tier son un prior; el
  grid walk-forward (incluyendo el torneo) decide la escala que minimiza log-loss,
  evitando sobre-pesar amistosos o el torneo.
- **Rolling vía feature 10**: reusa el harness ya construido; la comparación v1 vs
  v2 es honesta y reproducible, no un número suelto.

## Fuera de alcance

Cambios de forma funcional del modelo (Elo logístico, jerárquico bayesiano);
mercados nuevos; integración profunda del factor jugadores en el likelihood (aquí
solo se admite el multiplicador de ataque por roster de la feature 11 como entrada
a la λ, opcional).
