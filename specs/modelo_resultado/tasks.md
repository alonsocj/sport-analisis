# tasks.md — Feature 3: modelo_resultado

## Checklist de implementación

- [ ] `src/models/dixon_coles.py` — módulo único con:
  - [ ] Carga de silver (`pandas.read_csv`) validando columnas requeridas;
        `SilverNotFoundError` si falta archivo/columna.
  - [ ] Recorte `from_date <= date < as_of_date` (estricto), validación
        `YYYY-MM-DD` (`ValueError`), error claro con 0 partidos.
  - [ ] `decay_weights(dates, as_of_date, xi)` — `w = exp(−xi·días/365.25)`.
  - [ ] `match_rates(...)` — fórmula única de lambdas (gamma solo en home, vía `h`).
  - [ ] `tau_low_scores(...)` — corrección DC en (0,0), (0,1), (1,0), (1,1).
  - [ ] Objetivo NLL ponderada **vectorizada** (fancy indexing + máscaras numpy;
        SIN bucles Python por partido — el reviewer lo verifica por inspección),
        ridge `reg_lambda` sobre `att`/`def`, clip `tau ≥ 1e−10`.
  - [ ] Reparametrización suma-cero (`att_n = −Σ att_free`, ídem `def`), equipos en
        orden alfabético, init determinista, L-BFGS-B con `rho ∈ [−0.9, 0.9]`,
        opciones fijas (`maxiter=max_iter`, `maxfun=max_iter·(dim+1)`,
        `ftol=1e−12`, `gtol=1e−8`).
  - [ ] `convergencia` registrada; `success=False` → warning sin abortar
        (`max_iter` inyectable vía `DCConfig` para forzarlo en tests).
  - [ ] `min_matches`/`low_data_teams` (conteo sin ponderar, orden alfabético).
  - [ ] `save_params`/`load_params` — JSON con claves del contrato
        (`sort_keys=True, indent=2`); `NotFittedError` si falta archivo o claves.
  - [ ] `score_matrix(lambda_home, lambda_away, rho, max_goals)` — outer de pmfs
        Poisson, τ en celdas bajas, clip ≥ 0, renormalización (expuesta para
        feature 4).
  - [ ] `predict_match(params, home, away, max_goals=10, top_k=5)` — `h=1` solo si
        `is_host(home_code)`; 1X2 + lambdas + top-k (desempate determinista);
        `UnknownTeamError` para códigos fuera de `attack`/`defense`.
  - [ ] CLI opcional `python -m src.models.dixon_coles --as-of-date ...` (sin red).
- [ ] `tests/test_dixon_coles_fit.py` — R1–R10 (tabla abajo). Silver sintético en
      `tmp_path` con el esquema del contrato de la feature 2; semillas fijas.
- [ ] `tests/test_dixon_coles_predict.py` — R11–R18 (tabla abajo).
- [ ] Generador sintético determinista compartido (helper/fixture en los tests):
      parámetros verdaderos fijos, marcadores muestreados de `score_matrix` con
      `np.random.default_rng(semilla fija)`, calendario round-robin (~1900+ partidos
      para R9). Cero red, cero `now()` implícito.
- [ ] Docstrings en español citando `R<n>`; sin `API_FOOTBALL_KEY` ni secretos
      (módulo 100 % offline).
- [ ] NO se modifican módulos ni tests de features anteriores
      (`src/ingestion/*`, `src/features/*`, `tests/test_bronze|client|config|ingest|teams*`).
- [ ] `bash init.sh` verde.

## Trazabilidad R<n> → test (obligatoria)

