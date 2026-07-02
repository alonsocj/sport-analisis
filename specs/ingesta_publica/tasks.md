# tasks.md — Feature 7: ingesta_publica

## Checklist de implementación

- [ ] `src/ingestion/public_data.py` — módulo único de la feature: transporte inyectable
      (`url → texto CSV`, descarga real con `requests` solo por invocación explícita),
      `EXPECTED_HEADER` + validación de esquema, escritura bronze (CSV crudo byte a byte +
      sidecar `results.meta.json`), parseo tolerante con `IngestReport` de descartes,
      `DATASET_ALIASES` + `to_fifa_code`, filtro de las 48 + `from_date`, orquestación
      `ingest_public_results` y CLI (`python -m src.ingestion.public_data`).
      Docstrings en español citando R<n>.
- [ ] Verificar los alias de las 48 selecciones contra los nombres reales del dataset
      (divergencias conocidas: `United States`→USA, `South Korea`→KOR, `Ivory Coast`→CIV);
      la invariante "el mapa cubre los 48 códigos de `teams.py`" queda testeada (R7).
- [ ] NO modificar archivos existentes de otras features: `config.py`, `client.py`,
      `bronze.py`, `ingest.py`, `teams.py` se usan solo en lectura.
- [ ] `tests/fixtures/public_results_sample.csv` — muestra ~20 filas representativas:
      encabezado real de la fuente; partidos de anfitrionas (USA/MEX/CAN); `neutral`
      TRUE y FALSE; partidos de selecciones fuera de las 48; filas corruptas para R5
      (goles no numéricos y fecha inválida).
- [ ] `tests/test_public_data.py` — un test por R<n> (ver tabla). Todo offline:
      transporte falso que devuelve el contenido del fixture; cero red real; `fetched_at`
      inyectado fijo para asserts deterministas.
- [ ] `bash init.sh` verde.

## Trazabilidad R<n> → test (obligatoria)

| Req | Descripción                                            | Test                                                                          |
|-----|--------------------------------------------------------|-------------------------------------------------------------------------------|
| R1  | Fuente pública sin credenciales (sin `API_FOOTBALL_KEY`)| `tests/test_public_data.py::test_ingest_works_without_api_football_key`       |
| R2  | Transporte inyectable; cero red real                   | `tests/test_public_data.py::test_injected_transport_is_used`                  |
|     | Importar el módulo no descarga                         | `tests/test_public_data.py::test_import_module_triggers_no_download`          |
| R3  | Encabezado inválido → error claro y nada persiste      | `tests/test_public_data.py::test_header_mismatch_raises_and_persists_nothing` |
| R4  | Bronze: CSV crudo byte a byte + sidecar meta completo  | `tests/test_public_data.py::test_bronze_csv_verbatim_and_meta_sidecar`        |
| R5  | Filas corruptas descartadas y contadas por motivo      | `tests/test_public_data.py::test_corrupt_rows_discarded_and_counted`          |
| R6  | Tipos normalizados (date ISO, int, bool, str)          | `tests/test_public_data.py::test_valid_rows_normalized_types`                 |
| R7  | Alias map cubre los 48 códigos FIFA de `teams.py`      | `tests/test_public_data.py::test_alias_map_covers_48_codes`                   |
|     | Alias divergentes conocidos resuelven bien             | `tests/test_public_data.py::test_to_fifa_code_known_aliases`                  |
| R8  | Filtro: al menos una de las 48 participa               | `tests/test_public_data.py::test_filter_keeps_matches_with_world_cup_team`    |
| R9  | `from_date` excluye partidos estrictamente anteriores  | `tests/test_public_data.py::test_from_date_cuts_strictly_older`               |
|     | Sin `from_date` conserva la historia completa          | `tests/test_public_data.py::test_no_from_date_keeps_full_history`             |

## Definición de "done"

- Todos los R<n> con test verde (tabla completa).
- Ninguna llamada de red real en los tests (transporte falso + fixture CSV).
- `API_FOOTBALL_KEY` ni requerida ni escrita; cero secretos en el repo.
- Archivos de otras features sin modificar.
- La descarga real solo es alcanzable vía el CLI explícito (regla STOP de `CLAUDE.md`:
  ejecutar la descarga real requiere aprobación previa del usuario).
- Criterios de `CHECKPOINTS.md` § 7 `ingesta_publica` satisfechos.
