# design.md — Feature 23: fotmob_stats

## Arquitectura

```
fotmob liga 77 (matches/fixtures) ─▶ URLs de partidos WC2026 jugados
   └▶ por partido: match page __NEXT_DATA__ → content.stats.Periods.All
        └▶ por equipo: shots, shots_on_target, corners, cards, possession, xg
bronze/fotmob_stats/<slug>.json ─▶ normalize (to_fifa_code) ─▶ merge en silver por (date,home,away)
```

## Módulos

### `src/ingestion/fotmob_stats.py` (R1, R2)
- `fetch_match_urls(transport, league_id=77) -> list[MatchRef]`: parsea el `__NEXT_DATA__` de la
  página de partidos de la liga (matches/fixtures) → partidos WC2026 con `started/finished` y
  `pageUrl`. (Reusar el patrón de `src/ingestion/roster.py::fetch_playoff_match_urls`, pero
  sobre el listado completo de la liga, no solo el bracket.)
- `parse_match_stats(html) -> dict`: extrae `content.stats.Periods.All.stats` → mapea los
  títulos fotmob a claves del proyecto: `Ball possession→possession`, `Total shots→shots`,
  `Shots on target→shots_on_target`, `Corners→corners`, `Yellow cards`+`Red cards→cards`,
  `Expected goals (xG)→xg`. Devuelve `{home:{...}, away:{...}, teams:(name_h,name_a), date}`.
- `fetch_and_persist(transport, match_ref, fetched_at, out_dir)`: GET + parse + bronze
  `<slug>.json` + meta; saltar partido si el transporte falla o no hay stats.
- `normalize_stats(raw_list) -> (rows, coverage)`: `to_fifa_code`; filas
  `(date, home_code, away_code, {home/away_*})`.

### `src/features/silver.py` (R3) — punto de unión
- Añadir una fuente de stats fotmob: tras construir las filas públicas (stats nulas), hacer
  **merge por `(date, home_code, away_code)`** poblando `home/away_{corners,cards,shots,
  shots_on_target,possession}` y `home_xg/away_xg`. Si no hay bronze fotmob_stats → no-op
  (silver idéntico al actual). Añadir `home_xg,away_xg` al esquema de columnas avanzadas
  (default null) — los consumidores actuales no las leen (no-regresión).
- Reusar el normalizador de stats existente (`_statistics_columns`/`_stat_to_float`/
  `_possession_to_float`) donde aplique, para tipos consistentes.

### `src/cli.py` (R4)
- Subcomando `ingest-fotmob-stats [--league-id 77] [--out DIR]` (red real, patrón
  `ingest-roster`/`ingest-wiki-stats`). Subcomandos previos intactos.

## Mapeo de claves fotmob → proyecto

| fotmob (title)        | clave proyecto       | parseo |
|-----------------------|----------------------|--------|
| Ball possession       | possession           | int %  |
| Expected goals (xG)   | xg                   | float  |
| Total shots           | shots                | int    |
| Shots on target       | shots_on_target      | int    |
| Corners               | corners              | int    |
| Yellow cards + Red cards | cards             | suma int (null→0) |

(Cards: fotmob da `Yellow cards` y `Red cards` por separado; `cards` = amarillas+rojas.)

## Errores / degradación (R5)

- Partido sin `stats.Periods` (no jugado o sin datos) → bronze vacío, sin filas.
- Equipo sin `to_fifa_code` → omitir con aviso.
- `requests` falla en un partido → saltar ese partido (no abortar).
- Bronze fotmob_stats ausente en build-features → silver idéntico al actual.

## Decisiones

1. **Poblar las columnas que YA existen** en el silver (diseñadas para esto, vacías hasta hoy)
   + añadir `home_xg/away_xg`. Mínima cirugía de esquema.
2. **Merge por (date, equipos)**: los match_id de fotmob ≠ los del silver público; la unión
   robusta es fecha+códigos.
3. **Ingesta separada de los mercados**: F23 es solo la fundación de datos; córners/tarjetas/
   tiros/xG-goles son features posteriores que consumen estas columnas.

## Fuera de alcance

- No construye modelos de mercado (features siguientes).
- No backfillea el histórico martj42 (49k) — solo WC2026 jugados.
- No usa playerStats/shotmap por jugador (posible feature futura).
