# design.md — Feature 2: feature_store

## Arquitectura

Módulos nuevos en `src/features/`. Los módulos de la feature 1 (`teams.py`, `bronze.py`,
`ingest.py`) y de la feature 7 (`public_data.py`) se usan **solo en lectura** y NO se
modifican. Todo el procesamiento es **offline** (lee disco → escribe CSV): no hay red,
no se usa `API_FOOTBALL_KEY` ni `Settings` de `config.py`.

| Módulo                     | Responsabilidad                                                            | Requisitos    |
|----------------------------|----------------------------------------------------------------------------|---------------|
| `src/features/silver.py`   | Normalización bronze → silver: extracción API-Football + CSV público, códigos FIFA + fallback, `match_id`, dedupe, escritura preparada de `matches.csv`. | R1–R7         |
| `src/features/rolling.py`  | Medias móviles de hasta 15 observaciones por equipo y métrica (anti-leakage). | R8–R11        |
| `src/features/elo.py`      | Ratings Elo (eloratings.net parametrizable) + historial por partido.        | R12–R19       |
| `src/features/build.py`    | Orquesta silver → gold y **escribe los tres CSVs** de forma determinista.   | R7, R19–R21   |

Flujo:

```
data/bronze/fixtures/*.json ───────────────┐
data/bronze/fixtures_statistics/*.json ────┤→ silver.py → DataFrame silver ─→ build.py escribe data/silver/matches.csv
data/bronze/public_results/results.csv ────┘                  │
                                                              ├→ elo.py     → historial → data/gold/elo_history.csv
                                                              └→ rolling.py → features ┐
                                                                 elo vigente ──────────┴→ data/gold/team_features.csv
```

## Entradas bronze (contratos exactos)

### (a) API-Football — `data/bronze/fixtures/*.json` (R1)

Envoltorio escrito por `src/ingestion/bronze.py::write_bronze`:
`{endpoint, params, fetched_at, payload}`. De `payload.response` (lista de fixtures) se
extrae por partido:

| Campo silver  | Origen en el fixture                                   |
|---------------|--------------------------------------------------------|
| filtro FT     | `fixture.status.short == "FT"` (otro status → descarte)|
| `date`        | `fixture.date` ISO-8601 → `YYYY-MM-DD` en UTC          |
| nombres       | `teams.home.name`, `teams.away.name`                   |
| goles         | `goals.home`, `goals.away`                             |
| `tournament`  | `league.name`                                          |
| id de fixture | `fixture.id` → clave para buscar estadísticas          |

### (b) API-Football — `data/bronze/fixtures_statistics/*.json` (R2)

El endpoint `fixtures/statistics` se persiste con `endpoint_dir = "fixtures_statistics"`
(regla `replace("/", "_")` de `bronze.py`) y `param_key = "fixture=<id>"`. El payload
crudo se normaliza con `src/ingestion/ingest.py::normalize_statistics` (fuente de verdad
del esquema): `{home: {...}, away: {...}}` con `corners`, `cards` (amarillas + rojas),
`shots`, `shots_on_target`, `possession` por lado; los goles vienen del fixture, no de
statistics. **Posesión**: la API la entrega como string `"55%"` → se convierte a float
`55.0` (strip de `%`); `None` permanece null.

SI no existe el archivo de statistics de un fixture → columnas de stats nulas, sin fallar.

### (c) Fuente pública — `data/bronze/public_results/results.csv` (R3)

CSV crudo de la feature 7 (`ingesta_publica`), encabezado verificado:
`date,home_team,away_team,home_score,away_score,tournament,city,country,neutral`.
Mapeo a silver: `home_score/away_score → home_goals/away_goals` (int),
`neutral` `TRUE/FALSE` → bool, `tournament` tal cual, todas las stats nulas,
`source = "public_csv"`. `city`/`country` no se materializan en silver (no los usa
ningún requisito aguas abajo; bronze los conserva).

**Descarte tolerante (R3)**: el CSV real contiene filas del calendario del Mundial 2026
con `home_score/away_score = 'NA'` (partidos no jugados). `_load_public_rows` aplica las
mismas reglas que `parse_results` de la feature 7 (R5 de ingesta_publica): SI los goles
no son numéricos o la fecha no es estrictamente `YYYY-MM-DD`, la fila se descarta, se
cuenta (`logging`) y el lote continúa sin fallar. Decisión de implementación: validación
tolerante **propia** dentro del bucle `csv.DictReader` existente (no se reutiliza
`parse_results`), porque el fallback obligatorio para cuando la feature 7 no es
importable duplicaría la misma validación; las reglas son idénticas
(`date.fromisoformat` estricto + `int()`).

## Normalización a códigos FIFA (R4)

