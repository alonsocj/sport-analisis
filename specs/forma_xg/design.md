# design.md — Feature 26: forma_xg

## Arquitectura

Extiende `src/form/` (F16/F18) para llevar xG en la ventana y usarlo en la métrica, con
interruptor `use_xg`. Flag CLI en predict/backtest/simulate. No toca DC/roster/mercados.

```
silver (home_xg/away_xg, F23) ─▶ build_window/index (xg_for,xg_against) ─▶ team_form(use_xg)
                                                                            └▶ xgd_w o gd_w (mezcla) ─▶ factor
```

## Cambios

### `src/form/window.py`
- `MatchInWindow` añade `xg_for: float|None`, `xg_against: float|None` (default None).
- `index_matches_by_team` (F18) y `build_window_from_bucket`/`build_window`: leen
  `home_xg`/`away_xg` del DataFrame (perspectiva del equipo, como gf/ga). Null → None.

### `src/form/metrics.py`
- `team_form(window, elo, ..., use_xg=False)`: cuando `use_xg=True`, por partido usa
  `xg_for - xg_against` si ambos no-None, si no `gf - ga` (fallback). Agrega con los mismos
  pesos (decay·tier·calidad-rival). Devuelve la componente (reusa el campo `gd_w` o añade
  `xgd_w`; documentar). `use_xg=False` → idéntico a F16.

### `src/form/factor.py`
- `make_form_factor_fn(..., use_xg=False)` y `make_form_factory(..., use_xg=False)`: propagan
  el flag a `team_form`. `use_xg=False` → fast-path/idéntico a F16 (no-regresión, tol 1e-9).
- `src/form/config.py`: `use_xg` default False en `FormConfig` (o parámetro explícito).

### `src/cli.py`
- `--form-xg` (store_true, default False) en `predict`, `backtest`, `simulate`; se pasa a
  `make_form_factor_fn`/`make_form_factory`. Sin subcomandos nuevos.

## No-regresión (R3)

- `use_xg=False` ⇒ no se lee xG, métrica = gol-diff ⇒ salida idéntica a F16 (test 1e-9).
- `use_xg=True` pero ventana sin ningún xG ⇒ todo fallback a goles ⇒ idéntico a F16 también.

## Medición (R5)

`backtest --from-date 2026-06-14 --to-date 2026-06-28 --form-weight 0.2` con y sin `--form-xg`
→ comparar Brier/log-loss/exactitud. Veredicto: ¿xG-forma mejora a goles-forma? La corre el
LEADER en la validación (con datos reales ya en el silver por F23).

## Decisiones

1. **Mezcla por partido (xG donde haya, goles si no)** — maximiza el uso del xG sin perder los
   partidos pre-WC.
2. **Interruptor, default OFF** — no-regresión; se adopta solo si mide mejor (cultura del repo).
3. **Reusar pesos de F16** — solo cambia la señal por partido (xG vs gol), no la agregación.

## Fuera de alcance

- No integra el toggle xG en la app (si gana, se decide después hacerlo default o exponerlo).
- No backfillea xG histórico (solo WC2026, decisión del usuario).
