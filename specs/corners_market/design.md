# design.md — Feature 24: corners_market

## Arquitectura

Módulo nuevo `src/markets/corners.py` (espeja la estructura de `src/markets/goals.py` pero
para córners, con un modelo de tasa propio + shrinkage). CLI `corners`. Integración en el
sub-tab Mercados del detalle KO (`src/app/tabs/knockouts.py`, F22).

```
silver (home/away_corners, date<as_of) ─▶ team_corner_rates(shrinkage) ─▶ expected_corners
                                                                          └▶ poisson O/U (total+equipo)
```

## Modelo (R1, R2)

- `team_corner_rates(matches, as_of, k=5) -> dict[code, {att, dfn}]`: por equipo, media de
  córners-a-favor (att) y en-contra (dfn) sobre `date < as_of`, con shrinkage hacia la media
  global: `λ = (n·media + k·μ_global)/(n+k)`. μ_global = media de córners por equipo-partido.
- `expected_corners(rates, home, away, mu_global) -> (λ_home, λ_away, λ_total)`:
  `λ_home = μ_global · (att_home/μ_global) · (dfn_away/μ_global)` (y simétrico). Clip a >0.
- `CornersConfig`: `k` (shrinkage), líneas default. Versionado/documentado.

## Mercados (R3)

- `corners_over_under(λ, lines) -> {line: {over, under}}` con Poisson (`scipy.stats.poisson`
  o suma manual). Total usa `λ_total`; por equipo usa `λ_home`/`λ_away`.
- `corners_summary(matches, home, away, as_of, config) -> CornersSummary` (análogo a
  `market_summary` de goals): empaqueta λ + O/U total + O/U por equipo.

## CLI (R4)

`corners HOME AWAY [--as-of FECHA] [--lines 8.5,9.5,...] [--silver PATH] [--json]`. Offline
(lee silver). Subcomandos previos intactos (test del set exacto + el nuevo).

## App (R5)

En el sub-tab **Mercados** del detalle KO (helper de F22): tras los mercados de goles, añadir
una sección "Córners (O/U)" llamando `corners_summary(app_data... , as_of)`. Si el silver no
tiene córners para esos equipos → `st.caption` aviso, sin romper. Cachear con el resto del
análisis de la llave.

## Honestidad (R6)

`corners_summary` incluye `n_matches_home`/`n_matches_away` (cuántos partidos sustentan la
tasa); la UI y el `--json` muestran un aviso "base = N partidos (muestra chica; shrinkage
k=...)". Con n bajo la predicción tira a la media global por diseño.

## Decisiones

1. **Shrinkage obligatorio** — con 3 partidos/equipo, la media cruda es ruido; el shrinkage la
   regulariza hacia la liga. Es la diferencia entre un modelo usable y basura.
2. **Modelo propio (no DC)** — los córners no salen del Dixon-Coles (es de goles); modelo de
   tasa Poisson separado.
3. **Reusar el patrón de goals.py** — misma forma de API/summary para consistencia.

## Fuera de alcance

- No usa el factor de forma ni el roster (los córners son su propio modelo).
- No backfillea histórico (decisión del usuario: solo WC2026).
- Tarjetas/tiros/xG-goles son features posteriores.
