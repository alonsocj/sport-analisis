# requirements.md — Feature 4: modelos_mercados (solo goles)

Objetivo: probabilidades de **mercados de goles** derivadas de la matriz conjunta de
marcadores del modelo Dixon-Coles ya entrenado (feature 3, `score_matrix`/
`predict_match`): **over/under** en líneas `k + 0.5`, **BTTS** (ambos marcan) y
**totales por equipo**. Se exponen por **CLI** (subcomando nuevo `markets`) y en la
**app Streamlit** (sub-pestaña `Mercados` del detalle de partido, el hueco reservado
por la feature 9). Alcance reducido a goles por decisión del usuario (2026-06-09):
córners/tarjetas son **no-objetivo** (sin datos en ninguna capa; exigirían llamadas
API reales).

Notación EARS. Cada `R<n>` mapea a ≥1 test en `tests/test_markets.py`,
`tests/test_cli_markets.py` o `tests/test_app_markets_ui.py` (ver `tasks.md`).

---

**R1 — Módulo puro sobre el contrato de la matriz.**
El sistema DEBE implementar los cálculos en `src/markets/goals.py` como funciones
puras sobre la matriz del contrato de la feature 3 (`M[x][y]`, goles del local en
filas, suma 1, soporte `0..max_goals`), sin red, sin reloj, sin RNG y sin importar
`streamlit` ni módulos de red. `src/markets/__init__.py` no DEBE tener imports.

**R2 — Over/under en líneas medias.**
El sistema DEBE calcular `P(over línea) = P(X + Y > línea)` y
`P(under línea) = 1 − P(over línea)` para líneas de la forma `k + 0.5` (k ≥ 0
entero). Las líneas default DEBEN ser `(0.5, 1.5, 2.5, 3.5, 4.5)` y parametrizables.
SI se pasa una línea que no es de la forma `k + 0.5`, ENTONCES el sistema DEBE
fallar con `ValueError` cuyo mensaje indique el formato esperado. Para cada línea,
over + under DEBE sumar 1 (tolerancia 1e-9).

**R3 — BTTS (ambos marcan).**
El sistema DEBE calcular `P(BTTS sí) = P(X ≥ 1 ∧ Y ≥ 1)` y
`P(BTTS no) = 1 − P(BTTS sí)`; ambas DEBEN sumar 1 (tolerancia 1e-9).

**R4 — Totales por equipo.**
El sistema DEBE calcular `P(goles del local > línea)` y
`P(goles del visitante > línea)` para líneas `k + 0.5` (defaults `(0.5, 1.5, 2.5)`,
parametrizables), con la misma validación de línea de R2.

**R5 — Resumen de mercados con el modelo real.**
El sistema DEBE exponer `market_summary(params, home_code, away_code, ...)` que usa
`predict_match` real de la feature 3 sobre parámetros cargados con `load_params`
(sin reentrenar; la localía la resuelve `predict_match`) y devuelve una estructura
inmutable con: 1X2, over/under por línea, BTTS y totales por equipo. SI un código
no existe en los parámetros, la excepción `UnknownTeamError` de la feature 3 DEBE
propagarse sin envolver.

**R6 — Exactitud verificable con matriz conocida.**
Para una matriz sintética 3×3 con valores cerrados definidos en el test, los
resultados de R2–R4 DEBEN coincidir con los valores calculados a mano (tolerancia
1e-12). (Test de oráculo: protege contra errores de orientación filas/columnas y de
desigualdad estricta vs no estricta.)

**R7 — CLI: subcomando `markets`.**
El sistema DEBE añadir a `src/cli.py` el subcomando
`python -m src.cli markets HOME AWAY [--json] [--lines L1,L2,...]`: salida humana
con porcentajes a 1 decimal (convención de `predict`) y salida JSON parseable con
`--json`. Manejo de errores idéntico al de `predict`: params ausentes → mensaje
accionable (`train`) en stderr y exit `1`; equipo desconocido → mensaje claro y
exit `1`; error de uso argparse → exit `2`. CUANDO el cálculo termine con éxito el
exit code DEBE ser `0`. Los subcomandos existentes NO DEBEN cambiar de
comportamiento (la suite previa sigue verde).

**R8 — App: sub-pestaña Mercados en el detalle de partido.**
CUANDO un partido seleccionado sea predecible, el detalle de la app DEBE incluir
una cuarta sub-pestaña `Mercados` (tras Predicción/Equipos/Historial Elo) que
muestre over/under por línea, BTTS y totales por equipo con porcentajes a 1
decimal, calculados vía `src.markets` (misma fuente de verdad que el CLI). SI el
partido no es predecible, la sub-pestaña NO DEBE aparecer (el detalle ya degrada
según R9 de la feature 9).

**R9 — Determinismo.**
Para una misma matriz/parámetros y los mismos argumentos, todos los resultados de
R2–R5 DEBEN ser idénticos entre invocaciones (sin reloj, sin RNG; mismas líneas →
mismo orden de salida, ascendente por línea).

**R10 — Aislamiento e import sin efectos.**
Importar `src.markets` o `src.markets.goals` NO DEBE disparar lecturas de disco,
red ni efectos (solo definiciones). `src/markets/` NO DEBE importar `src.app`,
`src.report` ni `src.cli` (la dependencia es en sentido inverso: CLI y app importan
`src.markets`). Los módulos existentes distintos de `src/cli.py` y
`src/app/tabs/calendario.py` NO DEBEN modificarse.
