# tasks.md — Feature 22: knockouts_detalle_app

Checklist. Cada R<n> con ≥1 test. Refactor del tab Knockouts (tarjetas + detalle con
sub-pestañas). Depende de F17 (tab), F20 (markets/scorers), F21 (roster), F4 (figuras), F9
(app/data). Sin libs nuevas. NO toca `figures.py`, el tab Calendario, cli/simulation/models.

## Implementación

- [ ] T1. `src/app/tabs/knockouts.py`: helper `_neutral_matrix_pred(params, home, away,
      form_factor)` (matriz neutral promediada + MatchPrediction sintético con top-10);
      `_render_detalle_ko(fixture, app_data, gamma, ...)` con sub-pestañas Predicción/Mercados/
      Goleadores/Equipos/Elo (reusa fig_1x2, fig_heatmap, fig_comparativa, fig_elo_lines,
      market_summary, helper goleadores+roster) — R2, R3.
- [ ] T2. `src/app/tabs/knockouts.py`: tarjetas compactas por fecha con botón "ver detalle"
      (st.session_state, patrón Calendario); render del detalle seleccionado — R1, R4.
- [ ] T3. Tests `tests/test_app_knockouts_detalle.py` (offline, fixtures) — R1–R5.

## Tests (mapeo R<n> → test)

| Req | Test |
|-----|------|
| R1  | `::test_seleccion_abre_detalle`, `::test_sin_seleccion_no_excepciona` |
| R2  | `::test_subpestanas_presentes`, `::test_mercados_y_goleadores_en_detalle` |
| R3  | `::test_top10_marcadores_orden_desc`, `::test_matriz_neutral_promedia_orientaciones`, `::test_gamma_afecta_prediccion` |
| R4  | `::test_lista_llaves_y_slider_intactos`, `::test_otras_pestanas_intactas` |
| R5  | transversal (offline, degradación equipo/elo/roster ausente, sin libs nuevas) |

## Cierre

- [ ] T4. Suite completa verde (519 previos + nuevos), `bash init.sh` verde, sin warnings.
- [ ] T5. Review (Reviewer): trazabilidad R1–R5 ↔ tests; matriz neutral; top-10 orden; reuso de
      figuras sin modificarlas; γ respetado; otras pestañas intactas.
- [ ] T6. **Validación real (OK usuario)**: abrir tab Knockouts, seleccionar una llave y ver su
      página con Predicción (top-10), Mercados, Goleadores(roster), Equipos, Elo.
- [ ] T7. Actualizar `feature_list.json` (22 → done), `progress/current.md`, `README.md`.
