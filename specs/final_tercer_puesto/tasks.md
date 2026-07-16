# tasks.md — Feature 34: final_tercer_puesto

Checklist de implementación con mapeo **R<n> → test**. El Implementer NO se autoaprueba; el
Reviewer rechaza si falta el test de algún R<n>. Una feature a la vez. Tests en
`tests/test_final_tercer_puesto.py` salvo indicación.

> Estado: **IMPLEMENTADO + TESTEADO** (TDD, 2026-07-15). Fases A–G completas: 33 tests nuevos
> (test_final_tercer_puesto.py 25 · test_cli_simulate_match.py 3 · test_app_final.py 5), suite
> completa **717 verde**, no-regresión confirmada (flag OFF idéntico; subcomandos previos
> intactos + `simulate-match`; 6→7 pestañas aditivo). Módulos nuevos: `models/dead_rubber.py`,
> `simulation/match_sim.py`, `app/tabs/final.py`; extensiones en `ingestion/fotmob_ko.py`
> (KoMatch.is_third_place + detección 3P + writer r2/r3p), `cli.py` (subcomando `simulate-match`),
> `app/main.py` (tab Final). Smoke verificado end-to-end con params reales.
> **PENDIENTE (Fase H, regla STOP):** data update de semis (scrape real) → finalistas + 3er
> puesto reales → correr las simulaciones del entregable.

## Fase A — Fixtures Final + 3er puesto (writer)

- [x] A1. `_FIXTURE_FILES[5] = ("Final","r2_fixtures.csv")` + `_THIRD_PLACE_FILE` y paso 3P en
  `write_ko_fixtures`. → **R1**: `test_write_final_fixture_r2`, `test_write_r3p_fixture`,
  `test_r2_r3p_no_se_contaminan`, `test_tbd_omitido_final`
- [x] A2. Ordinales/etapas previos intactos con un bracket mixto. → **R1**:
  `test_fixtures_previos_intactos` (R16/QF/SF siguen escribiéndose)

## Fase B — Detección del 3er puesto

- [x] B1. Campo `is_third_place: bool = False` en `KoMatch` (retrocompatible) + derivación de
  `stage`. → **R2**: `test_komatch_is_third_place_default_false`
- [x] B2. `parse_playoff_bracket`: última ronda con >1 matchup → clasifica 3P por etiqueta
  fotmob. → **R2**: `test_detecta_3p_por_etiqueta`
- [x] B3. Fallback por emparejamiento (perdedores de semis) + regla conservadora si SF sin
  marcador. → **R2**: `test_detecta_3p_por_perdedores_sf`, `test_sf_sin_marcador_no_inventa_3p`

## Fase C — Dead-rubber (`src/models/dead_rubber.py`)

- [x] C1. `shrink_strengths` (delta) + `apply_dead_rubber` (kappa) + `DeadRubber` config con
  defaults documentados. → **R3**: `test_dead_rubber_off_identidad`,
  `test_dead_rubber_sube_goles`, `test_dead_rubber_baja_prob_favorito`, `test_dead_rubber_acotado`

## Fase D — Simulador de cruce fijo (`src/simulation/match_sim.py`)

- [x] D1. `MatchSimResult` + `simulate_fixture` (muestreo 90', modal, top-k, e_goals, mercados,
  std_err). → **R4**: `test_sim_determinista_misma_seed`, `test_sim_probs_suman_uno`,
  `test_sim_crosscheck_vs_analitico`, `test_sim_valida_n_min`
- [x] D2. Resolución empate → ET(×1/3) → penales; reparto reg/ET/pens. → **R5**:
  `test_sim_reparto_camino_suma_uno`, `test_sim_empate_resuelve_ganador`,
  `test_sim_dead_rubber_desplaza` (integra R3 en el simulador)

## Fase E — Artefactos + CLI

- [x] E1. `write_sim_result` → `final_sim.csv` / `r3p_sim.csv`, esquema estable. → **R6**:
  `test_sim_artifact_schema`, `test_sim_artifact_solo_bajo_data`
- [x] E2. Subcomando `simulate-match` (`--fixture/--home/--away/--n/--seed/--gamma/--dead-rubber/--out`).
  → **R7**: `test_cli_simulate_match_salida`, `test_cli_simulate_match_dead_rubber`
- [x] E3. Subcomandos previos EXACTOS + `simulate-match`. → **R7/R8**: `test_simulate_match_en_parser`
  (+ suites de subcomandos exactos actualizadas: test_cli/test_cli_form/test_cli_xg/… a 23 comandos)

## Fase F — No-regresión

- [x] F1. Flag dead-rubber OFF byte-idéntico (`test_dead_rubber_off_identidad`) + simulador no
  invocado no altera nada → suite completa **717 verde** (686 previos intactos). → **R8**

## Fase G — App: pestaña Final

- [x] G1. `TAB_FINAL` + `tabs[6]` con bloques Final (r2) y 3er puesto (r3p); panel MC por bloque;
  dead-rubber sólo en 3P. → **R9**: `test_tab_final_presente`, `test_siete_tabs_aditivo`,
  `test_final_dos_bloques`, `test_dead_rubber_solo_en_3p` (en `tests/test_app_final.py`)
- [x] G2. `render_sim_panel` (P(ganador), top marcadores, reparto, mercados). → **R9**:
  `test_sim_panel_render` (render sin excepción vía AppTest)

## Fase H — Data update (operativo, regla STOP)

- [ ] H1. **STOP**: aprobación del usuario para el scrape real. Luego `ingest-ko` + `ingest-lineups`
  (semis), `build-features`, `train --as-of-date 2026-07-15`. Verificar r2/r3p resueltos.
- [ ] H2. Correr `simulate-match --fixture r2` y `--fixture r3p --dead-rubber`; generar artefactos
  y dossier de resultado preciso. (No es test; es la corrida de producción del entregable.)

## Cobertura de trazabilidad

R1→A1,A2 · R2→B1,B2,B3 · R3→C1 · R4→D1 · R5→D2 · R6→E1 · R7→E2,E3 · R8→E3,F1 · R9→G1,G2.
Todos los R1–R9 con ≥1 test. **Sin test → rechazo del Reviewer.**
