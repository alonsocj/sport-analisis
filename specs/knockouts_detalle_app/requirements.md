# requirements.md — Feature 22: knockouts_detalle_app

Objetivo: dar a cada llave de eliminación su **página de detalle** (igual que la fase de
grupos en el tab Calendario): tarjetas por llave + un detalle con **sub-pestañas**
(Predicción / Mercados / Goleadores / Equipos / Elo). En Predicción se añaden los **top-10
marcadores más probables** (hoy el detalle de grupos muestra top-5). Consolida lo ya
construido (F17 predicción+forma, F20 markets+scorers, F21 roster) dentro de la página.

Coherencia con el tab: la predicción del detalle es **neutral** (promedio de orientaciones,
sede neutral de knockout) y respeta el **slider γ** (forma reciente). Los goleadores usan el
**roster** (F21). Reusa figuras existentes (`fig_1x2`, `fig_heatmap`, `fig_comparativa`,
`fig_elo_lines`) y el patrón de selección por `st.session_state` del tab Calendario.

Notación EARS. Cada `R<n>` mapea a ≥1 test en `tests/test_app_knockouts_detalle.py`.

---

**R1 — Tarjeta por llave + selección de detalle.**
El tab Knockouts DEBE listar las llaves (agrupadas por fecha) como tarjetas compactas con su
1X2/P(avanza) y un control "ver detalle". CUANDO el usuario selecciona una llave, el sistema
DEBE abrir su página de detalle (vía `st.session_state`, patrón del tab Calendario). Sin
selección → no se muestra detalle (o se muestra la primera por defecto, decisión de diseño).

**R2 — Página de detalle con sub-pestañas.**
La página DEBE mostrar sub-pestañas: **Predicción**, **Mercados**, **Goleadores**, **Equipos**,
**Elo**. Predicción: barras 1X2 (`fig_1x2`) + heatmap (`fig_heatmap`) + **top-10 marcadores
más probables**. Mercados: O/U + BTTS + totales (Feature 20). Goleadores: anytime-scorers por
equipo con filtro de roster y nota de bajas (Features 20+21). Equipos: comparativa
(`fig_comparativa`). Elo: historial (`fig_elo_lines`).

**R3 — Predicción neutral + forma + top-10.**
La predicción del detalle DEBE ser neutral: matriz de marcadores = promedio de las dos
orientaciones (`predict_match(A,B).matrix` y `predict_match(B,A).matrix` transpuesta),
renormalizada; de ahí se derivan 1X2, heatmap y los **top-10** marcadores (mayor probabilidad,
orden descendente). DEBE respetar el slider γ (forma): con γ=0 es v1, con γ>0 aplica el factor.

**R4 — Integración sin regresión.**
El detalle se añade al tab Knockouts SIN romper el slider γ, la lista de llaves, ni las
pestañas Calendario/Selecciones/Modelo. Sus tests previos siguen verdes. Reusa figuras y
helpers existentes (no los duplica).

**R5 — Determinismo, sin red, degradación, sin libs nuevas.**
Tests offline con fixtures (params, player_factor, roster). Equipo no resoluble / sin
player_factor / sin roster / sin Elo → degradación elegante (la sub-pestaña afectada avisa,
las demás siguen). Sin dependencias nuevas (Streamlit + plotly ya en el stack).
