# tasks.md — Feature 16: forma_reciente

Checklist de implementación. Cada R<n> con ≥1 test (el reviewer rechaza si falta).
Secuencia: T1 → T2 → T3 → T4 → T5 → cierre. Sin dependencias nuevas. Depende de
features 2 (silver), 3 (Dixon-Coles), 13 (simulate) y 14 (Elo externo). **NO empezar
hasta que el LEADER apruebe esta spec.**

## Implementación

- [ ] T1. `src/form/window.py`: `build_window(matches, team, as_of, k_pre=5)`; ≤3
      grupo WC + ≤K pre-WC; filtro estricto `date < as_of`; sin partidos → ventana
      parcial sin abortar — R1.
- [ ] T2. `src/form/metrics.py` + `src/form/config.py`: métricas ponderadas por
      recencia (decay) y tier (grupo vs pre-WC); parámetros versionados; `as_of`
      inyectado, sin reloj — R2.
- [ ] T3. `src/form/factor.py`: ajuste por Elo del rival (`external_elo.csv`, rival
      sin Elo → peso neutro); estandarización z entre 48; `factor(z,γ)=exp(γ·z)` — R3, R4.
- [ ] T4. Punto de extensión en el predictor (Features 3/13): callable opcional
      `form_factor`; sin él o `γ=0` → `(1.0,1.0)`. NO altera la fuerza base del DC — R4.
- [ ] T5. `src/cli.py`: flag `--form-weight` en `predict`/`backtest`/`simulate`;
      subcomandos previos EXACTAMENTE intactos — R6.
- [ ] T6. Tests: `tests/test_forma_reciente.py`, `tests/test_form_factor.py`,
      `tests/test_cli_form.py` (offline, fixtures silver/Elo) — ver tabla.

## Tests (mapeo R<n> → test)

| Req | Test |
|-----|------|
| R1  | `test_forma_reciente.py::test_ventana_3grupo_5prewc`, `::test_filtro_estricto_as_of_anti_fuga`, `::test_equipo_sin_partidos_ventana_parcial` |
| R2  | `test_forma_reciente.py::test_pesos_recencia_decay`, `::test_tier_grupo_pesa_mas_que_amistoso`, `::test_metricas_oraculo_deterministas` |
| R3  | `test_form_factor.py::test_ajuste_calidad_rival_elo`, `::test_rival_sin_elo_peso_neutro` |
| R4  | `test_form_factor.py::test_gamma0_equivale_v1_tol_1e9`, `::test_estandarizacion_z`, `::test_factor_exp_gamma_z`, `::test_ventana_vacia_factor_neutro` |
| R5  | `test_form_factor.py::test_backtest_v1_vs_forma_reproducible` |
| R6  | `test_cli_form.py::test_form_weight_en_predict`, `::test_subcomandos_exactos_intactos`, `::test_exit_codes_y_json` |
| R7  | transversal (sin red, `as_of` inyectado, degradación, escritura bajo data/, sin libs nuevas) |

## Cierre

- [ ] T7. Suite completa verde (previos + nuevos), `bash init.sh` verde, sin warnings.
- [ ] T8. Review (Reviewer): trazabilidad R1–R6 ↔ tests; equivalencia v1 con `γ=0`;
      anti-fuga; degradación (ventana vacía / rival sin Elo); subcomandos intactos.
- [ ] T9. **Validación real (con tu OK)**: backtest v1 vs v1+forma sobre los partidos
      WC2026 disponibles; reportar Brier/log-loss/accuracy y veredicto vs baseline v1.
- [ ] T10. Actualizar `feature_list.json` (16 → done), `progress/current.md`,
      `README.md`, `MEMORY.md`. Registrar veredicto (¿bate a v1?).
