# requirements.md — Feature 2: feature_store

Objetivo: transformar la **capa bronze** (respuestas crudas de API-Football + CSV de la
fuente pública) en una **capa silver** normalizada (`data/silver/matches.csv`) y una
**capa gold** de features para modelado (`data/gold/team_features.csv` y
`data/gold/elo_history.csv`): medias móviles de los últimos 15 partidos por equipo y
métrica, y ratings **Elo** por selección.

Notación EARS. Cada `R<n>` es verificable y mapea a ≥1 test (ver `tasks.md`).
Todo el procesamiento es **offline** (lee disco, no hace red); no requiere `API_FOOTBALL_KEY`.

---

## Silver — normalización bronze → silver

**R1 — Extracción de partidos API-Football.**
CUANDO existan archivos bronze en `data/bronze/fixtures/*.json` (envoltorio
`{endpoint, params, fetched_at, payload}`), el sistema DEBE extraer de `payload.response`
los partidos **finalizados** (`fixture.status.short == "FT"`), obteniendo: fecha
(`fixture.date` ISO-8601 → `YYYY-MM-DD` en UTC), equipos (`teams.home/away.name`),
goles (`goals.home/away`) y torneo (`league.name`).
SI un partido no está finalizado (status ≠ `FT`), ENTONCES el sistema DEBE descartarlo.

**R2 — Estadísticas API-Football y posesión como float.**
DONDE exista en `data/bronze/fixtures_statistics/` el archivo de estadísticas de un partido
extraído en R1, el sistema DEBE adjuntar al partido las métricas por lado — córners,
tarjetas, tiros, tiros a puerta y posesión — según el esquema de
`src/ingestion/ingest.py::normalize_statistics`, convirtiendo la posesión de string
(`"55%"`) a float (`55.0`).
SI no existen estadísticas para un partido, ENTONCES sus columnas de stats DEBEN quedar
nulas y el procesamiento DEBE continuar sin fallar.

**R3 — Lectura de la fuente pública.**
CUANDO exista `data/bronze/public_results/results.csv` (columnas `date, home_team,
away_team, home_score, away_score, tournament, city, country, neutral`), el sistema DEBE
cargar sus partidos como filas silver con `source = "public_csv"` y todas las columnas de
stats (córners, tarjetas, tiros, tiros a puerta, posesión) nulas.
SI una fila del CSV público tiene goles no numéricos o fecha no parseable como
YYYY-MM-DD, ENTONCES el sistema DEBE descartarla y continuar sin fallar (coherente con
R5 de ingesta_publica).

**R4 — Normalización de nombres a códigos FIFA.**
El sistema DEBE mapear los nombres de equipo a códigos FIFA de 3 letras usando las 48
selecciones de `src/ingestion/teams.py` más una tabla de alias (nombre en la fuente →
código FIFA).
SI un equipo no pertenece a las 48 ni a la tabla de alias, ENTONCES el sistema DEBE
asignarle un código *fallback* determinista derivado de su nombre y CONSERVAR el partido
en silver (la red completa de oponentes es necesaria para el Elo global, R19).

**R5 — `match_id` estable.**
El sistema DEBE generar para cada fila silver un `match_id` determinista y estable entre
ejecuciones y procesos: hash corto de la cadena `source|date|home_code|away_code`
(misma entrada → mismo `match_id`).

**R6 — Dedupe entre fuentes.**
SI un mismo partido — clave `(date, home_code, away_code)` — aparece en ambas fuentes,
ENTONCES el sistema DEBE conservar **una única** fila con `source = "api_football"`
(prioridad a la fuente con estadísticas), tomando `neutral` y `tournament` del registro
público cuando éste exista.

**R7 — Escritura de `data/silver/matches.csv`.**
El sistema DEBE escribir `data/silver/matches.csv` con exactamente el esquema, tipos y
orden de columnas del contrato definido en `design.md`.
SI falta una de las dos fuentes bronze, ENTONCES el sistema DEBE continuar con la fuente
disponible; SI no existe ninguna fuente, ENTONCES DEBE fallar con un error claro.

---

## Gold — medias móviles (últimos 15)

**R8 — Media móvil de 15 por equipo y métrica.**
El sistema DEBE calcular, por equipo y por métrica (goles a favor, goles en contra,
córners a favor, córners en contra, tarjetas, tiros, tiros a puerta, posesión), la media
de las **últimas hasta 15 observaciones no nulas** de esa métrica, considerando SOLO
partidos con fecha **estrictamente anterior** a `as_of_date`.

