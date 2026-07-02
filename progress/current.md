# progress/current.md — Estado al 2026-06-17 (post-jornada 1)

## ROADMAP v3 (mejoras con datos públicos free) — COMPLETO

Decisión usuario 2026-06-17: mejorar el modelo SOLO con datos free/scraping (sin
invertir). Verificación de fuentes: FBref (xG) bloqueado por Cloudflare; understat/
football-data solo cubren clubes. Fuentes free válidas para selecciones:
**eloratings.net** (Elo) y **Wikipedia** (tiros/posesión). Elegido A+B → 2 features:

- **Lib nueva**: `lxml>=6.1.1` instalada — security-lead APROBADO (cierra XXE; parser
  seguro obligatorio: pandas.read_html flavor=lxml / no_network / huge_tree=False).
- **Feature 14 `elo_externo_ensemble` — código DONE + QA (2026-06-17).** `ingest-elo`
  (eloratings, caché 7d, UA, validación de columnas) + sub-modelo Elo→1X2 + ensemble
  `(1−w)·DC + w·Elo` en `predict`/`predict-log` (w=0 = sin regresión; predict-log usa
  elo_history as-of leak-free, etiqueta `dc-ens`). `simulate` EXCLUIDO (ensemble es
  1X2, sim es marcador). 31 tests (suite **368, sin warnings**). LIMITACIÓN: eloratings
  da snapshot, no histórico → el Elo externo es prior live no-backtesteable; el
  ensemble se mide con elo_history propio. **PENDIENTE: validación LIVE (ingest-elo
  real + ajuste de w) requiere OK de scraping del usuario.**
- **Feature 15 `xg_proxy_wikipedia`** (pending): tiros/posesión Wikipedia (MediaWiki
  API) → proxy xG en la fuerza del modelo; default OFF; cobertura parcial.

- **Feature 15 `xg_proxy_wikipedia` — DONE (2026-06-18).** `ingest-wiki-stats` (MediaWiki
  API, UA, rate-limit 5s, caché 24h) + proxy xG `α·SoT+β·(shots−SoT)` → serie objetivo
  mezclada en el fit (default v=0 = v1). 40 tests (suite **413, sin warnings**). QA
  APROBADO CON OBSERVACIONES (2 BAJO sellados).

### Validación LIVE v3 (2026-06-18, OK del usuario)

- **eloratings**: `ingest-elo` requirió rework (fuente real = `World.tsv`, no HTML;
  códigos ISO alpha-2; bug SCO `SC`→`SQ` corregido). Scraper OK, 48 selecciones. Ensemble
  (leak-free, elo_history) **NO bate a v1** en jornada 1: dc-v1 1.015 < dc-ens(0.3) 1.058
  < dc-ens(0.5) 1.100. Elo externo = snapshot post-jornada-1 → no backtesteable.
- **Wikipedia**: artículos por partido WC2026 = redirects/stubs SIN tabla de tiros →
  **cobertura 0%** (8/8 has_stats=false); el xG-proxy degrada a DC puro como se diseñó.
  Deuda: `ingest-wiki-stats` aborta en error de red transitorio (robustez).

**CONCLUSIÓN v3:** ambas mejoras free construidas, probadas y SEGURAS (default OFF = v1),
pero **ninguna mejora a v1 con los datos free disponibles hoy**. v1 (Dixon-Coles ξ=0.35,
λ=0.25) sigue siendo el modelo desplegado. Causa: muestra pequeña (20 partidos) + las
fuentes free de selecciones no aportan la señal/cobertura necesaria (xG real está tras
Cloudflare en FBref). Re-evaluar tras más jornadas.

---

## ROADMAP v2 (post-jornada 1 WC2026) — COMPLETO

Decisión usuario 2026-06-17: tras la jornada 1 se abre v2 con 4 features nuevas
(una a la vez, SDD). Orden 10 → 11 → 12 → 13. Specs de las 4 ya escritas.

**Ingesta de actuales (T0)**: `ingest-public` + `build-features --as-of-date
2026-06-17` traen los 20 resultados reales de la jornada 1 (CC0, sin cuota) al
silver (antes terminaba en 2026-06-08).

