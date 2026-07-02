# tasks.md — Feature 6: cli_prediccion

## Checklist de implementación

- [ ] `src/cli.py` — reemplazar el stub: `main(argv=None) -> int`, `build_parser()`
      con los 5 subparsers (`required=True`) y `set_defaults(func=...)`;
      `if __name__ == "__main__": raise SystemExit(main())`.
- [ ] `cmd_ingest_public` — delega en `ingest_public_results` (con `fetched_at`
      UTC como metadato), relee bronze (`bronze_public_paths` + `parse_results` +
      `filter_world_cup_matches(from_date)`) e imprime el reporte con `✅`.
- [ ] `cmd_build_features` — `--as-of-date` requerido; delega en `build_all` e
      imprime `n_matches_silver`, `n_teams_gold` y las 3 rutas.
- [ ] `cmd_train` — `DCConfig(**kwargs)` solo con flags presentes; `fit_dixon_coles`
      + `save_params`; resumen con `✅`; aviso `⚠️` en stderr si no converge (exit 0).
- [ ] `cmd_predict` — validación de códigos (normalizar → formato → 48 → distintos,
      sugerencias `difflib`), `load_params` (sin reentrenar), `predict_match`,
      contexto gold opcional (`--features`), salida humana y `--json` (documento
      único, sin `✅`).
- [ ] `cmd_schedule` — lee CSV crudo (`--results-csv`), filtra
      `tournament == "FIFA World Cup"` + scores no numéricos, orden
      `(date, home_team, away_team)`, `--limit` (default 10); bronze ausente →
      error accionable exit 1.
- [ ] Traducción de errores R12: tabla explícita por subcomando (sin
      `except Exception`); helper `_error()` → stderr `error: ...` + return 1.
- [ ] `tests/test_cli.py` — todos los tests de la tabla. 100 % offline y
      deterministas: `main(argv)` en proceso; `monkeypatch` de las funciones
      delegadas referenciadas en `src.cli` (`ingest_public_results`,
      `bronze_public_paths`, `build_all`, `fit_dixon_coles`, `save_params`);
      params **JSON sintético** en `tmp_path` (contrato de la feature 3) para
      `predict` — CERO red, CERO entrenamientos reales, CERO `now()` en aserciones.
- [ ] Fixtures/helpers de test: params JSON sintético (todas las claves del contrato
      de la feature 3, 4–6 equipos de las 48), CSV de resultados con filas WC2026
      pendientes (`NA`) en `tmp_path` (puede reutilizar
      `tests/fixtures/public_results_sample.csv`), `team_features.csv` mínimo,
      `IngestReport` sintético, centinela anti-reentrenamiento sobre
      `fit_dixon_coles`.
- [ ] Sin dependencias nuevas; sin tocar módulos de las features 1/2/3/7.
- [ ] `bash init.sh` verde.

## Trazabilidad R<n> → test (obligatoria)

