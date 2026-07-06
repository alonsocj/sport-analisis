# design.md — Feature 28: jugadores_xi_fotmob

## Decisiones

1. **Módulo propio `fotmob_lineup.py`** (no extender roster F21): F21 sólo captura nombres
   desde la playoff page; F28 necesita `performance.seasonRating` desde la página de partido
   (`content.lineup`). Reutiliza transporte inyectable, `_extract_next_data`, mapeo FIFA.
2. **season_rating como señal pre-partido**: `performance.rating` es del partido (null antes de
   jugarse); `seasonRating` existe pre-partido → sirve para los 6 octavos por jugar. La fuerza
   se calcula sobre `season_rating` para ser comparable jugado/por-jugar.
3. **Split ataque/defensa por `usualPlayingPositionId`**: 0=GK,1=DEF → def_rating;
   3=MID contribuye a ambos con peso 0.5; 4=ATT → att_rating. Umbral simple y documentado.
4. **Fuerza como tabla gold aparte** (`lineup_strength.csv`), no se mete al modelo aquí; F29
   decide cómo integrarla (variante medible). Mantiene F28 = sólo datos+feature.

## Módulos

- `src/ingestion/fotmob_lineup.py`: `PlayerXI`, `parse_match_lineup(html)`,
  `fetch_and_persist_lineup(...)`, `ingest_lineups(bracket, ...)` (reusa `fetch_bracket` de F27
  para las URLs de partido). Bronze `data/bronze/lineups/<slug>.json` + meta.
- `src/features/lineup_strength.py`: `build_lineup_strength(bronze_dir) -> DataFrame`,
  `write_lineup_strength(df, gold_dir)`. Columnas: date, team_code, xi_rating, att_rating,
  def_rating, n_starters, lineup_type.
- `src/cli.py`: `ingest-lineups`, `build-lineup-strength`.

## Posiciones (usualPlayingPositionId de fotmob) — VERIFICADO en datos reales 2026-07-04

0=GK, 1=DEF, 2=MID, 3=ATT (E.Martínez GK=0; Kane/Mbappé/Lautaro=3; L.Martínez CB=1;
distribución 48/191/162/127 sobre 528 titulares = ~1/4/3.4/2.6 por equipo). NO existe el 4.
GK/DEF → def (w_def=1); MID → 0.5/0.5; ATT → att (w_att=1); desconocido → 0.5/0.5.

## Errores / seguridad

Transporte inyectable; `fetched_at` inyectado; escritura bajo `data/`; degrada si falta lineup;
rate-limit ≥2s; red real = STOP.
