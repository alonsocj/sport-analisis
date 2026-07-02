# requirements.md — Feature 23: fotmob_stats (ingesta de stats por partido)

Objetivo: **fundación de datos** para los nuevos mercados (córners, tarjetas, tiros, goles
con xG real). Ingestar desde fotmob las estadísticas por partido de los encuentros WC2026
**jugados** y poblar las **columnas avanzadas del silver que hoy están vacías** (córners,
tarjetas, tiros, tiros a puerta, posesión) + añadir **xG** real por equipo.

Contexto verificado (2026-06-28): el silver tiene 10 columnas avanzadas (`home/away_corners,
_cards, _shots, _shots_on_target, _possession`) pero **0/49.475 con dato** (eran para el xG
de Wikipedia/F15 que dio 0% cobertura). fotmob SÍ trae, por partido jugado (verificado en
RSA 0-1 CAN): `content.stats.Periods.All` con posesión, **xG** (open/set/xGOT), **tiros**
(total/on target/inside-outside box/blocked), **córners**, **tarjetas** (amarillas/rojas),
faltas, pases, duelos. fotmob responde a `requests` (HTTP 200; NO bloqueado, distinto a FBref).

Limitación honesta: solo partidos JUGADOS tienen stats. La cobertura útil = WC2026 jugados
(72 grupos + knockouts conforme se jueguen). El histórico martj42 (49k) NO trae estos stats y
no se backfillea aquí. Muestra chica → los mercados que se construyan encima nacen limitados.

Notación EARS. Cada `R<n>` mapea a ≥1 test en `tests/test_ingest_fotmob_stats.py` o
`tests/test_silver_fotmob_stats.py`.

---

**R1 — Ingesta fotmob de stats por partido (red real, transporte inyectable).**
El sistema DEBE descubrir las URLs de los partidos WC2026 jugados desde fotmob (página de
liga 77) y, por partido, obtener vía transporte HTTP INYECTABLE el `content.stats.Periods.All`,
extrayendo por equipo: `shots, shots_on_target, corners, cards (amarillas+rojas), possession,
xg`. Persistir bronze por partido `data/bronze/fotmob_stats/<slug>.json` + meta (`fetched_at`
INYECTADO, `url`, `sha256`). Rate-limit ≥1 req/2s, UA identificable. SI un partido no trae
stats → se registra vacío (no aborta). Transporte real = `requests`; tests = fixtures.

**R2 — Normalización, mapeo FIFA y unión al silver por (fecha, equipos).**
El sistema DEBE mapear los nombres de equipo fotmob a códigos FIFA (`to_fifa_code` +
alias si aplica) y unir las stats a la fila correspondiente del silver por
`(date, home_code, away_code)`, poblando `home/away_{corners,cards,shots,shots_on_target,
possession}` y añadiendo `home_xg/away_xg`. Un partido sin match en el silver → se omite con
aviso. DEBE reportar cobertura (partidos/equipos con stats).

**R3 — Integración en build-features, no-regresión.**
`build-features` DEBE poblar esas columnas cuando exista el bronze fotmob_stats; SI el bronze
no existe, el silver es IDÉNTICO al actual (columnas avanzadas nulas, `home_xg/away_xg`
nulas/ausentes según convención) — no-regresión exacta de los consumidores actuales
(modelo DC, forma, etc. no leen estas columnas).

**R4 — CLI.**
El sistema DEBE exponer `ingest-fotmob-stats` (red real; regla STOP). El conjunto EXACTO de
subcomandos previos DEBE permanecer intacto + `ingest-fotmob-stats`. Salida `✅`/`--json`.

**R5 — Determinismo, sin red en tests, degradación, sin libs nuevas.**
Tests 100% offline con fixtures `__NEXT_DATA__`; `fetched_at` inyectado; escritura solo bajo
`data/`; partido sin stats / equipo sin mapeo / bronze ausente → degradación elegante; sin
dependencias nuevas (`requests` ya está). Esta feature NO construye mercados (eso son features
posteriores); solo ingesta y población del silver.
