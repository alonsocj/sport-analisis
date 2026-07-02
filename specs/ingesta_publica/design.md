# design.md — Feature 7: ingesta_publica

## Arquitectura

Un único módulo nuevo en `src/ingestion/`; el resto de archivos de la feature 1
(`config.py`, `client.py`, `bronze.py`, `ingest.py`, `teams.py`) se usan **solo en lectura**
y NO se modifican.

| Módulo                          | Responsabilidad                                                          | Requisitos |
|---------------------------------|--------------------------------------------------------------------------|------------|
| `src/ingestion/public_data.py`  | Descarga (transport inyectable), validación de esquema, bronze CSV+meta, parseo tolerante, alias FIFA, filtro 48, `from_date`, CLI explícita. | R1–R9 |
| `src/ingestion/teams.py` (lectura) | Fuente de verdad de las 48 selecciones y sus códigos FIFA.            | R7, R8     |

Flujo de la ingesta:

```
fetch (transport) → validar encabezado → escribir bronze (crudo + meta)
                                            ↓
                              parsear filas (descartes contados)
                                            ↓
                  vista de consumo: filtro 48 selecciones + from_date
```

## Fuente pública (R1)

- URL (default parametrizable):
  `https://raw.githubusercontent.com/martj42/international_results/master/results.csv`
- Licencia **CC0**; dataset mantenido (resultados internacionales 1872 → presente,
  actualización frecuente). Verificado por el Leader el 2026-06-09 (HTTP 200).
- Encabezado verificado:
  `date,home_team,away_team,home_score,away_score,tournament,city,country,neutral`.
- Complementa API-Football **sin consumir cuota**: aporta profundidad histórica (Elo y
  medias móviles aguas abajo) mientras API-Football aporta estadísticas finas recientes.

### Sin secretos (R1)

Esta fuente no requiere autenticación. Por diseño, `public_data.py` **no usa**
`Settings`/`get_settings()` de `config.py`: ese constructor exige `API_FOOTBALL_KEY` (R1 de
la feature 1) y aquí obligaría a definir un secreto innecesario. Los parámetros (`url`,
`bronze_dir`, `transport`, `fetched_at`, `from_date`) se inyectan como argumentos con
defaults de módulo. La regla de no-secretos de `CLAUDE.md` sigue aplicando: ningún token,
key ni credencial se escribe en el repo ni en logs.

## Transporte inyectable y descarga explícita (R2)

Contrato del transporte (más simple que el de `client.py` porque es un único GET sin
headers ni params):

```
PublicTransport = Callable[[str], str]   # url -> texto CSV (UTF-8 decodificado)
```

- **Transporte por defecto** (descarga real): `requests.get(url, timeout=60)` con import
  perezoso (mismo patrón que `_default_transport` de `client.py`); status ≠ 2xx → error
  claro (`PublicDownloadError` con status y URL). Sin reintentos en v1: GitHub raw no
  presenta rate limit práctico para una descarga puntual (decisión revisable).
- **Tests**: inyectan un transporte falso que devuelve el contenido del fixture
  `tests/fixtures/public_results_sample.csv`. Cero red real, determinista.
- **Descarga real solo explícita**: únicamente vía la función orquestadora invocada por el
  CLI `python -m src.ingestion.public_data [--from-date YYYY-MM-DD]`. Importar el módulo no
  dispara red. Regla STOP de `CLAUDE.md`: la ejecución real del CLI requiere aprobación
  previa del usuario (llamada de red real, aunque sin coste de cuota).

## Esquema capa bronze (R4) — variante justificada del patrón

```
data/bronze/public_results/results.csv        # CSV crudo tal cual (byte a byte)
data/bronze/public_results/results.meta.json  # sidecar de metadatos
```

Contenido del sidecar:

```json
{
  "url": "https://raw.githubusercontent.com/martj42/international_results/master/results.csv",
  "fetched_at": "<timestamp inyectado>",
  "sha256": "<hash hex del contenido del CSV>",
  "n_rows": 12345,
  "header": ["date", "home_team", "away_team", "home_score", "away_score",
             "tournament", "city", "country", "neutral"]
}
```

**Justificación de la variante** (CSV crudo en lugar del JSON envuelto de `bronze.py`):

- El payload es **tabular y grande** (~49k filas): envolverlo como string dentro de un JSON
  duplicaría tamaño y obligaría a escapar todo el contenido, perdiendo legibilidad.
- "Crudo tal cual" byte a byte hace el `sha256` verificable contra la fuente y permite
  relectura directa (pandas / `csv` de stdlib) sin des-envolver.
- Los metadatos del patrón bronze de la feature 1 (`fetched_at` **inyectado**, origen,
  trazabilidad) se conservan en el **sidecar** `.meta.json`.
