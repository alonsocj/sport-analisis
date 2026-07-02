# design.md — Feature 9: app_streamlit

## Arquitectura

Paquete nuevo `src/app/`. Los módulos de otras features se usan **solo en
lectura/llamada** y NO se modifican; `src/report/` queda congelado (su retiro es un
paso posterior con aprobación explícita del usuario). Dependencia nueva:
**streamlit** (pin según dictamen de seguridad; instalación aprobada por el usuario
tras auditoría). Todo offline: sin red, sin `API_FOOTBALL_KEY`, sin escritura.

| Módulo                      | Responsabilidad                                                                    | Requisitos |
|-----------------------------|-------------------------------------------------------------------------------------|------------|
| `src/app/__init__.py`       | Marca de paquete (docstring, **sin imports**).                                      | R4, R13 |
| `src/app/data.py`           | Capa de datos PURA: carga/validación de insumos, partidos WC2026, predicciones, fichas. Sin `streamlit`. | R1–R7, R9–R12 |
| `src/app/figures.py`        | Constructores plotly PUROS (`go.Figure`): 1X2, heatmap, comparativa, líneas Elo, ranking, dispersión. Sin `streamlit`. | R8, R10, R11, R12 |
| `src/app/main.py`           | Entrada `streamlit run`: cachés, título, `st.tabs` nivel app, manejo de `AppInputError`. | R2, R14 |
| `src/app/tabs/calendario.py`| UI pestaña Calendario: tira de días, tarjetas, detalle con sub-pestañas.            | R3, R5–R9 |
| `src/app/tabs/selecciones.py`| UI pestaña Selecciones: ranking + ficha de equipo.                                 | R10 |
| `src/app/tabs/modelo.py`    | UI pestaña Modelo: metadatos + dispersión de fuerzas.                               | R11 |
| `.streamlit/config.toml`    | Telemetría off, servidor localhost (+ condiciones del dictamen).                    | R15 |

Contratos consumidos (idénticos a los de la feature 8, ver su `design.md`):
`load_params`, `predict_match`, `NotFittedError`, `UnknownTeamError`
(`src/models/dixon_coles.py`); `to_fifa_code` (`src/ingestion/public_data.py`);
`all_teams`, `HOST_CODES`, `is_host` (`src/ingestion/teams.py`); CSVs gold/bronze
con `csv.DictReader` (stdlib, nulls explícitos — mismo razonamiento que feature 8).

Flujo:

```
gold (features, elo_history) ─┐
params (load_params) ─────────┤→ data.load_app_data(paths) ──► AppData (frozen)
bronze results.csv (opcional)─┘        │ (validación R2; degradación R3)
                                       ├─ AppData.days / .matches  ──► tabs/calendario
                                       ├─ AppData.features / .history ──► tabs/selecciones
                                       └─ AppData.params ──► tabs/modelo
predicciones: data.predict_for(match) → predict_match (cacheada por (home,away))
figuras: figures.fig_*(datos) → go.Figure → st.plotly_chart
```

## Modelo de datos (data.py)

- `@dataclass(frozen=True) WcMatch`: `date, home_name, away_name, home_code,
  away_code, home_score, away_score, played: bool, predecible: bool`.
  `home_code/away_code = None` si `to_fifa_code` no resuelve → `predecible=False`.
- `@dataclass(frozen=True) AppData`: `features_rows, history_rows, params,
  matches: tuple[WcMatch, ...], bronze_disponible: bool`.
- `load_app_data(features_csv, elo_history_csv, params_path, results_csv) -> AppData`
  — validación R2 (orden gold → params → bronze; bronze único opcional, R3).
- `pending_default_day(matches) -> str | None` — primer `date` con pendiente; si no
  hay, último `date` con partidos (R5). Pura, sin reloj.
- `match_outcome_eval(match, pred) -> OutcomeEval` — para jugados: desenlace real
  (`1`/`X`/`2`), probabilidad asignada, `acierto = (desenlace real == argmax 1X2)`
  con desempate determinista por orden `(1, X, 2)` (R7).
- `team_profile(code, app_data) -> TeamProfile` — ficha R10 (Elo actual, forma,
  fuerzas, historial, partidos del equipo).
- `class AppInputError(Exception)` — mensajes accionables con el comando previo del
  pipeline (mismo patrón que features 6 y 8).

## Decisiones de UI (Streamlit)

- **Pestañas nivel app**: `st.tabs([TAB_CALENDARIO, TAB_SELECCIONES, TAB_MODELO])`
  con literales constantes en `main.py` (R14). Streamlit renderiza las tres pestañas
  en cada rerun (sin lazy): aceptable, los datos están cacheados.
- **Anidamiento controlado**: el detalle de partido usa `st.tabs` de segundo nivel
  DENTRO de `st.container(border=True)` con cabecera `<h3>` propia — separación
  visual del nivel app (decisión del usuario: pestañas en detalle, pestañas arriba).
- **Tira de días**: `st.pills` (una opción por fecha, etiqueta `"11 jun (3)"`,
  `selection_mode="single"`, default = `pending_default_day`). Mapeo etiqueta→date
  determinista. Día sin selección (usuario deselecciona) → se re-aplica el default.
