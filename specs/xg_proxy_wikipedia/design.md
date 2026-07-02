# design.md — Feature 15: xg_proxy_wikipedia

## Arquitectura

Reusa el patrón de ingesta, el silver de partidos, el Dixon-Coles y el harness de
backtest. Paquete nuevo `src/xg/`. Única dep nueva ya presente: `lxml` (parser
seguro, dictamen security-lead). Fuente: **MediaWiki Action API** de Wikipedia
(canal oficial preferido sobre scraping de HTML).

| Módulo                         | Responsabilidad                                                      | Requisitos |
|--------------------------------|---------------------------------------------------------------------|------------|
| `src/ingestion/wiki_stats.py`  | MediaWiki API (transporte inyectable), parseo seguro de stats, bronze+meta, caché 24h, UA. | R1 |
| `src/xg/__init__.py`           | Paquete vacío.                                                       | —          |
| `src/xg/proxy.py`              | Normalización al silver, emparejamiento, proxy xG, serie objetivo mezclada. | R2, R3, R4 |
| `src/models/dixon_coles.py` (ext.) | `load_training_data` admite una serie objetivo mezclada (goles↔xg) por partido; default = goles (v1). | R4 |
| `src/cli.py` (ext.)            | `ingest-wiki-stats`; flag `--xg-weight` en train/backtest.          | R6 |

Flujo:

```
ingest-wiki-stats ─► MediaWiki API por artículo de partido ─► bronze/wikipedia/<slug>.json (+meta)  (R1)
proxy.normalize ─► (match_id, team_code, shots, sot, possession) emparejado al silver; cobertura %  (R2)
proxy.xg ─► xg_proxy = α·SoT + β·(shots−SoT)  (documentado)                                          (R3)
goal_target = (1−v)·goles_reales + v·xg_proxy  (solo con cobertura; v=0 ⇒ v1)                        (R4)
fit_dixon_coles(goal_target, as_of) ─► fuerza aumentada (anti-fuga fecha<as_of)                      (R4)
backtest/evaluate sobre subconjunto con cobertura ─► v1 vs xG-aumentado                              (R5)
```

## Ingesta segura (R1, security-lead)

- **MediaWiki Action API**: `https://en.wikipedia.org/w/api.php?action=parse&page=<art>&prop=text&format=json`.
  Transporte inyectable (`url → texto`). UA identificable:
  `Mundial2026-ResearchBot/1.0 (academic; contact: <email>)`.
- Rate-limit ≥1 req/5s (inyectable como sleeper, desactivado en tests).
- Caché bronze 24h: si `data/bronze/wikipedia/<slug>.json` fresco → no re-fetch.
- Parseo del HTML embebido con `pandas.read_html(flavor="lxml")` o
  `etree.HTMLParser(no_network=True, huge_tree=False)`. NUNCA `etree.fromstring` sobre
  HTML crudo. Validar presencia de la sección de estadísticas; ausencia → sin stats
  (no error).

## Proxy de xG (R3)

- `xg_proxy = α·SoT + β·(shots − SoT)`. Calibración por defecto desde tasas
  históricas de conversión (documentadas en el módulo; α≈0.30 por SoT, β≈0.03 por
  tiro fuera, ajustables). Acotado a ≥0. Es un proxy GRUESO; documentado.
- Donde solo haya posesión (sin tiros) → no se calcula xg_proxy (sin cobertura).

## Fuerza aumentada y anti-fuga (R4)

- `goal_target_i = (1−v)·goals_i + v·xg_i` por equipo/partido, solo si el partido
  tiene cobertura; si no, `goal_target_i = goals_i`. `v=0` ⇒ serie = goles exactos
  ⇒ ajuste idéntico a v1 (test de equivalencia 1e-9).
- `load_training_data` recibe la serie objetivo ya construida; el filtro
  `fecha < as_of` garantiza que el xG de un partido nunca informa la predicción de
  ese mismo partido (anti-fuga).

## CLI (R6)

- `ingest-wiki-stats [--matches <csv>|schedule] [--ttl-hours 24] [--out]` (red real;
  test con transporte inyectado).
- `--xg-weight <v>` (default 0.0) en `train` y `backtest`. `v=0` no cambia nada.
- Conjunto de subcomandos: previos + `ingest-wiki-stats` (aserción exacta endurecida).

## Decisiones y justificación

- **xG en la fuerza, no en λ de un partido**: alimentar xG pasado a att/def mejora la
  predicción FUTURA sin fuga; mezclar la λ de un partido con sus propias stats sería
  retrodicción inútil para forecasting.
- **Cobertura parcial explícita**: el blend solo aplica donde hay stats; el resto usa
  goles (v1). Se reporta el % de cobertura; la medición se hace sobre el cubierto.
- **MediaWiki API, no scraping HTML**: canal oficial, menos frágil, alineado con el
  dictamen security-lead.

## Fuera de alcance

xG real entrenado (modelo de tiros con localización — no hay datos free fiables);
expected threat / posesión avanzada; cobertura de amistosos (Wikipedia no la trae);
beautifulsoup4 (solo si lxml resulta insuficiente → re-evaluación security-lead).
