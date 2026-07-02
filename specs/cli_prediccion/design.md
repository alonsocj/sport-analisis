# design.md — Feature 6: cli_prediccion

## Arquitectura

Un **único módulo a completar**: `src/cli.py` (hoy un stub `NotImplementedError`).
Es una capa de **orquestación fina**: parsea argumentos, delega en las APIs públicas
de las features 7, 2 y 3, formatea la salida y traduce errores. **NO reimplementa**
lógica de ingesta, features ni modelo, y **NO modifica** ningún módulo existente
(todos se usan solo en lectura/llamada). Sin dependencias nuevas: `argparse`, `csv`,
`json`, `difflib`, `pathlib`, `datetime` (stdlib).

| Módulo                          | Responsabilidad                                                            | Requisitos |
|---------------------------------|----------------------------------------------------------------------------|------------|
| `src/cli.py`                    | `main(argv)`, subparsers, una función por subcomando, formateo (texto/JSON), validación de códigos, traducción de errores. | R1–R13 |
| `src/ingestion/public_data.py` (llamada) | `ingest_public_results`, `bronze_public_paths`, `parse_results`, `filter_world_cup_matches`, `to_fifa_code`, `PublicDownloadError`, `PublicSchemaError`. | R2, R10, R12 |
| `src/features/build.py` (llamada)        | `build_all(as_of_date, ...) -> dict`.                              | R3, R12    |
| `src/features/silver.py` (lectura)       | `SilverInputError` (solo para capturarla).                         | R12        |
| `src/models/dixon_coles.py` (llamada)    | `fit_dixon_coles`, `DCConfig`, `save_params`, `load_params`, `predict_match`, `SilverNotFoundError`, `NotFittedError`, `UnknownTeamError`. | R4–R7, R12 |
| `src/ingestion/teams.py` (lectura)       | `all_teams()`: códigos y nombres canónicos de las 48.              | R5, R6     |

Flujo de subcomandos sobre el pipeline:

```
ingest-public ──► bronze público ──► build-features ──► silver + gold ──► train ──► params JSON
                       │                                      │                        │
                       └── schedule (lee bronze crudo)        └── contexto de predict  └── predict (load_params, sin reentrenar)
```

## Contratos consumidos (firmas reales / de spec)

Verificadas contra el código implementado (features 7 y 2) y contra
`specs/modelo_resultado/design.md` (feature 3, en implementación paralela: su
design.md es el contrato vinculante; el CLI casa con esas firmas):

- `ingest_public_results(fetched_at: str, transport=None, url=DEFAULT_URL, bronze_dir=DEFAULT_BRONZE_DIR) -> IngestReport`
  (`IngestReport`: `n_rows_total`, `n_valid`, `n_discarded`, `discarded_by_reason`).
- `bronze_public_paths(bronze_dir) -> tuple[Path, Path]` (csv crudo, sidecar meta).
- `parse_results(csv_text) -> tuple[list[PublicMatch], IngestReport]` y
  `filter_world_cup_matches(matches, from_date=None) -> list[PublicMatch]`.
- `build_all(as_of_date, bronze_dir=..., silver_dir=..., gold_dir=..., elo_params=None, window=15) -> dict`
  con claves `n_matches_silver`, `n_teams_gold`, `paths.{matches, elo_history, team_features}`.
- `fit_dixon_coles(as_of_date, silver_path="data/silver/matches.csv", config=DCConfig()) -> DixonColesParams`;
  `DCConfig(xi=0.65, from_date="2018-01-01", min_matches=5, reg_lambda=1.0, max_iter=1000)` (frozen);
  `save_params(params, path="data/gold/dixon_coles_params.json") -> Path`;
  `load_params(path) -> DixonColesParams`;
  `predict_match(params, home_code, away_code, max_goals=10, top_k=5) -> MatchPrediction`
  (`lambda_home, lambda_away, matrix, prob_home, prob_draw, prob_away, top_scores`).
- `all_teams() -> tuple[Team, ...]` (`Team.code` FIFA 3 letras, `Team.name` canónico).

## Estructura del CLI (R1)

- `main(argv: list[str] | None = None) -> int`: construye el parser, `parse_args(argv)`,
  despacha `return args.func(args)`. Invocación de módulo:
  `if __name__ == "__main__": raise SystemExit(main())`.
