# design.md — Feature 1: ingesta_datos

## Arquitectura

Módulos en `src/ingestion/`:

| Módulo       | Responsabilidad                                                        | Requisitos |
|--------------|-----------------------------------------------------------------------|------------|
| `config.py`  | `Settings` (pydantic-settings): lee env, valida `API_FOOTBALL_KEY`.   | R1         |
| `teams.py`   | Lista parametrizada de las 48 selecciones; anfitrionas marcadas.      | R8         |
| `client.py`  | Cliente HTTP API-Football: caché local + backoff en 429 + errores.   | R6, R7, R9 |
| `bronze.py`  | Escritura/lectura de la capa bronze (particionado determinista).      | R5         |
| `ingest.py`  | Orquesta: por selección → últimos 15 + stats + odds → bronze.        | R2,R3,R4,R9|

Dependencia HTTP inyectable: `client.py` recibe un `session`/transport mockeable para que
los tests corran **sin red real**.

## Configuración (`config.py`)

`Settings` (pydantic-settings) con prefijo de entorno:

- `API_FOOTBALL_KEY` (str, **requerido**) — sin default; si falta → error (R1).
- `API_FOOTBALL_BASE_URL` (str, default `https://v3.football.api-sports.io`).
- `BRONZE_DIR` (path, default `data/bronze`).
- `CACHE_DIR` (path, default `data/bronze/_cache`).
- `RATE_MAX_RETRIES` (int, default 3) — reintentos ante 429 (R7).
- `RATE_BACKOFF_SECONDS` (float, default 1.0) — base de backoff (R7).

La key se lee SOLO de env. Nunca se escribe en disco ni en logs.

## Endpoints API-Football (v3)

Header de auth: `x-apisports-key: <API_FOOTBALL_KEY>`.

| Recurso             | Endpoint                  | Parámetros clave                         | Requisito |
|---------------------|---------------------------|------------------------------------------|-----------|
| Últimos N partidos  | `GET /fixtures`           | `team=<id>`, `last=15`                    | R2        |
| Estadísticas partido| `GET /fixtures/statistics`| `fixture=<id>`                           | R3        |
| Cuotas              | `GET /odds`               | `fixture=<id>`                           | R4        |
| Equipos (ref)       | `GET /teams`              | `search=<nombre>` / `id=<id>`            | R8 (ref)  |

Mapeo de estadísticas (campo API → esquema interno):
`Shots on Goal → shots_on_target`, `Total Shots → shots`, `Corner Kicks → corners`,
`Yellow Cards`+`Red Cards → cards`, `Ball Possession → possession`, goles desde el fixture.

## Esquema capa bronze (R5)

Un archivo JSON crudo por respuesta, ruta determinista:

```
data/bronze/<endpoint>/<param_key>.json
  fixtures/team=<id>_last=15.json
  fixtures_statistics/fixture=<id>.json
  odds/fixture=<id>.json
```

Cada archivo guarda el payload tal cual lo devuelve la API (clave `response` + meta),
más un envoltorio con `endpoint`, `params` y `fetched_at` (timestamp inyectado, no `Date.now`
dentro de lógica pura — se pasa como argumento para tests deterministas).

`param_key` se deriva ordenando los params (`k=v` unidos por `_`) → idempotente.

## Caché local (R6)

- La **cache key** = misma `param_key` del bronze (endpoint + params ordenados).
- Antes de llamar HTTP, `client.py` busca el archivo en `CACHE_DIR`. Si existe → lo devuelve
  y NO hace request. Si no → hace request y escribe la respuesta en caché.
- En esta feature, bronze y caché comparten la respuesta cruda; la caché evita repetir llamadas
  entre ejecuciones. (TTL: no expira en v1; invalidación manual borrando el archivo.)

## Rate limiting (R7)

- Ante status `429`, reintentar hasta `RATE_MAX_RETRIES` con backoff
  `RATE_BACKOFF_SECONDS * (2 ** intento)` (exponencial). La función de espera (`sleep`) es
  inyectable para que los tests no esperen tiempo real.
- Agotados los reintentos → levantar `RateLimitError` para ese recurso (capturado por R9 a nivel lote).

## Manejo de errores (R9)

- `client.py` distingue: 2xx (ok), 429 (rate limit → R7), otros (error HTTP).
- `ingest.py` envuelve cada selección/partido en try/except: registra el fallo
  (`logging`) y continúa con el resto. Devuelve un resumen con `ok` y `errores`.

## Selecciones (R8) — `teams.py`

Estructura: lista de `{name, code, host}` con 48 entradas. `host=True` solo para
MEX, USA, CAN (localía parametrizada para features posteriores). Helper
`host_teams()` y `is_host(code)`. La lista es editable/parametrizable (no depende de red).

## Decisiones y justificación

- **Transport inyectable + sleep inyectable** → tests deterministas, offline, sin quemar cuota.
- **Bronze = crudo inmutable** → reproducibilidad; la limpieza vive en feature 2 (silver/gold).
- **param_key ordenada** → idempotencia de caché y bronze.
- **Sin TTL en v1** → simplicidad; suficiente para la ventana del torneo. Revisable.