- Ruta **fija y determinista**: es un recurso único sin parámetros, no aplica `param_key`.
  Cada descarga sobreescribe el snapshot; el `sha256` del meta permite detectar si la fuente
  cambió entre ejecuciones.

## Validación de esquema (R3)

- Constante `EXPECTED_HEADER` con los 9 nombres en orden exacto.
- Se compara la **primera línea** del CSV (parseada como CSV, no por string crudo) contra
  `EXPECTED_HEADER`. SI difiere → `PublicSchemaError` cuyo mensaje incluye encabezado
  esperado y recibido, y **no se persiste nada** (la validación ocurre antes de la escritura
  bronze).

## Parseo y validación de filas (R5, R6)

Parseo fila a fila con `csv` de stdlib (no `pandas.read_csv`): permite descartar y **contar
por motivo** cada fila corrupta de forma determinista, en lugar de abortar el lote o
coercionar en silencio.

Reglas de descarte (R5), cada una con su motivo en el reporte:

| Motivo                  | Condición                                                       |
|-------------------------|-----------------------------------------------------------------|
| `fecha_invalida`        | `date` no parseable como `YYYY-MM-DD` (`date.fromisoformat`).   |
| `goles_no_numericos`    | `home_score` o `away_score` no convertible a `int`.             |
| `columnas_incompletas`  | número de campos distinto de 9 (refinamiento defensivo).        |

Reporte del lote (dataclass `IngestReport`): `n_rows_total`, `n_valid`, `n_discarded`,
`discarded_by_reason: dict[str, int]`.

Registro parseado (dataclass `PublicMatch`, R6):

| Campo        | Tipo  | Normalización                                  |
|--------------|-------|------------------------------------------------|
| `date`       | str   | `YYYY-MM-DD` (ISO).                            |
| `home_team`  | str   | nombre tal como aparece en el dataset.         |
| `away_team`  | str   | nombre tal como aparece en el dataset.         |
| `home_score` | int   | goles local.                                   |
| `away_score` | int   | goles visitante.                               |
| `tournament` | str   | p. ej. `FIFA World Cup`, `Friendly`.           |
| `city`       | str   | ciudad.                                        |
| `country`    | str   | país sede.                                     |
| `neutral`    | bool  | `TRUE` → `True`, `FALSE` → `False` (case-insensitive). |

Firmas orientativas (sin código de app):

- `fetch_public_results(transport, url) -> str` — texto CSV crudo.
- `validate_header(csv_text) -> None` — levanta `PublicSchemaError` (R3).
- `write_bronze_public(csv_text, bronze_dir, url, fetched_at) -> tuple[Path, Path]` — R4.
- `parse_results(csv_text) -> tuple[list[PublicMatch], IngestReport]` — R5, R6.
- `to_fifa_code(dataset_name) -> str | None` — R7.
- `filter_world_cup_matches(matches, from_date=None) -> list[PublicMatch]` — R8, R9.
- `ingest_public_results(fetched_at, transport=None, url=DEFAULT_URL, bronze_dir=...) -> IngestReport` — orquesta.

## Alias nombre-dataset → código FIFA (R7) y filtro (R8)

- `DATASET_ALIASES: dict[str, str]` vive en `public_data.py` (junto a la fuente que
  introduce los nombres) y se **exporta** para que `feature_store` lo consuma al construir
  `home_code`/`away_code` en silver.
- Se construye desde los `name` de `teams.py` (la mayoría coinciden con el dataset) más
  alias explícitos para las divergencias. Ejemplos confirmados:
  `'United States'` → `USA`, `'South Korea'` → `KOR`, `'Ivory Coast'` → `CIV`.
  El implementer DEBE verificar los nombres de las 48 contra el dataset (un nombre del
  dataset puede mapear a un código; varios alias pueden apuntar al mismo código).
- **Invariante (testeada)**: el conjunto de valores del mapa cubre exactamente los 48
  códigos de `teams.py` (`{t.code for t in all_teams()}`).
- `to_fifa_code(name)`: lookup exacto en el mapa; nombre desconocido → `None`.
- Filtro (R8): conserva el partido si `to_fifa_code(home_team)` **o**
  `to_fifa_code(away_team)` no es `None`.

## Recorte temporal `from_date` (R9)

- Parámetro opcional `from_date: str | None` (`YYYY-MM-DD`), aplicado SOLO en la vista de
  consumo (`filter_world_cup_matches`): se conservan partidos con `date >= from_date`
  (comparación lexicográfica válida en ISO).
- Default `None` → historia completa: el decaimiento temporal es responsabilidad del modelo
  (feature 3), no de la ingesta.
- El recorte es **no destructivo**: bronze siempre conserva el CSV completo
  (reproducibilidad; cambiar `from_date` no exige re-descargar).

