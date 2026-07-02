# tasks.md — Feature 4: modelos_mercados (solo goles)

Checklist de implementación. Cada R<n> con ≥1 test (el reviewer rechaza si falta).

## Implementación

- [x] T1. `src/markets/__init__.py` (docstring, sin imports) — R1, R10.
- [x] T2. `src/markets/goals.py`: `_validate_line`, `prob_over`, `prob_btts`,
      `prob_team_over`, `MarketLine`, `MarketSummary`, `market_summary`,
      `DEFAULT_TOTAL_LINES`, `DEFAULT_TEAM_LINES` — R1–R6, R9.
- [x] T3. `src/cli.py`: subcomando `markets` (parser + handler, patrón `predict`;
      sin cambiar subcomandos existentes) — R7.
- [x] T4. `src/app/tabs/calendario.py`: cuarta sub-pestaña `Mercados` (solo
      partido predecible; cache por (home,away); % 1 decimal) — R8.

## Tests (mapeo R<n> → test)

| Req | Test |
|-----|------|
| R1  | `test_markets.py::test_modulo_puro_sin_streamlit_ni_red` |
| R2  | `test_markets.py::test_over_under_lineas_default_y_suma_1`, `::test_linea_invalida_valueerror` |
| R3  | `test_markets.py::test_btts_suma_1` |
| R4  | `test_markets.py::test_totales_por_equipo` |
| R5  | `test_markets.py::test_market_summary_modelo_real_y_unknown_team` |
| R6  | `test_markets.py::test_oraculo_matriz_3x3_a_mano` |
| R7  | `test_cli_markets.py::test_markets_salida_humana`, `::test_markets_json`, `::test_markets_lines_custom`, `::test_markets_errores_y_exit_codes`, `::test_subcomandos_previos_intactos` |
| R8  | `test_app_markets_ui.py::test_sub_pestana_mercados_presente`, `::test_sub_pestana_ausente_si_no_predecible` |
| R9  | `test_markets.py::test_determinismo` |
| R10 | `test_markets.py::test_import_sin_efectos_y_sin_dependencias_inversas` |

## Cierre

- [x] T5. Suite completa verde (172 previos + nuevos), `bash init.sh` verde.
- [x] T6. Review (Reviewer): trazabilidad R1–R10 ↔ tests; `src/cli.py` y
      `calendario.py` con extensión mínima; resto de módulos intactos.
- [x] T7. Dictamen security-lead (sin red, sin secretos, sin escritura).
- [x] T8. Actualizar `feature_list.json` (4 → done), `progress/current.md`,
      `README.md` (subcomando markets).
