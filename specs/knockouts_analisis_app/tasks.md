# tasks.md — Feature 20: knockouts_analisis_app

Checklist. Cada R<n> con ≥1 test. Solo lectura+render en el tab Knockouts. Depende de F9
(app), F4 (markets), F11 (scorers/player_factor), F17 (tab Knockouts). Sin libs nuevas. NO
toca cli/simulation/models/markets/players ni otras pestañas.

## Implementación

- [ ] T1. `src/app/tabs/knockouts.py`: helper `_render_analisis_llave(params, home, away,
      player_factor_path, top_k=3)` (mercados vía `market_summary` + goleadores vía
      `player_factor`/`compute_anytime_scorers` con λ v1; degradación si falta player_factor;
      `@st.cache_data` por (home,away)); integrarlo en un `st.expander` por llave dentro de
      `render_knockouts`, etiquetado "v1" — R1, R2, R3, R4.
- [ ] T2. Tests `tests/test_app_knockouts_analisis.py` (offline, fixtures params+player_factor) — R1–R5.

## Tests (mapeo R<n> → test)

| Req | Test |
|-----|------|
| R1  | `::test_mercados_presentes_por_llave` (O/U + BTTS) |
| R2  | `::test_goleadores_top_k_por_equipo`, `::test_sin_player_factor_degrada` |
| R3  | `::test_etiqueta_v1_presente`, `::test_cache_no_recalcula_por_slider` |
| R4  | `::test_render_knockouts_no_excepciona_con_analisis`, `::test_otras_pestanas_intactas` |
| R5  | transversal (offline, sin red, sin recálculo de modelo, sin libs nuevas) |

## Cierre

- [ ] T3. Suite completa verde (487 previos + nuevos), `bash init.sh` verde, sin warnings.
- [ ] T4. Review (Reviewer): trazabilidad R1–R5 ↔ tests; etiqueta v1; degradación sin
      player_factor; no toca core/cli/otras pestañas.
- [ ] T5. **Validación real (OK usuario)**: abrir tab Knockouts, expandir una llave y ver
      mercados + goleadores.
- [ ] T6. Actualizar `feature_list.json` (20 → done), `progress/current.md`, `README.md`.
