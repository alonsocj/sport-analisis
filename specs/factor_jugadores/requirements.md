# requirements.md — Feature 11: factor_jugadores

Objetivo: incorporar **rendimiento de jugadores** al pipeline usando exclusivamente
la fuente CC0 `goalscorers.csv` (mismo repo martj42, SIN cuota). Entrega: tasas/
cuotas de gol por jugador (con decaimiento temporal y anti-fuga), probabilidad
**anytime-scorer** por partido derivada de la λ del Dixon-Coles, y un **enganche de
ajuste de ataque por disponibilidad** (roster opcional) por el que el rendimiento
de jugadores alimenta el modelo y la simulación (features 12 y 13).

Límite explícito de la fuente: `goalscorers.csv` registra EVENTOS de gol, no
minutos ni alineaciones. NO hay ratings, xG ni lesiones (eso exigiría API real,
fuera de alcance). Las tasas son por evento de gol, no per-90; el supuesto se
documenta en el design.

Notación EARS. Cada `R<n>` mapea a ≥1 test en `tests/test_goalscorers_ingest.py`,
`tests/test_player_factor.py` o `tests/test_cli_scorers.py` (ver `tasks.md`).

---

**R1 — Ingesta CC0 de goleadores a bronze.**
El sistema DEBE descargar `goalscorers.csv` del repo CC0 martj42 mediante un
transporte INYECTABLE (`url → texto CSV`), validar el encabezado EXACTO
`[date, home_team, away_team, team, scorer, minute, own_goal, penalty]` y persistir
el CSV crudo en bronze + un sidecar `*.meta.json` con `fetched_at` INYECTADO (no
reloj), `url` y `sha256`. (Reusa el patrón de `src/ingestion/public_data.py`.)

**R2 — Normalización a silver de eventos de gol.**
El sistema DEBE normalizar a una tabla silver de eventos: las filas con
`own_goal == TRUE` se EXCLUYEN del crédito al goleador (no cuentan como gol del
jugador), `penalty` se conserva como flag. Fechas ISO válidas; el equipo del
goleador se mapea a códigos consistentes con el silver de partidos. Filas
malformadas se descartan contabilizadas con motivo, sin abortar.

**R3 — Tabla de rendimiento por jugador (decaimiento + anti-fuga).**
CUANDO se calcula con `as_of_date D`, el sistema DEBE usar SOLO eventos con
`fecha < D` y producir, por (`team`, `scorer`): goles ponderados por decaimiento
exponencial (parámetro ξ inyectable, default = el del modelo) y la **cuota del
jugador** = goles_ponderados_jugador / goles_ponderados_equipo (las cuotas de un
equipo suman ≈ 1, tol 1e-9). Un test DEBE verificar la anti-fuga: eventos con
`fecha ≥ D` no cambian la tabla.

**R4 — Probabilidad anytime-scorer.**
DADA la `lambda` de ataque del equipo (del Dixon-Coles) para un partido, el sistema
DEBE estimar `lambda_jugador = cuota_jugador × lambda_equipo` y
`P(marca ≥ 1) = 1 − exp(−lambda_jugador)` (thinning de Poisson), y devolver el
top-k por equipo. El supuesto (sin minutos/alineaciones) DEBE documentarse.

**R5 — Ajuste de ataque por disponibilidad (hook, default identidad).**
DONDE se provea un roster de jugadores disponibles por equipo (CSV
`team_code,scorer`), el sistema DEBE calcular un multiplicador de ataque por equipo
= suma de cuotas de los jugadores disponibles (acotado a [0,1] y normalizado según
design), aplicable a `lambda_equipo`. SIN roster, el multiplicador DEBE ser
exactamente 1.0 (modelo intacto). Este es el único punto donde el factor jugadores
modifica el modelo; sin datos de disponibilidad NO se altera nada.

**R6 — Artefacto determinista de factor jugadores (gold).**
El sistema DEBE persistir un artefacto gold determinista con la tabla de cuotas/
tasas por jugador (apto para consumo por features 12 y 13 y por el CLI). Misma
entrada → mismo contenido byte a byte. Escritura solo bajo `data/`.

**R7 — CLI `scorers`.**
El sistema DEBE exponer `scorers --home <cod> --away <cod> [--as-of <fecha>]
[--top-k N] [--roster <csv>]` que imprime las probabilidades anytime-scorer por
partido (top-k por equipo) usando la λ del modelo. Errores accionables con exit
codes (`0/1/2`). El conjunto EXACTO de subcomandos previos DEBE permanecer intacto
(más los nuevos de esta feature).

**R8 — Determinismo, sin red y sin reloj en tests.**
Los tests DEBEN correr offline con fixtures (transporte y `as_of`/`fetched_at`
inyectados); ninguna fecha del reloj del sistema; escritura confinada a `data/`.
