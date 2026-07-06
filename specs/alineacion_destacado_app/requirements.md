# requirements.md — Feature 31: alineacion_destacado_app

Objetivo: **hacer visible la alineación probable** de cada partido KO y **el jugador
destacado** por equipo, cerrando el hueco de F28 (extrajo XI a datos, sin UI). Nueva
sub-pestaña "Alineación" en el detalle de cada llave.

Contexto verificado (2026-07-04): fotmob `content.lineup.{home,away}Team.starters` trae por
jugador `marketValue` (COBERTURA 100%, incluso en XI **predicho** de octavos por jugar; a
diferencia de `seasonRating` que es esparso ~25%), `shirtNumber`, `primaryTeamName` (club),
`age`, `usualPlayingPositionId` (0=GK/1=DEF/2=MID/3=ATT). El "destacado" se ancla en
`marketValue` (robusto) + amenaza de gol vía `player_factor` (F11, cruce por nombre) + rating
si existe.

Notación EARS. Tests en `tests/test_lineup_view.py` (pura) + `tests/test_app_alineacion.py`
(AppTest). Transporte inyectable → cero red en tests. STOP: re-scrape real requiere aprobación.

---

**R1 — Captura ampliada en el extractor de alineación.**
`fotmob_lineup` DEBE capturar por titular, además de lo ya extraído (F28):
`market_value` (int|None), `shirt_number` (int|None), `club` (str|None), `age` (int|None).
No-regresión: JSON viejo sin esos campos se lee con valores `None`.

**R2 — Selección del jugador destacado (crack) por equipo.**
Dado el XI de un equipo, el sistema DEBE elegir como "destacado" al titular con **mayor
`market_value`** (desempate determinista por nombre). Si ningún titular tiene `market_value`,
el crack es `None` (la UI degrada). El crack DEBE exponer `name, club, market_value, rating,
goal_share`.

**R3 — Amenaza de gol del crack vía player_factor.**
El `goal_share` del crack DEBE obtenerse cruzando su nombre (normalizado: minúsculas + sin
acentos, match por nombre completo o apellido) contra los scorers del `player_factor` del
equipo. Sin match → `goal_share = None` (no rompe; el caveat de F11 de acentos se mitiga con la
normalización).

**R4 — Vista de alineación por partido.**
El sistema DEBE localizar en `bronze/lineups/` el doc del partido por `(date, {home_code,
away_code})` y construir, por equipo (orientado al `home_code`/`away_code` de la llave), el
`XI` (lista de `name, shirt_number, pos_label`) ordenado por posición (POR→DEF→MED→DEL) con el
crack marcado. SI no hay doc de lineup → la vista indica "sin alineación disponible" (no rompe).

**R5 — Sub-pestaña "Alineación" en el detalle KO.**
El detalle de cada llave DEBE añadir una sub-pestaña "Alineación" que muestre, por equipo: la
**tarjeta del crack** (nombre, club, valor, amenaza de gol, rating) + el **XI probable**.
Las sub-pestañas previas (Predicción/Mercados/Goleadores/Equipos/Elo) quedan intactas.

**R6 — Sin red en tests; sin libs nuevas; no-regresión.**
Lógica de vista es pura y testeable con fixtures. AppTest no lanza excepción. `requests` ya
está. Re-scrape real = paso explícito (STOP).
