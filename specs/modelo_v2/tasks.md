# tasks.md — Feature 12: modelo_v2

Checklist de implementación. Cada R<n> con ≥1 test (el reviewer rechaza si falta).
Secuencia: T1 → T2 → T3 → T4 → cierre. Depende de la feature 10 (harness eval).

## Implementación

- [ ] T1. `src/models/importance.py`: mapa tier → factor, clasificación de
      `tournament`, default identidad, fallback documentado — R1, R2.
- [ ] T2. ENMIENDA `src/models/dixon_coles.py`: `load_training_data`/`fit_dixon_coles`
      aceptan `importance_map` → `w = decay × importance`; default 1.0 = v1
      (equivalencia exacta) y anti-fuga preservada — R1, R3.
- [ ] T3. Extensión `src/backtest/`: grid sobre (ξ, reg_lambda, escala importancia)
      incl. torneo; comparación v1 vs v2 — R4, R7.
- [ ] T4. Extensión `src/cli.py`: `train --model-version --importance`, persistencia
      v2 diferenciada (`dixon_coles_params_v2.json`), selección de versión en
      predict/markets; flags de importancia en `backtest`. Subcomandos previos
      intactos — R5, R6.
- [ ] T5. Tests: `tests/test_modelo_v2.py`, `tests/test_dixon_coles_importance.py`,
      `tests/test_cli_train_v2.py` (offline, fixtures) — ver tabla.

## Tests (mapeo R<n> → test)

| Req | Test |
|-----|------|
| R1  | `test_dixon_coles_importance.py::test_default_identidad_equivale_v1`, `::test_w_es_decay_por_importance` |
| R2  | `test_modelo_v2.py::test_clasificacion_tiers_y_fallback` |
| R3  | `test_dixon_coles_importance.py::test_anti_fuga_con_importancia` |
| R4  | `test_modelo_v2.py::test_grid_importancia_ranking_reproducible` |
| R5  | `test_modelo_v2.py::test_rolling_por_jornada_anti_fuga_y_model_version` |
| R6  | `test_cli_train_v2.py::test_train_v2_persiste_sin_pisar_v1`, `::test_seleccion_version_en_predict` |
| R7  | `test_modelo_v2.py::test_comparacion_v1_vs_v2_determinista` |
| R8  | cubierto transversalmente (sin red, sin reloj, sin lib nueva) |

## Cierre

- [ ] T6. Suite completa verde (previos + nuevos), `bash init.sh` verde.
- [ ] T7. Review (Reviewer): trazabilidad R1–R7 ↔ tests; equivalencia v1 con default
      identidad (sin regresión); anti-fuga; sin lib nueva.
- [ ] T8. **Validación real**: re-grid con torneo + comparación v1 vs v2 (feature 10)
      sobre la jornada 1; pegar métricas en `progress/current.md`. Elegir config v2
      (decisión a registrar).
- [ ] T9. Dictamen security-lead (sin red; escritura bajo data/).
- [ ] T10. Actualizar `feature_list.json` (12 → done; promover 13 → pending),
      `progress/current.md`, `README.md`.
