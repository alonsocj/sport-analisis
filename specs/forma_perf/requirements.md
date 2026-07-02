# requirements.md — Feature 18: forma_perf

Objetivo: eliminar la deuda de performance O(n·N) de la construcción del factor de forma
(Feature 16) **sin cambiar ningún resultado**, para que el backtest `--form-weight` corra
con potencia y se pueda emitir el **veredicto medido v1 vs v1+forma**.

Causa raíz (verificada): `make_form_factor_fn` itera los `N` equipos y, por cada uno,
`build_window` recorre el silver COMPLETO con `df.iterrows()` (49.475 filas) → ~2.4M
iteraciones por build (48×49k). En backtest se reconstruye por cada ventana/fecha → se
**cuelga**. El cálculo es correcto; solo el coste es patológico.

Principio rector: **equivalencia exacta**. La optimización NO cambia las ventanas, métricas,
z ni factores: para los mismos inputs los factores resultantes son idénticos a Feature 16
(tol 1e-9). γ=0 sigue siendo v1 exacto. APIs públicas estables.

Notación EARS. Cada `R<n>` mapea a ≥1 test en `tests/test_form_perf.py` (más reuso de
`tests/test_forma_reciente.py` y `tests/test_form_factor.py` como no-regresión).

---

**R1 — Indexación en una sola pasada.**
El sistema DEBE construir las ventanas de los `N` equipos recorriendo el silver UNA sola
vez (no `N` veces): una pasada que agrupe los partidos por equipo (perspectiva de cada
equipo: `gf, ga, opp, result, is_group_wc, date`), y luego construir cada ventana desde el
bucket pequeño del equipo. Complejidad objetivo ≈ `O(filas + N·k·log k)` por build, sin
`iterrows()` sobre el DataFrame completo por equipo.

**R2 — Equivalencia exacta con Feature 16.**
El sistema DEBE producir, para los mismos `(matches, as_of, elo, gamma, teams, config)`,
factores `(mult_home, mult_away)` IDÉNTICOS (tol 1e-9) a la implementación previa, y las
mismas z por equipo. SI hay cualquier divergencia → es un bug (no se acepta "casi igual").

**R3 — API pública estable + anti-fuga preservada.**
`build_window(matches, team, as_of, k_pre)`, `team_form`, `make_form_factor_fn` y
`make_form_factory` DEBEN conservar su firma y semántica públicas (los tests de F16 siguen
verdes sin cambios). La condición estricta `date < as_of` (anti-fuga, R1 de F16) se
preserva. La selección (≤3 grupo WC + ≤k_pre pre-WC, más recientes, orden ascendente)
es idéntica.

**R4 — Backtest utilizable (no se cuelga).**
CUANDO se ejecuta el backtest con `--form-weight γ>0` sobre la ventana WC2026, el sistema
DEBE completar en tiempo razonable (sin cuelgue). DEBE existir un test de escala acotado
que verifique que un build sobre un silver grande no recorre el DataFrame por equipo
(p.ej. contando llamadas/coste, o un umbral de tiempo holgado y determinista).

**R5 — Determinismo, sin red, sin libs nuevas.**
Sin red; `as_of` inyectado; sin dependencias nuevas (pandas/numpy actuales); escritura solo
bajo `data/` (ninguna en esta feature). γ=0 → identidad exacta (v1).
