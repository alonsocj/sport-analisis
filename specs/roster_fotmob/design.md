# design.md — Feature 21: roster_fotmob

## Arquitectura

```
fotmob playoff (league 77) ──▶ URLs de partido R32 ──▶ por partido: match page __NEXT_DATA__
                                                          └▶ content.lineup.{home,away}Team
                                                               ├ starters + subs  → DISPONIBLES
                                                               └ unavailable      → NO DISPONIBLES
bronze/rosters/<slug>.json ──▶ normalizar (to_fifa_code) ──▶ data/rosters/r32_rosters.csv (--roster)
                                                          └▶ data/rosters/r32_unavailable.csv (display)
```

## Módulos

### `src/ingestion/roster.py` (R1, R2)
- `fetch_playoff_match_urls(transport, league_id=77) -> list[MatchRef]`: parsea el
  `__NEXT_DATA__` de la playoff page → `playoff.rounds[stage='1/16'].matchups` →
  `{matchId, pageUrl, homeTeam, awayTeam}`.
- `fetch_match_lineup(transport, match_ref) -> RawLineup`: GET de la match page → parsea
  `content.lineup.{homeTeam,awayTeam}` → por equipo `name, starters[], subs[], unavailable[
  {name, reason}]`. Persiste bronze `<slug>.json` + meta (`fetched_at` inyectado, url, sha256).
- `transport`: callable `(url) -> str(html)` INYECTABLE. Producción = wrapper `requests` con
  UA identificable + rate-limit ≥1 req/2s. Tests = devuelve fixtures guardados.
- `normalize_rosters(raw_lineups) -> (available_rows, unavailable_rows, coverage)`: mapea
  `to_fifa_code(team_name)`; disponibles = starters+subs; escribe `data/rosters/r32_rosters.csv`
  (`team_code,scorer`) y `data/rosters/r32_unavailable.csv` (`team_code,player,reason`).

### `src/cli.py` (R4)
- Subcomando `ingest-roster [--matches playoff|<csv>] [--ttl-hours] [--out DIR]`: red real
  (transporte real); imita el patrón de `ingest-wiki-stats`/`ingest-elo` (UA, rate-limit,
  caché bronze, `fetched_at` metadato). Subcomandos previos intactos.

### `src/app/tabs/knockouts.py` (R3)
- En `_compute_analisis_data`/`_render_analisis_llave` (Feature 20): cargar
  `data/rosters/r32_rosters.csv` (si existe); antes de `compute_anytime_scorers`, filtrar las
  `PlayerRate` a los disponibles del equipo y **renormalizar shares**; mostrar nota
  "sin {jugador} ({motivo})" desde `r32_unavailable.csv`. Sin roster → comportamiento F20.

## Contratos

- `r32_rosters.csv`: `team_code,scorer` (solo disponibles) — compatible con el `--roster`
  existente de `scorers`/`simulate` (sin columnas extra para no romper su parser).
- `r32_unavailable.csv`: `team_code,player,reason` — solo para display en la app.
- Nombres de jugador: normalización consistente con `players/normalize.py` (acentos) para
  casar con `player_factor.csv` (DEUDA conocida F11: acentos divididos — documentar match best-effort).

## Errores / degradación (R5)

- Partido sin `lineup` → bronze vacío, sin filas; cobertura lo refleja.
- Equipo sin `to_fifa_code` → descartar con aviso.
- `requests` falla en un partido → saltar ese partido (no abortar todo) — corrige la deuda
  de robustez de F15.
- Roster ausente en la app → panel de goleadores F20 sin filtro (idéntico).

## Seguridad / cortesía

- UA identificable con contacto; rate-limit ≥1 req/2s; caché bronze (TTL configurable); solo
  GET de páginas públicas; sin login. Dictamen security-lead recomendado en el cierre.

## Decisiones

1. **CLI ingestion real** (no solo browser): fotmob responde a `requests` (verificado), así
   que se integra como subcomando reproducible y testeable con transporte inyectado.
2. **Roster compatible con `--roster` existente**: máxima reutilización (CLI scorers/simulate
   ya lo consumen) sin tocar su parser.
3. **Filtrado + renormalización en la app**: el valor concreto (quitar a Zwane del top de RSA)
   se ve donde el usuario mira (tab Knockouts).

## Fuera de alcance

- No usa ratings/xG por jugador (otra feature si se quiere).
- No predice la alineación; consume la predicha por fotmob.
- No modifica el modelo DC ni el factor de forma.
