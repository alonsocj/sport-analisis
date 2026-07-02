# tasks.md — Feature 9: app_streamlit

Checklist de implementación. Cada tarea referencia sus requisitos; cada R<n> tiene
≥1 test concreto (el reviewer rechaza si falta alguno).

## Pre-implementación

- [x] T0. Dictamen de seguridad de `streamlit` emitido y aprobación del usuario
      para instalar (regla STOP). Añadir pin a `requirements.txt` según dictamen e
      instalar en `.venv`.

## Implementación

- [x] T1. `src/app/__init__.py` (docstring, sin imports) — R4, R13.
- [x] T2. `src/app/data.py`: `AppInputError`, `WcMatch`, `AppData`,
      `load_app_data` (validación gold→params→bronze, degradación R3),
      partidos WC2026 jugado/pendiente sin reloj, `pending_default_day`,
      `predict_for`, `match_outcome_eval`, `team_profile` — R1–R7, R9–R12.
- [x] T3. `src/app/figures.py`: `fig_1x2`, `fig_heatmap`, `fig_comparativa`,
      `fig_elo_lines`, `fig_ranking_elo`, `fig_fuerzas` (puros, deterministas) —
      R8, R10, R11, R12.
- [x] T4. `src/app/main.py`: cachés `st.cache_data`, título, `st.tabs` constantes,
      captura de `AppInputError` → `st.error` — R2, R14.
- [x] T5. `src/app/tabs/calendario.py`: tira de días (`st.pills`), tarjetas
      (pendiente/jugado/no-predecible), detalle con sub-pestañas
      (Predicción/Equipos/Historial Elo), disclaimer `as_of_date` — R3, R5–R9.
- [x] T6. `src/app/tabs/selecciones.py`: ranking + selector + ficha — R10.
- [x] T7. `src/app/tabs/modelo.py`: metadatos + aviso no-convergencia + dispersión — R11.
- [x] T8. `.streamlit/config.toml`: telemetría off, localhost, condiciones del
      dictamen — R15.

## Tests (mapeo R<n> → test)

| Req | Test (archivo::nombre orientativo) |
|-----|-------------------------------------|
| R1  | `test_app_data.py::test_rutas_inyectadas_tmp_path` |
| R2  | `test_app_data.py::test_falta_gold_error_accionable`, `::test_params_invalidos_error_accionable`; `test_app_ui.py::test_error_visible_sin_pestanas` |
| R3  | `test_app_data.py::test_sin_bronze_degradacion`; `test_app_ui.py::test_aviso_ingest_public` |
| R4  | `test_app_data.py::test_data_no_importa_streamlit_ni_red` |
| R5  | `test_app_data.py::test_clasificacion_jugado_pendiente_sin_reloj`, `::test_agrupacion_y_orden_por_dia`, `::test_dia_default` |
| R6  | `test_app_data.py::test_prediccion_pendiente_modelo_real`; `test_app_ui.py::test_tarjeta_pendiente_1x2` |
| R7  | `test_app_data.py::test_outcome_eval_acierto_y_fallo`; `test_app_ui.py::test_disclaimer_as_of_date` |
| R8  | `test_app_figures.py::test_fig_1x2_y_heatmap_contrato`; `test_app_ui.py::test_detalle_sub_pestanas` |
| R9  | `test_app_data.py::test_partido_sin_alias_no_predecible`; `test_app_ui.py::test_tarjeta_sin_prediccion_no_aborta` |
| R10 | `test_app_figures.py::test_ranking_orden_y_anfitrionas`; `test_app_ui.py::test_ficha_equipo` |
| R11 | `test_app_figures.py::test_fuerzas_solo_48`; `test_app_ui.py::test_metadatos_y_aviso_convergencia` |
| R12 | `test_app_data.py::test_determinismo_misma_entrada`, `::test_sin_reloj_en_fuente` |
| R13 | `test_app_data.py::test_import_app_sin_efectos` (+ inspección del reviewer) |
| R14 | `test_app_ui.py::test_tres_pestanas_literales` |
| R15 | `test_app_ui.py::test_config_toml_telemetria_off_localhost` |

## Cierre

- [x] T9. Suite completa verde (137 existentes + nuevos), `bash init.sh` verde.
- [x] T10. Review (Reviewer): trazabilidad R1–R15 ↔ tests, sin código de red,
      `src/report/` y `src/cli.py` intactos.
- [x] T11. Dictamen security-lead post-implementación (config, sin secretos).
- [x] T12. Actualizar `feature_list.json` (9 → done), `progress/current.md`,
      `README.md` (cómo lanzar la app).
