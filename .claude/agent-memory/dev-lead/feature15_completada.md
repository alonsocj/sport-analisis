---
name: feature15-xg-proxy-wikipedia-completada
description: Feature 15 xg_proxy_wikipedia implementada — proxy xG desde Wikipedia, 38 tests nuevos, 406 total, 14 subcomandos CLI (ingest-wiki-stats). Bloque v3 cerrado.
metadata:
  type: project
---

Feature 15 `xg_proxy_wikipedia` implementada y verificada (2026-06-17).

**Entregables:**
- `src/ingestion/wiki_stats.py` (R1): MediaWiki Action API, transporte inyectable, caché TTL 24h, parser seguro lxml, bronze+meta, degradación elegante sin stats.
- `src/xg/__init__.py` + `src/xg/proxy.py` (R2, R3, R4): normalización al silver, emparejamiento (match_id, team_code), xg_proxy = α·SoT + β·(shots−SoT) (α=0.30, β=0.03), serie objetivo mezclada goal_target.
- `src/models/dixon_coles.py` (R4): `load_training_data` y `fit_dixon_coles` aceptan `xg_target_map` opcional; default=None → goles reales → v1 exacto (tol 1e-9 verificado).
- `src/cli.py` (R6): subcomando `ingest-wiki-stats` + `--xg-weight` en train/backtest. Total 14 subcomandos.
- Tests: `tests/test_ingest_wiki.py`, `tests/test_xg_proxy.py`, `tests/test_cli_xg.py` — 38 tests nuevos.

**Verificaciones clave:**
- `test_v0_equivale_v1`: arrays x/y idénticos con v=0 vs sin xg_target_map (tol 1e-9) ✓
- `test_anti_fuga_xg_no_predice_su_partido`: partidos en/posteriores a as_of_date excluidos ✓
- `test_v0_nll_identica_a_v1`: NLL idéntica con v=0 (tol 1e-9) ✓
- Parser seguro: `pandas.read_html(flavor='lxml')` — nunca `etree.fromstring` sobre HTML ✓
- Sin librerías nuevas más allá de `lxml` (ya instalada) ✓

**Suite:** 406 passed, 0 warnings (incluso con `-W error`). Los 368 previos intactos.

**Deuda técnica:** La cobertura de Wikipedia es parcial (grandes torneos tienen stats, amistosos/clasificatorios rara vez). Documentado en requirements.md como limitación aceptada.

**Why:** R5 (backtest sobre cobertura) depende de datos reales de Wikipedia; T8 (validación real) pendiente de aprobación del usuario.
**How to apply:** Para la validación real (T8), ejecutar `ingest-wiki-stats` con red real requiere OK explícito del usuario (regla STOP de CLAUDE.md).
