# requirements.md — Feature 15: xg_proxy_wikipedia

Objetivo: incorporar una señal **tipo xG** (menos ruidosa que los goles) usando
estadísticas públicas free de **Wikipedia** (tiros, tiros a puerta, posesión por
partido). De ahí se deriva un **proxy de xG por equipo/partido** que mejora la
estimación de fuerza del modelo Dixon-Coles: se ajusta el modelo sobre una mezcla
de goles reales y proxy-xG (donde haya cobertura), reduciendo el impacto de
golizas/ruido (p.ej. GER 7-1). Mejora orientada a la PREDICCIÓN futura (alimentar
xG pasado a la fuerza del equipo), no a retrodecir un partido con sus propias stats.

Principio de no-regresión: con mezcla 0 (solo goles) el modelo reproduce v1.

Dictamen security-lead (2026-06-17): usar la **MediaWiki Action API** (no scraping
de HTML directo), UA identificable con contacto, rate-limit ≥1 req/5s, caché bronze
24h, `lxml>=6.1.1` con parser seguro para cualquier HTML embebido.

Limitación honesta (riesgo aceptado por el usuario): Wikipedia tiene stats
detalladas sobre todo para grandes torneos (Mundial, Euro…), rara vez para
amistosos/clasificatorios. La **cobertura será parcial**; el parseo de infoboxes/
tablas es frágil. El sistema DEBE degradar con elegancia (sin cobertura → goles
reales, comportamiento v1) y reportar la cobertura.

Notación EARS. Cada `R<n>` mapea a ≥1 test en `tests/test_ingest_wiki.py`,
`tests/test_xg_proxy.py` o `tests/test_cli_xg.py` (ver `tasks.md`).

---

**R1 — Ingesta Wikipedia vía MediaWiki API.**
El sistema DEBE obtener, por partido objetivo, las estadísticas disponibles (tiros,
tiros a puerta, posesión) usando un transporte INYECTABLE sobre la MediaWiki Action
API; parsear con `lxml` seguro (`no_network=True`, `huge_tree=False`); persistir
bronze por artículo `data/bronze/wikipedia/<slug>.json` + meta (`fetched_at`
INYECTADO, `url`, `sha256`). Caché TTL 24h (no re-fetch si fresco). UA identificable
inyectable. SI un artículo no trae stats → se registra sin ellas (no aborta).

**R2 — Normalización y emparejamiento al silver.**
El sistema DEBE normalizar las stats a una tabla por (`match_id`, `team_code`) con
`shots, shots_on_target, possession`, emparejando con el silver por fecha + equipos
(códigos del proyecto). Partidos sin stats → marcados `sin_cobertura`. El sistema
DEBE reportar el % de cobertura.

**R3 — Proxy de xG por equipo/partido.**
El sistema DEBE derivar un `xg_proxy` por equipo/partido mediante un modelo simple y
DOCUMENTADO (p.ej. `xg = α·SoT + β·(shots − SoT)`, con α,β calibrados por tasa
histórica de conversión, o una tasa por SoT). Determinista; documentar el método y
sus supuestos.

**R4 — Fuerza aumentada por xG (leak-free) + mezcla.**
El sistema DEBE poder ajustar el Dixon-Coles sobre una serie de objetivo mezclada:
`goal_target = (1−v)·goles_reales + v·xg_proxy` por partido, SOLO donde haya
cobertura (sin cobertura → goles reales). `v ∈ [0,1]`, default `v = 0` ⇒ ajuste
IDÉNTICO a v1 (test de equivalencia, tol 1e-9). El xG de un partido NUNCA se usa
para predecir ESE partido (solo entra como histórico para la fuerza prospectiva;
anti-fuga preservada por el filtro `fecha < as_of`).

**R5 — Ajuste/medición por backtest (cobertura limitada).**
El sistema DEBE permitir evaluar el efecto de `v` con el harness (backtest/feature
10) sobre el subconjunto con cobertura, reportando v1 vs xG-aumentado. DEBE
documentar que la cobertura parcial limita la potencia de la medición.

**R6 — CLI.**
El sistema DEBE exponer `ingest-wiki-stats` (red real vía MediaWiki API; test con
transporte inyectado) y un flag `--xg-weight <v>` (default 0) en `train`/`backtest`
para activar el objetivo aumentado. El conjunto EXACTO de subcomandos previos DEBE
permanecer intacto + `ingest-wiki-stats`.

**R7 — Determinismo, parser seguro, sin red en tests, degradación elegante.**
Tests offline con fixtures (JSON/HTML guardado); parser lxml seguro; `fetched_at`/
`as_of` inyectados; escritura solo bajo `data/`; sin cobertura ⇒ comportamiento v1;
sin librería nueva más allá de `lxml`.
