# requirements.md — Feature 19: forma_vs_v1_panel

Objetivo: hacer VISIBLE en la app Streamlit el **veredicto medido** de Feature 18 (la forma
reciente bate a v1 en el backtest). Un panel nuevo en la pestaña **Modelo** que lee una
comparativa ya consolidada (`data/reports/forma_vs_v1.json`) y muestra la tabla
γ × {log-loss, Brier, exactitud} con el delta vs v1 y el dictamen.

Decisión de diseño: el panel **NO recalcula** el backtest (es caro por el refit del DC);
solo LEE el artefacto JSON ya generado. Igual que el panel Backtest existente
(`_render_backtest_section`), que lee `summary.json`.

Principio: solo lectura + render. NO modifica el modelo, ni el CLI, ni las otras pestañas
ni las otras secciones del tab Modelo (metadatos, dispersión, backtest). Sin libs nuevas.

Notación EARS. Cada `R<n>` mapea a ≥1 test en `tests/test_app_modelo_forma.py` (ver `tasks.md`).

---

**R1 — Carga del artefacto de comparativa.**
El sistema DEBE leer la comparativa desde `data/reports/forma_vs_v1.json` (schema: `titulo,
from_date, to_date, n_eval, baseline, caveat, rows[{gamma, log_loss, brier, accuracy,
is_baseline}], verdict, fuente`). SI el archivo no existe o está malformado → la sección
muestra un aviso accionable (cómo regenerarlo) y NO rompe el tab (degradación elegante).

**R2 — Render de la comparativa con delta vs v1.**
El sistema DEBE renderizar, en el tab Modelo, una tabla con una fila por `gamma` y columnas
`log-loss`, `Brier`, `exactitud`, marcando la fila baseline (γ=0, v1) y mostrando el **Δ vs
v1** por métrica (log-loss y Brier: menor es mejor; exactitud: mayor es mejor). DEBE mostrar
el `verdict`, la ventana (`from_date`–`to_date`), `n_eval` y el `caveat` (texto honesto:
medido sobre continuación de grupos, muestra chica, no probado para knockouts).

**R3 — Integración sin regresión.**
El panel DEBE añadirse al final de `render_modelo` SIN alterar las secciones existentes
(Metadatos, Dispersión de fuerzas, Backtest) ni las pestañas Calendario/Selecciones/
Knockouts. Sus tests previos siguen verdes.

**R4 — Determinismo, sin red, sin recálculo, sin libs nuevas.**
Tests 100% offline con artefacto JSON de fixture; sin red; la app NO ejecuta backtest ni
toca el modelo; sin dependencias nuevas (Streamlit + stack actual).
