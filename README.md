# Modelos predictivos — Mundial 2026

Modelos estadísticos para predecir los partidos del **Mundial 2026** (USA/Canadá/México,
11 jun – 19 jul 2026; 48 selecciones, 12 grupos, 104 partidos) y sus mercados de apuestas
(1X2, marcador, over/under de goles, córners, tarjetas) a partir de los **últimos 15 partidos**
por selección.

## Cómo arranca

El proyecto sigue **Spec-Driven Development (SDD)**: una feature a la vez, con specs
(`requirements → design → tasks`) antes de implementar. Empieza leyendo `CLAUDE.md` y `AGENTS.md`.

### Entorno

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

### API key (obligatorio, nunca hardcodear)

La clave de API-Football se lee SIEMPRE de la variable de entorno:

```bash
export API_FOOTBALL_KEY="tu_clave"
```

### Verificar

```bash
bash init.sh        # valida specs SDD + corre pytest
```

### Interfaz gráfica (Streamlit)

```bash
.venv/bin/python -m streamlit run src/app/main.py
```

App local (solo `localhost`, telemetría desactivada vía `.streamlit/config.toml`):
calendario del Mundial 2026 (tira de días + tarjetas con 1X2; jugados con resultado
real vs predicción), fichas por selección (Elo, forma, fuerzas) y estado del modelo.
Reemplaza al dashboard HTML estático de la feature 8. Solo visualiza: el pipeline
se opera por CLI (`ingest-public → build-features → train`).

## Estructura

| Ruta              | Qué es                                          |
|-------------------|-------------------------------------------------|
| `CLAUDE.md`       | Reglas de gobierno (rol LEADER, flujo SDD, STOP)|
| `AGENTS.md`       | Mapa de lectura para agentes                     |
| `docs/specs.md`   | Flujo SDD detallado (EARS, plantillas)           |
| `feature_list.json` | Alcance y estado de las 6 features            |
| `CHECKPOINTS.md`  | Criterios de "estado final correcto"             |
| `specs/<feature>/`| requirements / design / tasks por feature        |
| `src/`            | ingestion · features · models · backtest · cli   |
| `data/`           | bronze / silver / gold (en `.gitignore`)         |
| `tests/`          | Tests reales por requisito                        |
| `progress/`       | Estado de la sesión activa                        |

## Roadmap (features)

1. **ingesta_datos** — últimos 15 partidos + cuotas → bronze. ✅
2. feature_store — normalización, medias móviles, Elo (silver/gold). ✅
3. modelo_resultado — Poisson/Dixon-Coles para 1X2 y marcador. ✅
4. modelos_mercados — mercados de goles: O/U (líneas .5), BTTS, totales
   (`python -m src.cli markets MEX RSA [--json] [--lines 0.5,2.5]`);
   córners/tarjetas = extensión futura (requieren datos no disponibles). ✅
5. backtesting — walk-forward anti-fuga: log-loss/Brier/calibración vs baselines,
   grid ξ/λ opcional (`--grid`), ROI opcional
   (`python -m src.cli backtest [--from-date F] [--refit-every month|week]
   [--odds RUTA] [--out DIR]`; reporte en `data/reports/backtest/`).
   ROI: aporta tú el CSV de cuotas con cabecera
   `date,home_code,away_code,odds_home,odds_draw,odds_away` (decimales > 1.0). ✅
6. cli_prediccion — CLI que predice un partido. ✅
7. ingesta_publica — resultados internacionales CC0 → bronze. ✅
8. dashboard_visual — HTML plotly (reemplazado por la app Streamlit, feature 9). ✅
9. app_streamlit — interfaz gráfica (ver arriba). ✅

### Roadmap v2 (post-jornada 1, Mundial 2026)

10. **registro_y_evaluacion** — log de predicciones + evaluación predicho-vs-ocurrido. ✅
    - `python -m src.cli predict-log --as-of YYYY-MM-DD --timestamp <iso> [--markets]
      [--targets schedule|<csv>]` → registra predicciones (1X2 + λ + mercados) en
      `data/predictions/log.csv` (append-only, timestamp inyectado, anti-fuga por `--as-of`).
    - `python -m src.cli evaluate [--from F] [--to F] [--markets]` → log-loss/Brier/
      exactitud/calibración + Brier de mercados + error de λ; reporte en
      `data/reports/evaluacion/`.
11. **factor_jugadores** — factor de jugadores desde CC0 goalscorers (anytime-scorer). ✅
    - `python -m src.cli ingest-goalscorers` → goalscorers CC0 → bronze (sin cuota).
    - `python -m src.cli scorers --home ARG --away ESP [--as-of F] [--top-k N] [--roster <csv>]`
      → P(anytime-scorer) por jugador (λ_equipo Dixon-Coles × cuota histórica).
    - `build-features` genera `data/gold/player_factor.csv` si hay bronze de goleadores.
12. **modelo_v2** — peso por importancia de partido + refit intra-torneo + re-grid. ✅
    - `train --model-version dc-v2 --as-of F [--importance default|off]`,
      `predict/markets --model-version dc-v2`, `predict-log --model-version dc-v2`,
      `evaluate --model-version dc-v1|dc-v2`, `backtest --grid --importance-scales ...`.
    - Hallazgo: el peso por importancia NO mejora a v1 (backtest v1 0.866 < v2 0.872);
      v1 sigue siendo el modelo por defecto. El refit intra-torneo (dc-v2 rolling) se
      evaluará al jugarse jornadas siguientes.
13. **simulacion_montecarlo** — simulación del torneo completo (~10k sims): % avance / % título. ✅
    - `python -m src.cli simulate [--n 10000] [--seed 42] [--as-of F]
      [--model-version dc-v1|dc-v2] [--roster <csv>] [--top-n N]` → grupos (resultados
      reales fijos + pendientes muestreados) → bracket → P(avance)…P(título) por
      selección; reporte en `data/reports/simulacion/`.

### Roadmap v3 (mejoras con datos públicos free)

14. **elo_externo_ensemble** — Elo de eloratings.net + ensemble Elo↔Dixon-Coles. ✅
    - `python -m src.cli ingest-elo` → Elo de selecciones (eloratings World.tsv) a bronze/gold.
    - `predict / predict-log --elo-weight <w>` → mezcla `(1−w)·DC + w·Elo` (w=0 = sin cambio;
      `predict-log` usa Elo histórico as-of, leak-free, etiqueta `dc-ens`).
    - Hallazgo (live): el ensemble NO bate a v1 en jornada 1 (1.015 < 1.058 con w=0.3);
      Elo externo = snapshot, no backtesteable. v1 sigue siendo el modelo por defecto.
15. **xg_proxy_wikipedia** — tiros/posesión de Wikipedia → proxy xG en la fuerza del modelo. ✅
    - `python -m src.cli ingest-wiki-stats --matches <csv>` (MediaWiki API, UA, rate-limit, caché);
      `train/backtest --xg-weight <v>` (v=0 = sin cambio).
    - Hallazgo (live): Wikipedia no tiene tablas de tiros parseables para los partidos de grupo
      WC2026 → cobertura 0%; el proxy degrada a DC puro. Útil si/cuando aparezcan stats.

## Fuentes de datos

- **Primaria**: API-Football (api-sports.io / RapidAPI).
- **Real-time / complementaria**: https://www.worldsoccerdata.com/.
- **Histórica (backtest)**: football-data.co.uk.
# sport-analisis