- **Tarjetas**: por partido, `st.container(border=True)` con `st.columns`:
  equipos/fecha, 1X2 (pendiente, R6) o marcador+✅/❌ (jugado, R7), y `st.button`
  "Ver análisis" (`key=f"sel-{date}-{home}-{away}"`) que fija
  `st.session_state["selected_match"]` (R8). No predecible → caption "sin
  predicción" (R9).
- **Cachés**: en `main.py`, wrappers `@st.cache_data` sobre `data.load_app_data`
  (TTL ∞, invalidación manual con el botón nativo "Rerun"; clave = rutas) y sobre la
  predicción por `(home_code, away_code)`. `data.py` queda libre de streamlit (R4) y
  las funciones cacheadas son envolturas finas.
- **Figuras**: `st.plotly_chart(fig, width="stretch")`; los builders viven
  en `figures.py` y devuelven `go.Figure` puros (deterministas, R12). Mismas
  convenciones visuales que la feature 8 (heatmap con goles del local en filas,
  porcentajes `.1f`, orden `(-elo, code)`, anfitrionas como traza separada).
  — *Enmienda 2026-06-10*: `use_container_width=True` deprecado en streamlit 1.58
  (retiro post-2025-12-31). Reemplazado por `width="stretch"` (parámetro oficial
  equivalente según `help(st.plotly_chart)`). Aplicado en todos los usos de
  `src/app/tabs/`.
- **Disclaimer R7**: `st.info` fijo en la pestaña Calendario con `as_of_date` de los
  params (única fecha mostrada, R12).

## Manejo de errores

| Situación                                   | Comportamiento                                                       | Requisito |
|---------------------------------------------|----------------------------------------------------------------------|-----------|
| Falta gold (features/history)               | `AppInputError` con ruta + `build-features`; `main` lo captura y `st.error` (sin pestañas de contenido). | R2 |
| Params ausentes/inválidos (`NotFittedError`) | `AppInputError` con `train`; ídem.                                  | R2 |
| Falta SOLO bronze                            | `AppData.bronze_disponible=False`; Calendario muestra aviso `ingest-public`; resto de pestañas normales. | R3 |
| Partido sin alias / `UnknownTeamError`       | `WcMatch.predecible=False`; tarjeta sin predicción, lote continúa.   | R9 |
| Fila bronze malformada                       | Ignorada de forma defensiva (espíritu features 6/7/8).               | R5 |
| Excepción no listada (bug)                   | NO se captura: se propaga.                                           | — |

## Testing (R<n> → test, ver tasks.md)

- `tests/test_app_data.py` — `data.py` puro con fixtures `tmp_path` (mismo estilo
  que `test_dashboard.py`): validación R2/R3, clasificación R5, evaluación R7,
  no-predecible R9, determinismo R12, pureza de imports R4.
- `tests/test_app_figures.py` — builders devuelven `go.Figure` con trazas/órdenes
  del contrato (R8, R10, R11): nombres de traza, `categoryarray`, etiquetas.
- `tests/test_app_ui.py` — `st.testing.AppTest.from_file("src/app/main.py")` con
  rutas inyectadas vía monkeypatch de los defaults de `data.py`: pestañas R14,
  error visible R2, aviso R3, tarjetas y detalle R5–R9 (smoke por contenido),
  config.toml R15 (parse del TOML del repo).
- Sin navegador real, sin red; `AppTest` corre headless.

## Decisiones y justificación

- **`data.py`/`figures.py` sin streamlit** → testeo unitario directo (90% de los
  R<n> se valida sin `AppTest`, que es más lento y de grano grueso); además protege
  contra acoplar lógica a la UI.
- **`st.pills` para la tira de días** → es el widget nativo más cercano al mockup
  aprobado (chips horizontales con recuento); evita componentes de terceros
  (regla: sin dependencias innecesarias).
- **Predicción de jugados con params vigentes + disclaimer** → honestidad sin
  bloquear: la predicción congelada pre-partido exige reentrenos versionados
  (feature 5, backtesting walk-forward). Decisión validada con el usuario.
- **`st.session_state` para el partido seleccionado** → patrón estándar Streamlit;
  el detalle sobrevive a los reruns y a cambios de pestaña.
- **Caché por rutas sin TTL** → los insumos cambian solo cuando el usuario corre el
  pipeline por CLI; el refresh es el rerun manual de Streamlit (alcance v1 "solo
  visualiza", decisión del usuario).
- **`csv.DictReader` (no pandas) en data.py** → mismo razonamiento que feature 8:
  nulls explícitos, cero inferencia, volúmenes pequeños.
- **`src/report/` intacto** → reemplazo sin riesgo: los 137 tests existentes no se
  tocan; el retiro (borrar archivos) requiere aprobación explícita (regla STOP).

## No-objetivos (explícitos)

- Retirar/borrar `src/report/` o sus tests (paso posterior aparte, con aprobación).
- Operar el pipeline desde la UI (ingest/build/train) — alcance v1 es solo lectura.
- Mercados over/under, córners, tarjetas (feature 4) y métricas/backtesting
  (feature 5): la UI solo les reserva sitio (pestaña futura en detalle; página
  futura Modelo/Backtest).
- Deploy remoto, autenticación, `secrets.toml`, multipágina `pages/`.
- Subcomando `python -m src.cli app` (extensión futura; el CLI no se toca).
