---
name: feature13-qa-findings
description: Feature 13 (simulacion_montecarlo) QA findings — APROBADO CON OBSERVACIONES; 337 passed; 3 hallazgos MEDIO/BAJO; suite 50s overhead
metadata:
  type: project
---

Feature 13 `simulacion_montecarlo` aprobada con observaciones. 337 passed, 56s total.

## Hallazgos

**H1 (MEDIO)**: `test_roster_multiplicador_en_simulacion` (tests/test_simulacion.py:711) — test vacuo para R9. La aserción `p_roster >= p_base OR abs(p_roster - p_base) < 0.1` siempre pasa (tolerancia 22 SEs), incluso si el multiplicador no modifica la simulación. El test efectivo de R9 es `test_roster_aplica_multiplicador_opcional` que verifica lambda directamente.

**H2 (BAJO)**: Suite ~50s overhead por 12 llamadas a `run_simulation` con `n=MIN_N_SIMULATIONS=1000`. Cada call cuesta ~4.5s. Los tests de determinismo (R3) y roster (R9) llaman 2 veces cada uno. Patrón: tests que solo necesitan 1 simulación completa para verificar estructura/monotonía podrían usar n=50-100 inyectado como parámetro en la función pura, manteniendo el test de rendimiento con 1000.

**H3 (BAJO)**: Simplificación de bracket documentada: los 8 mejores terceros se enfrentan entre sí (4 llaves adicionales) en vez de la tabla combinatoria FIFA de 495 combinaciones. Documentado en `bracket.py` y `design.md`. Aceptable para estimación de probabilidades.

## Correctitud verificada

- Score_matrix usa corrección Dixon-Coles tau (no Poisson ingenuo): diff(0,0)=0.0157 vs Poisson puro
- Partidos jugados NO se remuestrean (R2): fixture played no entra en precomputed dict
- Suma P(champion) = 1.000000 exacto con 1000 sims (seed=42)
- Suma P(r32) = 32.00, P(r16) = 16.00, P(qf) = 8.00 — coherencia global verificada
- P(group) = 1.0 para todos los 48 equipos
- Monotonía P(r32) >= P(r16) >= ... >= P(champion) verificada para todos los equipos
- Sin libs nuevas: solo csv, dataclasses, pathlib, typing, numpy (ya en stack)
- Seed inyectada con `numpy.random.default_rng(seed)`, nunca reloj
- Escritura confinada bajo data/ via `_assert_under_data` reutilizado de feature 10

## Patrón recurrente confirmado

Test de efectividad débil en run_simulation-level (R9): patron ya visto en features 4 y 5 (CLI-level tests con condiciones siempre verdaderas). La verificación real se hace a nivel unitario (precompute_match_params) pero el test de integración es vacuo.
