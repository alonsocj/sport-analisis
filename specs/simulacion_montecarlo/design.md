# design.md — Feature 13: simulacion_montecarlo

## Arquitectura

Paquete nuevo `src/simulation/` (lógica pura) + extensión mínima de `src/cli.py`
(subcomando `simulate`). Reusa `src/models/dixon_coles.py` (λ y matriz de
marcadores), el silver (resultados reales) y el bronze (fixtures). Opcionalmente el
factor jugadores (feature 11). SIN librería nueva (numpy basta).

| Módulo                          | Responsabilidad                                                  | Requisitos |
|---------------------------------|------------------------------------------------------------------|------------|
| `src/simulation/__init__.py`    | Paquete vacío.                                                    | —          |
| `src/simulation/bracket.py`     | Derivación de grupos desde fixtures, formato 48/12×4, mapeo del bracket eliminatorio. | R1, R5 |
| `src/simulation/standings.py`   | Tabla de grupo (3/1/0), desempates, top-2 + 8 mejores terceros. | R4         |
| `src/simulation/montecarlo.py`  | Muestreo de marcadores (RNG con seed), bucle de N simulaciones, agregación. | R2, R3, R6 |
| `src/simulation/report.py`      | Escritura determinista summary.json/advancement.csv.            | R7         |
| `src/cli.py` (extensión)        | Subcomando `simulate`.                                           | R8, R9     |

Flujo:

```
bronze fixtures ─► bracket.derive_groups (grafo de enfrentamientos)  ─► 12 grupos × 4   (R1)
modelo (v2|v1, as_of) ─► por cada par: λ_home, λ_away (+roster opc.)  ─► matrices DC     (R2,R9)
montecarlo.run(N, seed):
   por sim:
     partidos de grupo:  jugado → marcador real ; pendiente → muestreo DC               (R2,R3)
     standings ─► top2 + 8 mejores terceros                                              (R4)
     bracket R32→R16→QF→SF→Final: muestreo por cruce (empate → Bernoulli por P_victoria) (R5)
     registrar ronda alcanzada por selección
   agregación ─► P(avance), P(R16..Final), P(título), error MC                           (R6)
report.write ─► data/reports/simulacion/{summary.json, advancement.csv}                  (R7)
```

## Derivación de grupos y bracket (R1, R5)

- **Grupos**: construir grafo no dirigido equipo–equipo desde los 72 fixtures de
  grupo; las componentes conexas deben ser 12 cliques de 4 → grupos A..L (etiqueta
  por orden alfabético del primer equipo, determinista). Validar 12×4 o error.
- **Bracket**: mapeo documentado y parametrizable de las 32 plazas (ganadores,
  segundos y 8 mejores terceros) a las llaves de R32, siguiendo la estructura FIFA
  2026 (tabla en el módulo). El emparejamiento exacto es configurable; el default se
  documenta. La asignación de los 8 terceros a llaves usa la tabla combinatoria
  estándar (documentada/configurable).

## Muestreo y determinismo (R3)

- RNG: `numpy.random.default_rng(seed)` con **seed inyectada** (argumento, no reloj).
- Marcadores: muestreo desde la matriz de probabilidad de marcadores Dixon-Coles del
  partido (reusa `score_matrix`), o muestreo Poisson independiente con la corrección
  rho aplicada a los marcadores bajos (método documentado). λ por partido se
  precomputa una vez (no por simulación) para rendimiento (R10).
- Test de determinismo: misma seed + misma entrada → agregados idénticos.

## Desempates de grupo (R4)

Orden documentado y determinista: (1) puntos, (2) diferencia de goles global,
(3) goles a favor, (4) criterio final reproducible (p.ej. orden por fuerza de
ataque del modelo o índice estable) para romper empates residuales sin azar oculto.
Selección de **terceros**: ranking global de los 12 terceros por los mismos
criterios; entran los 8 mejores. Simplificaciones respecto al reglamento FIFA
completo (head-to-head, fair-play) se DOCUMENTAN explícitamente.

## Agregación e incertidumbre (R6)

- Contadores por selección y ronda / N. Error MC ≈ `sqrt(p(1−p)/N)` por probabilidad
  reportada (columna en el reporte). Con N=10 000, error típico ~0.5 pp.

## CLI (R8, R9)

- `simulate [--n 10000] [--seed 42] [--as-of <fecha>] [--model-version dc-v1|dc-v2]
  [--roster <csv>] [--out data/reports/simulacion]`. Imprime top-N por P(título) +
  ruta del reporte. Exit `0/1/2`. Aserción de subcomandos al conjunto exacto.
- `--roster` (R9): aplica el multiplicador de ataque del factor jugadores (feature
  11) a las λ antes de muestrear; sin él, modelo base.

## Decisiones y justificación

- **Resultados reales fijos para lo ya jugado**: la simulación parte del estado real
  del torneo (jornada 1), no re-simula lo conocido → tendencias condicionadas a lo
  ocurrido, que es lo que pidió el usuario.
- **λ precomputadas**: 10 000 sims × 72 partidos de grupo + bracket es barato si las
  matrices/λ se calculan una sola vez por par (R10).
- **Seed inyectada**: reproducibilidad total (alineado con la regla anti-reloj del
  proyecto); el usuario puede variar la seed para sensibilidad.
- **Bracket parametrizable**: el emparejamiento FIFA exacto puede ajustarse sin
  tocar el motor de simulación.

## Fuera de alcance

Reglas de desempate FIFA completas (head-to-head múltiple, fair-play, sorteo);
prórroga/penales con modelo dedicado (se usa Bernoulli por fuerza); apuestas/ROI
sobre la simulación; visualización en la app (futuro opcional).
