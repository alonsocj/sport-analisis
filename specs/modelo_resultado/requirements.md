# requirements.md — Feature 3: modelo_resultado

Objetivo: modelo **Poisson bivariado con corrección Dixon-Coles y decaimiento temporal**
que estima fuerzas ofensiva/defensiva por selección a partir de
`data/silver/matches.csv` (contrato exacto de la feature 2, `specs/feature_store/design.md`)
y produce, para un partido del Mundial 2026: probabilidades **1X2**, **distribución
conjunta de marcadores** y los marcadores más probables. Localía parametrizada: ventaja
SOLO cuando el equipo local es anfitriona (MEX/USA/CAN, `host=True` en
`src/ingestion/teams.py`).

Notación EARS. Cada `R<n>` es verificable y mapea a ≥1 test (ver `tasks.md`).
Todo el procesamiento es **offline** (lee disco → escribe
`data/gold/dixon_coles_params.json`); no hay red y no se usa `API_FOOTBALL_KEY`.
Los tests son deterministas: silver sintético escrito en `tmp_path` con el esquema del
contrato y datos generados con **semilla fija**; cero red real, cero `now()` implícito.

---

## Datos de entrenamiento

**R1 — Carga del silver y validación de contrato.**
CUANDO se entrena el modelo, el sistema DEBE leer `data/silver/matches.csv` (ruta
parametrizable) usando las columnas del contrato de la feature 2:
`match_id, date, home_code, away_code, home_goals, away_goals, neutral`.
SI el archivo no existe o carece de alguna de esas columnas, ENTONCES el sistema DEBE
fallar con un error claro (`SilverNotFoundError`, con la ruta y/o la columna ausente)
sin escribir ninguna salida.

**R2 — Recorte temporal con `as_of_date` inyectada.**
El sistema DEBE entrenar SOLO con partidos que cumplan `from_date <= date < as_of_date`
(estricto: los partidos con `date >= as_of_date` quedan fuera — anti-leakage), con
`as_of_date` SIEMPRE inyectada como argumento (nunca `now()` implícito) y `from_date`
configurable (default `2018-01-01`).
SI `as_of_date` o `from_date` no tienen formato `YYYY-MM-DD`, ENTONCES el sistema DEBE
fallar con `ValueError` claro.
SI el recorte deja 0 partidos, ENTONCES el sistema DEBE fallar con un error claro
(no hay nada que ajustar).

**R3 — Pesos de decaimiento temporal.**
El sistema DEBE ponderar cada partido `i` con
`w_i = exp(−xi · dias(date_i, as_of_date) / 365.25)`, con `xi` configurable
(default `0.65`, justificado en `design.md` con Dixon & Coles 1997).
Los pesos DEBEN ser estrictamente decrecientes con la antigüedad del partido
(a más días desde `as_of_date`, menor peso) y, DONDE `xi = 0`, todos los pesos
DEBEN valer exactamente 1.

## Modelo

**R4 — Especificación de las tasas y localía en entrenamiento.**
El sistema DEBE modelar las tasas de gol como
`lambda_home = exp(mu + att_home − def_away + gamma·h)` y
`lambda_away = exp(mu + att_away − def_home)`,
DONDE en **entrenamiento** `h = 1` SI `neutral = False` y `h = 0` SI `neutral = True`.
`gamma` NO DEBE intervenir nunca en `lambda_away`, ni con `h = 1`.

**R5 — Corrección Dixon-Coles τ en marcadores bajos.**
El sistema DEBE aplicar la corrección de dependencia
`tau(x, y; lambda_h, lambda_a, rho)` definida EXACTAMENTE como:
`tau(0,0) = 1 − lambda_h·lambda_a·rho`; `tau(0,1) = 1 + lambda_h·rho`;
`tau(1,0) = 1 + lambda_a·rho`; `tau(1,1) = 1 − rho`; y `tau(x,y) = 1` para
cualquier otro marcador.

## Ajuste (máxima verosimilitud ponderada)

**R6 — Estimación por MLE ponderada y reporte de convergencia.**
El sistema DEBE estimar `(mu, gamma, rho, att, def)` maximizando la log-verosimilitud
ponderada por `w_i` mediante `scipy.optimize.minimize` con método `L-BFGS-B`, punto
inicial determinista (fijo, documentado en `design.md`) y `rho` acotado, y DEBE
registrar el resultado de convergencia (`success`, iteraciones, mensaje, valor del
objetivo). El valor de la función objetivo vectorizada DEBE coincidir (tolerancia
1e−9) con una referencia calculada partido a partido con la misma fórmula.
SI el optimizador no converge, ENTONCES el sistema DEBE registrar
`convergencia.success = False`, emitir un warning, y NO abortar (los parámetros
quedan disponibles con el flag visible).

