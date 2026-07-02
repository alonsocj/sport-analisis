---
name: feature13-simulacion-montecarlo-completada
description: Feature 13 simulacion_montecarlo completada — Monte Carlo WC2026, 41 tests nuevos, 337 total, 12 subcomandos CLI.
metadata:
  type: project
---

Feature 13 `simulacion_montecarlo` completada (última del roadmap v2).

**Artefactos creados:**
- `src/simulation/__init__.py` — paquete vacío
- `src/simulation/bracket.py` — derivación de 12 grupos desde grafo de fixtures; mapeo bracket R32→Final; validación 12×4
- `src/simulation/standings.py` — tabla 3/1/0; desempates: puntos→DG→GF→fuerza_ataque→alfabético; ranking 12 terceros
- `src/simulation/montecarlo.py` — precomputo λ/matrices una vez; RNG `numpy.random.default_rng(seed)` inyectado; bucle N sims; agregación P(ronda) + SE=sqrt(p(1-p)/N)
- `src/simulation/report.py` — summary.json (sort_keys) + advancement.csv bajo data/; reusa `_assert_under_data`
- `src/cli.py` extendido — subcomando `simulate` (12°); funciones `cmd_simulate` + parser
- `tests/test_simulacion.py` — 33 tests (R1–R10)
- `tests/test_cli_simulate.py` — 8 tests (R8, subcomandos exactos)

**Suite:** 337 total (41 nuevos), 100% verde, 0 warnings nuevos.

**Decisiones técnicas:**
- Grupos: BFS sobre grafo de adyacencia, cliques de 4; etiquetas A..L por orden alfabético del primer equipo.
- Bracket: 12 directas (1°vs2° cross-bracket) + 4 llaves de terceros entre sí (terceros[0]vs[7], [1]vs[6], [2]vs[5], [3]vs[4]). Simplificación documentada: no modela sorteo FIFA geográfico.
- Empate en eliminatoria: Bernoulli P(home|draw) = prob_home/(prob_home+prob_away). Documentado.
- Precomputo: solo fixtures pendientes (None scores); matrices DC + λ calculadas 1 sola vez.
- MIN_N_SIMULATIONS = 1000 respetado; tests usan 1000 (suficientemente rápidos con equipos sintéticos).
- Tests previos que hardcodeaban 11 subcomandos actualizados a 12: test_cli.py, test_cli_eval.py, test_cli_scorers.py.

**Simplificaciones documentadas (fuera de alcance):**
- Head-to-head entre empatados en la tabla de grupo: no implementado.
- Fair-play (tarjetas): no implementado.
- Sorteo FIFA por zonas geográficas en R32: no implementado.
- Tabla combinatoria exacta de terceros (495 combinaciones): terceros se enfrentan entre sí en orden de ranking.

**Why:** última feature del roadmap v2; cierra el proyecto con simulación completa del torneo.
**How to apply:** para el cierre, ejecutar `simulate --n 10000 --seed 42` con el modelo dc-v1 entrenado.
