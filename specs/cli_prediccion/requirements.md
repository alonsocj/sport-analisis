# requirements.md — Feature 6: cli_prediccion

Objetivo: un **CLI único** en `src/cli.py` (argparse, sin dependencias nuevas) que
orquesta el pipeline completo del proyecto y **predice un partido del Mundial 2026**:

```
ingest-public  →  build-features  →  train  →  predict
                                                 schedule (auxiliar: qué predecir)
```

El CLI **consume** las APIs públicas ya especificadas: feature 7
(`src.ingestion.public_data.ingest_public_results`, `specs/ingesta_publica/design.md`),
feature 2 (`src.features.build.build_all`, `specs/feature_store/design.md`) y feature 3
(`fit_dixon_coles` / `save_params` / `load_params` / `predict_match` de
`src.models.dixon_coles`, `specs/modelo_resultado/design.md`). NO reimplementa lógica
de esas capas ni modifica sus módulos.

**No-objetivo (explícito, decisión del Leader 2026-06-09)**: los mercados
over/under, córners y tarjetas (feature 4 `modelos_mercados`) quedan FUERA del
alcance de este CLI v1. `predict` muestra SOLO 1X2, lambdas y marcadores; la
extensión a mercados se especificará cuando la feature 4 exista (el texto de
`CHECKPOINTS.md` § 6 "y sus mercados" se satisface en esa extensión futura).

Notación EARS. Cada `R<n>` es verificable y mapea a ≥1 test (ver `tasks.md`).
Tests 100 % **offline y deterministas**: el CLI se invoca **en proceso** vía
`main(argv)` con `monkeypatch`/fixtures (`tmp_path`, `capsys`); cero red real, cero
reentrenamientos costosos (los tests de `predict` usan un **JSON de parámetros
sintético** escrito en `tmp_path`), cero `now()` en lógica predictiva.

---

## Estructura del CLI

**R1 — Punto de entrada testeable y subcomandos.**
El sistema DEBE exponer en `src/cli.py` una función `main(argv: list[str] | None = None)
-> int` construida con `argparse` y EXACTAMENTE estos subcomandos: `ingest-public`,
`build-features`, `train`, `predict` y `schedule`, cada uno implementado en una
función propia. CUANDO se invoca sin subcomando o con un subcomando desconocido,
el sistema DEBE mostrar el uso/ayuda y terminar con código de salida distinto de 0.

## Subcomandos del pipeline

**R2 — `ingest-public`: ingesta delegada y reporte.**
CUANDO se invoca `ingest-public [--from-date YYYY-MM-DD]`, el sistema DEBE ejecutar la
ingesta vía `src.ingestion.public_data.ingest_public_results` (el transporte real por
defecto SOLO se usa en ejecución real explícita; en tests el transporte DEBE estar
mockeado — cero red) e imprimir con la convención `✅` el `IngestReport` resultante:
filas totales, válidas, descartadas, descartes por motivo, rutas bronze escritas y
tamaño de la vista de consumo (48 selecciones, con el `from_date` aplicado si se pasó),
terminando con exit 0.

**R3 — `build-features`: silver/gold delegado y resumen.**
CUANDO se invoca `build-features --as-of-date YYYY-MM-DD`, el sistema DEBE llamar a
`src.features.build.build_all(as_of_date, ...)` e imprimir con `✅` el resumen
devuelto: `n_matches_silver`, `n_teams_gold` (48) y las tres rutas escritas
(`matches`, `elo_history`, `team_features`), terminando con exit 0. `--as-of-date`
DEBE ser obligatorio (sin reloj implícito).

**R4 — `train`: ajuste delegado, persistencia y resumen.**
CUANDO se invoca `train --as-of-date YYYY-MM-DD [--from-date YYYY-MM-DD] [--xi F]`,
el sistema DEBE llamar a `fit_dixon_coles` (pasando `from_date`/`xi` en la
configuración SOLO si se proporcionaron; en su ausencia rigen los defaults de
`DCConfig`) y persistir con `save_params`, e imprimir con `✅` el resumen:
`n_matches`, `n_teams`, convergencia (`success`, iteraciones) y la ruta del JSON
escrito, terminando con exit 0. DONDE `convergencia.success = False`, el sistema
DEBE hacer visible un aviso en la salida SIN cambiar el exit code (coherente con
R6 de la feature 3: no se aborta).

## Predicción

**R5 — `predict`: caso feliz sin reentrenar.**
CUANDO se invoca `predict HOME_CODE AWAY_CODE [--top-k N] [--max-goals N]
[--params RUTA]` y la ruta de parámetros contiene un JSON válido del contrato de la
feature 3, el sistema DEBE cargar los parámetros con `load_params` (**sin
reentrenar**), llamar a `predict_match(params, home, away, max_goals, top_k)` y
mostrar en texto legible: ambos equipos (nombre canónico + código FIFA), las
probabilidades 1X2 en **porcentaje**, las lambdas esperadas (`lambda_home`,
`lambda_away`) y los `k` marcadores más probables con su probabilidad, terminando
con exit 0.