- Fuente de verdad de las 48: `src/ingestion/teams.py::all_teams()` (códigos FIFA 3 letras).
- Tabla de alias nombre-fuente → código: se **importa** `DATASET_ALIASES` /
  `to_fifa_code` de `src/ingestion/public_data.py` si el módulo existe (feature 7, en
  paralelo). SI no es importable aún, `silver.py` usa una tabla de alias **propia de
  fallback** con la misma invariante (cubre los 48 códigos: `'United States'` → `USA`,
  `'South Korea'` → `KOR`, `'Ivory Coast'` → `CIV`, …), vía `try/except ImportError`
  documentado. Una sola resolución (`resolve_code(name)`) para ambas fuentes bronze.
- **Fallback determinista para equipos fuera de las 48**: `code = slug(nombre)` =
  normalización Unicode (NFKD, sin acentos) + minúsculas + no-alfanumérico → `_`
  (p. ej. `"Scotland"` → `"scotland"`). Justificación: determinista entre ejecuciones
  (no usa `hash()` de Python, que varía con `PYTHONHASHSEED`), legible en
  `elo_history.csv` para depurar, y no colisiona con los códigos FIFA (estos son
  MAYÚSCULAS de 3 letras). El partido se **conserva** en silver: el Elo necesita la red
  completa de oponentes (ver Decisiones).
- `home_team`/`away_team` (nombre canónico): si el código pertenece a las 48 → `name`
  de `teams.py`; si no → el nombre de la fuente tal cual.

## `match_id` estable (R5)

`match_id = sha1("source|date|home_code|away_code")[:12]` (hex, vía `hashlib`).
Determinista entre ejecuciones **y procesos** (nunca `hash()` builtin). Se calcula
**después** del dedupe (sobre la fila superviviente).

## Dedupe entre fuentes (R6)

- Clave: `(date, home_code, away_code)`.
- SI un partido está en ambas fuentes → sobrevive **una** fila con
  `source = "api_football"` (tiene estadísticas), tomando `neutral` y `tournament` del
  registro público (es la fuente que declara explícitamente la neutralidad).
- **Default de `neutral` para filas API-Football sin contraparte pública**: `False`.
  Justificación: API-Football no expone un flag de neutralidad fiable en el contrato
  bronze usado; la mayoría de partidos internacionales tienen local real, y siempre que
  el partido exista también en el dataset público (caso normal: cubre 1872 → presente)
  el dedupe lo corrige con el valor explícito. Decisión revisable.

## Contrato silver — `data/silver/matches.csv` (R7)

Esquema, tipos y **orden de columnas** exactos (contrato del Leader, 2026-06-09):

| # | Columna                | Tipo            | Notas                                              |
|---|------------------------|-----------------|----------------------------------------------------|
| 1 | `match_id`             | str             | hash corto de `source\|date\|home_code\|away_code` |
| 2 | `date`                 | str             | `YYYY-MM-DD`                                       |
| 3 | `home_code`            | str             | FIFA 3 letras o slug fallback                      |
| 4 | `away_code`            | str             | ídem                                               |
| 5 | `home_team`            | str             | nombre canónico                                    |
| 6 | `away_team`            | str             | nombre canónico                                    |
| 7 | `home_goals`           | int             |                                                    |
| 8 | `away_goals`           | int             |                                                    |
| 9 | `tournament`           | str             |                                                    |
| 10| `neutral`              | bool            | `True`/`False`                                     |
| 11| `source`               | str             | `'api_football'` \| `'public_csv'`                 |
| 12–21 | `home_corners`, `away_corners`, `home_cards`, `away_cards`, `home_shots`, `away_shots`, `home_shots_on_target`, `away_shots_on_target`, `home_possession`, `away_possession` | float **nullable** | solo `source='api_football'`; null → celda vacía en CSV |

Orden de filas determinista: `(date, match_id)` ascendente. Salida **CSV** (no parquet:
`pyarrow` no está en `requirements.txt`).

SI faltan ambas fuentes bronze → error claro (`SilverInputError`); SI falta una → se
continúa con la disponible (R7). Un archivo bronze ilegible (JSON corrupto) se registra
(`logging`) y se omite sin abortar el lote (coherente con R9 de la feature 1).

## Gold — medias móviles (R8–R11) — `rolling.py`

- Vista **larga** desde silver: 2 filas por partido (una por equipo) con métricas en
  perspectiva de equipo: `gf` (goles a favor), `ga` (en contra), `corners_for`,
  `corners_against`, `cards`, `shots`, `shots_on_target`, `possession` (las *_for/own
  del lado propio; *_against del rival).
- Para una `as_of_date`: filtrar `date < as_of_date` **estrictamente** (R9: el propio
  partido y cualquier futuro quedan fuera), ordenar por `(date, match_id)` y tomar por
  métrica las **últimas hasta 15 observaciones no nulas**; media aritmética.