- `argparse.ArgumentParser(prog="python -m src.cli")` +
  `add_subparsers(dest="command", required=True)` con EXACTAMENTE 5 subparsers:
  `ingest-public`, `build-features`, `train`, `predict`, `schedule`. Cada subparser
  registra su función con `set_defaults(func=cmd_<nombre>)`:
  `cmd_ingest_public`, `cmd_build_features`, `cmd_train`, `cmd_predict`,
  `cmd_schedule` — todas `(argparse.Namespace) -> int`.

### Política de códigos de salida

| Código | Caso                                                                  |
|--------|-----------------------------------------------------------------------|
| `0`    | Éxito. Incluye estados válidos no-error: aviso de no convergencia (R4) y "sin partidos pendientes" (R10). |
| `1`    | Errores de dominio traducidos por el CLI: códigos de equipo inválidos (R6), `UnknownTeamError` (R7), bronze ausente en `schedule` (R11), excepciones de capas inferiores (R12). Mensaje en **stderr** con prefijo `error:`, sin traceback. |
| `2`    | Errores de uso de `argparse` (sin subcomando, subcomando desconocido, flag requerido ausente, tipo inválido): `SystemExit(2)` de argparse **se propaga** (no se captura). |

Justificación del `2`: es la convención Unix/argparse para errores de uso; R1 solo
exige "distinto de 0" y capturarlo para re-emitir `1` añadiría código sin valor. Los
tests in-proceso lo verifican con `pytest.raises(SystemExit)` y `excinfo.value.code != 0`;
los exit `0/1` se verifican por el retorno de `main(argv)`.

Errores de dominio: cada `cmd_*` envuelve SOLO sus llamadas delegadas en
`try/except` de las excepciones **explícitamente listadas** (tabla de R12); un helper
`_error(msg) -> int` imprime `error: {msg}` en stderr y devuelve `1`. No hay
`except Exception` genérico: cualquier excepción no listada (bug) se propaga con
traceback (R12).

## `ingest-public [--from-date YYYY-MM-DD]` (R2)

Único subcomando que toca red (regla STOP de `CLAUDE.md`: la ejecución real requiere
aprobación previa). Flujo (calcado del precedente `public_data.main`):

1. `fetched_at = datetime.now(timezone.utc).isoformat()` — **única** lectura de reloj
   de todo el CLI, y solo como **metadato de descarga** del sidecar bronze (excepción
   documentada de R13; ninguna lógica predictiva la consume).
2. `report = ingest_public_results(fetched_at)` (transporte real por defecto; en tests
   esta función se monkeypatchea — cero red).
3. Vista de consumo: `csv_path, meta_path = bronze_public_paths(...)`; releer el CSV
   persistido, `parse_results(texto)`, `filter_world_cup_matches(matches, from_date=args.from_date)`.
4. Imprime con `✅`: filas totales/válidas/descartadas, `discarded_by_reason`, las dos
   rutas bronze y `len(vista)` con el `from_date` aplicado. `return 0`.

`--from-date` solo afecta a la vista informativa (la ingesta bronze es siempre
completa y no destructiva, R9 de la feature 7). Sin flags de ruta: el contrato del
Leader fija `ingest-public [--from-date]`; en tests se monkeypatchean
`src.cli.ingest_public_results` y `src.cli.bronze_public_paths` (parseo/filtro reales
sobre el fixture `tests/fixtures/public_results_sample.csv` escrito en `tmp_path`).

## `build-features --as-of-date YYYY-MM-DD` (R3)

- `--as-of-date` **requerido** (`required=True`; sin reloj implícito). Faltante → exit 2.
- `summary = build_all(args.as_of_date)` (rutas default de la feature 2).
- Imprime con `✅`: `n_matches_silver`, `n_teams_gold` y las tres rutas de
  `summary["paths"]` (`matches`, `elo_history`, `team_features`). `return 0`.

## `train --as-of-date YYYY-MM-DD [--from-date] [--xi]` (R4)

- `--as-of-date` requerido; `--from-date` (str) y `--xi` (`type=float`) opcionales
  con default `None`.
- Construcción de la configuración **solo con lo proporcionado**:
  `kwargs = {}` + `from_date`/`xi` solo si no son `None`; `config = DCConfig(**kwargs)`.
  Así los campos no pasados conservan EXACTAMENTE los defaults de `DCConfig`
  (`xi=0.65`, `from_date="2018-01-01"`, …) sin duplicarlos en el CLI (una sola fuente
  de verdad: la feature 3).
- `params = fit_dixon_coles(args.as_of_date, config=config)`;
  `path = save_params(params)` (ruta default `data/gold/dixon_coles_params.json`).
