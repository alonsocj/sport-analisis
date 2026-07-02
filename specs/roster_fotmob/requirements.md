# requirements.md — Feature 21: roster_fotmob

Objetivo: ingestar la **disponibilidad de jugadores** desde fotmob (alineación predicha +
suplentes = disponibles; lesionados/sancionados = no disponibles) para alimentar el flag
`--roster` existente, de modo que `scorers` (CLI y panel de la app) **ignore a quien no
juega** y renormalice las probabilidades de goleador.

Viabilidad verificada (2026-06-28): fotmob NO bloquea a Python (`requests` → HTTP 200);
el HTML trae `__NEXT_DATA__ → props.pageProps.content.lineup.{homeTeam,awayTeam}` con
`starters` (11), `subs` (~14) y `unavailable` (con campo `unavailability`/motivo y fecha de
retorno). A diferencia de FBref (F15, Cloudflare). Demo: RSA sin Themba Zwane, CAN sin
Ismaël Koné — y Zwane está en el top-5 de goleadores de RSA → el roster lo filtra.

Limitación honesta: pre-partido fotmob da **alineación PREDICHA** (no confirmada hasta ~1h
antes). El roster es la mejor estimación de disponibilidad, no la oficial.

Notación EARS. Cada `R<n>` mapea a ≥1 test en `tests/test_ingest_roster.py`,
`tests/test_roster_normalize.py` o `tests/test_app_knockouts_roster.py`.

---

**R1 — Ingesta fotmob (red real, transporte inyectable).**
El sistema DEBE, dado el conjunto de partidos R32, obtener por partido el `lineup` de fotmob
vía un transporte HTTP INYECTABLE (en producción `requests` con UA identificable y
rate-limit ≥1 req/2s; en tests un transporte que devuelve fixtures `__NEXT_DATA__`
guardados). Parsear `content.lineup.{homeTeam,awayTeam}` → por equipo: `starters`+`subs`
(disponibles) y `unavailable` (no disponibles, con motivo/fecha). Persistir bronze por
partido `data/bronze/rosters/<slug>.json` + meta (`fetched_at` INYECTADO, `url`, `sha256`).
SI un partido no trae lineup → se registra vacío (no aborta).

**R2 — Normalización a roster + mapeo a códigos FIFA.**
El sistema DEBE mapear los nombres de equipo de fotmob a los **códigos FIFA del proyecto**
(`to_fifa_code`), y los nombres de jugador de forma normalizada. DEBE escribir
`data/rosters/r32_rosters.csv` compatible con el flag `--roster` existente
(columnas `team_code,scorer` con los **disponibles**), y capturar aparte los **no
disponibles** (`team_code,player,reason`) para visualización. DEBE reportar cobertura
(equipos/partidos con roster). Equipo sin mapeo FIFA → se descarta con aviso (no aborta).

**R3 — Integración en el panel de goleadores de la app (tab Knockouts).**
DONDE exista roster para un equipo, el panel de goleadores (Feature 20) DEBE filtrar a los
jugadores NO disponibles antes de calcular anytime-scorers (renormalizando las `share` de
los disponibles) y mostrar una nota de quién está fuera y por qué. SIN roster → comportamiento
idéntico a Feature 20 (sin filtro). El flag `--roster` del CLI `scorers`/`simulate` ya existe
y consume el mismo CSV de disponibles.

**R4 — CLI.**
El sistema DEBE exponer el subcomando `ingest-roster` (red real vía transporte inyectable;
regla STOP de CLAUDE.md). El conjunto EXACTO de subcomandos previos DEBE permanecer intacto
+ `ingest-roster`. Salida `✅`/`--json` consistente.

**R5 — Determinismo, sin red en tests, degradación, sin libs nuevas.**
Tests 100% offline con fixtures `__NEXT_DATA__`; `fetched_at` inyectado (sin reloj en lógica);
escritura solo bajo `data/`; partido sin lineup / equipo sin mapeo / roster ausente →
degradación elegante; sin dependencias nuevas (`requests` ya está en el stack).
