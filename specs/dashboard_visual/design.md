# design.md — Feature 8: dashboard_visual

## Arquitectura

Un **paquete nuevo**: `src/report/` (`__init__.py` + `dashboard.py`). Todos los
módulos de otras features se usan **solo en lectura/llamada** y NO se modifican; en
particular `src/cli.py` queda **intacto** (feature 6 en implementación paralela; la
integración como subcomando es un no-objetivo, ver al final). Todo es **offline**: no
hay red, no se usa `API_FOOTBALL_KEY` ni `Settings` de `config.py` (mismo
razonamiento que features 2, 3, 6 y 7). Única dependencia de visualización:
**plotly >= 5** (ya en `requirements.txt`, instalación aprobada por el usuario
2026-06-09). Sin kaleido/orca (no se exportan imágenes estáticas).

| Módulo                                  | Responsabilidad                                                                 | Requisitos |
|-----------------------------------------|---------------------------------------------------------------------------------|------------|
| `src/report/__init__.py`                | Marca de paquete (docstring). **Sin imports** → importar `src.report` no arrastra plotly. | R14 |
| `src/report/dashboard.py`               | Carga de insumos, validación accionable, construcción de figuras, ensamblado HTML autocontenido, CLI. | R1–R14 |
| `src/models/dixon_coles.py` (llamada)   | `load_params`, `predict_match`, `NotFittedError`, `UnknownTeamError`.            | R2, R10, R11 |
| `src/ingestion/public_data.py` (llamada)| `to_fifa_code` (alias nombre-dataset → código FIFA).                             | R10, R11   |
| `src/ingestion/teams.py` (lectura)      | `all_teams()` (códigos/nombres canónicos de las 48), `HOST_CODES`/`is_host`.     | R6, R7, R8 |

Flujo:

```
data/gold/team_features.csv ──────────┐
data/gold/elo_history.csv ────────────┤            (validación R2; figuras R6, R7, R9)
data/gold/dixon_coles_params.json ────┤→ generate_dashboard ──► data/reports/dashboard.html
data/bronze/public_results/results.csv┘   │  (cabecera R5; dispersión R8)        (único archivo, R4)
        (opcional: degradación R3)        │
                                          └─ pendientes WC2026 ──► predict_match ──► heatmap + 1X2 (R10)
```

## Entradas: contratos consumidos (R1)

Rutas como argumentos con defaults de módulo (constantes):

| Constante                 | Default                                  | Contrato de origen                       |
|---------------------------|------------------------------------------|------------------------------------------|
| `DEFAULT_FEATURES_CSV`    | `data/gold/team_features.csv`            | feature 2, R20: `code, as_of_date, matches_count, gf_ma15, ga_ma15, …, elo`; nulls = celda vacía. |
| `DEFAULT_ELO_HISTORY_CSV` | `data/gold/elo_history.csv`              | feature 2, R19: `date, code, opponent_code, elo_pre, elo_post, k, g, we, score`; orden cronológico. |
| `DEFAULT_PARAMS_PATH`     | `data/gold/dixon_coles_params.json`      | feature 3, R11: claves `as_of_date, n_matches, n_teams, mu, home_advantage, rho, attack, defense, convergencia, …`. Se carga SOLO vía `load_params` (validación del contrato delegada en la feature 3). |
| `DEFAULT_RESULTS_CSV`     | `data/bronze/public_results/results.csv` | feature 7, R4: CSV crudo con encabezado `date,home_team,away_team,home_score,away_score,tournament,city,country,neutral`. |
| `DEFAULT_OUT`             | `data/reports/dashboard.html`            | salida (en `data/`, cubierto por `.gitignore`). |
| `DEFAULT_MATCH_LIMIT`     | `12`                                     | contrato del Leader.                     |
| `DEFAULT_TOP_N_LINES`     | `10`                                     | top-N por Elo para la sección de líneas. |
| `WC_TOURNAMENT`           | `"FIFA World Cup"`                       | mismo literal que `schedule` (feature 6).|

Lectura de los CSVs con `csv.DictReader` (stdlib): control explícito de nulls (celda
vacía → `None`) y cero dependencia de inferencia de dtypes de pandas; coherente con
la capa fina del CLI (feature 6). Comparaciones de fecha por string ISO
(lexicográficas, válidas en `YYYY-MM-DD`).

## Salida y ensamblado HTML (R4, R13)

- Documento construido por plantilla propia mínima: `<!DOCTYPE html>` +
  `<meta charset="utf-8">` (nombres como `Curaçao`) + `<style>` inline corto +
  secciones `<section>` con `<h2>`. Textos dinámicos escapados con `html.escape`.
