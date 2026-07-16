# requirements.md — Feature 34: final_tercer_puesto (Final + 3er puesto WC2026)

Objetivo: cerrar el torneo. Exponer en el pipeline y la app la **Final** (Round of 2) y el
**partido por el 3er puesto**, y añadir un **simulador Monte Carlo de un enfrentamiento fijo**
que produzca un resultado preciso (P(ganador), marcador modal, camino 90'/prórroga/penales y
mercados) para cada uno de esos dos partidos.

Contexto (medido en el repo, 2026-07-15): el silver termina en cuartos (07-11). Las semis
(FRA-ESP 14-jul, ENG-ARG 15-jul) NO están ingestadas → los finalistas y la pareja del 3er
puesto se resuelven con la data update de semis (pre-requisito operativo, regla STOP para el
scrape real). El módulo `simulation/montecarlo.py` simula el torneo completo (grupos→campeón)
y **no tiene nodo de 3er puesto** ni simulación de un cruce fijo aislado: esta feature lo añade.

Motivación del usuario (LEADER): modelar la Final y la lucha por el 3er puesto; el 3er puesto
se juega "sin ánimos / de trámite" → debe recibir un **factor de amortiguación de motivación
explícito** (dead-rubber), apagado por defecto en todo lo demás.

Principio de no-regresión: la feature es **aditiva y aislada**. El motor 1X2/marcador actual,
los subcomandos previos y las 6 pestañas existentes NO cambian. Con el flag dead-rubber OFF y
sin invocar el simulador nuevo, todas las salidas previas son byte-idénticas.

Notación EARS. Cada `R<n>` mapea a ≥1 test en `tests/test_final_tercer_puesto.py`
(salvo indicación de fichero distinto).

---

**R1 — Fixtures de Final y 3er puesto.**
El sistema DEBE emitir `data/knockouts/r2_fixtures.csv` (etapa `Final`, ordinal 5) y
`data/knockouts/r3p_fixtures.csv` (etapa `3P`, 3er puesto) con el MISMO esquema que
`r32/r16/r8/r4_fixtures.csv` (`draw_order,date,stage,home_code,away_code,source`). Sólo se
escriben partidos con AMBOS códigos FIFA resueltos; los `TBD`/`Winner SF x` se omiten (no se
fuerza código inválido). Los ordinales/etapas previos siguen escribiéndose intactos.

**R2 — Detección del 3er puesto en la estructura fotmob.**
El sistema DEBE distinguir el partido por el 3er puesto de la Final aunque fotmob los exponga
en la MISMA ronda (`playoff.rounds` puede traer, en la última ronda, dos matchups: 3er puesto
y Final). La clasificación DEBE ser determinista: por etiqueta de fotmob si existe, o por
emparejamiento (el 3er puesto enfrenta a los dos perdedores de semis; la Final a los dos
ganadores). Un `KoMatch` del 3er puesto DEBE quedar marcado con `stage == "3P"` y NO
contaminar el fixture de la Final.

**R3 — Amortiguación dead-rubber determinista.**
El sistema DEBE exponer `apply_dead_rubber(...)` que, dados los parámetros de fuerza de dos
equipos, (a) **encoja** la desviación de ataque/defensa de cada equipo hacia la media por un
factor `delta ∈ [0,1]` (aplana la ventaja del favorito) y (b) aplique un **bump de apertura**
`kappa ≥ 1` sobre ambas λ (los partidos de trámite marcan más). DEBE ser determinista y
documentado. Con `delta=0, kappa=1` (OFF) el resultado es byte-idéntico al baseline. Con ON:
`E[goles_totales]_ON ≥ E[goles_totales]_baseline` y `P(gana_favorito)_ON ≤ P(gana_favorito)_baseline`.
Los defaults se documentan con su base histórica (partidos de 3er puesto de Mundiales marcan
más goles por partido que las finales).

**R4 — Simulador Monte Carlo de un enfrentamiento fijo.**
El sistema DEBE ofrecer `simulate_fixture(home, away, params, n, seed, form_factor=None,
dead_rubber=None) -> MatchSimResult` que, muestreando N veces de la matriz Dixon-Coles del
cruce (fuente analítica; reusa `score_matrix`/`sample_score`), agregue: `p_home`, `p_away`
(probabilidad de ganar el enfrentamiento, incluida resolución de empate), reparto del camino
(`p_reg`, `p_et`, `p_pens`), marcador **modal de 90'** y top-k marcadores 90' con su
probabilidad, `e_goals`, mercados (over/under 1.5/2.5/3.5, BTTS) y **error MC** por métrica.
DEBE ser determinista dado `seed` (RNG inyectado, nunca del reloj) y validar `n ≥ MIN` salvo
flag interno de tests.

**R5 — Empate → prórroga → penales.**
El sistema DEBE resolver el empate de 90' del simulador (R4) muestreando un **tiempo extra**
fresco de 30' (λ escaladas ×1/3) y, si persiste el empate, **penales** por Bernoulli ponderada
por la fuerza del modelo (`p_home/(p_home+p_away)`), coherente con
`simulate_elimination_match`. El camino recorrido (regular/ET/penales) DEBE contabilizarse
para el reparto de R4.

**R6 — Artefactos de predicción.**
El sistema DEBE persistir el resultado agregado del simulador en
`data/predictions/final_sim.csv` y `data/predictions/r3p_sim.csv` con un esquema estable
(equipos, p_home/p_away, camino, marcador modal, top-k, e_goals, mercados, n, seed). Escritura
sólo bajo `data/`.

**R7 — CLI.**
El sistema DEBE añadir un subcomando `simulate-match` que, dado un fixture (`--fixture r2|r3p`
o `--home/--away`), ejecute R4 con los parámetros entrenados (forma-xG γ configurable;
`--dead-rubber` opcional), escriba R6 e imprima una tabla legible. Los subcomandos previos
DEBEN permanecer EXACTAMENTE intactos (mismo conjunto).

**R8 — Interruptor + no-regresión.**
El flag `--dead-rubber` DEBE estar OFF por defecto. Con OFF y sin invocar el simulador nuevo,
el conjunto EXACTO de salidas previas (predict/markets/simulate/ingest/train y sus subcomandos)
permanece idéntico. Ningún test previo (686) se rompe.

**R9 — App: pestaña Final.**
La app DEBE añadir UNA pestaña nueva `🏆 Final` que contenga DOS bloques —Final (`state_key=r2`)
y 3er puesto (`state_key=r3p`)— cada uno con el detalle de predicción KO existente
(`render_knockouts`) MÁS un panel "Simulación Monte Carlo" (P(ganador), top marcadores 90',
reparto 90'/ET/penales, mercados). La amortiguación dead-rubber DEBE aplicarse SÓLO al bloque
del 3er puesto. Las pestañas previas (6) permanecen intactas → 7 pestañas de contenido.

---

## Trazabilidad R<n> → test (a completar por el Implementer)

Cada R1–R9 con ≥1 test en `tasks.md`. Sin test → rechazo del Reviewer.
