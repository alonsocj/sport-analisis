# tasks.md — Feature 32: senal_por_mitad

Checklist de implementación con mapeo **R<n> → test**. El Implementer NO se autoaprueba;
el Reviewer rechaza si falta el test de algún R<n>. Una feature a la vez.

> Estado: **IMPLEMENTADO + INTEGRADO** (2026-07-08, aprobado por el usuario). 27 tests nuevos,
> suite completa verde (681), no-regresión confirmada (subcomandos exactos intactos, markets previo
> byte-idéntico con flag OFF; sub-pestañas app actualizadas a 7). Núcleo A–F + integración G
> (gold `data/gold/half_signal.csv`, CLI ajuste-rival, **sub-pestaña «Mitades» en el app** verificada
> por render). PENDIENTE SOLO: **veredicto de adopción empírico** de R8 — el harness está listo y
> testeado, pero con la data actual solo hay n=1 partido con ambos equipos en la señal (el gold
> cubre los 8 de cuartos; casi todos los partidos son QF-vs-no-QF) → el veredicto real requiere
> per-mitad histórico out-of-sample de muchos equipos (scrape amplio, regla STOP).

## Fase A — Ingesta per-mitad (bronze)

- [x] A1. Generalizar `parse_match_stats` → `parse_period(period_dict)` y llamarla por
  `All`/`FirstHalf`/`SecondHalf`. Persistir `periods.{first,second}` en el bronze (opcional).
  → **R1**: `test_parse_periods_firsthalf_secondhalf`, `test_bronze_schema_retrocompat`
- [x] A2. Parsear eventos de gol (`matchFacts.events.events`, `type=="Goal"`): minuto,
  overloadTime, isHome, ownGoal. → **R1**: `test_parse_goal_events_minutes`
- [x] A3. Función `half_of(minute)` → `1T|2T|ET` determinista; orientación home/away.
  → **R2**: `test_half_assignment_1t_2t_et`, `test_goal_orientation_home_away`

## Fase B — Silver por-mitad

- [x] B1. Builder `build_silver_por_mitad(as_of)` → tabla (match, team, half, gf/ga/xg/shots,
  cover_xg). Combina fotmob (xG) + goalscorers (minutos pre-torneo). Anti-fuga `date<as_of`.
  → **R3**: `test_silver_por_mitad_row`, `test_xg_null_sin_cobertura`, `test_antifuga_as_of`

## Fase C — Señal (gold)

- [x] C1. `half_signal(team, half)` con ajuste por rival + **shrinkage** (`k` documentado)
  hacia el prior de la mitad. Preferencia xG con fallback a goles.
  → **R4**: `test_half_strength_shrinkage`, `test_ajuste_rival`, `test_muestra_chica_shrink_fuerte`

## Fase D — Mercados por mitad

- [x] D1. `src/markets/by_half.py`: λ_1T/λ_2T por equipo → Poisson por mitad. NO tocar
  `goals.py`/`corners.py`. → **R5**: `test_market_ou_1t`, `test_market_ou_2t`
- [x] D2. Mercados «equipo marca en 2T» y «gol 76-90» (sub-split del bucket).
  → **R5**: `test_market_equipo_marca_2t`, `test_market_gol_tardio`

## Fase E — Interruptor + CLI + app

- [x] E1. Flag `--by-half` / subcomando `half-markets`; param `use_half_signal`. OFF = idéntico.
  → **R6**: `test_flag_off_equivalencia`, `test_no_regresion_markets_previos`
  → **R7**: `test_cli_subcomandos_intactos`, `test_cli_half_markets_salida`
- [x] E2. Sub-pestaña «Mitades» en la pestaña Knockouts (tendencias 1T/2T por equipo +
  mercados por mitad con ajuste-rival). Verificada por render; tests de app actualizados a 7 sub-pestañas.

## Fase F — Validación

- [x] F1. Backtest de calibración por mitad vs naïve 45/55. Adopción solo si bate.
  → **R8**: `test_backtest_por_mitad_calibra_vs_naive`

## Cobertura de trazabilidad

Todos los R1–R8 tienen ≥1 test mapeado arriba. **Sin test → rechazo del Reviewer.**

## Artefactos de research ya disponibles (no-código, informan la impl.)

- `tmp/acquire.py` — valida rutas fotmob per-mitad + eventos (reutilizable como referencia).
- `tmp/profiles.py` — lógica de agregación por mitad + buckets (referencia para B1/C1).
- Dossier `Radiografía por mitades` (Artifact) — prototipo visual para E2.
