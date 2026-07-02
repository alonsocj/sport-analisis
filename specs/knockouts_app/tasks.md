# tasks.md — Feature 17: knockouts_app

Checklist. Cada R<n> con ≥1 test (el reviewer rechaza si falta). Depende de F9 (app),
F3 (predict) y F16 (forma). Sin dependencias nuevas. NO tocar bronze/CLI/simulate.

## Implementación

- [ ] T1. `src/app/tabs/knockouts.py`: `load_knockout_fixtures` (CSV de datos, ausente→[]),
      `neutral_prediction` (promedio orientaciones + `p_adv_home`), `render_knockouts`
      (slider γ, factor 1×/render cacheado, agrupado por fecha) — R1, R2, R3, R4.
- [ ] T2. `src/app/main.py`: añadir pestaña "Knockouts"; las otras 3 intactas — R4.
- [ ] T3. Tests: `tests/test_app_knockouts.py` (offline, fixtures CSV, `form_builder`
      inyectado) — ver tabla.

## Tests (mapeo R<n> → test)

| Req | Test |
|-----|------|
| R1  | `test_app_knockouts.py::test_carga_fixtures_csv_ordenado`, `::test_csv_ausente_no_rompe` |
| R2  | `::test_gamma0_equivale_v1`, `::test_gamma_positivo_aplica_forma` |
| R3  | `::test_neutral_promedia_orientaciones`, `::test_p_avanza_formula` |
| R4  | `::test_render_no_excepciona`, `::test_tabs_existentes_intactas` |
| R5  | transversal (sin red, `as_of` inyectado, no escribe bronze, `form_builder` inyectado, sin libs nuevas) |

## Cierre

- [ ] T4. Suite completa verde (previos + nuevos), `bash init.sh` verde, sin warnings.
- [ ] T5. Review (Reviewer): trazabilidad R1–R5 ↔ tests; γ=0 ≡ v1; no toca bronze/CLI/
      simulate; degradación (CSV ausente, código no resoluble); tabs existentes intactas.
- [ ] T6. **Validación real (con tu OK)**: levantar la app y verificar la pestaña Knockouts
      con el bracket R32 real y el slider γ (v1 ↔ forma).
- [ ] T7. Actualizar `feature_list.json` (17 → done), `progress/current.md`, `README.md`.
