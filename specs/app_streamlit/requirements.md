# requirements.md — Feature 9: app_streamlit

Objetivo: una **app Streamlit local** (una página, pestañas `📅 Calendario`,
`🏆 Selecciones`, `📈 Modelo`) que **reemplaza** al dashboard HTML estático
(feature 8) como interfaz del proyecto. Solo **visualiza**: consume en lectura el
bronze público (feature 7), el gold (feature 2) y los parámetros Dixon-Coles +
`load_params`/`predict_match` (feature 3). El pipeline (ingest/build/train) sigue
operándose por CLI. Decisiones de producto validadas con el usuario (2026-06-09):
calendario híbrido (tira de días + tarjetas), detalle de partido con pestañas,
partidos jugados con resultado real + predicción comparada, paquete nuevo `src/app/`.
El retiro de `src/report/` es un **no-objetivo** (paso posterior aparte).

Notación EARS. Cada `R<n>` es verificable y mapea a ≥1 test en
`tests/test_app_data.py`, `tests/test_app_figures.py` o `tests/test_app_ui.py`
(ver `tasks.md`).

---

**R1 — Insumos parametrizables con defaults.**
El sistema DEBE leer sus insumos desde rutas parametrizables con estos defaults:
`data/gold/team_features.csv`, `data/gold/elo_history.csv`,
`data/gold/dixon_coles_params.json` y `data/bronze/public_results/results.csv`;
y los nombres/códigos de las 48 selecciones desde `src/ingestion/teams.py`
(solo lectura). CUANDO se inyecten rutas alternativas (p. ej. `tmp_path` en tests),
el sistema DEBE construir todo su estado exclusivamente a partir de ellas.

**R2 — Errores claros y accionables ante insumos críticos ausentes.**
SI falta `team_features.csv`, `elo_history.csv` o el JSON de parámetros no existe /
no cumple el contrato (`NotFittedError` de `load_params`), ENTONCES la capa de datos
DEBE fallar con `AppInputError` cuyo mensaje incluye la ruta ausente y el comando del
pipeline a ejecutar primero (`build-features` o `train`, con su invocación
`python -m ...`), y la app DEBE mostrar ese mensaje como error visible (sin
traceback) sin renderizar las pestañas de contenido.

**R3 — Degradación parcial sin bronze público.**
SI falta SOLO `results.csv`, ENTONCES la pestaña Calendario DEBE mostrar un aviso
visible que mencione `ingest-public` (sin partidos), y las pestañas Selecciones y
Modelo DEBEN seguir funcionando con normalidad. No es un fallo.

**R4 — Capa de datos pura, sin streamlit y sin efectos al importar.**
La carga y preparación de datos DEBE vivir en `src/app/data.py` como funciones puras
que NO importan `streamlit` ni módulos de red (`src.ingestion.client`, `config`,
`ingest`) y NO usan `API_FOOTBALL_KEY`. Importar cualquier módulo de `src/app/`
NO DEBE disparar lecturas de disco, red, escritura ni apertura de navegador.

**R5 — Calendario: partidos WC2026, tira de días y estado sin reloj.**
*(Enmienda 2026-06-10: el dataset histórico contiene TODOS los Mundiales desde
1930; el calendario es solo de la edición 2026.)*
El sistema DEBE extraer del CSV bronze crudo los partidos con
`tournament == "FIFA World Cup"` **y `date >= WC2026_FROM_DATE`** (constante de
módulo `"2026-01-01"`; sin reloj — las ediciones pasadas quedan excluidas),
clasificarlos **sin reloj** como `jugado`
(ambos scores convertibles a `int`) o `pendiente` (criterio de `schedule`,
feature 6), y agruparlos por `date` ascendente. La pestaña Calendario DEBE mostrar
una tira de días seleccionable donde cada día muestra su fecha y su número de
partidos, y al seleccionar un día DEBE listar exactamente los partidos de ese día
como tarjetas, en orden `(date, home_team, away_team)`. El día seleccionado por
defecto DEBE ser el primero (orden cronológico) con ≥1 partido pendiente; si no hay
pendientes, el último día con partidos.

**R6 — Tarjeta de partido pendiente: 1X2 del modelo real.**
CUANDO un partido pendiente sea predecible, su tarjeta DEBE mostrar los nombres
canónicos y códigos FIFA de ambos equipos (vía `to_fifa_code` + `teams.py`) y las
tres probabilidades 1X2 de `predict_match` real sobre los parámetros cargados con
`load_params` (sin reentrenar), en porcentaje con 1 decimal.