**R7 — Identificabilidad.**
Tras el ajuste, el sistema DEBE garantizar `sum(att) = 0` y `sum(def) = 0`
(tolerancia 1e−8) mediante la reparametrización descrita en `design.md`.

**R8 — Universo de equipos y equipos con pocos partidos.**
El sistema DEBE asignar parámetros `att`/`def` a TODOS los equipos presentes en el
recorte temporal de entrenamiento (incluidos códigos slug fuera de las 48).
DONDE un equipo tenga menos de `min_matches` (default 5) partidos en el recorte, el
sistema DEBE incluirlo igualmente en el ajuste, listarlo en `low_data_teams` de los
parámetros persistidos, y sus coeficientes DEBEN quedar contraídos hacia 0 por la
penalización L2 configurable (`reg_lambda`): a mayor `reg_lambda`, menor magnitud
de `att`/`def` para ese equipo.

**R9 — Recuperación de parámetros en datos sintéticos (sanidad estadística).**
CUANDO se entrena sobre partidos sintéticos generados desde el propio modelo
(marcadores muestreados de la matriz conjunta con parámetros verdaderos conocidos,
semilla fija, ≥ ~1900 partidos, `xi = 0`, `reg_lambda = 0`), el sistema DEBE recuperar
los parámetros verdaderos dentro de las tolerancias holgadas documentadas en
`design.md` (|Δmu| ≤ 0.05, |Δgamma| ≤ 0.05, |Δrho| ≤ 0.1, max|Δatt| ≤ 0.15,
max|Δdef| ≤ 0.15).

**R10 — Determinismo de reentrenamiento.**
CUANDO se entrena dos veces con la misma entrada y la misma configuración, el sistema
DEBE producir parámetros idénticos (diferencia ≤ 1e−12 por coeficiente): sin RNG,
sin reloj, punto inicial fijo, orden de datos y de equipos determinista.

## Persistencia de parámetros

**R11 — Serialización JSON round-trip.**
El sistema DEBE persistir los parámetros en `data/gold/dixon_coles_params.json` (ruta
parametrizable) con al menos las claves del contrato: `as_of_date, from_date, xi, mu,
home_advantage, rho, attack (dict código → float), defense (dict código → float),
n_matches, convergencia`, y DEBE poder cargarlos para predecir **sin reentrenar**:
guardar → cargar DEBE devolver parámetros idénticos y producir exactamente las mismas
predicciones que los parámetros originales.

**R12 — Error con parámetros sin entrenar.**
SI se intenta cargar parámetros desde un archivo inexistente o un JSON que no cumple
el contrato (claves ausentes), ENTONCES el sistema DEBE fallar con `NotFittedError`
claro (ruta y motivo), sin predecir.

## Predicción

**R13 — Localía en predicción SOLO para anfitrionas.**
CUANDO se predice un partido del Mundial 2026, el sistema DEBE aplicar `h = 1` SOLO SI
el equipo local es anfitriona (`is_host` de `src/ingestion/teams.py`: MEX/USA/CAN) y
`h = 0` en cualquier otro partido (sede neutral para el resto); `gamma` NO DEBE
afectar a `lambda_away` en ningún caso.

**R14 — Matriz conjunta de marcadores.**
El sistema DEBE producir la matriz `P(X = x, Y = y)` para `x, y ∈ {0..max_goals}`
(default 10, configurable) con la corrección τ aplicada y renormalizada, de modo que
la matriz sume 1 (tolerancia 1e−9), y DEBE exponerla en la salida de predicción
(la feature 4 de mercados la reutilizará).

**R15 — τ modifica solo marcadores bajos.**
DONDE `rho ≠ 0`, la matriz conjunta (antes de renormalizar) DEBE diferir de la matriz
con `rho = 0` ÚNICAMENTE en las celdas `(0,0), (0,1), (1,0), (1,1)`; el resto de
celdas DEBEN ser idénticas, y la matriz final renormalizada DEBE seguir sumando 1
(tolerancia 1e−9).

**R16 — Probabilidades 1X2 y lambdas esperadas.**
El sistema DEBE derivar de la matriz conjunta `prob_home` (suma de celdas con
`x > y`), `prob_draw` (`x = y`) y `prob_away` (`x < y`), que DEBEN sumar 1
(tolerancia 1e−9), y DEBE exponer en la salida las tasas esperadas
`lambda_home` y `lambda_away` del partido.

**R17 — Top-k marcadores más probables.**
El sistema DEBE devolver los `k` marcadores más probables (default 5, configurable)
en orden descendente de probabilidad, con desempate determinista por
`(home_goals, away_goals)` ascendente.

**R18 — Equipo desconocido en predicción.**
SI un código de equipo solicitado no existe en `attack`/`defense` de los parámetros
cargados, ENTONCES el sistema DEBE fallar con `UnknownTeamError` que incluya el
código desconocido.
