# design.md — Feature 25: count_markets

## Arquitectura

Motor genérico `src/markets/counts.py` que parametriza por columna de stat la misma maquinaria
que `corners.py` (F24): shrinkage + expected + Poisson O/U. Subcomando `count-market`.
Integración en el sub-tab Mercados del detalle KO.

```
silver (home/away_<stat>, date<as_of) ─▶ team_rates(stat, shrinkage) ─▶ expected ─▶ poisson O/U
   stat ∈ {cards, shots, shots_on_target}
```

## Módulo `src/markets/counts.py` (R1, R2)

- `STAT_SPECS: dict[str, StatSpec]` con, por stat (`cards`,`shots`,`sot`→`shots_on_target`):
  columnas silver, líneas default, etiqueta, `noisy_note` (tarjetas → aviso árbitro).
- `count_rates(matches, as_of, stat, k) -> dict[code,{att,dfn}]`, `expected_counts(...)`,
  `count_over_under(λ, lines)`, `count_summary(matches, home, away, as_of, stat, config)`
  con `n_matches_*`. Espeja `corners.py`; puede importar sus helpers Poisson si conviene
  (sin modificar corners.py).

## CLI (R3)

`count-market HOME AWAY --stat {cards,shots,sot} [--as-of] [--lines] [--silver] [--json]`.
Offline. Subcomandos previos intactos + `count-market` (test del set exacto).

## App (R4)

En el sub-tab Mercados del detalle KO (helper F22/F24): tras goles y córners, iterar sobre
`{cards, shots, sot}` y mostrar cada O/U (total+equipo) con su etiqueta; tarjetas con el aviso
de ruido por árbitro. Degrada por stat ausente. Cachear con el resto.

## Decisiones

1. **Motor genérico** en vez de 3 módulos casi iguales — DRY; córners ya existe aparte (no se
   refactoriza para no romper sus tests; se permite leve duplicación o reuso de helpers).
2. **Líneas por stat** — defaults sensatos (tarjetas ~2.5-4.5, tiros ~20.5+, SoT ~6.5+).
3. **Aviso de ruido en tarjetas** — honestidad: sin datos de árbitro, alta varianza.

## Fuera de alcance

- No usa forma/roster. No backfill (solo WC2026). xG-goles es la feature siguiente (F26).