**R9 — Anti-leakage (exclusión del partido actual y futuros).**
SI un partido tiene `date >= as_of_date`, ENTONCES el sistema NO DEBE incluirlo en ningún
cálculo de features para esa `as_of_date` (en particular, el propio partido que se quiere
predecir queda excluido).

**R10 — Ventana corta.**
SI un equipo tiene menos de 15 partidos anteriores a `as_of_date`, ENTONCES el sistema
DEBE usar los partidos disponibles y reportar el número usado en `matches_count`.
SI un equipo tiene 0 partidos anteriores, ENTONCES sus features de medias móviles DEBEN
ser nulas y `matches_count = 0`, sin fallar.

**R11 — Stats nullable con solo fuente pública.**
MIENTRAS un equipo solo tenga observaciones sin estadísticas (p. ej. todas sus filas
provienen de `source = "public_csv"`), el sistema DEBE devolver null en las medias de
stats (`corners_for_ma15`, `corners_against_ma15`, `cards_ma15`, `shots_ma15`,
`shots_on_target_ma15`, `possession_ma15`) manteniendo calculadas `gf_ma15` y `ga_ma15`.

---

## Gold — ratings Elo

**R12 — Rating inicial.**
CUANDO un equipo aparece por primera vez en el histórico, el sistema DEBE asignarle el
rating inicial 1500 (valor parametrizable).

**R13 — Actualización tras victoria / empate / derrota.**
CUANDO se procesa un partido, el sistema DEBE actualizar el rating de cada equipo como
`elo_post = elo_pre + K · G · (score − We)`, con `score = 1` (victoria), `0.5` (empate),
`0` (derrota): el ganador sube, el perdedor baja, y en el empate sube el equipo con menor
expectativa `We` y baja el de mayor expectativa.

**R14 — K por importancia del torneo.**
El sistema DEBE determinar `K` a partir del campo `tournament` mediante un mapa
configurable con valores por defecto: Mundial = 60; torneos continentales y eliminatorias
mundialistas = 50; Nations League / Copa Confederaciones = 40; amistosos = 20;
default = 30.

**R15 — Multiplicador de margen `G`.**
El sistema DEBE aplicar el multiplicador por margen de goles `diff = |home_goals −
away_goals|`: `diff <= 1 → G = 1.0`; `diff == 2 → G = 1.5`; `diff >= 3 → G = (11 +
diff) / 8`.

**R16 — Ventaja de localía solo en sede no neutral.**
El sistema DEBE calcular la expectativa del local como `We = 1 / (1 + 10^(−dr/400))` con
`dr = elo_home − elo_away + 100` SI `neutral = False`, y `dr = elo_home − elo_away`
(sin el +100) SI `neutral = True`. El valor `100` DEBE ser parametrizable.

**R17 — Simetría (suma de cambios = 0).**
CUANDO se procesa un partido, la suma de los cambios de rating de ambos equipos DEBE ser
exactamente 0 (mismo `K` y `G` para ambos lados; `score_away = 1 − score_home`;
`We_away = 1 − We_home`).

**R18 — Orden cronológico estable y determinista.**
El sistema DEBE procesar los partidos en orden cronológico ascendente con desempate
determinista para partidos de la misma fecha (por `match_id`).
CUANDO se ejecuta dos veces sobre la misma entrada, el sistema DEBE producir exactamente
los mismos ratings e historial.

**R19 — Elo global e historial por partido.**
El sistema DEBE calcular el Elo sobre **todos** los partidos de silver (incluidos los de
equipos fuera de las 48, conservados por R4) y DEBE escribir
`data/gold/elo_history.csv` con una fila por equipo y partido:
`date, code, opponent_code, elo_pre, elo_post, k, g, we, score`.

---

## Gold — construcción y orquestación

**R20 — `data/gold/team_features.csv` para las 48 selecciones.**
CUANDO se construye la capa gold para una `as_of_date`, el sistema DEBE escribir
exactamente **una fila por cada una de las 48 selecciones** (aunque alguna no tenga
partidos previos) con el esquema del contrato: `code, as_of_date, matches_count,
gf_ma15, ga_ma15, corners_for_ma15, corners_against_ma15, cards_ma15, shots_ma15,
shots_on_target_ma15, possession_ma15, elo`, donde `elo` es el rating vigente a
`as_of_date` (solo partidos estrictamente anteriores).

**R21 — Orquestación bronze → silver → gold.**
El sistema DEBE exponer una orquestación que, dada una `as_of_date` inyectada (nunca
`now()` implícito), construya silver y gold y escriba los tres CSVs (`matches.csv`,
`team_features.csv`, `elo_history.csv`) de forma determinista: misma entrada → mismos
archivos de salida.
