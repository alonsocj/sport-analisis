# design.md — Feature 29: modelo_v3

## Decisión central

La "v3" del modelo NO es un algoritmo nuevo: es **forma-xG re-entrenado con datos frescos**
(F27). Los intentos de mecanismo nuevo históricos (F12 importancia, F14 Elo externo, F15 xG
Wikipedia) NO batieron a v1; F28 mostró que el rating por jugador de fotmob es esparso. La
palanca real de precisión hoy es el DATO, no un modelo más complejo. Se mide y se reporta la
verdad (metodología de F10/F18).

## Procedimiento reproducible (sin código nuevo)

1. `train --as-of-date 2026-07-05` → re-fit params con KO incluido (R1).
2. `backtest --from-date 2026-06-28 --to-date 2026-07-05 --refit-every week [--form-weight γ
   --form-xg]` → v1 vs forma-xG en la ventana fresca (R2, R3).
3. `neutral_prediction(params, home, away, form_factor(γ=0.2, use_xg=True))` por octavo por
   jugar → tabla 1X2 + P(avanza) (R4).

## Config de producción

forma-xG, γ=0.2, use_xg=True, refit semanal. γ≥0.4 rechazado por overfit al tamaño de muestra.
El tab Knockouts/Round-of-16 (F30) ya arranca el slider en γ=0.2 (mejor modelo medido). El
default de CLI/librería sigue en γ=0 (baseline nombrado; contratos/tests intactos).

## Fuera de alcance

Integración de jugadores/XI (decisión usuario). La fuerza-XI de F28 queda disponible como
`gold/lineup_strength.csv` para una futura feature cuando la cobertura de rating mejore.
