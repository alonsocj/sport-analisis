# tasks.md — Feature 2: feature_store

## Checklist de implementación

- [ ] `src/features/silver.py` — extracción API-Football (FT, fecha UTC, goles, torneo),
      adjunto de statistics (posesión `"55%"` → float), carga del CSV público, resolución
      de códigos FIFA (alias de `public_data.py` si existe + fallback propio + slug
      determinista fuera de 48), `match_id` (`hashlib`, 12 hex), dedupe
      `(date, home_code, away_code)` con prioridad `api_football`, esquema silver exacto.
- [ ] `src/features/rolling.py` — vista larga por equipo, medias de hasta 15
      observaciones no nulas por métrica con `date < as_of_date` estricto,
      `matches_count`, nulls sin fallar.
- [ ] `src/features/elo.py` — `EloParams` (initial, home_advantage, `k_rules` ordenadas,
      default_k), G por margen, We con +100 solo si `neutral=False`, actualización
      simétrica, orden `(date, match_id)`, historial por equipo-partido, rating vigente
      a `as_of_date`.
- [ ] `src/features/build.py` — `build_all(as_of_date, ...)` determinista: escribe
      `data/silver/matches.csv`, `data/gold/elo_history.csv`,
      `data/gold/team_features.csv` (48 filas); errores claros (sin fuentes /
      `as_of_date` inválida); CLI opcional sin red.
- [ ] `tests/fixtures/feature_store/` — fixtures nuevas, pequeñas y deterministas:
      - [ ] `fixtures/last=15_team=10.json` — envoltorio bronze con fixtures FT
            (con `fixture.date` y `league.name`) y ≥1 no-FT (descartable).
      - [ ] `fixtures_statistics/fixture=<id>.json` — payload crudo de statistics con
            posesión `"55%"` y tarjetas amarillas/rojas.
      - [ ] `public_results/results.csv` — muestra con: un duplicado del partido API
            (dedupe), equipos fuera de las 48, `neutral` TRUE y FALSE, varios torneos
            (Mundial, eliminatoria, amistoso) para K.
- [ ] `tests/test_silver.py`, `tests/test_rolling.py`, `tests/test_elo.py`,
      `tests/test_gold_build.py` — un test por R<n> (tabla abajo). Todo offline
      (`tmp_path` + fixtures); cero red real. NO se modifican los tests existentes de
      otras features (`test_bronze/test_client/test_config/test_ingest/test_teams`).
- [ ] Docstrings en español citando `R<n>`; sin `API_FOOTBALL_KEY` ni secretos.
- [ ] `bash init.sh` verde.

## Trazabilidad R<n> → test (obligatoria)

| Req | Descripción                                        | Test                                                                      |
|-----|----------------------------------------------------|---------------------------------------------------------------------------|
| R1  | Extrae fixtures FT (fecha/equipos/goles/torneo); descarta no finalizados | `tests/test_silver.py::test_extrae_fixtures_ft_y_descarta_no_finalizados` |
| R2  | Adjunta stats; posesión `"55%"` → float; sin stats → nulls sin fallar | `tests/test_silver.py::test_adjunta_stats_y_posesion_float`               |
|     |                                                    | `tests/test_silver.py::test_sin_statistics_columnas_nulas`                |
| R3  | CSV público → filas silver `source='public_csv'` con stats nulas | `tests/test_silver.py::test_carga_csv_publico_stats_nulas`                |
|     | Filas con goles no numéricos o fecha inválida → descarte tolerante sin fallar | `tests/test_silver.py::test_filas_publicas_corruptas_descartadas_sin_fallar` |
| R4  | Códigos FIFA vía teams+alias; fuera de 48 → slug determinista, partido conservado | `tests/test_silver.py::test_codigos_fifa_y_alias`                         |
|     |                                                    | `tests/test_silver.py::test_fallback_slug_determinista_conserva_partido`  |
| R5  | `match_id` estable entre ejecuciones               | `tests/test_silver.py::test_match_id_estable`                             |
| R6  | Dedupe `(date, home_code, away_code)` prioriza api_football; neutral/tournament del público | `tests/test_silver.py::test_dedupe_prioriza_api_football`                 |
| R7  | `matches.csv` con esquema/orden exactos; una fuente basta; ninguna → error | `tests/test_silver.py::test_matches_csv_esquema_contrato`                 |
|     |                                                    | `tests/test_silver.py::test_continua_con_una_sola_fuente`                 |
|     |                                                    | `tests/test_silver.py::test_sin_fuentes_error_claro`                      |
| R8  | Media móvil de hasta 15 obs. no nulas por equipo y métrica | `tests/test_rolling.py::test_media_movil_15_por_metrica`                  |
| R9  | Anti-leakage: excluye `date >= as_of_date` (incluido el partido actual) | `tests/test_rolling.py::test_excluye_partido_actual_y_futuros`            |
| R10 | <15 partidos → usa disponibles y reporta `matches_count`; 0 → nulls sin fallar | `tests/test_rolling.py::test_ventana_corta_matches_count`                 |
|     |                                                    | `tests/test_rolling.py::test_cero_partidos_features_nulas`                |
| R11 | Solo fuente pública → stats null pero `gf_ma15`/`ga_ma15` calculadas | `tests/test_rolling.py::test_stats_nulas_con_solo_fuente_publica`         |
| R12 | Rating inicial 1500 (parametrizable)               | `tests/test_elo.py::test_rating_inicial_1500`                             |
| R13 | Actualización tras victoria / empate / derrota     | `tests/test_elo.py::test_actualizacion_victoria_empate_derrota`           |
| R14 | K por torneo (mapa configurable; precedencia eliminatoria vs Mundial) | `tests/test_elo.py::test_k_por_torneo_configurable`                       |
| R15 | Multiplicador de margen G (≤1, ==2, ≥3)            | `tests/test_elo.py::test_multiplicador_margen_g`                          |
| R16 | +100 de localía solo si `neutral=False`            | `tests/test_elo.py::test_ventaja_localia_solo_no_neutral`                 |
| R17 | Simetría: suma de cambios = 0                       | `tests/test_elo.py::test_simetria_suma_cambios_cero`                      |
| R18 | Orden cronológico con desempate determinista; re-ejecución idéntica | `tests/test_elo.py::test_orden_cronologico_determinista`                  |
| R19 | Elo global (incluye equipos fuera de 48) + `elo_history.csv` con su esquema | `tests/test_elo.py::test_elo_global_incluye_fuera_de_48`                  |
|     |                                                    | `tests/test_gold_build.py::test_elo_history_csv_esquema_contrato`         |
| R20 | `team_features.csv`: 48 filas exactas, esquema y `elo` vigente | `tests/test_gold_build.py::test_team_features_48_filas_esquema`           |
| R21 | Orquestación determinista con `as_of_date` inyectada; escribe los 3 CSVs | `tests/test_gold_build.py::test_build_all_determinista_tres_csv`          |

## Definición de "done"

- Todos los R<n> con test verde (tabla completa); reviewer rechaza si falta alguno.
- Tests 100% offline y deterministas (fixtures en `tests/fixtures/feature_store/`,
  `tmp_path`; cero red real, cero `now()` implícito).
- Ningún secreto ni `API_FOOTBALL_KEY` literal en el repo (esta feature ni la lee).
- Archivos de tests de otras features intactos.
- Salidas solo en CSV con los esquemas exactos del contrato (`design.md`).
- Criterios de `CHECKPOINTS.md` § 2 feature_store satisfechos.
