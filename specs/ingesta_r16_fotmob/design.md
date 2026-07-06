# design.md — Feature 27: ingesta_r16_fotmob

## Decisiones

1. **fotmob autoritativo para KO (no martj42).** martj42 llega tarde; los KO se materializan
   desde `bronze/fotmob_stats`. Requiere capturar el marcador en el extractor (R2) porque hoy
   el JSON sólo trae stats. Alternativa rechazada: CSV intermedio de resultados (más piezas) o
   parchear martj42 (no reproducible).

2. **Reutilizar el patrón existente.** El descubrimiento del bracket y la extracción de partido
   reusan el transporte inyectable, el mapeo FIFA (`to_fifa_code` + alias) y el layout bronze
   (`<slug>.json` + `.meta.json`) de F21/F23. Sin arquitectura nueva.

3. **Materialización vs enriquecimiento en silver.** Se separa el join fotmob en dos caminos:
   (a) partido con fila martj42 → **enriquece** (comportamiento actual, intacto);
   (b) partido fotmob sin fila martj42 y con marcador → **materializa** fila nueva
   `source="fotmob"`. La clave de match sigue siendo `(date, frozenset({home,away}))`.

4. **Marcador = resultado fotmob (incluye prórroga, excluye penales).** Para el modelo de goles
   se usa el marcador reportado por fotmob (p.ej. GER 1-1 PAR, empate; PAR avanzó por penales
   pero eso NO cuenta como gol). Decisión explícita y documentada.

5. **Bracket para F30.** `r16_fixtures.csv` (8) y `r8_fixtures.csv` (4) se generan aquí como
   dato derivado; la UI (F30) sólo los lee. Cuartos con equipos aún indefinidos
   (`Winner QF x`) se omiten o marcan `TBD` (no se fuerza código FIFA inválido).

## Módulos

- `src/ingestion/fotmob_ko.py` (nuevo): `parse_playoff_bracket(next_data) -> list[KoMatch]`,
  `fetch_bracket(transport, league_id) -> list[KoMatch]`, `write_ko_fixtures(bracket, dir)`.
  `KoMatch` = dataclass `(round_ordinal, home_name, away_name, home_goals, away_goals,
  match_id, utc_time, finished, started)`.
- `src/ingestion/fotmob_stats.py` (extender): el parser de partido añade `home_goals`,
  `away_goals` al dict persistido (R2). Lectura tolerante a JSONs viejos sin esas claves.
- `src/features/silver.py` (extender): tras enriquecer, un segundo paso materializa filas KO
  desde el índice fotmob para partidos sin fila martj42 con marcador no nulo (R4/R5).
- `src/cli.py` (extender): subcomando `ingest-ko` (bracket + stats KO en vivo) y
  `build-ko-fixtures` (escribe los CSV). Subcomandos previos intactos.

## Flujo

`fetch_bracket (playoff)` → lista KO con IDs + marcadores → por cada KO **finished**:
`fetch_and_persist` del partido (marcador+stats) en bronze → `build_all` materializa filas KO
en silver → refit gold. En paralelo, `write_ko_fixtures` → `r16_fixtures.csv`/`r8_fixtures.csv`.

## Errores / seguridad

- Transporte inyectable; `fetched_at` inyectado; escritura sólo bajo `data/`.
- Degradación: KO sin stats se registra con marcador y stats null (no aborta).
- Rate-limit ≥2s/req, UA identificable. Red real = STOP con aprobación per-tanda.