- Cada figura se serializa con `plotly.io.to_html(fig, full_html=False,
  include_plotlyjs=..., div_id=...)`:
  - **Primera figura**: `include_plotlyjs=True` → bundle plotly.js **inline**
    (es la forma `include_plotlyjs=True` del contrato del Leader aplicada a
    fragmentos; cero red al abrir).
  - **Figuras siguientes**: `include_plotlyjs=False` → el bundle aparece
    **exactamente una vez** en el documento (verificable: el literal `"plotly.js v"`
    del banner del bundle aparece 1 vez; `"Plotly.newPlot"` aparece una vez por
    figura).
  - `div_id` **estable y legible** por figura (elimina los uuid aleatorios de plotly
    y da anclas verificables, R13): `fig-ranking-elo`, `fig-evolucion-elo`,
    `fig-fuerzas`, `fig-forma`, `fig-partido-<i>-marcadores`, `fig-partido-<i>-1x2`
    (`i` = 1..N en orden cronológico).
- Recuento de figuras determinista: `4 + 2·n_partidos_renderizados` (R13).
- Escritura: `out_path.parent.mkdir(parents=True, exist_ok=True)` + texto UTF-8.
- Sin `<script src>` externo ni URLs de CDN; el HTML abre con `file://` sin servidor.

### Títulos de sección (constantes de módulo, testeables)

| Constante           | Texto exacto                                  | Sección |
|---------------------|-----------------------------------------------|---------|
| `TITULO_DASHBOARD`  | `Dashboard — Mundial 2026`                    | `<h1>`  |
| `SEC_METADATOS`     | `Metadatos del modelo`                        | (1) R5  |
| `SEC_RANKING`       | `Ranking Elo`                                 | (2) R6  |
| `SEC_EVOLUCION`     | `Evolución temporal del Elo`                  | (3) R7  |
| `SEC_FUERZAS`       | `Fuerzas ataque vs defensa`                   | (4) R8  |
| `SEC_FORMA`         | `Forma reciente (gf_ma15 / ga_ma15)`          | (5) R9  |
| `SEC_PARTIDOS`      | `Próximos partidos del Mundial 2026`          | (6) R10 |

Los tests asertan presencia/ausencia de estos literales y de los `div_id` (contenido,
no bytes, R13).

## Secciones

### (1) Cabecera de metadatos (R5)

Tabla/lista HTML (no figura plotly) con valores de `DixonColesParams` cargados:
`as_of_date`, `from_date`, `n_matches`, `n_teams`, `xi`, y convergencia
(`success`, `n_iter`). **Nunca** `datetime.now()`/`date.today()`: la única fecha
mostrada es `as_of_date` de los params (mismo principio que `predict` de la feature
6). DONDE `convergencia["success"]` sea falso → bloque de aviso visible
(`⚠️ el optimizador no convergió`).

### (2) Ranking Elo (R6)

- Datos: filas de `team_features.csv` (todas; 48 en producción, contrato R20), campo
  `elo` (float, nunca nulo: default `initial`).
- Orden total determinista: `(-elo, code)`; en barras horizontales el orden visual se
  fija con `categoryorder="array"` + `categoryarray` explícito (evita ambigüedad
  entre trazas).
- **Dos trazas** con nombres fijos: `Anfitrionas` (códigos en `HOST_CODES`, color
  destacado) y `Resto`. Los nombres de traza quedan en el JSON embebido del HTML →
  aserción directa en tests.

### (3) Evolución temporal del Elo (R7)

- Selección default = helper **público y puro**
  `select_line_teams(features_rows, top_n=DEFAULT_TOP_N_LINES) -> list[str]`:
  top-`n` por `(-elo, code)` ∪ anfitrionas presentes en el CSV, sin duplicados,
  resultado en orden `(-elo, code)` (determinista, testeable en aislamiento).
- Parametrizable: argumento `line_teams: list[str] | None` de `generate_dashboard`
  (`None` → default). La parametrización es por API Python; el CLI no expone flag
  (contrato del Leader: solo `--out/--limit/--open`).
- Datos: `elo_history.csv` filtrado por `code ∈ selección`; una traza por código
  (nombre de traza = código), `x = date` (ISO), `y = elo_post`, orden `(date, code)`
  ascendente. Código sin filas en el historial → traza omitida sin fallar.

### (4) Dispersión ataque vs defensa (R8)

- Datos: dicts `attack`/`defense` de los params. Filtro: SOLO códigos en
  `{t.code for t in all_teams()}` (los slugs del recorte de entrenamiento se
  excluyen; son ruido visual y no son selecciones del torneo).