- `matches_count` = nº de partidos previos usados en la ventana de goles
  (= `min(15, partidos previos)`; `gf`/`ga` nunca son nulos en silver). Las métricas de
  stats pueden promediar menos observaciones (solo las no nulas, R11).
- 0 partidos previos → todas las medias null y `matches_count = 0`, sin fallar (R10).
- Comparación de fechas por string ISO (`YYYY-MM-DD`), lexicográficamente válida.

## Gold — Elo (R12–R19) — `elo.py`

Fórmula estándar eloratings.net, **parametrizable** vía un objeto de parámetros
(dataclass `EloParams`) inyectable con estos defaults:

- `initial = 1500.0` (R12) — rating al primer partido de cada equipo.
- `home_advantage = 100.0` (R16) — se suma a `dr` SOLO si `neutral == False`.
- `default_k = 30.0` y `k_rules` (R14): lista **ordenada** de pares
  `(patrón_substring_case_insensitive, K)`; primera coincidencia gana. Defaults:

| Orden | Patrón sobre `tournament`        | K  | Cubre                                          |
|-------|----------------------------------|----|------------------------------------------------|
| 1     | `world cup` + `qualif`           | 50 | eliminatorias mundialistas (ambas fuentes)     |
| 2     | `world cup`                      | 60 | Mundial (fase final)                           |
| 3     | `nations league`                 | 40 | UEFA/CONCACAF Nations League                   |
| 4     | `confederations cup`             | 40 | Copa Confederaciones                           |
| 5     | `copa américa` / `uefa euro` / `africa(n) cup of nations` / `asian cup` / `gold cup` / `concacaf championship` / `ofc nations cup` | 50 | torneos continentales |
| 6     | `friendl`                        | 20 | `Friendly` (público) y `Friendlies` (API)      |
| —     | default                          | 30 | resto                                          |

  La precedencia 1 > 2 evita que `"FIFA World Cup qualification"` capture el K del
  Mundial. El mapa es configurable: los valores exactos se pueden ajustar sin tocar el
  algoritmo.

- Cálculo por partido (R13, R15, R16, R17):
  - `dr = elo_home − elo_away + (home_advantage si not neutral else 0)`
  - `We_home = 1 / (1 + 10^(−dr/400))`; `We_away = 1 − We_home`
  - `score_home ∈ {1, 0.5, 0}` según resultado; `score_away = 1 − score_home`
  - `G`: `diff = |home_goals − away_goals|`; `diff ≤ 1 → 1.0`; `diff == 2 → 1.5`;
    `diff ≥ 3 → (11 + diff) / 8`
  - `elo_post = elo_pre + K · G · (score − We)` para cada lado, con el **mismo** `K` y
    `G`; por construcción `Δhome + Δaway = 0` (R17).
- Orden de proceso (R18): ascendente por `(date, match_id)` — desempate determinista en
  la misma fecha. Estado en memoria `code → rating` (default `initial`). Misma entrada
  → mismos ratings e historial, byte a byte.
- Alcance global (R19): el Elo se calcula sobre **todas** las filas de silver, incluidas
  las de equipos fuera de las 48 (códigos slug). Ver Decisiones.
- Historial: 2 filas por partido (una por equipo) con
  `date, code, opponent_code, elo_pre, elo_post, k, g, we, score`; `we` y `score` son
  los del equipo de la fila. `elo vigente a as_of_date` = replay del historial con
  `date < as_of_date`; equipo sin partidos previos → `initial`.

## Contratos gold

### `data/gold/elo_history.csv` (R19)

| Columna         | Tipo  | Notas                                  |
|-----------------|-------|----------------------------------------|
| `date`          | str   | `YYYY-MM-DD`                           |
| `code`          | str   | equipo de la fila (FIFA o slug)        |
| `opponent_code` | str   | rival                                  |
| `elo_pre`       | float | rating antes del partido               |
| `elo_post`      | float | rating después                         |
| `k`             | float | K aplicado (mismo para ambos lados)    |
| `g`             | float | multiplicador de margen                |
| `we`            | float | expectativa del equipo de la fila      |
| `score`         | float | 1 / 0.5 / 0 del equipo de la fila      |

Orden de filas: `(date, match_id, lado)` — cronológico y determinista.

### `data/gold/team_features.csv` (R20)

Exactamente **48 filas** (una por selección de `teams.py`, aunque no tenga partidos
previos), columnas en este orden:

| Columna                 | Tipo  | Notas                                       |
|-------------------------|-------|---------------------------------------------|
| `code`                  | str   | FIFA 3 letras (solo las 48)                 |
| `as_of_date`            | str   | `YYYY-MM-DD` inyectada                      |
| `matches_count`         | int   | partidos previos usados (≤ 15)              |
| `gf_ma15`, `ga_ma15`    | float nullable | null si `matches_count = 0`        |
| `corners_for_ma15`, `corners_against_ma15`, `cards_ma15`, `shots_ma15`, `shots_on_target_ma15`, `possession_ma15` | float nullable | null si no hay observaciones con stats (p. ej. solo fuente pública, R11) |
| `elo`                   | float | rating vigente a `as_of_date`; `initial` si sin partidos |