- Imprime con `✅`: `n_matches`, `n_teams`, convergencia (`success`, `n_iter`) y `path`.
- DONDE `convergencia["success"]` sea falso: imprime además una línea de aviso
  `⚠️ el optimizador no convergió ...` en **stderr** (visible y separable del resumen)
  y `return 0` igualmente — coherente con R6 de la feature 3: no se aborta.

## `predict HOME AWAY [--top-k] [--max-goals] [--params] [--features] [--json]` (R5–R9)

Flags y defaults:

| Flag          | Default                              | Notas                                          |
|---------------|--------------------------------------|------------------------------------------------|
| `HOME`, `AWAY`| posicionales requeridos              | códigos FIFA (se normalizan a MAYÚSCULAS).     |
| `--top-k`     | `5`                                  | mismo default que `predict_match` (feature 3). |
| `--max-goals` | `10`                                 | ídem.                                          |
| `--params`    | `data/gold/dixon_coles_params.json`  | ruta del JSON de parámetros (R5).              |
| `--features`  | `data/gold/team_features.csv`        | "ruta parametrizable" del contexto gold (R8).  |
| `--json`      | off                                  | salida machine-readable (R9).                  |

### Orden de validación (R6) — antes de tocar disco

1. Normalizar: `strip()` + `upper()` sobre ambos códigos.
2. Formato: regex `^[A-Z]{3}$`. 3. Pertenencia: `code in {t.code for t in all_teams()}`.
4. `HOME == AWAY` → error de uso.

Cualquier fallo → stderr con el código rechazado + **sugerencia determinista**:
`difflib.get_close_matches(code, sorted(códigos_48), n=3, cutoff=0.4)` (stdlib,
determinista sobre entrada ordenada) y, siempre, la indicación de dónde consultar los
48 (`src/ingestion/teams.py`). `return 1` SIN llamar a `load_params`, sin red y sin
traceback.

### Caso feliz (R5, R7)

- `params = load_params(args.params)` — **nunca** se llama a `fit_dixon_coles` desde
  `predict` (sin reentrenar; un test lo verifica con un centinela).
  `NotFittedError` → traducción R12 ("ejecuta antes `train`").
- `pred = predict_match(params, home, away, max_goals=args.max_goals, top_k=args.top_k)`.
  `UnknownTeamError` (código de las 48 ausente de `attack`/`defense`) → stderr con el
  código y la acción: reentrenar con `train --as-of-date ... --from-date <más antigua>`
  para ampliar la ventana; `return 1` sin traceback (R7).

### Contexto gold opcional (R8)

- SI `Path(args.features).exists()`: leer con `csv.DictReader`, indexar por `code` y
  extraer `elo`, `gf_ma15`, `ga_ma15` de ambos equipos. Celda vacía (null del CSV) o
  fila ausente (defensivo) → `n/d` en texto / `null` en JSON.
- SI no existe: se omite la sección de contexto por completo, sin mensaje de error,
  sin alterar exit code ni el resto de la salida.

### Salida humana (texto)

Líneas con la convención `✅` del repo. Elementos verificables (los tests asertan
contenido, no maquetación exacta): `"<Nombre> (<CODE>)"` de ambos equipos; el
`as_of_date` y la ruta de los parámetros usados; probabilidades 1X2 en **porcentaje**
con 1 decimal (`f"{100*p:.1f}%"`); `lambda_home`/`lambda_away` con 2 decimales;
`top_k` marcadores como `"<h>-<a>  <prob en %>"` en el orden devuelto por
`predict_match`; sección de contexto (elo / gf_ma15 / ga_ma15 por equipo) solo si
aplica R8.

### Salida `--json` (R9)

Un único `json.dumps(doc, ensure_ascii=False)` a stdout — **sin** líneas `✅` ni texto
adicional (stdout íntegramente parseable). Esquema:

```json
{
  "home": {"code": "ARG", "name": "Argentina"},
  "away": {"code": "MEX", "name": "Mexico"},
  "as_of_date": "2026-06-01",
  "params_path": "data/gold/dixon_coles_params.json",
  "lambda_home": 1.83,
  "lambda_away": 0.94,
  "probs": {"home": 0.61, "draw": 0.22, "away": 0.17},
  "top_scores": [{"home_goals": 1, "away_goals": 0, "prob": 0.14}],
  "context": {
    "home": {"elo": 2100.5, "gf_ma15": 2.1, "ga_ma15": 0.7},
    "away": {"elo": 1850.0, "gf_ma15": null, "ga_ma15": null}
  }
}
```