**R7 — Tarjeta de partido jugado: resultado real + predicción comparada.**
CUANDO un partido esté jugado, su tarjeta DEBE mostrar el marcador real y la
comparación con el modelo: la probabilidad que los parámetros vigentes asignan al
desenlace 1X2 ocurrido y un indicador de acierto (✅ SI el desenlace real fue el más
probable del modelo, ❌ en caso contrario). La pestaña DEBE incluir un aviso visible
de que la comparación usa los parámetros vigentes (`as_of_date`) y no una predicción
congelada pre-partido (la evaluación walk-forward es de la feature 5).

**R8 — Detalle de partido con pestañas.**
CUANDO se seleccione una tarjeta, el sistema DEBE renderizar un detalle con tres
pestañas: **Predicción** (barras 1X2 + heatmap de la matriz de marcadores
`0..max_goals` con goles del local en filas + top-5 marcadores con desempate
determinista de `predict_match`), **Equipos** (comparativa de ambos: `elo`,
`attack`/`defense`, `gf_ma15`/`ga_ma15`) y **Historial Elo** (líneas `elo_post` por
`date` de ambos equipos desde `elo_history.csv`, orden cronológico). El detalle DEBE
permanecer asociado al partido seleccionado en `st.session_state` hasta seleccionar
otro.

**R9 — Partido no predecible: degradar sin abortar.**
SI un partido del calendario no puede predecirse (nombre sin alias FIFA según
`to_fifa_code`, o `UnknownTeamError`), ENTONCES su tarjeta DEBE mostrarse igualmente
(equipos y fecha) con un aviso de "sin predicción" en lugar de probabilidades, y el
resto del calendario DEBE continuar sin abortar.

**R10 — Selecciones: ranking Elo y ficha por equipo.**
La pestaña Selecciones DEBE mostrar (a) el ranking Elo de todas las selecciones de
`team_features.csv` en orden `(-elo, code)` con las anfitrionas (`HOST_CODES`)
destacadas como traza separada, y (b) un selector de equipo que al elegirlo muestra
su ficha: evolución Elo (`elo_post` cronológico), forma (`gf_ma15`/`ga_ma15`),
fuerzas `attack`/`defense` y sus partidos WC2026 (jugados y pendientes). SI el
equipo no tiene historial o forma (`matches_count = 0`), ENTONCES la ficha DEBE
indicarlo sin fallar.

**R11 — Modelo: metadatos y fuerzas.**
La pestaña Modelo DEBE mostrar los metadatos de los parámetros (`as_of_date`,
`from_date`, `n_matches`, `n_teams`, `xi` y convergencia `success`/`n_iter`), un
aviso visible DONDE `convergencia.success` sea falso, y la dispersión
`attack` (x) vs `defense` (y) etiquetada por código FIFA SOLO para las 48
selecciones (los slugs del recorte de entrenamiento NO DEBEN mostrarse).

**R12 — Sin reloj y determinismo.**
La única fecha de referencia mostrada DEBE ser `as_of_date` de los parámetros; el
estado jugado/pendiente es la marca del dataset (R5). El sistema NO DEBE usar
`datetime.now()`/`date.today()`/RNG en datos ni figuras: para una misma entrada, la
capa de datos y las figuras DEBEN producir el mismo contenido (mismos órdenes,
mismos textos, mismas probabilidades).

**R13 — Offline, solo lectura y aislamiento.**
La app NO DEBE realizar llamadas de red ni escribir archivos en ninguna interacción
(solo lectura de los insumos). El sistema DEBE implementarse en el paquete nuevo
`src/app/` sin modificar ningún módulo existente (`src/report/` queda intacto y
congelado).

**R14 — Entrada única y estructura de pestañas.**
El sistema DEBE exponerse como `streamlit run src/app/main.py` y renderizar el
título de la app y exactamente tres pestañas de nivel superior con literales
constantes del módulo: `📅 Calendario`, `🏆 Selecciones`, `📈 Modelo` (verificable
con `st.testing.AppTest`).

**R15 — Configuración local segura.**
El repo DEBE incluir `.streamlit/config.toml` con la telemetría desactivada
(`browser.gatherUsageStats = false`) y el servidor limitado a localhost
(`server.address = "localhost"`), más cualquier condición que imponga el dictamen
de seguridad de la dependencia. La app NO DEBE requerir secretos: `secrets.toml`
no se usa y `API_FOOTBALL_KEY` no se lee.