Orden de filas: `code` ascendente.

## Orquestación (R21) — `build.py`

Firma orientativa (sin código de app):

- `build_all(as_of_date, bronze_dir="data/bronze", silver_dir="data/silver", gold_dir="data/gold", elo_params=None) -> dict`
  — construye silver, calcula Elo global + medias móviles, escribe los tres CSVs y
  devuelve un resumen (`n_matches_silver`, `n_teams_gold`, rutas escritas).
- `as_of_date` es **siempre inyectada** (argumento `YYYY-MM-DD`); nunca `now()`
  implícito → reproducible y testeable. Formato inválido → `ValueError` claro.
- Determinismo: ordenaciones estables definidas arriba, orden de columnas fijo,
  serialización CSV por pandas con null → celda vacía. Misma entrada → mismos bytes.
- CLI opcional `python -m src.features.build --as-of-date YYYY-MM-DD` (sin red; no
  aplica la regla STOP de llamadas reales).

## Manejo de errores

| Situación                                   | Comportamiento                                      | Requisito |
|---------------------------------------------|-----------------------------------------------------|-----------|
| Ninguna fuente bronze presente              | `SilverInputError` con mensaje claro; no escribe.   | R7        |
| Falta una de las dos fuentes                | Continúa con la disponible.                         | R7        |
| Fixture con status ≠ `FT`                   | Descarte silencioso (contado en logging).           | R1        |
| Sin statistics para un fixture              | Stats nulas; continúa.                              | R2        |
| Nombre fuera de 48 + alias                  | Código slug fallback; el partido se conserva.       | R4        |
| Equipo sin partidos previos a `as_of_date`  | Medias null, `matches_count=0`, `elo=initial`.      | R10, R20  |
| Archivo bronze JSON ilegible                | Log + omitir archivo; el lote continúa.             | (robustez)|
| `as_of_date` mal formada                    | `ValueError` con formato esperado.                  | R21       |

## Configuración

Sin variables de entorno nuevas y **sin** `API_FOOTBALL_KEY` (procesamiento offline;
no se usa `Settings`/`get_settings`, mismo razonamiento que la feature 7). Todos los
parámetros son argumentos con defaults de módulo: rutas (`bronze_dir`, `silver_dir`,
`gold_dir`), ventana `ROLLING_WINDOW = 15`, `EloParams` (`initial`, `home_advantage`,
`k_rules`, `default_k`). Dependencias inyectables → tests deterministas con `tmp_path`.

## Decisiones y justificación

- **Elo sobre TODOS los partidos del CSV público, no solo las 48** → el rating de una
  selección depende de la fuerza de sus oponentes, que a su vez depende de los oponentes
  de estos: recortar la red a las 48 sesgaría los ratings (oponentes "fantasma" sin
  rating informativo) e impediría la convergencia. Silver conserva esos partidos (R4) y
  `elo_history.csv` los incluye (R19); `team_features.csv` solo expone las 48 (R20).
- **Prioridad api_football en dedupe** → es la única fuente con estadísticas finas
  (córners, tarjetas, tiros, posesión); `neutral`/`tournament` se toman del registro
  público porque ahí son explícitos y verificados.
- **`match_id` con `hashlib` y no `hash()`** → estable entre procesos
  (`PYTHONHASHSEED`); requisito explícito de estabilidad (R5).
- **Slug legible como código fallback** → determinista, depurable en `elo_history.csv`
  y sin colisión con códigos FIFA (mayúsculas, 3 letras).
- **Fechas como string ISO comparadas lexicográficamente** → simple, determinista y
  suficiente (`YYYY-MM-DD` preserva el orden); evita timezones en lógica pura.
- **`as_of_date` inyectada** → mismo principio que `fetched_at` en features 1 y 7: nada
  de reloj interno; anti-leakage verificable en tests (R9).
- **Medias por métrica sobre observaciones no nulas** → mezcla de fuentes: un equipo con
  3 partidos API + 12 públicos promedia stats solo sobre los 3 con datos en vez de
  diluirlas con nulls o fallar (R11).
- **`k_rules` como lista ordenada de patrones** → los nombres de torneo difieren entre
  fuentes (`Friendly` vs `Friendlies`); substring + precedencia explícita resuelve
  ambigüedades (`qualification` antes que `World Cup`) y queda configurable sin tocar
  el algoritmo (R14).
- **Salidas en CSV** → `pyarrow` no está en `requirements.txt`; stack mínimo del repo.
