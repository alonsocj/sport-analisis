---
name: feature21-roster-fotmob-completada
description: Feature 21 roster_fotmob implementada — scraper fotmob R32, ingest-roster CLI, panel knockouts con filtro de bajas. 25 tests nuevos, 519 total, 15 subcomandos CLI.
metadata:
  type: project
---

Feature 21 `roster_fotmob` implementada (T1–T5). Suite verde 519/519, init.sh verde.

**Archivos creados:**
- `src/ingestion/roster.py` — scraper fotmob con injectable transport, bronze+meta pattern, FOTMOB_ALIASES, normalize_rosters
- `tests/test_ingest_roster.py` — 8 tests R1/R4/R5
- `tests/test_roster_normalize.py` — 6 tests R2
- `tests/test_app_knockouts_roster.py` — 11 tests R3

**Archivos modificados:**
- `src/cli.py` — añadido `ingest-roster` subcommand + `cmd_ingest_roster` (15 subcomandos total)
- `src/app/tabs/knockouts.py` — añadido `_load_rosters`, `_load_unavailable`, `_filter_and_renormalize`; extendido `_compute_analisis_data` con `rosters_csv_str`/`unavailable_csv_str`
- Tests previos de subcomandos exactos actualizados en 7 archivos (14→15)

**Decisiones clave:**
- FOTMOB_ALIASES: mapeo supplementario para nombres que fotmob usa distintos (Korea Republic, Côte d'Ivoire, Congo DR, USA)
- Cache key: `rosters_csv_str`/`unavailable_csv_str` como strings (hashable para @st.cache_data)
- Degradación: file ausente → `{}` → sin filtro; transport error → warn+skip; equipo sin mapeo → warn+discard
- Rate-limit: sleeper ANTES del fetch, ≥1 req/2s en producción, sleeper=None en tests

**Pendiente (requiere OK usuario):**
- T6: Review trazabilidad
- T7: Dictamen security-lead
- T8: Validación real (ingest-roster sobre R32 con red fotmob)
- T9: Actualizar feature_list.json, progress/current.md, README.md, MEMORY.md

**Why:** Feature 21 es bloque v4 del roadmap — rosters R32 para refinar predicciones con bajas reales.
**How to apply:** Para T8, necesita OK explícito del usuario antes de hacer llamadas reales a fotmob.
