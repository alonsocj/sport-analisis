# tasks.md — Feature 14: elo_externo_ensemble

Checklist de implementación. Cada R<n> con ≥1 test (el reviewer rechaza si falta).
Secuencia: T1 → T2 → T3 → T4 → cierre. Dep `lxml>=6.1.1` ya instalada (security-lead
APROBADO 2026-06-17, parser seguro obligatorio).

## Implementación

- [ ] T1. `src/ingestion/elo_ratings.py`: descarga (transporte inyectable), parser
      seguro lxml/`pandas.read_html`, validación de columnas o `EloParseError`,
      mapeo a códigos, bronze+meta con `fetched_at` inyectado, caché TTL, UA
      identificable — R1, R2.
- [ ] T2. `src/elo_ext/__init__.py` + `src/elo_ext/model.py`: sub-modelo Elo→1X2
      (fórmula + param empate), fuente de Elo as-of (elo_history) vs externo,
      artefacto gold `external_elo.csv`, rechazo de Elo externo en backtest — R3, R4, R7.
- [ ] T3. `src/elo_ext/ensemble.py`: mezcla `p=(1−w)·p_DC + w·p_Elo` (w=0 = v1) +
      ajuste de w/d por backtest walk-forward leak-free + comparación DC vs ensemble — R5, R6.
- [ ] T4. `src/cli.py`: `ingest-elo`; flags `--elo-weight` en predict/predict-log/
      simulate; barrido de w en backtest. Subcomandos previos intactos — R8.
- [ ] T5. Tests: `tests/test_ingest_elo.py`, `tests/test_elo_model.py`,
      `tests/test_cli_elo.py` (offline, fixtures HTML) — ver tabla.

## Tests (mapeo R<n> → test)

| Req | Test |
|-----|------|
| R1  | `test_ingest_elo.py::test_descarga_transporte_inyectable_y_meta`, `::test_columnas_invalidas_fallan_ruidoso`, `::test_cache_ttl_no_redescarga` |
| R2  | `test_ingest_elo.py::test_mapeo_codigos_y_descarte_sin_mapeo` |
| R3  | `test_elo_model.py::test_artefacto_gold_determinista` |
| R4  | `test_elo_model.py::test_elo_a_1x2_oraculo_y_neutral` |
| R5  | `test_elo_model.py::test_ensemble_w0_equivale_dc`, `::test_ensemble_mezcla_y_renormaliza` |
| R6  | `test_elo_model.py::test_ajuste_w_por_backtest_reproducible` |
| R7  | `test_elo_model.py::test_anti_fuga_elo_as_of`, `::test_elo_externo_rechazado_en_backtest` |
| R8  | `test_cli_elo.py::test_ingest_elo`, `::test_elo_weight_en_predict`, `::test_subcomandos_exactos_intactos`, `::test_exit_codes` |
| R9  | transversal (parser seguro, sin red, sin reloj, escritura bajo data/) |

## Cierre

- [ ] T6. Suite completa verde (previos + nuevos), `bash init.sh` verde, sin warnings.
- [ ] T7. Review (Reviewer): trazabilidad R1–R8 ↔ tests; equivalencia v1 con w=0;
      anti-fuga; parser seguro lxml; Elo externo no usable en backtest.
- [ ] T8. **Validación real**: `ingest-elo` (red, con tu OK) + ajuste de w por
      backtest + comparación DC vs ensemble; pegar métricas en `progress/current.md`.
- [ ] T9. Dictamen security-lead del código (parser seguro aplicado, caché, UA, sin
      secrets). (Lib ya aprobada.)
- [ ] T10. Actualizar `feature_list.json` (14 → done; promover 15 → pending),
      `progress/current.md`, `README.md`.
