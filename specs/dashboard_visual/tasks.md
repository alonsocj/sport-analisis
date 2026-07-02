# tasks.md — Feature 8: dashboard_visual

## Checklist de implementación

- [ ] `src/report/__init__.py` — marca de paquete (docstring, **sin imports**).
- [ ] `src/report/dashboard.py` — constantes (rutas default, títulos de sección,
      `WC_TOURNAMENT`, `AVISO_SIN_BRONZE`, `MSG_SIN_PENDIENTES`), `DashboardInputError`,
      carga/validación de insumos (gold dura, bronze blanda), `select_line_teams`,
      constructores de figuras (ranking, evolución, fuerzas, forma, heatmap, 1X2),
      pendientes WC2026 sin reloj, ensamblado HTML autocontenido (`div_id` estables,
      plotly.js inline una sola vez), `generate_dashboard`, `build_parser`, `main`.
- [ ] `tests/test_dashboard.py` — insumos sintéticos pequeños construidos en `tmp_path`
      (helpers/fixtures locales del archivo): params JSON con el contrato de la
      feature 3 y 4–6 equipos de las 48 (p. ej. ARG, BRA, FRA, JPN, MEX, USA),
      `team_features.csv` y `elo_history.csv` mínimos coherentes (incluida una
      selección con `matches_count=0` y medias nulas), `results.csv` público con
      encabezado verificado, 2 partidos WC2026 pendientes (scores `NA`) y 1 jugado.
      Cero red, cero entrenamientos (`fit_dixon_coles` jamás se invoca), `monkeypatch`
      de `webbrowser.open` para `--open`.
- [ ] Verificar que el HTML generado en tests es parseable (parser HTML de stdlib),
      contiene el bundle plotly.js embebido **una sola vez** y ningún `<script src>`
      externo.
- [ ] **NO tocar `src/cli.py`** ni ningún módulo existente (features 1, 2, 3, 6, 7
      solo en lectura/llamada).
- [ ] `bash init.sh` verde.

## Trazabilidad R<n> → test (obligatoria)

| Req | Descripción                                            | Test                                                                       |
|-----|--------------------------------------------------------|-----------------------------------------------------------------------------|
| R1  | Insumos por rutas parametrizables con defaults         | `tests/test_dashboard.py::test_custom_paths_generate_html`                 |
| R2  | Error accionable si falta gold / params                | `tests/test_dashboard.py::test_missing_gold_raises_actionable_error`       |
|     |                                                        | `tests/test_dashboard.py::test_missing_params_raises_actionable_error`     |
| R3  | Degradación parcial sin bronze público                 | `tests/test_dashboard.py::test_missing_bronze_degrades_without_matches_section` |
| R4  | HTML único autocontenido, plotly embebido 1 vez, sin red | `tests/test_dashboard.py::test_html_self_contained_plotly_embedded_once`  |
| R5  | Cabecera con metadatos del modelo, sin `now()`         | `tests/test_dashboard.py::test_header_shows_model_metadata_not_now`        |
| R6  | Ranking Elo ordenado, anfitrionas destacadas           | `tests/test_dashboard.py::test_elo_ranking_sorted_hosts_highlighted`       |
| R7  | Evolución Elo: selección default determinista          | `tests/test_dashboard.py::test_elo_history_default_team_selection`         |
|     | Evolución Elo: selección inyectada                     | `tests/test_dashboard.py::test_elo_history_custom_team_selection`          |
| R8  | Dispersión attack/defense con etiquetas, sin slugs     | `tests/test_dashboard.py::test_attack_defense_scatter_labels`              |
| R9  | Forma reciente; nulos excluidos sin fallar             | `tests/test_dashboard.py::test_recent_form_excludes_teams_without_matches` |
| R10 | Pendientes WC2026 sin reloj: heatmap + 1X2 reales      | `tests/test_dashboard.py::test_upcoming_matches_heatmap_and_1x2`           |
|     | `limit` parametrizable                                 | `tests/test_dashboard.py::test_upcoming_matches_limit`                     |
|     | Bronze presente y 0 pendientes → mensaje, sin fallo    | `tests/test_dashboard.py::test_no_pending_matches_message`                 |
| R11 | Partido no predecible se omite con aviso               | `tests/test_dashboard.py::test_unpredictable_match_skipped_with_notice`    |
| R12 | CLI: éxito imprime `✅` + ruta, exit 0                  | `tests/test_dashboard.py::test_cli_writes_html_and_prints_check`           |
|     | CLI: `--open` usa `webbrowser`; default no abre        | `tests/test_dashboard.py::test_cli_open_flag_uses_webbrowser`              |
|     | CLI: insumo crítico ausente → stderr `error:` + exit 1 | `tests/test_dashboard.py::test_cli_missing_input_exit_1`                   |
| R13 | Misma entrada → mismo contenido verificable            | `tests/test_dashboard.py::test_same_input_same_content`                    |
| R14 | Paquete aislado; import sin `src.cli` ni efectos       | `tests/test_dashboard.py::test_import_does_not_pull_cli_or_side_effects`   |

Notas de verificación (contenido, no bytes — R13):

- Nº de figuras = ocurrencias de `Plotly.newPlot` = `4 + 2·n_partidos_renderizados`;
  bundle = literal `plotly.js v` exactamente 1 vez (R4, R10).
- Probabilidades 1X2 como literales `"<p>.<d>%"` presentes en el HTML, consistentes
  con `predict_match` real sobre los params sintéticos (R10).
- `div_id` estables (`fig-ranking-elo`, …, `fig-partido-1-1x2`) como anclas de
  aserción por sección (R6–R10, R13).
- R14: limpiar `sys.modules` (`src.cli`, `src.report.dashboard`) e importar en
  fresco; asertar `"src.cli" not in sys.modules` y que el import no crea archivos ni
  invoca `webbrowser`.

## Definición de "done"

- Todos los R<n> con test verde (tabla completa); `bash init.sh` verde.
- Tests 100 % offline y deterministas: cero red, cero reloj en contenido, cero
  entrenamientos; insumos sintéticos en `tmp_path`.
- `src/cli.py` y todos los módulos de otras features intactos (`git status` limpio
  fuera de `src/report/`, `tests/test_dashboard.py` y `specs/dashboard_visual/`).
- Ninguna dependencia nueva más allá de `plotly>=5` (ya aprobada e instalada);
  ninguna API key ni secreto en el repo.
- Criterios de `CHECKPOINTS.md` § 8 (dashboard_visual) satisfechos.
