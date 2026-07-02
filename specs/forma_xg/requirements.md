# requirements.md — Feature 26: forma_xg (forma reciente basada en xG)

Objetivo: mejorar el factor de **forma reciente** (F16) usando el **xG real** (de fotmob,
F23) en la ventana, en vez del gol-diff. El xG es menos ruidoso que los goles (una goleada
0-1 con xG 0.1-2.0 refleja mejor el dominio). Es la mejor palanca del xG porque la ventana
de forma son partidos RECIENTES, y los recientes (WC2026) SÍ tienen xG.

Cobertura honesta: solo los partidos WC2026 de la ventana tienen xG; los pre-WC (amistosos no
scrapeados) no → **fallback a goles** por partido. En una ventana típica de knockout (~3 WC +
5 pre-WC), ~3/8 (los más recientes, más ponderados) usan xG.

Principio de no-regresión: con la opción xG **OFF** (default), el factor es IDÉNTICO a F16
(gol-diff). Se adopta solo si **bate a la forma-goles** en el backtest.

Notación EARS. Cada `R<n>` mapea a ≥1 test en `tests/test_form_xg.py` (más reuso de los tests
de F16 como no-regresión).

---

**R1 — La ventana de forma lleva xG (con fallback).**
La ventana (`build_window`/índice F18) DEBE poder cargar, por partido, `xg_for`/`xg_against`
desde el silver (`home_xg`/`away_xg`), además de `gf`/`ga`. SI un partido no tiene xG (null) →
se marca sin-xG (se usará gol como fallback). Anti-fuga preservada (`date < as_of`).

**R2 — Métrica de forma con xG (mezcla por partido).**
El cálculo de forma DEBE poder usar **xG-diff** donde haya xG y **gol-diff** donde no, por
partido (mezcla a nivel de partido), con los mismos pesos de recencia/tier/calidad-de-rival de
F16. La componente resultante (`xgd_w` análoga a `gd_w`) es determinista y documentada.

**R3 — Activación + no-regresión exacta.**
El sistema DEBE exponer un interruptor `use_xg` (config + flag CLI `--form-xg`) que activa la
métrica xG. Con `use_xg=False` (default) la salida es IDÉNTICA a F16 (gol-diff; test de
equivalencia tol 1e-9). El interruptor compone con `--form-weight γ` (γ=0 sigue siendo v1).

**R4 — CLI.**
El sistema DEBE aceptar `--form-xg` en `predict`, `backtest` y `simulate` (junto a
`--form-weight`). El conjunto EXACTO de subcomandos previos DEBE permanecer intacto (no se
añaden subcomandos; solo un flag). Salida consistente.

**R5 — Medición vs forma-goles.**
El sistema DEBE permitir backtestear forma-goles vs forma-xG (mismo γ) sobre la ventana WC2026,
reportando Brier/log-loss/exactitud → **veredicto** (¿el xG mejora la forma?). DEBE documentar
que la cobertura parcial (solo WC en la ventana) limita el efecto.

**R6 — Determinismo, sin red, sin libs nuevas.**
Tests offline con silver fixture (con y sin columnas xG); `as_of` inyectado; degradación
(sin xG → goles); `use_xg=False` ≡ F16 exacto; sin dependencias nuevas. NO toca el modelo DC,
el roster, los mercados.