| Req | Descripción                                            | Test                                                                      |
|-----|--------------------------------------------------------|----------------------------------------------------------------------------|
| R1  | `main(argv)`, 5 subcomandos, función por subcomando    | `tests/test_cli.py::test_main_sin_subcomando_exit_no_cero`                 |
|     | sin/desconocido subcomando → uso + exit ≠ 0            | `tests/test_cli.py::test_subcomando_desconocido_exit_no_cero`              |
|     |                                                        | `tests/test_cli.py::test_cinco_subcomandos_con_funcion_propia`             |
| R2  | `ingest-public` delegado + reporte `✅`                | `tests/test_cli.py::test_ingest_public_delegada_e_imprime_reporte`         |
|     | `--from-date` aplicado a la vista de consumo           | `tests/test_cli.py::test_ingest_public_from_date_filtra_vista`             |
| R3  | `build-features` delega en `build_all` + resumen       | `tests/test_cli.py::test_build_features_llama_build_all_e_imprime_resumen` |
|     | `--as-of-date` obligatorio (sin reloj implícito)       | `tests/test_cli.py::test_build_features_sin_as_of_date_falla`              |
| R4  | `train` ajusta, persiste e imprime resumen             | `tests/test_cli.py::test_train_ajusta_persiste_e_imprime_resumen`          |
|     | `from_date`/`xi` solo si se pasan (defaults `DCConfig`)| `tests/test_cli.py::test_train_pasa_from_date_y_xi_solo_si_se_dan`         |
|     | no convergencia → aviso visible, exit 0                | `tests/test_cli.py::test_train_no_convergencia_avisa_sin_cambiar_exit`     |
| R5  | `predict` caso feliz: carga params, NO reentrena       | `tests/test_cli.py::test_predict_caso_feliz_sin_reentrenar`                |
| R6  | normalización a MAYÚSCULAS                             | `tests/test_cli.py::test_predict_normaliza_a_mayusculas`                   |
|     | código inválido/fuera de 48 → error + sugerencia       | `tests/test_cli.py::test_predict_codigo_invalido_error_y_sugerencia`       |
|     | `HOME == AWAY` → error de uso                          | `tests/test_cli.py::test_predict_codigos_iguales_error_de_uso`             |
| R7  | 48 sin params → `UnknownTeamError` traducido           | `tests/test_cli.py::test_predict_equipo_sin_parametros_mensaje_accionable` |
| R8  | contexto gold mostrado si existe (`n/d` para nulls)    | `tests/test_cli.py::test_predict_contexto_gold_presente`                   |
|     | sin gold → omite contexto sin fallar                   | `tests/test_cli.py::test_predict_sin_gold_omite_contexto_sin_fallar`       |
| R9  | `--json`: documento único parseable, claves, probs Σ=1 | `tests/test_cli.py::test_predict_json_documento_unico_y_claves`            |
|     | `--json` sin gold → `context: null`                    | `tests/test_cli.py::test_predict_json_context_null_sin_gold`               |
| R10 | `schedule`: pendientes WC, orden y `--limit`           | `tests/test_cli.py::test_schedule_lista_pendientes_orden_y_limite`         |
|     | sin pendientes → mensaje claro, exit 0                 | `tests/test_cli.py::test_schedule_sin_pendientes_mensaje_y_exit_0`         |
| R11 | `schedule` sin bronze → error accionable, exit ≠ 0     | `tests/test_cli.py::test_schedule_sin_bronze_error_accionable`             |
| R12 | excepciones de capas inferiores → mensaje accionable   | `tests/test_cli.py::test_errores_capas_inferiores_traducidos`              |
|     | excepción no listada (bug) NO se oculta                | `tests/test_cli.py::test_excepcion_no_listada_se_propaga`                  |
| R13 | import + subcomandos offline sin `API_FOOTBALL_KEY`    | `tests/test_cli.py::test_offline_sin_api_key_ni_red`                       |
|     | `predict` reporta `as_of_date` de los params, no hoy   | `tests/test_cli.py::test_predict_as_of_date_viene_de_params`               |

Notas de los tests (vinculantes para el implementer):

- `test_errores_capas_inferiores_traducidos` es **parametrizado** y cubre como mínimo:
  `SilverInputError` (build-features → sugiere `ingest-public`), `ValueError` de fecha
  (build-features/train → formato `YYYY-MM-DD`), `SilverNotFoundError` (train →
  sugiere `build-features`), `NotFittedError` (predict → sugiere `train`),
  `PublicDownloadError` y `PublicSchemaError` (ingest-public). Cada caso aserta:
  exit 1, mensaje en stderr con el comando previo/acción, sin traceback.
- `test_predict_caso_feliz_sin_reentrenar` monkeypatchea `fit_dixon_coles` con un
  centinela que falla si se invoca, y usa `load_params`/`predict_match` **reales**
  sobre el JSON sintético de `tmp_path` (rápido, sin optimización).
- `test_offline_sin_api_key_ni_red` ejecuta con `monkeypatch.delenv("API_FOOTBALL_KEY",
  raising=False)` los subcomandos offline (`build-features`, `train`, `predict`,
  `schedule`) y verifica que ninguno falla por configuración/entorno.
- Las salidas se capturan con `capsys`; los tests de formato humano asertan
  **contenido** (códigos, porcentajes, lambdas, marcadores), no maquetación exacta;
  el de `--json` hace `json.loads(stdout)` completo.

## Definición de "done"

- Todos los `R<n>` (R1–R13) con test verde según la tabla (el reviewer rechaza si
  falta alguno).
- `bash init.sh` verde; cero red real, cero entrenamientos reales, cero `now()` en
  lógica predictiva (única excepción: metadato `fetched_at`, ver `design.md`).
- Ninguna key literal en el repo; `src/cli.py` no importa `config`/`client`/`ingest`.
- Sin features fuera de alcance: mercados (feature 4) NO aparecen en el CLI.
- Criterios de `CHECKPOINTS.md` § 6 satisfechos (predicción de un partido del
  Mundial 2026; mercados diferidos por el no-objetivo explícito del Leader,
  ver `requirements.md`).
