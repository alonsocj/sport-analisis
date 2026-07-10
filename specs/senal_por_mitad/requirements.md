# requirements.md — Feature 32: senal_por_mitad (tendencia por mitad 1T/2T)

Objetivo: dotar al pipeline de una **señal de tendencia por mitad** (primer tiempo vs
segundo tiempo) para cada selección, derivada de fotmob (`Periods.FirstHalf`/`SecondHalf`
+ eventos de gol con minuto), y usarla para (a) enriquecer el análisis de eliminatorias
en la app y (b) alimentar **mercados por mitad** (over/under de goles por mitad, equipo
que marca en 2T, gol tardío 76-90).

Motivación (medida en cuartos WC2026, research LEADER): las selecciones muestran perfiles
por mitad marcados y explotables — p.ej. surge de 2T de Francia (xG 1T 0.51 → 2T 1.62 en el
torneo), colapso defensivo de 2T de Suiza (GA 2T 27 vs 1T 7 en ~27 partidos recientes),
Argentina que dobla tiros en 2T (4.6 → 9.0). Hoy el modelo (Dixon-Coles + forma-xG + Elo)
predice SOLO el marcador del partido completo; ignora **cuándo** ocurre el juego.

Cobertura honesta: el detalle per-mitad (xG/tiros) sólo existe para partidos scrapeados de
fotmob (WC2026 + los que se scrapeen). Para minutos de gol pre-torneo se usa
`goalscorers.csv` (hasta 2026-06-25). Muestra chica por equipo (~5 partidos de torneo) →
**shrinkage obligatorio** hacia la media del bracket/histórica.

Principio de no-regresión: la feature es **aditiva y aislada**. El modelo 1X2/marcador
completo actual NO cambia; la señal por mitad vive en una tabla nueva y en mercados nuevos.
Con la señal desactivada, todas las salidas previas son idénticas.

Notación EARS. Cada `R<n>` mapea a ≥1 test en `tests/test_senal_por_mitad.py`.

---

**R1 — Ingesta per-mitad desde fotmob (bronze).**
El sistema DEBE extraer, por partido fotmob, `content.stats.Periods.FirstHalf` y
`SecondHalf` (posesión, xG, tiros, tiros a puerta, córners, tarjetas, big chances) ADEMÁS
del `Periods.All` actual, y los **eventos de gol** (`content.matchFacts.events.events` con
`type=="Goal"`: minuto, `overloadTime`, `isHome`, `ownGoal`, jugador). Se persiste en el
bronze de fotmob_stats (esquema extendido, retrocompatible: los campos nuevos son
opcionales; los JSON viejos siguen siendo válidos). Transporte INYECTABLE (cero red en
tests). Regla STOP: ejecución con transporte real requiere aprobación.

**R2 — Asignación de mitad determinista.**
El sistema DEBE clasificar cada gol en `1T` (minuto ≤ 45), `2T` (46 ≤ minuto ≤ 90) o
`ET` (minuto > 90, tiempo extra) de forma determinista. Los goles de `ET` NO cuentan como
2T. La orientación equipo/rival se deriva de `isHome` + local/visitante del partido.

**R3 — Tabla silver por-mitad.**
El sistema DEBE construir, por partido y equipo, una fila con: goles_for/against por mitad,
xG_for/against por mitad, tiros_for/against por mitad (donde haya cobertura). SIN xG (partido
no scrapeado) → columnas per-mitad de xG en null (los goles por minuto siguen desde
`goalscorers.csv`). Anti-fuga: sólo partidos con `date < as_of`.

**R4 — Señal de tendencia por mitad (con shrinkage y ajuste por rival).**
El sistema DEBE calcular, por equipo y mitad, una señal `half_strength[team][half]` =
(ataque_for − defensa_against) ajustada por la calidad del rival, con **shrinkage** hacia
la media (bracket/histórica) proporcional a `1/n` de partidos con cobertura. La señal es
determinista y documentada. Muestra chica DEBE reflejarse en un shrinkage fuerte (no
sobre-confiar en n≈5).

**R5 — Mercados por mitad.**
El sistema DEBE exponer, para un enfrentamiento A vs B, probabilidades derivadas de la
señal para: (a) over/under de goles del **1T** y del **2T** por separado, (b) “equipo X
marca en 2T”, (c) “gol en 76-90”. Se reusa el motor Poisson/Dixon-Coles existente aplicado
por mitad (λ_1T, λ_2T por equipo) en vez de re-implementar. Salida consistente con el
formato de los mercados actuales (`src/markets/`).

**R6 — Interruptor + no-regresión.**
El sistema DEBE exponer un flag/param que active la señal y los mercados por mitad. Con el
flag OFF (default), el conjunto EXACTO de salidas previas (predict/markets/simulate y sus
subcomandos) permanece idéntico (test de equivalencia). No se rompe ningún test de F23/F24/F25.

**R7 — CLI + app.**
El sistema DEBE aceptar la nueva salida en un subcomando o flag (`markets --by-half` o
`half-markets`) SIN eliminar subcomandos previos, y la pestaña Knockouts DEBE poder mostrar
el perfil por mitad de cada equipo del cruce (1T vs 2T: goles/xG/tiros + timing).

**R8 — Validación (backtest por mitad).**
El sistema DEBE validarse con un backtest que evalúe la calibración de los mercados por
mitad (log-loss/Brier del over/under 1T y 2T) sobre los partidos WC2026 con cobertura. Se
ADOPTA sólo si calibra mejor que la línea base naïve (repartir el λ total 45/55 fijo).
Reporte honesto de muestra chica.

---

## Trazabilidad R<n> → test (a completar por el Implementer)

| Req | Test (tests/test_senal_por_mitad.py) |
|-----|--------------------------------------|
| R1  | `test_parse_periods_firsthalf_secondhalf`, `test_parse_goal_events_minutes`, `test_bronze_schema_retrocompat` |
| R2  | `test_half_assignment_1t_2t_et`, `test_goal_orientation_home_away` |
| R3  | `test_silver_por_mitad_row`, `test_xg_null_sin_cobertura`, `test_antifuga_as_of` |
| R4  | `test_half_strength_shrinkage`, `test_ajuste_rival`, `test_muestra_chica_shrink_fuerte` |
| R5  | `test_market_ou_1t`, `test_market_ou_2t`, `test_market_equipo_marca_2t`, `test_market_gol_tardio` |
| R6  | `test_flag_off_equivalencia`, `test_no_regresion_markets_previos` |
| R7  | `test_cli_subcomandos_intactos`, `test_cli_half_markets_salida` |
| R8  | `test_backtest_por_mitad_calibra_vs_naive` |