**Feature 10 `registro_y_evaluacion` — DONE (2026-06-17).** Log de predicciones
(`predict-log`, append-only, timestamp inyectado, anti-fuga por `--as-of`) +
`evaluate` predicho-vs-ocurrido. 34 tests nuevos (suite **227 verde**). QA APROBADO
CON OBSERVACIONES: 3 hallazgos BAJO sellados (imports muertos, ruta de grep robusta,
guarda `_assert_under_data` simétrica en `log_predictions`).

**Reconstrucción real jornada 1 (out-of-sample, as_of=2026-06-11):**

| Métrica | v1 jornada 1 | contexto |
|---------|--------------|----------|
| log-loss | 1.0150 | backtest histórico 0.8641; uniforme 1.0986 |
| Brier | 0.6304 | |
| Exactitud | 55.0% (11/20) | |
| RMSE λ | 1.2886 | golizas (GER 7-1, ARG 3-0, FRA 3-1) castigan |
| Brier O/U2.5 | 0.2563 | ~baseline 0.25 |
| Brier BTTS | 0.2786 | |

Lectura: v1 apenas supera al baseline uniforme en el torneo → justifica v2 (peso por
importancia de partido, refit intra-torneo). Log en `data/predictions/log.csv`,
reporte en `data/reports/evaluacion/`.

**Feature 11 `factor_jugadores` — DONE (2026-06-17).** Ingesta CC0 goalscorers
(`ingest-goalscorers`), normalización a eventos (excluye own goals), tabla de cuotas
por jugador con decaimiento+anti-fuga, anytime-scorer (thinning Poisson) `scorers`,
multiplicador de ataque por roster (default identidad → cero regresión 1X2),
artefacto `gold/player_factor.csv`. 46 tests nuevos (suite **273 verde**). QA
APROBADO CON OBSERVACIONES (2 BAJO selladas). Validado real: 47663 filas CC0, 6265
entradas de factor, `scorers ARG/ESP` (Messi 29.8%, Lautaro 18.3%).

DEUDA conocida F11: nombres con/sin acento se cuentan como jugadores distintos
("Julián Alvarez" vs "Julián Álvarez" dividen la cuota) → candidato de refinamiento
(normalización de nombres; accent-folding ingenuo arriesga fundir homónimos). No
bloquea. ~24.6k eventos descartados (mayoría `equipo_sin_codigo`: el dataset trae
todas las selecciones, solo 48 del Mundial tienen código — esperado).

**Feature 12 `modelo_v2` — DONE (2026-06-17).** Mecanismo: `src/models/importance.py`
(tier→factor, default identidad), enmienda `dixon_coles` (`w=decay×importance`,
equivalencia v1 exacta con default), grid con dimensión importancia, wiring v2 en el
harness (`--model-version dc-v2` en predict-log/evaluate, persistencia
`dixon_coles_params_v2.json`). 23 tests nuevos (suite **296 verde**). QA APROBADO CON
OBSERVACIONES (gates críticos PASAN; 3 hallazgos sellados, incl. normalización
Unicode de torneos "Copa América").

HALLAZGO CLAVE (T8, validación real): **el peso por importancia NO mejora a v1.**

| Config | log-loss histórico | log-loss jornada 1 |
|--------|--------------------|--------------------|
| v1 (ξ=0.35, λ=0.25, sin importancia) | **0.8660** | **1.0150** |
| mejor grid v2 (imp_scale 2.0, ξ=0.5, λ=0.5) | 0.8717 | — |
| v2 importancia default (jornada 1) | — | 1.0197 |

Decisión registrada: **v1 sigue siendo el modelo desplegado por defecto.** El
mecanismo v2 queda disponible (importancia + refit intra-torneo + versión dc-v2);
su valor real = refit incorporando la jornada jugada, **medible al jugarse la
jornada 2** (`predict-log --as-of <fecha_j2> --model-version dc-v2`). No se fabrica
una mejora inexistente. Grid v2 en `data/reports/backtest_v2grid/`.

