# tasks.md — Feature 18: forma_perf

Checklist. Cada R<n> con ≥1 test (el reviewer rechaza si falta). Optimización SIN cambio de
comportamiento (equivalencia 1e-9). Depende de F16. Sin libs nuevas. NO tocar cli/app/
simulation/models.

## Implementación

- [ ] T1. `src/form/window.py`: extraer la lógica de parseo/perspectiva/selección a funciones
      puras compartidas; añadir `index_matches_by_team` (1 pasada `itertuples`) y
      `build_window_from_bucket`; re-implementar `build_window` sobre ellas (firma estable) — R1, R3.
- [ ] T2. `src/form/factor.py`: `make_form_factor_fn` construye el índice UNA vez y arma cada
      ventana desde el bucket; resto sin cambios — R1, R2.
- [ ] T3. Tests `tests/test_form_perf.py`: equivalencia oráculo (factores+z idénticos a la ruta
      clásica por-equipo, tol 1e-9), índice 1 sola pasada, escala acotada — R1, R2, R4.

## Tests (mapeo R<n> → test)

| Req | Test |
|-----|------|
| R1  | `test_form_perf.py::test_indice_una_sola_pasada`, `::test_build_window_from_bucket_equivale` |
| R2  | `test_form_perf.py::test_factores_identicos_ruta_clasica_1e9`, `::test_z_por_equipo_identicas` |
| R3  | reuso `test_forma_reciente.py` + `test_form_factor.py` (verdes sin cambios) + `::test_build_window_api_estable` |
| R4  | `test_form_perf.py::test_escala_no_recorre_df_por_equipo` (silver grande, coste no multiplicativo en N) |
| R5  | transversal (sin red, sin libs nuevas, γ=0 ≡ v1 exacto) |

## Cierre

- [ ] T4. Suite completa verde (469 previos + nuevos), `bash init.sh` verde, sin warnings.
- [ ] T5. Review (Reviewer): equivalencia 1e-9 vs F16; API estable; anti-fuga; índice 1 pasada;
      sin tocar cli/app/simulation/models.
- [ ] T6. **VALIDACIÓN/VEREDICTO (con OK usuario)**: correr `backtest --from-date 2026-06-14
      --to-date 2026-06-28 --form-weight {0,0.2,0.3}`; reportar Brier/log-loss/accuracy v1 vs
      forma; **emitir veredicto** (¿la forma bate a v1?). Registrar el número.
- [ ] T7. Actualizar `feature_list.json` (18 → done + veredicto), `progress/current.md`, `MEMORY.md`.
