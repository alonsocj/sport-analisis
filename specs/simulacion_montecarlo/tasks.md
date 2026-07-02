# tasks.md — Feature 13: simulacion_montecarlo

Checklist de implementación. Cada R<n> con ≥1 test (el reviewer rechaza si falta).
Secuencia: T1 → T2 → T3 → T4 → T5 → cierre. Usa el mejor modelo (v2 feature 12 si
existe, si no v1); factor jugadores (feature 11) opcional.

## Implementación

- [ ] T1. `src/simulation/__init__.py` + `src/simulation/bracket.py`: derivación de
      grupos desde fixtures (grafo, validación 12×4), mapeo del bracket — R1, R5.
- [ ] T2. `src/simulation/standings.py`: tabla de grupo, desempates deterministas,
      top-2 + 8 mejores terceros — R4.
- [ ] T3. `src/simulation/montecarlo.py`: muestreo de marcadores (RNG con seed
      inyectada), partidos jugados fijos + pendientes muestreados, bucle de N sims,
      agregación + error MC — R2, R3, R6.
- [ ] T4. `src/simulation/report.py`: summary.json (sort_keys) + advancement.csv
      deterministas, solo bajo data/ — R7.
- [ ] T5. `src/cli.py` (extensión): subcomando `simulate` (n, seed, as-of,
      model-version, roster); subcomandos previos intactos — R8, R9.
- [ ] T6. Tests: `tests/test_simulacion.py`, `tests/test_cli_simulate.py`
      (offline, fixtures, seed fija) — ver tabla.

## Tests (mapeo R<n> → test)

| Req | Test |
|-----|------|
| R1  | `test_simulacion.py::test_deriva_12_grupos_de_4`, `::test_estructura_invalida_falla` |
| R2  | `test_simulacion.py::test_partidos_jugados_fijos_pendientes_muestreados` |
| R3  | `test_simulacion.py::test_determinismo_misma_seed` |
| R4  | `test_simulacion.py::test_standings_desempates_y_mejores_terceros` |
| R5  | `test_simulacion.py::test_bracket_r32_a_final_y_empate_resuelto` |
| R6  | `test_simulacion.py::test_agregacion_probabilidades_y_error_mc` |
| R7  | `test_simulacion.py::test_reporte_determinista_solo_bajo_data` |
| R8  | `test_cli_simulate.py::test_simulate_exito_y_reporte`, `::test_subcomandos_exactos_intactos`, `::test_exit_codes` |
| R9  | `test_simulacion.py::test_roster_aplica_multiplicador_opcional` |
| R10 | `test_simulacion.py::test_lambda_precomputadas_una_vez` (o asercion de rendimiento acotado) |

## Cierre

- [ ] T7. Suite completa verde (previos + nuevos), `bash init.sh` verde.
- [ ] T8. Review (Reviewer): trazabilidad R1–R10 ↔ tests; determinismo con seed;
      sin red; sin lib nueva; escritura bajo data/.
- [ ] T9. **Validación real**: `simulate --n 10000 --seed 42` con el mejor modelo;
      pegar top de % título / % avance en `progress/current.md`.
- [ ] T10. Dictamen security-lead (sin red; seed inyectada; escritura bajo data/).
- [ ] T11. Actualizar `feature_list.json` (13 → done), `progress/current.md`,
      `README.md`. Cierre del roadmap v2.