**Feature 13 `simulacion_montecarlo` — DONE (2026-06-17).** Paquete `src/simulation/`
(bracket, standings, montecarlo, report) + subcomando `simulate`. Deriva 12 grupos del
grafo de fixtures, fija los resultados reales de la jornada 1, muestrea los pendientes
desde la matriz Dixon-Coles (con tau), RNG con seed inyectada, bracket R32→Final
(empate por Bernoulli ponderada). 41 tests nuevos (suite **337 verde**, ~21s tras
optimizar). QA APROBADO CON OBSERVACIONES (motor correcto; 2 hallazgos sellados; bracket
de terceros simplificado documentado).

Validación real `simulate --n 10000 --seed 42 --as-of 2026-06-17` (condicionada a la
jornada 1):

| Selección | P(título) | P(Final) | P(R16) |
|-----------|-----------|----------|--------|
| ARG | 26.8% | 37.1% | 84.0% |
| ESP | 13.3% | 20.3% | 72.3% |
| ENG | 8.3% | 17.5% | 62.0% |
| BRA | 7.1% | 11.8% | 63.3% |
| FRA | 6.6% | 14.7% | 63.0% |

Reporte en `data/reports/simulacion/`.

---

## ROADMAP v2 COMPLETO (2026-06-17)

Las 4 features nuevas (10, 11, 12, 13) DONE bajo SDD. Suite **337 verde**, `init.sh`
verde, sin librerías nuevas. CLI: **12 subcomandos**. Estado del modelo: **dc-v1 sigue
siendo el desplegado** (la importancia de la feature 12 no mejoró). Mantenimiento por
jornada: `ingest-public → build-features --as-of-date <hoy> → predict-log
--as-of <inicio_jornada> [--model-version dc-v2] → evaluate` y `simulate
--as-of <hoy>` para refrescar tendencias.

---

# Estado previo — 2026-06-11 (día inaugural)

## Bloque 2026-06-10/11: retiro dashboard + grid + nuevos hiperparámetros

- **Dashboard viejo RETIRADO** (aprobación usuario): src/report/, test_dashboard.py
  (20 tests), dashboard.html, png/ borrados; matplotlib fuera de requirements;
  specs/dashboard_visual/ conservadas (registro SDD, init.sh las exige).
  Deprecation sellada: `use_container_width=True` → `width="stretch"` (7 usos).
- **Grid walk-forward (17 configs, 3 rondas)**: la config vieja (ξ=0.65, λ=1.0,
  log-loss 0.8943) era 5ª de 9; tendencia clara hacia memoria larga + menos ridge.
  Usuario eligió **ξ=0.35, λ=0.25** (robusta, log-loss 0.8641, exactitud 60.6%)
  sobre la esquina 0.2/0.1 (0.8606, ≈ruido de diferencia, ridge casi nulo).
- **Enmienda aplicada** (DCConfig + BacktestConfig defaults + docstrings +
  specs/modelo_resultado/design.md); cero tests hardcodeaban defaults.
  **Producción reentrenada** (as_of=2026-06-11, 8.080 partidos, converge en 534
  iter): MEX–RSA pasa de 63.6/23.7/12.7 a **64.4/23.4/12.2**. Backtest oficial
  refrescado: reproduce exactamente el 0.8641 del grid. low_data_en_torneo sigue
  False; isle_of_man attack=0.92 con ridge 0.25 (visible, no en torneo).
- **Enmienda calendario (feature 9, R5)**: solo edición 2026 (excluye Mundiales
  1930–2022 del dataset histórico); reportado por el usuario.
- **Suite: 193 tests verdes** (213 − 20 del dashboard retirado). init.sh verde.
- Roadmap: córners/tarjetas EXCLUIDOS definitivamente (decisión usuario).
  Candidata feature 10 `factor_jugadores` v1: goalscorers.csv del mismo repo CC0
  (tasas por jugador + mercado anytime scorer); spec pendiente de OK del usuario.

# Estado previo (cierre 2026-06-09)

## Estado: BACKLOG COMPLETO — las 9 features done

