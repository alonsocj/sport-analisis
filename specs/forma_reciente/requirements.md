# requirements.md — Feature 16: forma_reciente

Objetivo: incorporar una señal de **forma reciente de ventana corta** que ajuste la
fuerza prospectiva del modelo ganador **v1 (Dixon-Coles)** para predecir los
**próximos partidos del Mundial 2026** (las últimas jornadas de grupos pendientes y,
una vez resueltos los standings, los cruces de eliminación). Por equipo se toma una
ventana de **hasta 3 partidos de la fase de grupos WC2026 + los últimos K partidos
pre-Mundial** (K default 5), se derivan métricas de forma **ponderadas por recencia
y calidad de rival**, y se traducen en un **factor multiplicativo** sobre las
intensidades (λ) del Dixon-Coles. Mejora orientada a la PREDICCIÓN futura, no a
retrodecir un partido con su propia información.

Principio de no-regresión: con peso de forma `γ = 0` el modelo reproduce v1 EXACTO
(test de equivalencia, tol 1e-9). Default `γ = 0` ⇒ la feature nace OFF y se activa
solo si bate al baseline en el harness F10.

Encuadre de datos (verificado 2026-06-28, post-scrape): la fuente pública martj42
tiene **60/72** partidos de grupo con marcador; los **12 últimos (J3, 26-27 jun)
están `NA`** → 24 equipos con solo 2 partidos de grupo en la ventana, y el bracket
R32 (derivado de standings en `src/simulation/bracket.py`) **aún no es determinable**.
La feature DEBE funcionar con ventana parcial y degradar con elegancia.

Limitación honesta (riesgo aceptado): la ventana es **muestra chica y ruidosa** (≤8
partidos/equipo, 24 equipos con ≤7); los partidos pre-WC son amistosos/clasificatorios
de **calidad de rival heterogénea**. El ajuste por Elo del rival (R3) mitiga en parte,
pero la potencia estadística es limitada; por eso default OFF y medición obligatoria.
**No hay stats avanzadas por partido** (tiros/posesión) para WC2026 — Wikipedia da 0%
cobertura (ver Feature 15) —; las métricas se limitan a goles, resultado y Elo.

Notación EARS. Cada `R<n>` mapea a ≥1 test en `tests/test_forma_reciente.py`,
`tests/test_form_factor.py` o `tests/test_cli_form.py` (ver `tasks.md`).

---

**R1 — Ventana corta por equipo, leak-free.**
El sistema DEBE construir, por equipo y para una fecha de corte `as_of` INYECTADA, una
ventana ordenada por fecha con: (a) hasta 3 partidos de grupo `tournament == "FIFA
World Cup"` de WC2026 con `fecha < as_of`, y (b) los últimos `K` partidos pre-Mundial
(`fecha < 2026-06-11`, default `K = 5`) con `fecha < as_of`. La condición `fecha <
as_of` es estricta: el partido a predecir NUNCA entra en su propia ventana. SI un
equipo no tiene partidos en algún tramo, la ventana se forma con los disponibles (sin
abortar).

**R2 — Métricas de forma deterministas, ponderadas por recencia.**
El sistema DEBE derivar por equipo, a partir de la ventana, métricas DETERMINISTAS y
DOCUMENTADAS: goles a favor/contra promedio, diferencia de goles, puntos por partido
(3/1/0) y racha de resultados, cada una agregada con **pesos de recencia exponenciales**
(el más reciente pesa más) y con un **tier separado** para partidos de grupo WC vs
pre-WC (los de grupo pesan ≥ que los amistosos). Los parámetros (decay, ratio de tier)
son explícitos y versionados; sin lectura de reloj (`as_of` inyectado).

**R3 — Ajuste por calidad de rival (Elo externo).**
El sistema DEBE ponderar la señal de cada partido de la ventana por la **fuerza del
rival** usando el Elo externo (`data/gold/external_elo.csv`, Feature 14): un resultado
ante un rival fuerte aporta más que ante uno débil. El método es determinista y
documentado. SI falta el Elo de un rival → peso neutro para ese partido (no aborta).

**R4 — Factor de forma sobre λ del Dixon-Coles + no-regresión + anti-fuga.**
El sistema DEBE traducir las métricas de forma en un **factor multiplicativo** sobre
las intensidades del Dixon-Coles en la predicción: `λ' = λ_DC · exp(γ · f_team)`, donde
`f_team` es la componente de forma estandarizada (z) entre las 48 selecciones y
`γ ∈ [0,1]` es el peso de forma. Con `γ = 0` la predicción es IDÉNTICA a v1 (tol 1e-9).
La forma de un partido NUNCA se usa para predecir ESE partido (anti-fuga garantizada
por `fecha < as_of` de R1). El factor NO reentrena el Dixon-Coles: lo ajusta en
inferencia (no toca `src/models/dixon_coles.py` salvo punto de extensión limpio).

**R5 — Medición walk-forward vs v1 (harness F10).**
El sistema DEBE permitir evaluar el efecto de `γ` con el harness de backtest/Feature 10
sobre los partidos WC2026 disponibles, reportando v1 vs v1+forma con métricas
comparables (Brier 1X2, log-loss, accuracy). DEBE documentar que la ventana corta y la
cobertura parcial limitan la potencia; el criterio de adopción es **batir a v1**.

**R6 — CLI.**
El sistema DEBE exponer un flag `--form-weight <γ>` (default `0`) en `predict`,
`backtest` y `simulate`, que activa el factor de forma sin reentrenar. El conjunto
EXACTO de subcomandos previos DEBE permanecer intacto (sin añadir ni quitar
subcomandos). Salida texto `✅` / `--json` consistente con el resto del CLI.

**R7 — Determinismo, sin red, degradación, sin libs nuevas.**
Tests 100% offline con fixtures de silver/Elo; `as_of` inyectado (sin reloj en lógica
predictiva); escritura solo bajo `data/`; equipo con ventana vacía → factor neutro
(`1.0`, comportamiento v1); rival sin Elo → peso neutro; sin dependencias nuevas más
allá del stack actual (pandas/numpy/scipy).