| Req | Descripción                                              | Test                                                                              |
|-----|----------------------------------------------------------|-----------------------------------------------------------------------------------|
| R1  | Carga silver con columnas del contrato; falta archivo/columna → error claro | `tests/test_dixon_coles_fit.py::test_carga_silver_contrato`                       |
|     |                                                          | `tests/test_dixon_coles_fit.py::test_silver_inexistente_o_sin_columnas_error`     |
| R2  | Recorte `[from_date, as_of_date)` estricto; fechas inválidas → `ValueError`; recorte vacío → error | `tests/test_dixon_coles_fit.py::test_recorte_temporal_estricto`                   |
|     |                                                          | `tests/test_dixon_coles_fit.py::test_fecha_invalida_error`                        |
|     |                                                          | `tests/test_dixon_coles_fit.py::test_recorte_vacio_error`                         |
| R3  | Pesos `exp(−xi·días/365.25)` decrecientes; `xi=0` → 1    | `tests/test_dixon_coles_fit.py::test_pesos_decrecientes_con_antiguedad`           |
|     |                                                          | `tests/test_dixon_coles_fit.py::test_xi_cero_pesos_unitarios`                     |
| R4  | Lambdas según especificación; gamma solo en home y solo con `h=1` (neutral en entrenamiento) | `tests/test_dixon_coles_fit.py::test_match_rates_especificacion`                  |
|     |                                                          | `tests/test_dixon_coles_fit.py::test_gamma_solo_si_no_neutral_entrenamiento`      |
| R5  | τ exacta en las 4 celdas bajas; 1 en el resto            | `tests/test_dixon_coles_fit.py::test_tau_definicion_celdas_bajas`                 |
| R6  | NLL vectorizada = referencia por bucle; convergencia registrada; no-convergencia → warning sin abortar | `tests/test_dixon_coles_fit.py::test_nll_coincide_con_referencia_bucle`           |
|     |                                                          | `tests/test_dixon_coles_fit.py::test_fit_reporta_convergencia`                    |
|     |                                                          | `tests/test_dixon_coles_fit.py::test_no_convergencia_warning_sin_abortar`         |
|     | `maxfun = max_iter·(dim+1)`: `maxiter` es el límite efectivo con gradiente numérico | `tests/test_dixon_coles_fit.py::test_maxfun_escala_con_dimension`                 |
| R7  | `sum(att)=0` y `sum(def)=0` tras el ajuste (1e−8)        | `tests/test_dixon_coles_fit.py::test_identificabilidad_sum_att_def_cero`          |
| R8  | Equipo con `< min_matches` incluido, en `low_data_teams`; mayor `reg_lambda` → menor magnitud | `tests/test_dixon_coles_fit.py::test_equipo_pocos_partidos_listado_low_data`      |
|     |                                                          | `tests/test_dixon_coles_fit.py::test_shrinkage_mayor_reg_menor_magnitud`          |
| R9  | Recuperación de parámetros en sintéticos del propio modelo (semilla fija, tolerancias de design) | `tests/test_dixon_coles_fit.py::test_recuperacion_parametros_datos_sinteticos`    |
| R10 | Reentrenamiento con la misma entrada → parámetros idénticos (≤1e−12) | `tests/test_dixon_coles_fit.py::test_reentrenamiento_determinista`                |
| R11 | JSON con claves del contrato; round-trip guardar→cargar idéntico; misma predicción sin reentrenar | `tests/test_dixon_coles_predict.py::test_json_contiene_claves_contrato`           |
|     |                                                          | `tests/test_dixon_coles_predict.py::test_round_trip_json_parametros`              |
|     |                                                          | `tests/test_dixon_coles_predict.py::test_prediccion_identica_tras_cargar`         |
| R12 | Params inexistentes o JSON sin claves → `NotFittedError` | `tests/test_dixon_coles_predict.py::test_params_inexistentes_not_fitted_error`    |
|     |                                                          | `tests/test_dixon_coles_predict.py::test_json_invalido_not_fitted_error`          |
| R13 | `h=1` solo con local anfitriona (MEX/USA/CAN); resto neutral; gamma nunca en away | `tests/test_dixon_coles_predict.py::test_h_uno_solo_anfitriona`                   |
| R14 | Matriz `(max_goals+1)²` suma 1 (1e−9); `max_goals` configurable; expuesta en la salida | `tests/test_dixon_coles_predict.py::test_matriz_conjunta_suma_uno`                |
|     |                                                          | `tests/test_dixon_coles_predict.py::test_max_goals_configurable`                  |
| R15 | Con `rho≠0` solo cambian (0,0),(0,1),(1,0),(1,1) pre-normalización; la matriz sigue sumando 1 | `tests/test_dixon_coles_predict.py::test_tau_solo_modifica_marcadores_bajos`      |
| R16 | 1X2 desde la matriz, suman 1 (1e−9); lambdas expuestas   | `tests/test_dixon_coles_predict.py::test_1x2_suma_uno_y_lambdas_expuestas`        |
| R17 | Top-k descendente con desempate determinista; `k` configurable | `tests/test_dixon_coles_predict.py::test_top_k_descendente_desempate_determinista`|
| R18 | Código desconocido → `UnknownTeamError` con el código    | `tests/test_dixon_coles_predict.py::test_equipo_desconocido_error`                |

## Definición de "done"

- Todos los `R<n>` con test verde (tabla completa); el reviewer rechaza si falta alguno.
- Tests 100 % offline y deterministas: silver sintético en `tmp_path`, semillas fijas
  (`np.random.default_rng`), cero red real, cero `API_FOOTBALL_KEY`, cero `now()`.
- Objetivo de la MLE vectorizado (sin bucles Python por partido) — verificado por el
  reviewer por inspección, además del test de equivalencia numérica (R6).
- `data/gold/dixon_coles_params.json` cumple el contrato de claves de `design.md`.
- Archivos de otras features intactos (módulos y tests).
- Criterios de `CHECKPOINTS.md` § 3 `modelo_resultado` satisfechos: Poisson bivariado
  Dixon-Coles con decaimiento temporal; fuerzas ofensiva/defensiva por selección;
  localía solo anfitrionas MEX/USA/CAN; salidas 1X2 + distribución de marcadores.
