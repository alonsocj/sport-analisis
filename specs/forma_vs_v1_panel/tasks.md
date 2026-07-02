# tasks.md — Feature 19: forma_vs_v1_panel

Checklist. Cada R<n> con ≥1 test (el reviewer rechaza si falta). Solo lectura+render en el
tab Modelo. Depende de F9 (app) y F18 (artefacto/veredicto). Sin libs nuevas. NO toca
cli/simulation/models ni otras pestañas.

## Implementación

- [ ] T1. `src/app/tabs/modelo.py`: `DEFAULT_FORMA_VS_V1` + `_render_forma_vs_v1(path)`
      (carga JSON con degradación, tabla γ × log-loss/Brier/exactitud con Δ vs v1, verdict,
      ventana, n_eval, caveat); llamada al final de `render_modelo` — R1, R2, R3.
- [ ] T2. Tests `tests/test_app_modelo_forma.py` (offline, artefacto JSON de fixture) — R1, R2, R4.

## Tests (mapeo R<n> → test)

| Req | Test |
|-----|------|
| R1  | `test_app_modelo_forma.py::test_carga_artefacto_ok`, `::test_artefacto_ausente_no_rompe`, `::test_json_malformado_no_rompe` |
| R2  | `::test_tabla_tiene_filas_y_delta_vs_v1`, `::test_baseline_marcado_y_verdict_presente` |
| R3  | `::test_render_modelo_no_excepciona_con_panel`, `::test_otras_secciones_y_tabs_intactas` (reuso `test_app_ui.py`) |
| R4  | transversal (offline, sin red, sin recálculo, sin libs nuevas) |

## Cierre

- [ ] T3. Suite completa verde (480 previos + nuevos), `bash init.sh` verde, sin warnings.
- [ ] T4. Review (Reviewer): trazabilidad R1–R4 ↔ tests; degradación (artefacto ausente/
      malformado); no toca cli/simulation/models ni otras secciones/pestañas.
- [ ] T5. **Validación real (con OK usuario)**: levantar app, abrir tab Modelo y ver el panel
      "Forma reciente vs v1" con la tabla y el veredicto.
- [ ] T6. Actualizar `feature_list.json` (19 → done), `progress/current.md`, `README.md`.
