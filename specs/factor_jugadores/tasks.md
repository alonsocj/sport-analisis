# tasks.md — Feature 11: factor_jugadores

Checklist de implementación. Cada R<n> con ≥1 test (el reviewer rechaza si falta).
Secuencia: T0 (ingesta operativa) → T1 → T2 → T3 → T4 → cierre.

## Implementación

- [ ] T0. **Ingesta operativa** (Leader, sin código de test): `ingest-goalscorers`
      trae `goalscorers.csv` CC0 a bronze (sin cuota).
- [ ] T1. `src/ingestion/goalscorers.py`: descarga (transporte inyectable),
      validación de encabezado exacto, bronze + meta con `fetched_at` inyectado — R1.
- [ ] T2. `src/players/__init__.py` + `src/players/normalize.py`: bronze → silver
      de eventos (excluye own goals, mapea equipo a código, descartes con motivo) — R2.
- [ ] T3. `src/players/factor.py`: tabla de cuotas/tasas (decaimiento ξ, anti-fuga),
      anytime-scorer (thinning Poisson), multiplicador por roster (default 1.0),
      artefacto gold determinista — R3–R6.
- [ ] T4. `src/cli.py` (extensión): `ingest-goalscorers`, `scorers`, y extensión de
      `build-features` para el artefacto de jugadores — R7. Subcomandos previos
      intactos (aserción de conjunto exacto).
- [ ] T5. Tests: `tests/test_goalscorers_ingest.py`, `tests/test_player_factor.py`,
      `tests/test_cli_scorers.py` (offline, fixtures) — ver tabla.

## Tests (mapeo R<n> → test)

| Req | Test |
|-----|------|
| R1  | `test_goalscorers_ingest.py::test_descarga_transporte_inyectable_y_meta`, `::test_encabezado_invalido_falla` |
| R2  | `test_player_factor.py::test_normaliza_excluye_own_goals_y_mapea_equipo`, `::test_descarta_malformados_con_motivo` |
| R3  | `test_player_factor.py::test_cuotas_suman_uno_por_equipo`, `::test_anti_fuga_eventos_posteriores_no_cambian` |
| R4  | `test_player_factor.py::test_anytime_scorer_thinning_poisson_oraculo` |
| R5  | `test_player_factor.py::test_multiplicador_roster_y_default_identidad` |
| R6  | `test_player_factor.py::test_artefacto_gold_determinista` |
| R7  | `test_cli_scorers.py::test_scorers_exito_y_topk`, `::test_ingest_goalscorers`, `::test_subcomandos_exactos_intactos`, `::test_exit_codes` |
| R8  | cubierto transversalmente por los tests anteriores (transporte/as_of/fetched_at inyectados, sin red, escritura bajo data/) |

## Cierre

- [ ] T6. Suite completa verde (previos + nuevos), `bash init.sh` verde.
- [ ] T7. Review (Reviewer): trazabilidad R1–R7 ↔ tests; sin red en tests; sin lib
      nueva; multiplicador por defecto = identidad (cero regresión en 1X2/backtest).
- [ ] T8. Dictamen security-lead (si surgiera lib nueva → pasar antes de instalar;
      no se anticipa ninguna).
- [ ] T9. Actualizar `feature_list.json` (11 → done; promover 12 → pending),
      `progress/current.md`, `README.md` (subcomandos `ingest-goalscorers`, `scorers`).