- `x = attack`, `y = defense`, modo `markers+text`, etiqueta de texto = código FIFA,
  orden de puntos `code` ascendente (determinismo). Convención de signos en los
  títulos de eje: mayor `attack` → más gol; mayor `defense` → mejor defensa
  (contrato feature 3, R4).

### (5) Forma reciente (R9)

- Datos: `team_features.csv`, columnas `gf_ma15`/`ga_ma15`; celda vacía → `None`.
- Filas con `gf_ma15` o `ga_ma15` nulos (`matches_count = 0`) se **excluyen** de la
  figura sin fallar (no hay forma que mostrar; el ranking Elo ya lista al equipo).
- Barras **agrupadas** (`barmode="group"`): dos trazas fijas `gf_ma15` y `ga_ma15`,
  eje x = códigos en orden ascendente.

### (6) Próximos partidos WC2026 (R10, R11)

Criterio de pendiente **sin reloj** (idéntico al de `schedule`, feature 6 — se
duplica el helper trivial `_is_int` en lugar de importarlo de `src.cli`, ver
Decisiones):

```
pendiente(fila) := fila["tournament"] == WC_TOURNAMENT
                   y (home_score no convertible a int o away_score no convertible a int)
```

- Lectura del **CSV crudo** bronze con `csv.DictReader` (NO la vista de consumo de la
  feature 7: `parse_results` descarta los pendientes por `goles_no_numericos`).
  Filas malformadas/incompletas se ignoran de forma defensiva (mismo espíritu
  tolerante de las features 6 y 7).
- Orden ascendente `(date, home_team, away_team)`; se toman los primeros
  `limit` (default `DEFAULT_MATCH_LIMIT = 12`, parametrizable por argumento y por
  `--limit`).
- Por partido:
  1. `home_code = to_fifa_code(home_team)`, `away_code = to_fifa_code(away_team)`.
  2. `pred = predict_match(params, home_code, away_code)` — params cargados **una
     sola vez** con `load_params` al inicio; **nunca** se llama a `fit_dixon_coles`
     (sin reentrenar). La localía la resuelve `predict_match` internamente
     (`is_host`, feature 3 R13).
  3. Encabezado `<h3>` del partido: `"<nombre canónico> (<CODE>) vs <nombre canónico>
     (<CODE>) — <date>"` (nombre canónico de `teams.py`).
  4. **Heatmap** (`go.Heatmap`): `z = pred.matrix` con la orientación del contrato
     de la feature 3 (`matrix[x][y]`, filas = goles del **local**): eje y = goles del
     local, eje x = goles del visitante, `0..max_goals` (default 10 de
     `predict_match`; fijo en v1, YAGNI); hover con la probabilidad de cada marcador.
  5. **Barras 1X2** (`go.Bar`): categorías `1 — <HOME>`, `X`, `2 — <AWAY>` con
     `prob_home/prob_draw/prob_away`; texto sobre barra `f"{100*p:.1f}%"` (misma
     convención de formato que el `predict` de la feature 6) → los porcentajes quedan
     literales en el HTML (aserción de tests).
- **Robustez por partido (R11)**: SI `to_fifa_code` devuelve `None` para algún lado,
  o `predict_match` levanta `UnknownTeamError` → el partido se **omite**, se acumula
  en `skipped` (lista de descripciones) y se renderiza un aviso visible en la sección
  con los partidos omitidos. El resto continúa. Ninguna otra excepción se captura
  (un bug se propaga, mismo principio que la feature 6).
- Bronze presente y 0 pendientes → la sección muestra el literal
  `Sin partidos pendientes` (constante `MSG_SIN_PENDIENTES`), 0 figuras de partido.

### Degradación parcial (R3)

