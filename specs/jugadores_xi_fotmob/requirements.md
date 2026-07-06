# requirements.md — Feature 28: jugadores_xi_fotmob (alineaciones + ratings)

Objetivo: capturar las **alineaciones** (XI confirmado en partidos jugados, **predicho** en
los por jugar) con **ratings por jugador** desde fotmob `content.lineup`, y derivar una
**fuerza de alineación** por (partido, equipo) que el modelo v3 (F29) pueda consumir.
Complementa F21 (roster = nombres) y F11 (player_factor histórico) con señal de calidad
del XI real. Depende de F27 (bracket/slugs de partido).

Contexto verificado (2026-07-04): `content.lineup.{homeTeam,awayTeam}` trae `starters[]` y
banca con `name`, `positionId`, `usualPlayingPositionId`, `performance.rating` (del partido,
null pre-partido) y `performance.seasonRating` (histórico, disponible pre-partido). `lineupType`
distingue confirmado/predicho. Los 6 octavos por jugar exponen XI predicho.

Notación EARS. Cada `R<n>` mapea a ≥1 test en `tests/test_fotmob_lineup.py` o
`tests/test_lineup_strength.py`. Transporte INYECTABLE → cero red en tests. STOP: red real
requiere aprobación (concedida, per-tanda).

---

**R1 — Extracción de alineación por partido desde fotmob.**
El sistema DEBE, vía transporte INYECTABLE, parsear `content.lineup` de una página de partido
y devolver por equipo la lista de jugadores `(name, position_id, is_starter, match_rating,
season_rating)` + `lineup_type` (confirmed/predicted) + código FIFA del equipo. SI no hay
lineup → registro vacío (no aborta).

**R2 — Persistencia bronze.**
El sistema DEBE persistir cada alineación en `bronze/lineups/<slug>.json` + sidecar meta
(`fetched_at` INYECTADO, `url`, `sha256`, `lineup_type`). Escritura sólo bajo `data/`.

**R3 — Fuerza de alineación por (partido, equipo).**
El sistema DEBE derivar, desde el bronze de lineups, una tabla `gold/lineup_strength.csv` con,
por `(date, team_code)`: `xi_rating` (media de `season_rating` de titulares), `att_rating`
(media de titulares en posiciones ofensivas), `def_rating` (media en defensivas/portero),
`n_starters`, `lineup_type`. Jugadores sin `season_rating` se omiten del promedio (no rompen).

**R4 — Robustez y no-regresión.**
SI no existe `bronze/lineups/` → la tabla de fuerza se omite sin romper el pipeline
(build-features sigue idéntico). Nombres de equipo → código FIFA con el mapeo existente.

**R5 — CLI.**
El sistema DEBE exponer `ingest-lineups` (scrape XI de los partidos del bracket, red real,
STOP) y `build-lineup-strength` (deriva la tabla desde bronze, offline). Subcomandos previos
intactos (conjunto exacto actualizado).

**R6 — Sin red en tests; sin libs nuevas.**
Tests con transporte inyectado + fixtures. `requests` ya está. `fetched_at` inyectado.