**R6 — Validación de códigos de equipo en la entrada.**
El sistema DEBE normalizar `HOME_CODE`/`AWAY_CODE` a MAYÚSCULAS antes de validar.
SI un código normalizado no tiene formato de 3 letras (`A–Z`) o no pertenece a las
48 selecciones de `src.ingestion.teams.all_teams()`, ENTONCES el sistema DEBE
terminar con exit ≠ 0 e imprimir en stderr un error claro que incluya el código
rechazado y una sugerencia de códigos válidos (los más cercanos y/o la indicación
de cómo consultar los 48), SIN cargar parámetros, SIN red y SIN traceback.
SI `HOME_CODE == AWAY_CODE` (tras normalizar), ENTONCES el sistema DEBE fallar
con error de uso claro y exit ≠ 0.

**R7 — Equipo de las 48 sin parámetros entrenados.**
SI el código pertenece a las 48 pero `predict_match` levanta `UnknownTeamError`
(código ausente de `attack`/`defense` de los parámetros cargados), ENTONCES el
sistema DEBE traducirlo a un mensaje claro en stderr que incluya el código y la
acción sugerida (reentrenar con `train` ampliando la ventana `--from-date`),
terminando con exit 1 y sin traceback.

**R8 — Contexto gold opcional en `predict`.**
DONDE exista el CSV de features de equipo (default `data/gold/team_features.csv`,
ruta parametrizable), `predict` DEBE mostrar adicionalmente el contexto de ambos
equipos: `elo` y forma `gf_ma15`/`ga_ma15` (valores nulos → `n/d`).
SI el archivo no existe, ENTONCES el sistema DEBE omitir la sección de contexto
**sin fallar** y sin alterar el exit code ni el resto de la salida.

**R9 — Salida machine-readable `--json`.**
DONDE se pase `--json` a `predict`, la salida en stdout DEBE ser un **único
documento JSON parseable** (sin líneas decorativas `✅` mezcladas) con las claves:
`home`/`away` (objetos `{code, name}`), `as_of_date` (la de los parámetros),
`params_path`, `lambda_home`, `lambda_away`, `probs` (`{home, draw, away}` como
fracciones 0–1 que suman 1), `top_scores` (lista de
`{home_goals, away_goals, prob}`) y `context` (objeto con `elo`/`gf_ma15`/`ga_ma15`
por equipo, o `null` si el gold no existe). La matriz conjunta completa NO DEBE
incluirse (decisión justificada en `design.md`).

## Calendario

**R10 — `schedule`: próximos partidos del Mundial 2026.**
CUANDO se invoca `schedule [--limit N]` y existe el bronze público
(`data/bronze/public_results/results.csv`, ruta parametrizable), el sistema DEBE
listar los partidos del Mundial 2026 **aún no jugados** — filas con
`tournament == "FIFA World Cup"` y scores **no numéricos** (la marca de "pendiente"
del dataset; NUNCA una comparación contra la fecha actual: cero reloj) — en orden
cronológico ascendente (desempate determinista), mostrando fecha y ambos equipos
con su código FIFA cuando el alias exista, limitado a los primeros `N` (default
documentado en `design.md`), terminando con exit 0. SI no hay partidos pendientes,
DEBE indicarlo con un mensaje claro y exit 0 (estado válido, no error).

**R11 — `schedule` sin bronze público.**
SI el bronze público no existe en la ruta esperada, ENTONCES `schedule` DEBE
imprimir en stderr un mensaje claro y accionable (ejecutar antes
`ingest-public`) y terminar con exit ≠ 0.

## Errores y entorno

**R12 — Traducción accionable de errores de capas inferiores.**
SI una capa inferior levanta `SilverInputError` (build-features),
`SilverNotFoundError` (train), `NotFittedError` (predict), `ValueError` de fecha
mal formada (build-features/train), `PublicSchemaError` o `PublicDownloadError`
(ingest-public), ENTONCES el sistema DEBE capturar la excepción e imprimir en
stderr un mensaje accionable que indique **qué comando del flujo ejecutar primero**
(`ingest-public → build-features → train → predict`), terminando con exit 1 y
sin traceback. Las excepciones NO listadas (bugs) NO DEBEN ocultarse.

**R13 — Offline por defecto, sin secretos y sin reloj predictivo.**
El sistema NO DEBE requerir `API_FOOTBALL_KEY` ni acceso de red para importar
`src.cli`, mostrar la ayuda, ni ejecutar los subcomandos offline
(`build-features`, `train`, `predict`, `schedule`). El único subcomando que toca
la red es `ingest-public` en ejecución real explícita (regla STOP de `CLAUDE.md`);
`as_of_date` es SIEMPRE un argumento explícito y ningún subcomando usa `now()`
en lógica predictiva (el único uso de reloj es el metadato `fetched_at` de la
descarga real, ver `design.md`).