- `as_of_date` = el de los parámetros cargados (NO la fecha actual: cero reloj).
- `probs` como fracciones 0–1 sin redondear (suman 1 por la renormalización de la
  feature 3; tolerancia 1e−9 en tests). `context` = `null` si el gold no existe.
- **La matriz conjunta NO se incluye.** Justificación: son `(max_goals+1)²` ≥ 121
  floats que ningún consumidor del CLI necesita (1X2 + lambdas + top-k ya resumen);
  hincharía y desestabilizaría la salida (cambiaría con `--max-goals`); y el consumidor
  programático legítimo (feature 4) consumirá `score_matrix`/`predict_match` por API
  Python, no parseando stdout del CLI.

## `schedule [--limit N] [--results-csv RUTA]` (R10, R11)

- `--limit` default **`10`**. Justificación: vista compacta de "qué predecir ahora"
  (≈ una jornada); el calendario WC2026 completo en bronze son 70+ filas y se obtiene
  subiendo `--limit`. `--results-csv` default `data/bronze/public_results/results.csv`
  — la "ruta parametrizable" de R10 (tests con `tmp_path` sin monkeypatch de rutas).
- SI la ruta no existe → stderr: el bronze público no existe; ejecutar antes
  `python -m src.cli ingest-public`; `return 1` (R11).
- Lectura del **CSV crudo** con `csv.DictReader` — deliberadamente NO se usa
  `parse_results`/`filter_world_cup_matches` (feature 7): esa vista de consumo
  **descarta** los partidos pendientes precisamente porque sus scores no son numéricos
  (`goles_no_numericos`). El criterio de "pendiente" es la marca del dataset, nunca el
  reloj (cero `now()`):

  ```
  pendiente(fila) :=  fila["tournament"] == "FIFA World Cup"
                      y (home_score no convertible a int  o  away_score no convertible a int)
  ```

  Helper local `_is_int` propio del CLI (no se importan privados de `public_data`).
  Filas con campos ausentes/malformadas se ignoran de forma defensiva (mismo espíritu
  tolerante del parseo de la feature 7).
- Orden: ascendente por `(date, home_team, away_team)` — cronológico con desempate
  determinista (ISO `YYYY-MM-DD` compara lexicográficamente). Se muestran los
  primeros `N`: fecha y `"<home_team> (<CODE>) vs <away_team> (<CODE>)"`, con el
  código vía `to_fifa_code(nombre)`; alias inexistente → solo el nombre, sin código.
- 0 pendientes → mensaje claro en stdout (estado válido) y `return 0`.

## Manejo de errores (R6, R7, R11, R12)

| Subcomando       | Excepción / condición            | Mensaje en stderr (accionable)                                        | Exit |
|------------------|----------------------------------|------------------------------------------------------------------------|------|
| (todos)          | uso inválido de argparse         | uso/ayuda de argparse                                                  | 2    |
| `ingest-public`  | `PublicDownloadError`            | descarga falló (status/URL en el mensaje de la excepción); verificar conectividad/URL y reintentar `ingest-public` (es la cabeza del flujo: nada que ejecutar antes). | 1 |
| `ingest-public`  | `PublicSchemaError`              | el esquema de la fuente cambió (esperado vs recibido); no continuar el flujo, revisar `specs/ingesta_publica`. | 1 |
| `build-features` | `SilverInputError`               | no hay bronze: ejecutar primero `ingest-public`.                       | 1    |
| `build-features` / `train` | `ValueError` (fecha)   | fecha mal formada; formato esperado `YYYY-MM-DD`.                      | 1    |
| `train`          | `SilverNotFoundError`            | no hay silver: ejecutar primero `build-features --as-of-date ...`.     | 1    |
| `predict`        | código inválido / fuera de 48 / HOME==AWAY | código rechazado + sugerencias difflib + dónde ver los 48 (R6). | 1    |
| `predict`        | `NotFittedError`                 | no hay parámetros entrenados: ejecutar primero `train --as-of-date ...`. | 1  |
| `predict`        | `UnknownTeamError`               | el código no está en los parámetros: reentrenar ampliando ventana (`train ... --from-date`). | 1 |
| `schedule`       | CSV bronze inexistente           | ejecutar primero `ingest-public` (R11).                                | 1    |
| (todos)          | excepción NO listada (bug)       | NO se captura: se propaga con traceback.                               | —    |

