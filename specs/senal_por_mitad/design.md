# design.md — Feature 32: senal_por_mitad

Decisiones técnicas para la señal de tendencia por mitad (1T/2T). Coherente con la
arquitectura bronze→silver→gold y el motor Dixon-Coles existente. **Aditiva y aislada**:
el modelo de marcador completo (1X2) NO cambia.

## 0. Evidencia que motiva el diseño (research LEADER, cuartos WC2026)

Medido con fotmob per-mitad (n=5/equipo torneo) + goalscorers (ventana 2023-06, ~20-30
part.), verificado 100% contra el silver:

| Equipo | Señal por mitad dominante (dato) |
|--------|----------------------------------|
| FRA | xG torneo 0.51 (1T) → **1.62** (2T); 19 goles recientes en 76-90 |
| MAR | se apaga: xG 0.93 → 0.59; concede antes (GA torneo 1T 3 / 2T 1) |
| ESP | muralla torneo (0 GA en 5); pero reciente afloja 2T (GA 8 → 16) |
| BEL | frágil temprano (1-15: 6 GA rec.); revive 2T (46-60: 15 GF rec.) |
| NOR | encaja tarde: GA rec. 1T 7 / **2T 16**; dominada en tiros |
| ENG | cierre letal: GF rec. 1T 27 / 2T 40; 19 en 76-90 |
| ARG | dobla tiros en 2T (4.6 → 9.0); 14 goles rec. en 76-90 |
| SUI | **colapso 2T**: GA rec. 1T 7 / 2T 27; 17 en 76-90 |

Conclusión: el «cuándo» del gol es sistemático por equipo. El modelo actual lo ignora.

## 1. Fuentes y flujo de datos

```
fotmob match page  ──_extract_next_data──▶  Periods.{FirstHalf,SecondHalf}  ─┐
                                            matchFacts.events (min, isHome)  ─┤
goalscorers.csv (minuto, pre-torneo) ─────────────────────────────────────── ┼─▶ silver_por_mitad
                                                                              │        │
                                                                              │   half_signal (gold)
                                                                              │        │
                                                                         markets/by_half
```

- **Reutilización obligatoria**: `parse_match_stats` ya lee `Periods.All`. Se generaliza a
  `parse_period(period_dict)` y se llama por `All`/`FirstHalf`/`SecondHalf` (el research en
  `tmp/acquire.py` ya validó las rutas: `stats[].stats[]` con `{title, stats:[home,away]}`).
- **Eventos de gol**: `content.matchFacts.events.events`, `type=="Goal"` → `time`,
  `overloadTime`, `isHome`, `ownGoal`. Asignación: 1T ≤45, 46≤2T≤90, ET >90.
- **Retrocompatibilidad**: los campos nuevos del bronze son opcionales; los `.json` viejos
  (solo `Periods.All`) siguen parseando sin error (test R1).

## 2. Esquema silver_por_mitad (una fila por equipo-partido)

`match_id, date, team_code, is_home, half ∈ {1T,2T}, gf, ga, xg_for, xg_against, shots_for,
shots_against, cover_xg (bool)`

- `cover_xg=False` cuando el partido no fue scrapeado (solo minutos de gol vía goalscorers):
  `gf/ga` presentes, `xg_*` en null.
- Anti-fuga: el builder filtra `date < as_of` (idéntico patrón a F18/F26).

## 3. Señal `half_signal` (gold) — con shrinkage y ajuste por rival

Para equipo `t`, mitad `h`:

```
raw_att[t,h]  = media( gf[t,h] − baseline_ga_opp[h] )   # ataque relativo a lo que suele encajar el rival en h
raw_def[t,h]  = media( ga[t,h] − baseline_gf_opp[h] )   # defensa relativa
n[t,h]        = nº de partidos con cobertura
shrunk[x]     = (n·raw_x + k·prior_h) / (n + k)          # prior_h = media del bracket/histórica en la mitad h
```

- `k` (fuerza de shrinkage) alto (p.ej. `k≈6`) porque `n≈5`: la señal NO debe sobre-confiar.
  `k` es un hiperparámetro documentado; se fija por el backtest (R8), no a ojo.
- Salida: `λ_1T[t]`, `λ_2T[t]` (goles esperados por mitad, atacando) y sus análogos defensivos.
  Se combinan con el λ del rival (att_t vs def_opp) por mitad, igual que DC pero por período.
- **Preferencia xG**: donde `cover_xg`, usar xG por mitad (menos ruidoso); fallback a goles.
  Mismo principio que forma-xG (F26).

## 4. Mercados por mitad (R5) — reusar el motor, no reimplementar

- `src/markets/goals.py` ya modela goles con Poisson/DC. Se aplica **por mitad**: `λ_1T_home,
  λ_1T_away, λ_2T_home, λ_2T_away` → distribuciones Poisson independientes por mitad.
- Derivados:
  - **O/U 1T** y **O/U 2T** (líneas 0.5/1.5) desde la Poisson de cada mitad.
  - **«equipo X marca en 2T»** = `1 − P(0 goles de X en 2T)`.
  - **«gol en 76-90»** = usar la fracción histórica del bucket 76-90 dentro del 2T del equipo
    (de `gf_bucket`) como sub-split de `λ_2T`.
- Consistencia: `λ_1T + λ_2T ≈ λ_total` del modelo de partido completo (chequeo de sanidad,
  no restricción dura; ET aparte).

## 5. Interruptor y no-regresión (R6)

- Flag `--by-half` en `markets` (o subcomando `half-markets`) + param `use_half_signal` en config.
- OFF (default): salida byte-idéntica a la actual (test de equivalencia). Ningún test de
  F23/F24/F25 se toca.
- El motor por mitad es un módulo nuevo (`src/markets/by_half.py`); no muta `goals.py`/`corners.py`.

## 6. App (R7)

- Pestaña Knockouts: nuevo bloque por-cruce «Radiografía por mitades» (1T/2T: goles/xG/tiros +
  distribución por franja) — el HTML/estructura ya prototipado en el research (dossier).
- Sub-pestaña Mercados: añadir O/U 1T, O/U 2T, «marca en 2T».

## 7. Validación (R8)

- Backtest de calibración por mitad sobre WC2026 con cobertura: log-loss/Brier del O/U 1T y 2T
  vs línea base naïve (λ_total repartido 45/55 fijo, sin señal de equipo).
- Criterio de adopción: la señal DEBE bajar log-loss del O/U por mitad vs naïve. Reporte
  honesto de muestra chica (IC amplios). Igual disciplina que forma-xG (se midió, batió, se adoptó).

## 8. Riesgos / deuda

- **Muestra chica** (n≈5 torneo): el shrinkage la mitiga pero no la elimina; la señal es para
  inclinar mercados de mitad, no para el 1X2.
- **Cobertura xG parcial** pre-torneo: los goles por minuto sí existen (goalscorers), el xG no.
- **ET/penales** fuera de alcance (no son «mitades» de regulación).
- **Coste de scrape**: re-fetch per-mitad de partidos = red real (regla STOP, aprobación).
