# requirements.md — Feature 25: count_markets (tarjetas, tiros, tiros a puerta O/U)

Objetivo: generalizar el mercado de conteo (igual maquinaria que córners F24: tasa por equipo
con shrinkage + Poisson O/U) a **tarjetas**, **tiros** y **tiros a puerta**, con un motor
genérico parametrizado por la columna de stat del silver. Un subcomando `count-market` +
secciones en el sub-tab Mercados del detalle KO.

Reusa el diseño de F24 (shrinkage bayesiano hacia la media global, anti-fuga por `as_of`).
Misma realidad de muestra chica (3 partidos/equipo WC2026). Honestidad EXTRA: **las tarjetas
dependen del árbitro** (no disponible) → son el mercado más ruidoso; se etiqueta como tal.

Notación EARS. Cada `R<n>` mapea a ≥1 test en `tests/test_count_markets.py` o
`tests/test_cli_count.py`.

---

**R1 — Motor de conteo genérico (shrinkage, leak-free).**
El sistema DEBE exponer un motor que, dada una columna de stat (`cards`, `shots`,
`shots_on_target`), estime tasas att/dfn por equipo con shrinkage hacia la media global
(`λ=(n·media+k·μ)/(n+k)`), solo con `date < as_of` (anti-fuga), y derive λ esperados por
partido (ataque local × defensa visitante, normalizado por μ). Reusa/espeja la lógica de
`src/markets/corners.py` (F24). Stat no presente/poblada → degrada (prior global / aviso).

**R2 — Over/Under (Poisson) total y por equipo.**
El sistema DEBE derivar over/under (total y por equipo) para líneas por defecto adecuadas a
cada stat (p.ej. tarjetas 2.5/3.5/4.5; tiros 20.5/24.5/…; SoT 6.5/8.5/…), con Poisson. over+under≈1.

**R3 — CLI.**
El sistema DEBE exponer `count-market HOME AWAY --stat {cards,shots,sot} [--as-of] [--lines]
[--json]` (offline; lee silver). El conjunto EXACTO de subcomandos previos DEBE permanecer
intacto + `count-market`. Salida `✅`/`--json`.

**R4 — Integración en el detalle KO (app).**
El sub-tab **Mercados** del detalle de knockout DEBE mostrar también tarjetas, tiros y SoT
(O/U total + por equipo), junto a goles y córners. SIN datos → degrada con aviso. Las
tarjetas DEBEN llevar una nota de "depende del árbitro / muy ruidoso".

**R5 — Determinismo, sin red, honestidad, sin libs nuevas.**
Tests offline con silver fixture; `as_of` inyectado; degradación; avisos de muestra chica y de
ruido de tarjetas; sin dependencias nuevas (numpy/scipy ya están). NO toca el modelo DC, la
forma, el roster ni `markets/goals.py`/`markets/corners.py` (los reusa/espeja, no los rompe).
