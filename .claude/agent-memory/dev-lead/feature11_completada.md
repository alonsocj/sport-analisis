---
name: feature11-players-completada
description: Feature 11 factor de jugadores implementada — ingest-goalscorers, scorers, 46 tests nuevos, 273 total, 11 subcomandos CLI.
metadata:
  type: project
---

Feature 11 `players` implementada y en verde (2026-06-17).

**Why:** Añadir factor de jugadores (goleadores) como señal adicional al modelo Dixon-Coles del Mundial 2026.

**Archivos creados:**
- `src/ingestion/goalscorers.py` — Ingesta CC0 con transporte inyectable, validación de encabezado exacto, bronze + meta.json (R1)
- `src/players/__init__.py` — Paquete vacío (R2)
- `src/players/normalize.py` — Bronze → silver de eventos: excluye own_goals, mapea team→código FIFA, descarta malformados con motivo (R2)
- `src/players/factor.py` — Cuotas/tasas con decaimiento ξ, anti-fuga, anytime-scorer (thinning Poisson), multiplicador de ataque por roster, artefacto gold determinista (R3–R6)
- `tests/fixtures/goalscorers_sample.csv` — Fixture con 15 filas
- `tests/test_goalscorers_ingest.py` — 8 tests R1
- `tests/test_player_factor.py` — 22 tests R2–R6, R8
- `tests/test_cli_scorers.py` — 16 tests R7

**Archivos modificados:**
- `src/cli.py` — Añade `cmd_ingest_goalscorers`, `cmd_scorers`, extiende `cmd_build_features` para player_factor.csv, añade 2 subcomandos (9→11)
- `tests/test_cli.py` — Actualizado a 11 subcomandos
- `tests/test_cli_eval.py` — Actualizado EXPECTED_SUBCOMMANDS a 11

**Decisiones técnicas clave:**
- `test_sin_reloj_en_build_player_rates` usa `inspect.getsource` porque `datetime.datetime.now` es inmutable en Python 3.13 y no puede parchearse
- `build-features` omite player_factor sin romper el flujo (usa `except Exception` amplio deliberadamente)
- `cmd_scorers` construye tasas al vuelo desde el bronze si no existe el gold precalculado

**Suite:** 273 tests, 0 fallos. Sin librerías nuevas.

**Subcomandos (11):** ingest-public, build-features, train, predict, schedule, markets, backtest, predict-log, evaluate, ingest-goalscorers, scorers.

**How to apply:** Si se trabaja sobre el CLI, el conjunto exacto de subcomandos ahora es 11. Los tests test_cli.py y test_cli_eval.py reflejan este conjunto.
