# requirements.md — Feature 13: simulacion_montecarlo

Objetivo: simular el **Mundial 2026 completo** muchas veces (default 10 000, ≥1000)
para estimar tendencias: probabilidad de **avanzar de grupo**, de alcanzar cada
ronda eliminatoria y de **ganar el título** por selección. Usa el mejor modelo
disponible (v2 si existe, si no v1) y, DONDE exista, el factor jugadores (feature
11). Los partidos ya jugados (jornada 1) usan resultados reales; los pendientes se
muestrean de la distribución Dixon-Coles.

Formato 2026 (verificado en el dataset): 48 selecciones, 12 grupos de 4 (round-
robin, 72 partidos de grupo), avanzan los 2 primeros de cada grupo (24) + los 8
mejores terceros → 32 → R32 → R16 → Cuartos → Semis → Final.

Notación EARS. Cada `R<n>` mapea a ≥1 test en `tests/test_simulacion.py` o
`tests/test_cli_simulate.py` (ver `tasks.md`).

---

**R1 — Derivación de grupos y calendario desde datos.**
El sistema DEBE derivar los 12 grupos y los 72 partidos de grupo del Mundial 2026 a
partir de los fixtures del bronze (agrupando por el grafo de enfrentamientos:
componentes de 4 selecciones que se juegan entre sí), SIN hardcodear los resultados
ni los grupos. SI la estructura no es 12×4 → error accionable.

**R2 — Resultados reales + simulación de pendientes.**
CUANDO un partido de grupo ya tiene marcador real en el silver, la simulación DEBE
usar ese marcador fijo; los pendientes DEBEN simularse muestreando la distribución
del partido. El modelo usado DEBE entrenarse con `as_of` inyectado (anti-fuga).

**R3 — Muestreo de marcadores reproducible.**
El sistema DEBE muestrear marcadores desde la distribución del modelo
(Poisson/Dixon-Coles con corrección rho de marcadores bajos) usando un RNG con
**seed INYECTADA** (no reloj). Un test DEBE verificar determinismo: misma seed →
mismos agregados (byte a byte).

**R4 — Clasificación de grupos con desempates.**
El sistema DEBE calcular la tabla de cada grupo con puntos (3/1/0) y desempates
documentados y deterministas (diferencia de goles, goles a favor, y un criterio
final reproducible para empates residuales), seleccionando 2 primeros por grupo + 8
mejores terceros (ranking de terceros documentado).

**R5 — Bracket eliminatorio.**
El sistema DEBE construir el bracket (R32 → R16 → Cuartos → Semis → Final) según un
mapeo DOCUMENTADO (y parametrizable) y simular cada cruce; un empate en eliminatoria
DEBE resolverse por la probabilidad de victoria del modelo para ese cruce (método
documentado, p.ej. prórroga/penales como Bernoulli ponderada por fuerza).

**R6 — Agregación Monte Carlo.**
Con `N` simulaciones (default 10 000, parametrizable, mínimo 1000), el sistema DEBE
estimar por selección: P(avanzar de grupo), P(R16), P(Cuartos), P(Semis), P(Final)
y P(título). DEBE reportar también una medida de incertidumbre acorde a `N`
(p.ej. error estándar de Monte Carlo).

**R7 — Reporte determinista en disco.**
El sistema DEBE escribir `data/reports/simulacion/{summary.json (sort_keys),
advancement.csv}` con orden determinista (p.ej. por P(título) desc). Misma seed/
entrada → mismo contenido byte a byte. Escritura solo bajo `data/`.

**R8 — CLI `simulate`.**
El sistema DEBE exponer `simulate [--n 10000] [--seed 42] [--as-of <fecha>]
[--model-version dc-v1|dc-v2] [--out <dir>]` que corre la simulación, escribe el
reporte e imprime un top-N por P(título). Exit codes `0/1/2`. El conjunto EXACTO de
subcomandos previos DEBE permanecer intacto (más `simulate`).

**R9 — Uso opcional del factor jugadores.**
DONDE exista el artefacto del factor jugadores (feature 11) y se aporte un roster,
el sistema DEBE poder aplicar el multiplicador de ataque por equipo a la λ antes de
muestrear. SIN ello, la simulación corre con el modelo base intacto.

**R10 — Rendimiento, determinismo y sin lib nueva.**
10 000 simulaciones DEBEN completar en tiempo razonable (objetivo orientativo
≤ ~30 s) reusando matrices/λ precomputadas por partido. Sin red, sin reloj, sin
dependencias nuevas (numpy basta).