SI `results_csv` no existe → no hay sección de figuras de partidos; en su lugar se
renderiza el bloque de aviso (constante `AVISO_SIN_BRONZE`, contiene el literal
`ingest-public`: *"falta el bronze público; ejecuta primero `python -m src.cli
ingest-public` (o `python -m src.ingestion.public_data`)"*). La generación termina
con éxito; `DashboardResult.bronze_disponible = False`.

## Manejo de errores (R2, R3, R11)

Orden de validación: gold → params → bronze (el bronze es el único opcional).

| Situación                                        | Comportamiento                                                                 | Requisito |
|--------------------------------------------------|--------------------------------------------------------------------------------|-----------|
| Falta `team_features.csv` o `elo_history.csv`    | `DashboardInputError` con la ruta y "ejecuta primero build-features (`python -m src.features.build --as-of-date YYYY-MM-DD`)"; no se escribe HTML. | R2 |
| Params inexistentes / sin claves del contrato    | `NotFittedError` de `load_params` capturada y traducida a `DashboardInputError` con "ejecuta primero train (`python -m src.models.dixon_coles --as-of-date YYYY-MM-DD`)"; no se escribe HTML. | R2 |
| Falta SOLO `results.csv`                         | Degradación parcial: HTML sin sección 6 + `AVISO_SIN_BRONZE` (menciona `ingest-public`); éxito. | R3 |
| Pendiente sin alias FIFA / `UnknownTeamError`    | Partido omitido + aviso visible en la sección; el lote continúa.               | R11 |
| Fila bronze malformada                           | Ignorada de forma defensiva; el lote continúa.                                 | R10 (robustez) |
| Excepción no listada (bug)                       | NO se captura: se propaga con traceback.                                       | — |

En el CLI, `DashboardInputError` → `error: <mensaje>` en stderr + exit `1` (sin
traceback); argparse → exit `2` (convención de la feature 6).

## CLI (R12)

`python -m src.report.dashboard [--out RUTA] [--limit N] [--open]`

| Flag      | Default                       | Notas                                            |
|-----------|-------------------------------|--------------------------------------------------|
| `--out`   | `data/reports/dashboard.html` | ruta del HTML de salida.                         |
| `--limit` | `12`                          | `type=int`; nº máximo de próximos partidos.      |
| `--open`  | off (`store_true`)            | abre el HTML con `webbrowser.open(uri)` (stdlib) SOLO tras generar con éxito; default NO abrir. |

- `main(argv: list[str] | None = None) -> int` + `build_parser()`;
  `if __name__ == "__main__": raise SystemExit(main())` (patrón de las features 3 y 6).
- Éxito (incluida degradación R3): imprime `✅ dashboard generado: <ruta>` (y, si
  aplica, una línea informativa de la degradación/omisiones) y `return 0`.
- El comando es **offline** (no aplica la regla STOP de llamadas reales). `--open` en
  tests se verifica con `monkeypatch` de `webbrowser.open` (cero navegador real).

## Configuración y determinismo (R13, R14)

- Sin variables de entorno nuevas y **sin** `API_FOOTBALL_KEY` (no se importa
  `src.ingestion.config`, `client` ni `ingest`). Importar `src.report.dashboard` no
  dispara red ni efectos: solo definiciones (plotly, stdlib y los imports en lectura
  de features 3/7; `public_data` importa `requests` de forma perezosa).
- **Cero reloj y cero RNG** en todo el módulo: la fecha visible es `as_of_date` de
  los params (R5) y el criterio de pendiente es la marca del dataset (R10). No hay
  `datetime.now()`/`date.today()`/`random` (el reviewer lo verifica por inspección;
  el test de determinismo lo cubre de forma indirecta).
- Misma entrada → mismo contenido: ordenaciones totales definidas en cada sección,
  `div_id` estables, títulos constantes, formato de números fijo (`.1f` en %, Elo con
  1 decimal). Los uuid internos que plotly genera al no fijar `div_id` quedan
  eliminados por diseño; aun así el contrato de tests es **contenido, no bytes**.

## Firmas orientativas (sin código de app)

- `@dataclass(frozen=True) DashboardResult`: `out_path: Path, n_figures: int,
  n_matches_rendered: int, skipped: tuple[str, ...], bronze_disponible: bool`.
- `generate_dashboard(out_path=DEFAULT_OUT, features_csv=DEFAULT_FEATURES_CSV,
  elo_history_csv=DEFAULT_ELO_HISTORY_CSV, params_path=DEFAULT_PARAMS_PATH,
  results_csv=DEFAULT_RESULTS_CSV, limit=DEFAULT_MATCH_LIMIT, line_teams=None)
  -> DashboardResult` — orquestador (R1–R11, R13).
- `select_line_teams(features_rows, top_n=DEFAULT_TOP_N_LINES) -> list[str]` —
  pura, pública (R7).
- Helpers privados: `_load_team_features(path) -> list[dict]`,
  `_load_elo_history(path) -> list[dict]` (validación R2),
  `_pending_world_cup_rows(results_csv, limit) -> list[dict]`, `_is_int(value) -> bool`
  (R10), constructores de figuras `_fig_ranking_elo`, `_fig_evolucion_elo`,
  `_fig_fuerzas`, `_fig_forma`, `_fig_heatmap_partido`, `_fig_1x2_partido`
  (cada uno devuelve `go.Figure`), `_render_html(partes) -> str` (R4).
- `build_parser() -> argparse.ArgumentParser`, `main(argv=None) -> int` — R12.
- Excepción: `class DashboardInputError(Exception)` — R2.

## Decisiones y justificación

- **Paquete nuevo `src/report/` y `src/cli.py` intacto** → contrato del Leader: la
  feature 6 está en implementación paralela; tocarla crearía conflicto y violaría
  "una feature a la vez" en el código. La integración como subcomando se difiere
  (no-objetivo).
- **`__init__.py` sin imports** → importar `src.report` no carga plotly ni módulos de
  otras features; el punto de entrada único es `src.report.dashboard` (R14).
- **Duplicar el helper trivial `_is_int`/criterio de pendiente en lugar de importarlo
  de `src.cli`** → R14 prohíbe la dependencia (feature 6 inacabada y privados no son
  contrato). El criterio es de 3 líneas y está fijado por el contrato del Leader
  ("mismo criterio sin reloj que el CLI"); el coste de duplicación es mínimo frente a
  acoplarse a un módulo en cambio.
- **plotly.js inline en la primera figura + `include_plotlyjs=False` en el resto** →
  un solo bundle embebido (≈3–4 MB), cero red al abrir y al generar (R4); un único
  archivo es trivial de compartir. El peso es aceptable para un informe local y no
  hay alternativa sin CDN.
- **`div_id` estables y legibles** → elimina la única fuente de aleatoriedad de
  `to_html` (uuid por figura), da anclas verificables en tests y hace el HTML
  diffable (R13).
- **`csv` de stdlib (no pandas) para leer gold/bronze** → nulls explícitos (celda
  vacía), cero inferencia de dtypes, coherente con la capa de orquestación fina de la
  feature 6; los volúmenes (48 filas, ~100k filas de historial) no justifican pandas.
- **`load_params` + `predict_match` reales (nunca `fit_dixon_coles`)** → el dashboard
  es una vista del modelo entrenado, no un entrenador; mismas probabilidades que el
  CLI `predict` (una sola fuente de verdad, feature 3).
- **Slugs excluidos de la dispersión (R8)** → el dashboard es del Mundial 2026: los
  ~cientos de equipos del recorte de entrenamiento saturarían la figura sin aportar;
  `attack`/`defense` completos siguen disponibles en el JSON gold.
- **Equipos sin forma (`matches_count=0`) excluidos de la sección 5** → no hay dato
  que graficar; mostrarlos como 0 mentiría (0 goles ≠ sin datos). El ranking Elo
  (sección 2) garantiza que toda selección aparece en el dashboard.
- **Validación gold/params dura y bronze blando (R2 vs R3)** → sin gold/params no hay
  NADA que mostrar (5 de 6 secciones dependen de ellos) → error accionable; sin
  bronze solo se pierde la sección 6 → degradación parcial con aviso, más útil que
  fallar (contrato del Leader).
- **Mensajes de error con el comando previo del pipeline** → mismo patrón accionable
  de la feature 6 (`ingest-public → build-features → train`); los tests asertan el
  literal del comando en el mensaje.
- **`--limit 12` default** → contrato del Leader (≈ una ronda completa de fase de
  grupos por día-bloque; el calendario completo se obtiene subiendo `--limit`).
- **Selección de líneas por API y no por flag CLI** → contrato del Leader fija el CLI
  en `--out/--limit/--open`; `line_teams` queda en `generate_dashboard` (YAGNI: un
  flag de lista se añadiría como extensión futura sin romper nada).
- **`webbrowser` (stdlib) solo bajo `--open`** → cero dependencias nuevas, default
  no intrusivo, monkeypatcheable en tests (R12).
- **Cero reloj** → mismo principio que features 2, 3 y 6: `as_of_date` viene de los
  params y "pendiente" es una marca del dataset; reproducibilidad total (R5, R10, R13).

## No-objetivos (explícitos)

- **Integración como subcomando de `src.cli`** (`python -m src.cli dashboard`):
  extensión futura tras cerrar la feature 6; documentada aquí para que el reviewer no
  la exija ni el implementer la añada.
- Servidor web / app Dash / auto-refresh: el contrato es un HTML estático.
- Exportación de imágenes estáticas (kaleido/orca): dependencias no aprobadas.
- Mercados de la feature 4 (over/under, córners, tarjetas): no existen aún.
- Flags CLI adicionales (`--params`, `--features`, `--line-teams`, …): las rutas son
  parametrizables por API Python; el CLI queda fijado por el contrato del Leader.