| # | Feature | Tests | Resumen |
|---|---------|-------|---------|
| 1 | ingesta_datos | 14 | API-Football → bronze (sesión anterior) |
| 7 | ingesta_publica | 12+1 | Fuente pública CC0 (martj42) → bronze |
| 2 | feature_store | 28 | bronze → silver (49.376) → gold (Elo + ma15) |
| 3 | modelo_resultado | 31+3 | Dixon-Coles MLE ponderada + enmienda jac analítico (7.9x) |
| 6 | cli_prediccion | 32 | CLI (7 subcomandos tras F4/F5) |
| 8 | dashboard_visual | 20 | HTML plotly (reemplazado por feature 9; código congelado) |
| 9 | app_streamlit | 35+2 | App Streamlit: Calendario/Selecciones/Modelo + Mercados/Backtest |
| 4 | modelos_mercados | 16+ | O/U .5, BTTS, totales (solo goles) — CLI `markets` + app |
| 5 | backtesting | 25 | Walk-forward anti-fuga + métricas + ROI opcional + grid |

**Suite: 213 tests verdes. `bash init.sh` verde.**

Enmienda 2026-06-10 (feature 9, R5): el calendario de la app filtraba solo por
`tournament == "FIFA World Cup"` y mostraba 1.036 partidos de TODAS las ediciones
desde 1930; ahora `date >= WC2026_FROM_DATE` ("2026-01-01", sin reloj) → solo la
edición 2026 (72 partidos en dataset; crecerá con las eliminatorias). Reportado
por el usuario; sellado con test de mutación.

## Resultados del backtest real (T8 feature 5; 2026-06-09)

Walk-forward mensual 2024-01-01 → 2026-06-08, 30 refits, 2.510 partidos (7 skipped),
7.5 s total (jac analítico):

| Config | log-loss | Brier | Exactitud |
|--------|----------|-------|-----------|
| **Modelo Dixon-Coles** | **0.8943** | **0.5264** | **59.16%** |
| Baseline marginal | 1.0540 | 0.6358 | 47.41% |
| Baseline uniforme | 1.0986 | 0.6667 | 47.41% |

El modelo bate ambos baselines en todas las métricas. `low_data_en_torneo: False`
(artefacto 'isle_of_man' no toca a las 48). Reporte: `data/reports/backtest/`
(summary.json, windows.csv, calibration.csv).

## Comandos de uso

```
.venv/bin/python -m streamlit run src/app/main.py    # interfaz gráfica
.venv/bin/python -m src.cli predict MEX RSA [--json]
.venv/bin/python -m src.cli markets MEX RSA [--json] [--lines 0.5,2.5]
.venv/bin/python -m src.cli backtest [--grid] [--odds CSV] [--refit-every week]
.venv/bin/python -m src.cli schedule --limit 20
.venv/bin/python -m src.cli train --as-of-date YYYY-MM-DD
bash init.sh
```

## Decisiones clave del bloque

- Usuario: app Streamlit REEMPLAZA dashboard HTML; solo visualiza; F4 solo goles;
  paralelo F4∥F5 autorizado; auditar cada librería antes de instalar.
- Seguridad: streamlit 1.58.0 + pyarrow>=14.0.1 auditados e instalados;
  .streamlit/config.toml (telemetría off, localhost).
- Reviews adversariales sellaron: BUG-1 (top-5, F9), aserción exacta de
  subcomandos (F4), test vacuo R10 + borde anti-fuga </<= + R9 recursivo +
  validación refit_every (F5) — todos con demostración de mutación.
- Lección: no correr dos implementers en paralelo si uno ejecuta la suite completa
  mientras otro edita módulos compartidos (falso fallo en F4∥T1-jac).

## Pendientes (ninguno bloqueante)

- Retiro de `src/report/` (dashboard viejo): REQUIERE aprobación explícita del
  usuario (regla STOP borrado). La app ya lo reemplaza.
- Extensiones futuras documentadas: córners/tarjetas (necesitan datos → API real),
  ingesta de cuotas para ROI, baselines fuertes (Elo logístico), staking Kelly.
- Deuda baja: requirements-lock.txt opcional; deprecation use_container_width
  (streamlit post-2025); weak-hash SNYK streamlit sin parche; --out sin
  restricción de ruta base (herramienta local single-user); elif explícito en
  _generate_window_starts.
- Si el usuario corre `--grid` y elige otra config: reentrenar con `train`
  (el grid NO cambia producción automáticamente).

## Mantenimiento durante el torneo (arranca 2026-06-11)

Tras cada jornada: `ingest-public → build-features → train`; la app refleja los
cambios al rerun. Reejecutar `backtest` periódicamente para vigilar calibración
con los partidos del Mundial ya jugados.
