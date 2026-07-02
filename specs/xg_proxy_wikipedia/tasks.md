# tasks.md — Feature 15: xg_proxy_wikipedia

Checklist de implementación. Cada R<n> con ≥1 test (el reviewer rechaza si falta).
Secuencia: T1 → T2 → T3 → T4 → cierre. Dep `lxml` ya instalada (parser seguro
obligatorio). Depende de features 2 (silver) y 3 (DC).

## Implementación

- [ ] T1. `src/ingestion/wiki_stats.py`: MediaWiki Action API (transporte inyectable),
      parseo seguro lxml, bronze+meta con `fetched_at` inyectado, caché 24h, UA
      identificable, rate-limit inyectable; sin stats → registro sin ellas — R1.
- [ ] T2. `src/xg/__init__.py` + `src/xg/proxy.py`: normalización y emparejamiento al
      silver (cobertura %), proxy xG documentado, serie objetivo mezclada
      `goal_target=(1−v)·goles+v·xg` (solo con cobertura) — R2, R3, R4.
- [ ] T3. ENMIENDA `src/models/dixon_coles.py`: `load_training_data` admite serie
      objetivo mezclada; default = goles reales (equivalencia v1 exacta) — R4.
- [ ] T4. `src/cli.py`: `ingest-wiki-stats`; flag `--xg-weight` en train/backtest;
      subcomandos previos intactos — R6.
- [ ] T5. Tests: `tests/test_ingest_wiki.py`, `tests/test_xg_proxy.py`,
      `tests/test_cli_xg.py` (offline, fixtures JSON/HTML) — ver tabla.

## Tests (mapeo R<n> → test)

| Req | Test |
|-----|------|
| R1  | `test_ingest_wiki.py::test_mediawiki_transporte_inyectable_y_meta`, `::test_cache_24h_no_refetch`, `::test_articulo_sin_stats_no_aborta` |
| R2  | `test_xg_proxy.py::test_emparejamiento_silver_y_cobertura`, `::test_partidos_sin_cobertura_marcados` |
| R3  | `test_xg_proxy.py::test_proxy_xg_formula_oraculo` |
| R4  | `test_xg_proxy.py::test_v0_equivale_v1`, `::test_serie_mezclada_solo_con_cobertura`, `::test_anti_fuga_xg_no_predice_su_partido` |
| R5  | `test_xg_proxy.py::test_backtest_sobre_cobertura_reproducible` |
| R6  | `test_cli_xg.py::test_ingest_wiki_stats`, `::test_xg_weight_en_train`, `::test_subcomandos_exactos_intactos`, `::test_exit_codes` |
| R7  | transversal (parser seguro, sin red, sin reloj, degradación elegante, escritura bajo data/) |

## Cierre

- [ ] T6. Suite completa verde (previos + nuevos), `bash init.sh` verde, sin warnings.
- [ ] T7. Review (Reviewer): trazabilidad R1–R6 ↔ tests; equivalencia v1 con v=0;
      anti-fuga; parser seguro; degradación elegante sin cobertura; cobertura reportada.
- [ ] T8. **Validación real**: `ingest-wiki-stats` (red, con tu OK) sobre la jornada 1;
      reportar % cobertura + comparación v1 vs xG-aumentado donde haya datos.
- [ ] T9. Dictamen security-lead del código (MediaWiki API, UA, rate-limit, caché,
      parser seguro).
- [ ] T10. Actualizar `feature_list.json` (15 → done), `progress/current.md`,
      `README.md`. Cierre del bloque v3 (mejoras free A+B).
