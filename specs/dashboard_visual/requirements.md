# requirements.md — Feature 8: dashboard_visual

Objetivo: generar, por comando explícito, un **dashboard HTML interactivo y
autocontenido** (plotly, sin servidor y sin red) que visualice el estado del modelo
del Mundial 2026: metadatos del entrenamiento, ranking y evolución Elo, fuerzas
ataque/defensa Dixon-Coles, forma reciente y predicciones (heatmap de marcadores +
1X2) de los próximos partidos WC2026. Consume en **solo lectura** las salidas de las
features 7 (bronze público), 2 (gold) y 3 (parámetros + `load_params`/`predict_match`).
NO modifica `src/cli.py` ni ningún módulo existente.

Notación EARS. Cada `R<n>` es verificable y mapea a ≥1 test en
`tests/test_dashboard.py` (ver `tasks.md`).

---

**R1 — Insumos parametrizables con defaults.**
El sistema DEBE leer sus insumos desde rutas parametrizables con estos defaults:
`data/gold/team_features.csv`, `data/gold/elo_history.csv`,
`data/gold/dixon_coles_params.json` y `data/bronze/public_results/results.csv`;
y los nombres/códigos de las 48 selecciones desde `src/ingestion/teams.py`
(solo lectura). CUANDO se inyecten rutas alternativas (p. ej. `tmp_path` en tests),
el sistema DEBE generar el dashboard exclusivamente a partir de ellas.

**R2 — Errores claros y accionables ante insumos críticos ausentes.**
SI falta `team_features.csv` o `elo_history.csv`, ENTONCES el sistema DEBE fallar con
`DashboardInputError` cuyo mensaje incluye la ruta ausente y el comando a ejecutar
primero (`build-features`, `python -m src.features.build --as-of-date YYYY-MM-DD`).
SI el JSON de parámetros no existe o no cumple el contrato de la feature 3
(`NotFittedError` de `load_params`), ENTONCES el sistema DEBE fallar con
`DashboardInputError` que indica ejecutar primero `train`
(`python -m src.models.dixon_coles --as-of-date YYYY-MM-DD`).
En ambos casos NO se escribe ningún HTML.

**R3 — Degradación parcial sin bronze público.**
SI falta SOLO el CSV bronze público (`results.csv`) y el resto de insumos está
disponible, ENTONCES el sistema DEBE generar el dashboard completo SIN la sección de
próximos partidos, incluir en el HTML un aviso visible que mencione el comando
`ingest-public`, y terminar con éxito (no es un fallo).

**R4 — Un único HTML autocontenido, cero red.**
El sistema DEBE escribir UN único archivo HTML en la ruta de salida (default
`data/reports/dashboard.html`, creando los directorios intermedios si no existen) con
plotly.js **embebido exactamente una vez** y sin ninguna referencia de red (sin CDN ni
`<script src>` externo). El archivo DEBE poder abrirse en un navegador sin servidor, y
la generación NO DEBE realizar ninguna llamada de red.

**R5 — Cabecera con metadatos del modelo (sin reloj).**
El sistema DEBE incluir una cabecera con los metadatos leídos del JSON de parámetros:
`as_of_date`, `n_matches`, `n_teams` y convergencia (`success`, `n_iter`). La fecha
mostrada DEBE ser el `as_of_date` de los parámetros y NUNCA la fecha actual (cero
`now()` en el contenido). DONDE `convergencia.success` sea falso, la cabecera DEBE
mostrar un aviso visible de no convergencia.

**R6 — Ranking Elo con anfitrionas destacadas.**
El sistema DEBE incluir una figura de barras horizontales con el Elo vigente de todas
las selecciones presentes en `team_features.csv` (las 48 en producción, contrato R20
de la feature 2), ordenadas descendentemente por `elo` (desempate `code` ascendente),
con las anfitrionas (MEX/USA/CAN) destacadas visualmente como traza separada
(`Anfitrionas` vs `Resto`).

**R7 — Evolución temporal del Elo con equipos seleccionables.**
El sistema DEBE incluir una figura de líneas con la evolución del Elo (`elo_post` por
`date` desde `elo_history.csv`, una traza por equipo, orden cronológico) para un
conjunto de equipos parametrizable; el default DEBE ser el top-10 por Elo vigente
de `team_features.csv` unión las anfitrionas presentes, con selección y orden
deterministas (orden `(-elo, code)`; sin duplicados). CUANDO se inyecte una lista
explícita de códigos, el sistema DEBE graficar exactamente esos equipos.

