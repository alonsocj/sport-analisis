# design.md — Feature 20: knockouts_analisis_app

## Arquitectura

Ampliar `src/app/tabs/knockouts.py`: por cada llave, además del 1X2/P(avanza) actual,
un `st.expander("Mercados y goleadores (v1)")` con mercados + top-scorers. Reusa módulos
existentes; no los modifica.

```
predict_match (v1, sin form) ─→ λ_home, λ_away ─→ market_summary + compute_anytime_scorers
player_factor.csv (gold) ──────────────────────┘
```

## Fuentes a reusar (NO modificar)

- `src/markets/goals.py::market_summary(params, home, away)` → `MarketSummary` (O/U totales,
  BTTS, totales por equipo). Llama predict_match internamente (v1).
- `src/players/factor.py`: `load_player_factor(path)`, `build_player_rates(...)`,
  `compute_anytime_scorers(player_rates, lambda_team, top_k)`. Replicar el wiring de
  `cmd_scorers` en `src/cli.py` (de ahí se obtiene cómo se calcula λ_team por equipo y cómo
  se arma la lista de goleadores). NO reimplementar la lógica: importar y llamar.

## Helper nuevo en knockouts.py

- `_render_analisis_llave(params, home, away, player_factor_path, top_k=3)`:
  - `summary = market_summary(params, home, away)` → render O/U (líneas) + BTTS + totales.
  - Goleadores: cargar player_factor; obtener λ_home/λ_away de `predict_match(params, home,
    away)` (v1); `compute_anytime_scorers` por equipo; render top_k con P(marca).
  - Si player_factor ausente → `st.caption` aviso, omitir goleadores.
- Cachear con `@st.cache_data` keyed por `(home, away, player_factor_path_str)` para no
  recalcular al mover el slider γ (que no afecta este panel).
- Llamar dentro del bucle de llaves de `render_knockouts`, en un `st.expander` por llave.

## Etiquetado (R3)

Título del expander y un `st.caption`: "Mercados y goleadores se calculan con v1 (sin factor
de forma). El 1X2 / P(avanza) de arriba sí usa el slider γ." Evita la confusión de mezclar.

## Degradación (R2, R5)

- `player_factor.csv` ausente → omitir goleadores con aviso; mercados siguen (no dependen de
  jugadores).
- Equipo no resoluble en params → el render de la llave ya lo maneja (F17); el panel se omite.

## Tests (R1–R5)

`tests/test_app_knockouts_analisis.py` (AppTest + fixtures sintéticos de params y
player_factor; monkeypatch de paths). Verifica: mercados presentes, goleadores presentes,
degradación sin player_factor, etiqueta v1, y que el tab/otros tabs no se rompen.

## Fuera de alcance

- NO se aplica el factor de forma a mercados/goleadores (requeriría extender market_summary
  y el wiring de scorers para aceptar form_factor — feature aparte si se quiere).
- NO usa roster/disponibilidad (eso es la feature siguiente: ingesta fotmob → --roster).
- NO toca CLI ni añade subcomandos.
