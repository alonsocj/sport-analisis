# design.md — Feature 18: forma_perf

## Estrategia

Una sola pasada sobre el silver construye un **índice por equipo**; cada ventana se arma
desde el bucket pequeño del equipo. Cero cambios de comportamiento (equivalencia 1e-9).

## Cambios

### `src/form/window.py`
- Nuevo helper interno `index_matches_by_team(matches, teams) -> dict[str, list[_Row]]`:
  UNA pasada con `itertuples()` (no `iterrows()`); por cada fila válida (goles numéricos),
  si `home_code ∈ teams` añade el registro en perspectiva de home a su bucket, e ídem para
  away. `_Row` lleva `date, is_group_wc, gf, ga, opp_code, result` (mismos campos que
  `MatchInWindow`). El cómputo de `is_group_wc`, perspectiva y `result` es IDÉNTICO al de
  `build_window` (misma lógica, extraída a una función pura compartida para garantizar
  equivalencia).
- Nuevo `build_window_from_bucket(bucket, as_of, k_pre) -> list[MatchInWindow]`: filtra
  `date < as_of`, separa tramos (WC-group / pre-WC), ordena y toma los más recientes
  (≤3 / ≤k_pre), combina ascendente. Lógica idéntica a la cola de `build_window`.
- `build_window(matches, team, as_of, k_pre)` se mantiene (firma pública estable) y se
  re-implementa internamente como `build_window_from_bucket(index_matches_by_team(matches,
  [team])[team], as_of, k_pre)` o equivalente — mismo resultado.

### `src/form/factor.py`
- `make_form_factor_fn`: construir el índice UNA vez (`index_matches_by_team(matches, teams)`)
  antes del bucle, y por equipo llamar `build_window_from_bucket(index.get(team, []), as_of,
  k_pre)`. El resto (team_form, estandarización z, callable) sin cambios.

## Equivalencia (R2) — cómo se garantiza

- La lógica de parseo/perspectiva/`is_group_wc`/`result`/selección se **comparte** entre el
  camino viejo y el nuevo (función pura única). Así el nuevo camino no puede divergir.
- Test oráculo: para un fixture de silver, comparar `make_form_factor_fn` (nuevo) contra una
  referencia que reconstruye factores con el `build_window` por-equipo clásico; asertar
  factores y z idénticos a 1e-9 sobre un conjunto de llaves.

## Escala (R4)

- `index_matches_by_team` recorre el DataFrame UNA vez para los N equipos. Test: con un
  silver sintético grande, verificar que el número de pasadas completas = 1 (p.ej.
  instrumentando un contador sobre `itertuples`, o midiendo que el coste no crece con N de
  forma multiplicativa). Umbral de tiempo holgado y determinista como respaldo.

## Riesgos / mitigación

- **Orden y desempates**: preservar el `sort(key=date)` y el `[-3:]`/`[-k_pre:]` EXACTOS;
  si dos partidos comparten fecha, el orden relativo debe coincidir con el de `iterrows()`
  original (orden de aparición en el DataFrame). El índice debe respetar el orden de
  inserción de la pasada (estable) → mismo resultado que el viejo.
- **No tocar** `team_form`, `factor` math, ni el módulo `app`/`cli`/`simulation`.

## Validación (post-implementación, con OK usuario)

Correr `backtest --from-date 2026-06-14 --to-date 2026-06-28 --form-weight {0,0.2,0.3}` y
reportar Brier/log-loss/accuracy v1 vs v1+forma → **veredicto medido**. Registrar en
`feature_list.json` (F16/F18) si la forma bate o no a v1 sobre la evidencia disponible.

## Fuera de alcance

- No cambia el modelo, ni el factor matemático, ni los defaults (γ=0 OFF).
- No añade caché Streamlit (esa es deuda menor de F17, aparte).
