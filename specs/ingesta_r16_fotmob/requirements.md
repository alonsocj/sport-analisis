# requirements.md — Feature 27: ingesta_r16_fotmob (refresh KO desde fotmob)

Objetivo: **cerrar el hueco R32+R16 en el training set** y generar el bracket de octavos,
todo desde fotmob (que **complementa**, no reemplaza, el pipeline actual), sin romper
silver→gold. Es la base de datos de la v3 del modelo (F28 jugadores/XI, F29 modelo, F30 UI).

Contexto verificado (2026-07-04):
- El silver corta en **2026-06-27** (fin de fase de grupos); **R32 = 0 filas**. martj42
  (`bronze/public_results/results.csv`) llega tarde: su última fecha es 2026-06-27. Los
  knockouts NO están en el dataset de resultados.
- El JSON de `bronze/fotmob_stats/*.json` trae stats por equipo
  (`possession, xg, shots, shots_on_target, corners, cards`) **pero NO el marcador**. Hoy el
  marcador sólo proviene de martj42. Para que fotmob sea autoritativo en KO hay que capturar
  también los goles.
- `build_silver` **enriquece** filas de martj42 con stats fotmob (join por `(date, {codes})`);
  **no materializa** filas nuevas. Por eso un partido KO ausente de martj42 no produce fila.
- Bracket real (playoff fotmob, liga 77): R32 (16, todos FIN) → R16/octavos (8; `PAR 0-1 FRA`
  y `CAN 0-3 MAR` FIN) → cuartos (4) → semis → final. **18 partidos KO jugados** a inyectar.

Notación EARS. Cada `R<n>` mapea a ≥1 test en `tests/test_ingest_r16_fotmob.py` o
`tests/test_silver_ko_materializa.py`. Transporte HTTP INYECTABLE → cero red en tests.
Regla STOP: ejecutar con transporte real requiere aprobación (concedida esta sesión, per-tanda).

---

**R1 — Descubrimiento del bracket KO desde el playoff de fotmob.**
El sistema DEBE, vía transporte HTTP INYECTABLE, obtener del playoff de fotmob
(`/leagues/{id}/playoff/world-cup`) el árbol `props.pageProps.playoff.rounds` y devolver,
por partido KO, `(round_ordinal, home_name, away_name, home_goals, away_goals, match_id,
utc_time, finished, started)`. Rondas por ordinal: 1=R32, 2=R16, 3=QF, 4=SF, 5=Final.
SI una ronda no existe → se omite sin fallar.

**R2 — Extracción del marcador en el extractor de partido fotmob.**
El extractor de partido (`fotmob_stats`) DEBE capturar `home_goals`/`away_goals` del
`__NEXT_DATA__` del partido, además de las stats. El JSON persistido en
`bronze/fotmob_stats/<slug>.json` DEBE incluir las claves `home_goals`, `away_goals`
(o `null` si el partido no ha terminado). No-regresión: partidos ya persistidos sin esas
claves siguen leyéndose (goles = `null`).

**R3 — Persistencia de los KO jugados en bronze.**
El sistema DEBE persistir cada partido KO **finished** en `bronze/fotmob_stats/<slug>.json`
(marcador + stats, si las hay) + sidecar meta (`fetched_at` INYECTADO, `url`, `sha256`).
SI un KO no trae stats → se registra con marcador y stats `null` (degrada, no aborta).

**R4 — Materialización de filas KO en silver desde fotmob (mecanismo autoritativo).**
`build_silver` DEBE **materializar** una fila para todo partido de `bronze/fotmob_stats`
con marcador no nulo que **no** exista en martj42 (los KO), poblando
`home_goals/away_goals` + las columnas de stats, con `source="fotmob"`. Las filas de grupos
(que sí están en martj42) siguen **enriqueciéndose** igual que hoy — **no-regresión exacta**.

**R5 — Dedupe: un KO no duplica una fila existente.**
Un partido fotmob que YA tenga fila en el silver (mismo `(date, {home_code, away_code})`)
NUNCA DEBE materializar una segunda fila; enriquece la existente. La orientación
home/away se resuelve por conjunto de equipos (no por qué lado llame "home" cada fuente).

**R6 — Generación del bracket de octavos `data/knockouts/r16_fixtures.csv`.**
El sistema DEBE escribir `data/knockouts/r16_fixtures.csv` con el mismo esquema que
`r32_fixtures.csv` (`draw_order,date,stage,home_code,away_code,source`) para los 8 partidos
de R16, y `data/knockouts/r8_fixtures.csv` para los 4 de cuartos (para F30). Nombres → código
FIFA con el mapeo existente + alias. `stage="R16"` / `"QF"`. `source="fotmob_official"`.

**R7 — Rebuild gold reproducible incluye KO.**
`build_all` (offline, `as_of_date` inyectada) DEBE reconstruir gold
(`silver/matches.csv`, `gold/team_features.csv`, `gold/elo_history.csv`,
`gold/dixon_coles_params.json`) incluyendo las 18 filas KO, de forma determinista. El modelo
forma-xG DEBE poder entrenar con R32/R16 (Elo y medias móviles cubren los KO).

**R8 — Sin red en tests; STOP en ejecución real; sin libs nuevas.**
Los tests DEBEN correr con transporte inyectado + fixtures `__NEXT_DATA__` (cero red).
`fetched_at` SIEMPRE inyectado; escritura sólo bajo `data/`; `requests` ya está (sin libs
nuevas). Ejecutar con red real = paso explícito con aprobación (STOP).
