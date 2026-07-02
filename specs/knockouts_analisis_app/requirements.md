# requirements.md — Feature 20: knockouts_analisis_app

Objetivo: enriquecer la pestaña **Knockouts** con el análisis completo por llave que ya
existe en el CLI: **mercados de goles** (`markets`: O/U totales + BTTS) y **goleadores
anytime** (`scorers`: top-K por equipo). Hoy el tab solo muestra 1X2 + P(avanza); esta
feature añade, por llave, un panel expandible con mercados y goleadores.

Decisión de alcance (app-only): se reusan tal cual `market_summary` (src/markets/goals.py)
y la lógica de goleadores (src/players/factor.py, según `cmd_scorers` en cli.py). NO se
modifican esos módulos core. Por eso **mercados y goleadores se muestran a v1** (su λ sale
de `predict_match` SIN factor de forma); el 1X2/P(avanza) del tab sigue usando el slider γ.
Se etiqueta claramente esa diferencia (honestidad).

Principio: solo lectura + render. No toca cli/simulation/models/markets/players ni las otras
pestañas. Sin libs nuevas.

Notación EARS. Cada `R<n>` mapea a ≥1 test en `tests/test_app_knockouts_analisis.py`.

---

**R1 — Mercados de goles por llave.**
Por cada llave, el sistema DEBE mostrar (en un expander) el resumen de mercados vía
`market_summary(params, home, away)`: O/U para las líneas de totales, BTTS sí/no, y totales
por equipo. Los valores se presentan legibles (porcentajes).

**R2 — Goleadores anytime por llave.**
Por cada llave, el sistema DEBE mostrar los top-K (default 3) anytime-scorers por equipo
(probabilidad P(marca)), reusando `player_factor.csv` (gold) y la λ por equipo de
`predict_match` (v1). SI `player_factor.csv` no existe → se omite la sección de goleadores
con un aviso (degradación), sin romper el tab.

**R3 — Etiquetado v1 + eficiencia.**
El panel de mercados/goleadores DEBE etiquetarse explícitamente como **v1** (no usa el factor
de forma), para no confundir con el 1X2/P(avanza) que sí responde al slider γ. El cálculo por
llave DEBE cachearse (`st.cache_data` por `(home, away)`) para no recalcular en cada
re-render del slider.

**R4 — Integración sin regresión.**
El panel se añade DENTRO del render de cada llave en el tab Knockouts SIN romper el 1X2/
P(avanza) existente ni las pestañas Calendario/Selecciones/Modelo. Sus tests previos siguen
verdes.

**R5 — Determinismo, sin red, sin libs nuevas.**
Tests offline con fixtures (params + player_factor sintéticos); sin red; sin recálculo de
modelo; sin dependencias nuevas (Streamlit + stack actual).
