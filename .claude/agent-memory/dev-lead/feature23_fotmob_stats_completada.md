---
name: feature23-fotmob-stats-completada
description: Feature 23 fotmob_stats completada — ingesta stats fotmob + silver merge, 24 tests nuevos, 556 total, 16 subcomandos CLI
metadata:
  type: project
---

Feature 23 (`fotmob_stats`) implementada y verificada. 556 tests, 0 fallos.

**Why:** Fundación de datos (xG, corners, cards, shots, possession) para futuros mercados de betting. NO implementa mercados.

**Archivos creados/modificados:**
- `src/ingestion/fotmob_stats.py` — scraper fotmob con transporte inyectable, bronze+meta, normalize_stats
- `src/features/silver.py` — `home_xg`/`away_xg` añadidos a STAT_COLUMNS; `_load_fotmob_stats_index` + `_apply_fotmob_stats` merge por (date,home_code,away_code)
- `src/cli.py` — subcomando `ingest-fotmob-stats` (16 total)
- `tests/test_ingest_fotmob_stats.py` — 15 tests offline (R1-R4)
- `tests/test_silver_fotmob_stats.py` — 9 tests offline (R3)
- `tests/test_ingest_roster.py` — EXPECTED_SUBCOMMANDS_F21 actualizado a 16
- `tests/test_cli.py`, `test_cli_elo.py`, `test_cli_eval.py`, `test_cli_form.py`, `test_cli_scorers.py`, `test_cli_simulate.py`, `test_cli_xg.py` — conteos actualizados de 15→16 subcomandos

**Decisiones técnicas:**
- Merge silver por `(date, home_code, away_code)` porque fotmob match_id ≠ silver match_id
- `pd.to_numeric(..., errors="coerce")` antes de asignar para evitar TypeError en pandas 2.x con object arrays conteniendo NaN
- Solo rellenar stats donde silver es null Y fotmob tiene valor (preserva api_football)
- xG siempre de fotmob (era null antes)
- Sin bronze fotmob_stats/ → silver idéntico al anterior (no-regresión)

**How to invoke:**
```bash
python -m src.cli ingest-fotmob-stats  # usa league_id=77, bronze en data/bronze/fotmob_stats/
python -m src.cli build-features       # incorpora stats fotmob si el bronze existe
```

**Deuda técnica:**
- FOTMOB_STATS_ALIASES puede necesitar actualizaciones si fotmob cambia nombres de equipos
- No hay test de integración real (por diseño: 100% offline); el scraping real lo corre el LEADER