## Contrato de datos del Leader (referencia aguas abajo)

Esta feature entrega **bronze + registros parseados + alias map**. La materialización
silver/gold corresponde a la feature 2 (`feature_store`), que consumirá lo anterior bajo
este contrato (definido por el Leader, 2026-06-09):

**SILVER `data/silver/matches.csv`** — columnas:
`match_id` (str estable: hash corto de `source|date|home_code|away_code`), `date`
(`YYYY-MM-DD`), `home_code`, `away_code` (FIFA 3 letras), `home_team`, `away_team` (nombre
canónico), `home_goals`, `away_goals` (int), `tournament` (str), `neutral` (bool), `source`
(`'api_football'` | `'public_csv'`), y columnas opcionales **nullable** solo para
`source='api_football'`: `home_corners`, `away_corners`, `home_cards`, `away_cards`,
`home_shots`, `away_shots`, `home_shots_on_target`, `away_shots_on_target`,
`home_possession`, `away_possession`.

→ Los registros de esta feature alimentan las filas `source='public_csv'`: `PublicMatch`
aporta `date`, `home_goals`/`away_goals`, `tournament`, `neutral` directamente, y
`home_code`/`away_code` vía `DATASET_ALIASES`; las columnas de estadísticas quedan null.

**GOLD** (definido por el Leader; se especifica e implementa en `specs/feature_store/`,
feature 2 — aquí se copia para fijar el contrato de consumo):

- `data/gold/team_features.csv`: `code, as_of_date, matches_count, gf_ma15, ga_ma15`,
  stats ma15 **nullable** (`corners_for_ma15, corners_against_ma15, cards_ma15, shots_ma15,
  shots_on_target_ma15, possession_ma15`) y `elo`.
- `data/gold/elo_history.csv`: detalle por partido
  (`date, code, opponent_code, elo_pre, elo_post, k, g, we, score`).
- **Elo** (fórmula estándar eloratings.net, parametrizable): inicial 1500; `K` por
  importancia del torneo (mapa configurable: Mundial=60, continental y eliminatorias
  mundialistas=50, Nations League/Confederaciones=40, amistosos=20, default=30);
  multiplicador de margen `G` con `diff = |home_goals − away_goals|`:
  `diff <= 1 → 1.0`, `diff == 2 → 1.5`, `diff >= 3 → (11 + diff) / 8`;
  esperado `We = 1/(1 + 10^(−dr/400))` con `dr = elo_home − elo_away + 100` si
  `neutral=False` (sin el +100 si `neutral=True`).
- **Medias móviles**: últimas 15 observaciones por equipo y métrica, usando SOLO partidos
  **estrictamente anteriores** a `as_of_date` (sin fuga de información / leakage).

Salidas de datos siempre en **CSV** (no parquet: `pyarrow` no está en `requirements.txt`).

## Manejo de errores

| Situación                              | Comportamiento                                            | Requisito |
|----------------------------------------|-----------------------------------------------------------|-----------|
| HTTP ≠ 2xx en descarga real            | `PublicDownloadError` con status y URL; nada se persiste. | R2        |
| Encabezado distinto del esperado       | `PublicSchemaError` (esperado vs recibido); no persiste.  | R3        |
| Fila con goles/fecha inválidos         | Descarte contado por motivo; el lote continúa.            | R5        |
| Nombre de equipo desconocido           | `to_fifa_code` → `None`; el filtro lo excluye sin fallar. | R7, R8    |

## Decisiones y justificación

- **Transport `url → texto` inyectable** → tests offline y deterministas; la firma es más
  simple que la de `client.py` porque no hay headers, params ni paginación.
- **Sin `Settings`/`get_settings`** → la fuente no usa secretos; reutilizar la config de la
  feature 1 exigiría `API_FOOTBALL_KEY` sin necesidad (violaría R1 de esta feature).
- **CSV crudo + sidecar de metadatos** (variante bronze) → payload tabular grande,
  `sha256` verificable, relectura directa; los metadatos del patrón se conservan.
- **Bronze completo; filtros solo en consumo** → reproducibilidad: `from_date` y el filtro
  de las 48 no destruyen historia.
- **`csv` de stdlib para el parseo** → control fila a fila para descartar/contar corruptas
  (R5) sin abortar ni coercionar en silencio.
- **Alias map en este módulo** → cohesión con la fuente que introduce los nombres;
  `feature_store` lo importa (una sola fuente de verdad para la traducción a FIFA).
- **`fetched_at` inyectado** → mismo principio que la feature 1: nada de reloj interno en
  lógica pura; tests deterministas.
- **Sin reintentos/backoff en v1** → descarga única a GitHub raw sin rate limit práctico;
  simplicidad. Revisable si la fuente cambia de hosting.
