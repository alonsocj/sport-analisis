# requirements.md — Feature 24: corners_market (mercado de córners O/U)

Objetivo: primer mercado nuevo sobre la fundación F23. Modelar la tasa de córners por equipo
y derivar **over/under de córners** (total y por equipo) para un partido. Mostrarlo en el
sub-tab Mercados del detalle de knockout (F22).

Realidad de muestra (verificada): hoy solo hay **3 partidos/equipo** con córners (WC2026
grupos). Una media cruda es ruido (CAN 11.7 por un 6-0; MEX 1.3). Por eso el modelo DEBE usar
**SHRINKAGE bayesiano** hacia la media global: con n pequeño la estimación tira a la media de
la liga; conforme crecen los partidos, al equipo. Honestidad: hoy las predicciones ≈ media
global + ajuste chico; mejoran con cada jornada.

Notación EARS. Cada `R<n>` mapea a ≥1 test en `tests/test_corners_market.py` o
`tests/test_cli_corners.py`.

---

**R1 — Tasa de córners por equipo con shrinkage (leak-free).**
El sistema DEBE estimar, por equipo y para una fecha `as_of` inyectada, dos tasas desde el
silver (solo `date < as_of`, anti-fuga): **córners-a-favor** (ataque) y **córners-en-contra**
(defensa). Cada tasa con shrinkage: `λ = (n·media_equipo + k·media_global) / (n + k)`, con
`k` (pseudo-cuenta) DOCUMENTADO y configurable (default p.ej. 5). Equipo sin partidos → media
global (factor neutro).

**R2 — Córners esperados por partido.**
El sistema DEBE combinar la tasa de ataque del local con la de defensa del visitante (y
simétrico), normalizando por la media global: p.ej.
`λ_home = media_global · (ataque_home/media_global) · (defensa_away/media_global)`. Devuelve
`λ_home_corners`, `λ_away_corners`, `λ_total = λ_home + λ_away`. Determinista.

**R3 — Mercados over/under (Poisson).**
El sistema DEBE derivar over/under para líneas de córners totales (default p.ej. 8.5, 9.5,
10.5, 11.5) y por equipo, usando Poisson con `λ` de R2. Probabilidades en [0,1], over+under≈1.

**R4 — CLI.**
El sistema DEBE exponer `corners HOME AWAY [--as-of] [--lines ...]` (offline; usa silver +
no requiere red). El conjunto EXACTO de subcomandos previos DEBE permanecer intacto +
`corners`. Salida `✅`/`--json`.

**R5 — Integración en el detalle KO (app).**
El sub-tab **Mercados** del detalle de knockout (F22) DEBE mostrar también el over/under de
córners (total + por equipo) junto a los de goles. SIN datos de córners → degrada con aviso,
los mercados de goles siguen.

**R6 — Determinismo, sin red, honestidad, sin libs nuevas.**
Tests offline con silver de fixture; `as_of` inyectado; degradación (equipo sin dato → prior
global); la salida/UI DEBE indicar que la base es muestra chica (aviso honesto). Sin
dependencias nuevas (numpy/scipy ya están).
