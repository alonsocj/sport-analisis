# requirements.md — Feature 14: elo_externo_ensemble

Objetivo: mejorar la precisión mezclando un **sub-modelo Elo → 1X2** con el
Dixon-Coles (ensemble a nivel de probabilidad, peso ajustado por backtest) e
incorporar **Elo externo de eloratings.net** (fuente pública free) como prior de
predicción live. Los ensembles DC+Elo bajan log-loss de forma fiable; el Elo
externo aporta una valoración más calibrada y con más historia que nuestra ventana
2018+.

Principio de no-regresión: el ensemble con peso 0 reproduce v1 EXACTAMENTE.

Limitación honesta de la fuente: eloratings.net publica solo el **snapshot actual**
de Elo (no series históricas). Por tanto el Elo EXTERNO no es backtesteable sin
fuga temporal: el ajuste y la medición del ensemble usan NUESTRO `elo_history`
(leak-free, feature 2); el Elo externo se usa como prior en predicción live y su
beneficio se argumenta, no se backtestea (documentado).

Dictamen security-lead (2026-06-17): usar `lxml>=6.1.1` con parser seguro
(`no_network=True, resolve_entities=False, huge_tree=False`); caché bronze; UA
identificable; validar columnas esperadas o fallar ruidosamente.

Notación EARS. Cada `R<n>` mapea a ≥1 test en `tests/test_ingest_elo.py`,
`tests/test_elo_model.py` o `tests/test_cli_elo.py` (ver `tasks.md`).

---

**R1 — Ingesta eloratings.net a bronze.**
El sistema DEBE descargar la tabla de Elo de selecciones vía transporte INYECTABLE
(`url → texto HTML`), parsearla con `lxml`/`pandas.read_html` usando parser seguro
(`no_network=True`, `huge_tree=False`; nunca `etree.fromstring` sobre HTML crudo),
validar que el resultado tiene las columnas esperadas (selección y rating) o FALLAR
ruidosamente, y persistir bronze + sidecar meta (`url`, `fetched_at` INYECTADO,
`sha256`). SI existe un bronze del día (TTL configurable, default 7 días) → NO
re-descargar (caché).

**R2 — Mapeo de selecciones a códigos.**
El sistema DEBE mapear los nombres de eloratings a los códigos del proyecto
(reusa `DATASET_ALIASES` de `public_data`). Selecciones sin mapeo → descartadas con
motivo, sin abortar.

**R3 — Artefacto gold de Elo externo.**
El sistema DEBE persistir `data/gold/external_elo.csv` determinista (columnas
`fetched_date, team_code, elo`, orden por `team_code`). Misma entrada → mismo
contenido byte a byte. Escritura solo bajo `data/`.

**R4 — Sub-modelo Elo → 1X2.**
El sistema DEBE producir P(1X2) a partir del Elo de dos equipos y la ventaja local
(respetando `neutral`) mediante una fórmula Elo estándar documentada
(`expected_score = 1/(1+10^(-(ΔElo+H)/400))`) con un parámetro de empate
inyectable. DEBE poder alimentarse tanto con nuestro `elo_history` (as-of, histórico)
como con el Elo externo (snapshot live).

**R5 — Ensemble con Dixon-Coles.**
El sistema DEBE mezclar las probabilidades 1X2: `p = (1−w)·p_DC + w·p_Elo`,
`w ∈ [0,1]`, renormalizando si procede. El DEFAULT `w = 0` DEBE producir
predicciones IDÉNTICAS a v1/DC (test de equivalencia, tol 1e-9).

**R6 — Ajuste del peso por backtest (leak-free).**
El sistema DEBE elegir `w` (y el parámetro de empate) minimizando log-loss en el
backtest walk-forward (reusa `src/backtest/`) usando NUESTRO `elo_history` as-of
por ventana (sin fuga). DEBE reportar v1 (DC) vs ensemble de forma reproducible.

**R7 — Anti-fuga.**
En el backtest, el Elo del sub-modelo para un partido DEBE ser un valor as-of con
fecha `< fecha_partido` (de `elo_history`). Un test DEBE verificar la propiedad. El
Elo EXTERNO (eloratings) es snapshot actual → SOLO para predicción live, NUNCA en el
backtest histórico (documentado; el código DEBE impedir su uso en backtest).

**R8 — CLI.**
El sistema DEBE exponer el subcomando `ingest-elo` (CC0/free, red real; test con
transporte inyectado) y un flag `--elo-weight <w>` (default 0) en `predict` y
`predict-log` que APLIQUE el ensemble de verdad (con `w>0` la salida cambia; en
`predict-log` el `model_version` se etiqueta `dc-ens` y el Elo es `elo_history`
as-of, leak-free, para poder medirlo con la feature 10). `simulate` queda EXCLUIDO
del ensemble (trabaja a nivel de marcador, no 1X2; decisión documentada en design).
El conjunto EXACTO de subcomandos previos DEBE permanecer intacto + `ingest-elo`.

**R9 — Determinismo, parser seguro, sin red en tests.**
Tests offline con fixtures (HTML guardado); parser lxml seguro; `fetched_at`/`as_of`
inyectados (sin reloj); escritura solo bajo `data/`; sin librería nueva más allá de
`lxml` (ya aprobada/instalada).