Todos los mensajes recuerdan el orden del flujo cuando aplica:
`ingest-public → build-features → train → predict`.

## Firmas orientativas (sin código de app)

- `main(argv: list[str] | None = None) -> int` — R1.
- `build_parser() -> argparse.ArgumentParser` — registro de los 5 subparsers.
- `cmd_ingest_public(args) -> int` — R2, R12.
- `cmd_build_features(args) -> int` — R3, R12.
- `cmd_train(args) -> int` — R4, R12.
- `cmd_predict(args) -> int` — R5–R9, R12.
- `cmd_schedule(args) -> int` — R10, R11.
- Helpers puros: `_error(msg) -> int` (stderr + 1), `_validate_team_code(raw) -> str`
  (normaliza/valida/sugiere), `_read_team_context(path, codes) -> dict | None` (R8),
  `_is_int(value) -> bool`, `_pending_world_cup_rows(csv_path) -> list[dict]` (R10).
- Constantes de módulo: `DEFAULT_PARAMS_PATH`, `DEFAULT_FEATURES_CSV`,
  `DEFAULT_RESULTS_CSV`, `DEFAULT_SCHEDULE_LIMIT = 10`,
  `WC_TOURNAMENT = "FIFA World Cup"`.

## Configuración y entorno (R13)

- Sin variables de entorno nuevas y **sin** `API_FOOTBALL_KEY`: `src/cli.py` NO importa
  `src.ingestion.config`, `client` ni `ingest` (los módulos que sí la requieren).
  Importar `src.cli` no dispara red: `public_data` importa `requests` de forma
  perezosa solo en su transporte real, y `build`/`dixon_coles` son offline por diseño.
- Todos los defaults son constantes de módulo + flags; nada se lee de env.
- Reloj: el ÚNICO uso es `fetched_at` (metadato de la descarga real en
  `ingest-public`, ver arriba). `as_of_date` es siempre argumento explícito
  (`build-features`, `train`); `predict` reporta el `as_of_date` **de los parámetros
  cargados**; `schedule` detecta pendientes por la marca del dataset. Decisión
  alineada con la preferencia del Leader: **ningún subcomando defaultea a "hoy"**.

## Decisiones y justificación

- **CLI como capa fina de orquestación** → toda la lógica vive en las features 7/2/3
  ya especificadas; el CLI solo parsea, delega, formatea y traduce errores. Evita
  duplicación y deriva de contratos.
- **`set_defaults(func=cmd_*)` + una función por subcomando** → contrato del Leader;
  cada subcomando testeable en aislamiento vía `main(argv)` y `monkeypatch` de las
  funciones delegadas referenciadas en `src.cli`.
- **Exit 2 de argparse sin capturar** → convención estándar; R1 solo pide ≠ 0;
  capturarlo añadiría indirection sin beneficio. Dominio = 1, éxito = 0.
- **Traducción de errores por lista explícita (sin `except Exception`)** → R12: los
  errores esperables del flujo se vuelven accionables (qué comando ejecutar antes);
  los bugs no se enmascaran.
- **`DCConfig(**kwargs)` solo con flags presentes** → los defaults del modelo viven
  SOLO en la feature 3 (una fuente de verdad); el CLI no los copia ni los pisa.
- **`schedule` lee el bronze crudo, no la vista de consumo de la feature 7** → los
  partidos pendientes tienen scores `NA` y `parse_results` los descarta por diseño
  (`goles_no_numericos`); la marca "score no numérico" es además el detector de
  pendiente SIN reloj (R10/R13).
- **`--limit 10` default** → vista compacta de "próximos a predecir"; ampliable.
- **Sugerencias con `difflib` (stdlib)** → determinista, cero dependencias nuevas,
  errores de tipeo (`ARH` → `ARG`) resueltos en un paso (R6).
- **`--json` sin matriz conjunta** → salida pequeña y estable; los consumidores que
  necesitan la matriz (feature 4) usan la API Python (`score_matrix`), no stdout.
- **Mercados (feature 4) fuera de alcance** → no-objetivo explícito del Leader
  (2026-06-09); `predict` muestra SOLO 1X2 + lambdas + top-k. La extensión "y sus
  mercados" de `CHECKPOINTS.md` § 6 se especificará cuando la feature 4 exista.
- **`fetched_at = now()` solo como metadato de descarga** → idéntico principio que
  features 1 y 7: el reloj nunca entra en lógica predictiva; en tests la función
  ingestora está monkeypatcheada y el valor ni se usa.
