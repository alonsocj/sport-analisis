# design.md — Feature 31: alineacion_destacado_app

## Decisiones

1. **`marketValue` como ancla del "destacado"** (no seasonRating): cobertura 100% en XI
   predicho de octavos (verificado POR/ESP/USA/BEL) vs seasonRating 0%. Cracks sensatos:
   ESP Lamine Yamal, USA Pulisic, BEL Doku.
2. **Lógica de vista PURA y testeable** en `src/features/lineup_view.py` (sin streamlit): la UI
   (knockouts.py) solo pinta. Facilita tests deterministas con fixtures.
3. **Cruce de nombres tolerante** (normalización sin acentos + apellido) reusando el
   `player_factor` que la sub-pestaña Goleadores ya carga → mitiga el caveat de acentos de F11.
4. **Reusar el bronze de F28**: se re-scrapea solo para añadir los campos nuevos (marketValue…);
   el resto del pipeline no cambia.

## Módulos

- `src/ingestion/fotmob_lineup.py` (extender): `PlayerXI` + `_parse_players` capturan
  `market_value, shirt_number, club, age`. Serialización bronze automática (asdict).
- `src/features/lineup_view.py` (nuevo, puro):
  - `POS_LABELS = {0:"POR",1:"DEF",2:"MED",3:"DEL"}`.
  - `_norm(name)` (minúsculas + sin acentos).
  - `find_lineup_doc(bronze_dir, date, home_code, away_code) -> dict|None` (match por date+set).
  - `pick_crack(starters, scorers) -> dict|None` (max market_value + goal_share por cruce).
  - `build_lineup_view(doc, home_code, away_code, scorers_home, scorers_away) -> dict`
    (por lado: `crack`, `xi` ordenado por posición).
- `src/app/tabs/knockouts.py`: sub-pestaña "Alineación" (índice 5) en `_render_detalle_ko`;
  usa el `player_factor` ya cargado en `analisis_data` para el goal_share.

## UI

Dos columnas (home | away). Por columna: tarjeta del crack (nombre, club, €valor, ⚽ share,
★ rating si existe) + tabla del XI (dorsal, nombre, posición) con el crack resaltado.
Degradación: sin doc de lineup → caption "sin alineación disponible".

## Errores / seguridad

Vista pura; sin red en UI (lee bronze). Re-scrape real = STOP. Sin libs nuevas.