**R8 — Dispersión de fuerzas ataque vs defensa.**
El sistema DEBE incluir una figura de dispersión con `attack` (eje x) vs `defense`
(eje y) del JSON de parámetros para las selecciones de las 48 presentes en
`attack`/`defense`, cada punto etiquetado con su código FIFA. Los equipos fuera de
las 48 (códigos slug del recorte de entrenamiento) NO DEBEN mostrarse.

**R9 — Forma reciente gf_ma15 / ga_ma15.**
El sistema DEBE incluir una figura de barras agrupadas con `gf_ma15` y `ga_ma15` por
selección de `team_features.csv`, en orden `code` ascendente. SI una selección tiene
`gf_ma15`/`ga_ma15` nulos (`matches_count = 0`), ENTONCES DEBE excluirse de la figura
sin fallar.

**R10 — Próximos partidos WC2026: heatmap de marcadores + 1X2 del modelo real.**
El sistema DEBE detectar los próximos partidos del Mundial 2026 en el CSV bronze
crudo con el criterio **sin reloj** (el mismo de `schedule`, feature 6):
`tournament == "FIFA World Cup"` y `home_score` o `away_score` no convertible a
`int`; ordenarlos ascendentemente por `(date, home_team, away_team)` y tomar los
primeros `N` (default **12**, parametrizable). Por cada partido el sistema DEBE
incluir: (a) un heatmap de la matriz de marcadores obtenida con `predict_match`
**real** de la feature 3 sobre los parámetros cargados con `load_params` (sin
reentrenar), y (b) una figura de barras 1X2 con las tres probabilidades en porcentaje
(1 decimal). CUANDO el bronze exista pero no haya partidos pendientes, la sección
DEBE mostrar un mensaje de "sin partidos pendientes" sin fallar.

**R11 — Partido pendiente no predecible: omitir sin abortar.**
SI un partido pendiente no puede predecirse (nombre sin alias FIFA según
`to_fifa_code`, o código ausente de `attack`/`defense` → `UnknownTeamError`),
ENTONCES el sistema DEBE omitir SOLO ese partido, dejar un aviso visible en la
sección (con el partido afectado) y continuar con el resto sin abortar la generación.

**R12 — CLI explícito.**
El sistema DEBE exponer `python -m src.report.dashboard [--out RUTA] [--limit N]
[--open]`. CUANDO la generación termine con éxito, DEBE imprimir una línea con la
convención `✅` que incluya la ruta del HTML escrito y devolver exit code `0`
(incluida la degradación parcial de R3). SI falta un insumo crítico (R2), ENTONCES
DEBE imprimir `error: <mensaje accionable>` en stderr y devolver exit code `1`, sin
traceback. Los errores de uso de argparse devuelven exit code `2`. DONDE se pase
`--open`, el sistema DEBE abrir el HTML generado con `webbrowser` (stdlib) tras
escribirlo; sin `--open` NO DEBE abrir nada (default).

**R13 — Determinismo de contenido.**
El sistema DEBE producir, para una misma entrada, el mismo contenido verificable:
mismos títulos de sección, mismos códigos de equipo, mismo número de figuras y mismas
probabilidades renderizadas. No DEBE usar RNG propio ni lecturas de reloj en el
contenido, y los `div_id` de las figuras DEBEN ser estables y legibles. (Los IDs
aleatorios internos de plotly quedan fuera del contrato: los tests verifican
contenido, no bytes exactos.)

**R14 — Aislamiento: paquete nuevo, import sin efectos.**
El sistema DEBE implementarse en el paquete nuevo `src/report/` (`__init__.py` +
`dashboard.py`) sin modificar ningún módulo existente (en particular `src/cli.py`,
feature 6 en implementación paralela). Importar `src.report.dashboard` NO DEBE
importar `src.cli`, ni disparar generación, red, escritura de archivos o apertura de
navegador: todos los efectos ocurren solo al invocar `generate_dashboard(...)` /
`main(...)`.
