# tasks.md — Feature 1: ingesta_datos

## Checklist de implementación

- [ ] `src/ingestion/config.py` — `Settings` (pydantic-settings), valida `API_FOOTBALL_KEY`.
- [ ] `src/ingestion/teams.py` — 48 selecciones, anfitrionas marcadas; helpers.
- [ ] `src/ingestion/client.py` — cliente HTTP: caché + backoff 429 + errores (transport/sleep inyectables).
- [ ] `src/ingestion/bronze.py` — escritura/lectura bronze con `param_key` determinista.
- [ ] `src/ingestion/ingest.py` — orquesta últimos 15 + stats + odds → bronze; resumen ok/errores.
- [ ] `tests/fixtures/*.json` — respuestas mock de API-Football.
- [ ] `tests/` — un test por R<n> (ver tabla). Todo offline.
- [ ] `bash init.sh` verde.

## Trazabilidad R<n> → test (obligatoria)

| Req | Descripción                                  | Test                                                        |
|-----|----------------------------------------------|-------------------------------------------------------------|
| R1  | API key desde env; falla si falta            | `tests/test_config.py::test_api_key_required`               |
|     |                                              | `tests/test_config.py::test_api_key_loaded_from_env`        |
| R2  | Últimos 15 partidos finalizados              | `tests/test_ingest.py::test_fetch_last_15_fixtures`         |
| R3  | Estadísticas por partido normalizadas        | `tests/test_ingest.py::test_fetch_fixture_statistics`       |
| R4  | Cuotas (y sin cuotas no falla)               | `tests/test_ingest.py::test_fetch_odds`                     |
|     |                                              | `tests/test_ingest.py::test_missing_odds_does_not_fail`     |
| R5  | Persistencia en bronze (particionado)        | `tests/test_bronze.py::test_write_bronze_partitioned`       |
| R6  | Caché: no repite llamada                      | `tests/test_client.py::test_cache_hit_skips_http`           |
| R7  | Backoff ante 429; aborta tras reintentos     | `tests/test_client.py::test_retry_on_429_then_success`      |
|     |                                              | `tests/test_client.py::test_429_exhausts_retries_raises`    |
| R8  | 48 selecciones, anfitrionas marcadas         | `tests/test_teams.py::test_48_teams_hosts_marked`           |
| R9  | Errores no abortan el lote                    | `tests/test_ingest.py::test_error_in_one_team_continues`    |

## Definición de "done"

- Todos los R<n> con test verde (tabla completa).
- Ninguna llamada real a la API en los tests (mocks/fixtures).
- Ninguna API key literal en el repo.
- Criterios de `CHECKPOINTS.md` § ingesta_datos satisfechos.
