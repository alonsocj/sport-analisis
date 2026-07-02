# design.md — Feature 22: knockouts_detalle_app

## Arquitectura

Refactor del tab Knockouts (`src/app/tabs/knockouts.py`): de "lista con expander por llave"
a "tarjetas compactas + página de detalle con sub-pestañas", espejando el tab Calendario
(`render_calendario` + `_render_detalle`). Reusa figuras y datos existentes.

```
fixtures (F17) ─▶ tarjetas por fecha (1X2/avanza + botón "ver detalle")
                    │ click → st.session_state["selected_ko"]
                    ▼
        _render_detalle_ko(fixture, app_data, gamma, paths...)
          ├ Predicción : fig_1x2 + fig_heatmap + TOP-10 (matriz neutral)
          ├ Mercados   : market_summary (F20)
          ├ Goleadores : anytime-scorers + roster (F20+F21)
          ├ Equipos    : fig_comparativa (team_profile)
          └ Elo        : fig_elo_lines
```

## Predicción neutral + top-10 (R3)

- `pred_ab = predict_match(params, A, B, form_factor)`, `pred_ba = predict_match(params, B, A,
  form_factor)`.
- **Matriz neutral**: `M = (pred_ab.matrix + pred_ba.matrix.T) / 2`; renormalizar a suma 1.
  (En `pred_ba` los ejes están invertidos → transponer alinea A=filas, B=columnas.)
- **1X2 neutral**: ya lo calcula `neutral_prediction` (reusar).
- **Top-10**: aplanar `M`, tomar los 10 índices `(i, j)` de mayor probabilidad, orden
  descendente → `[(goles_A, goles_B, prob), ...]`.
- Para `fig_1x2`/`fig_heatmap` (esperan un `MatchPrediction`): construir un `MatchPrediction`
  neutral sintético con `matrix=M`, `prob_home/draw/away` neutrales, `top_scores=top10`,
  `lambda_home/away` = λ promedio. Así se reusan las figuras sin modificarlas.

## Selección de detalle (R1)

Patrón Calendario: cada tarjeta tiene un `st.button("Ver detalle", key=...)` que setea
`st.session_state["selected_ko"] = (date, home_code, away_code)`. Al final del render, si hay
selección, resolver la `KnockoutFixture` y llamar `_render_detalle_ko`. El slider γ se lee una
vez y se pasa al detalle (factor de forma construido 1×, como F20).

## Sub-pestañas (R2) — reuso

- Predicción: `fig_1x2(neutral_pred, ...)`, `fig_heatmap(neutral_pred)`, lista top-10.
- Mercados: `market_summary(params, home, away)` (F20) — v1, etiquetado.
- Goleadores: helper de F20/F21 (anytime-scorers + filtro roster + nota bajas).
- Equipos: `fig_comparativa` con `team_profile(code, app_data)` (de `..data`).
- Elo: `fig_elo_lines` con el `elo_history` de `app_data`.

## Degradación (R5)

- Equipo no resoluble en params → la página avisa y omite Predicción/Mercados/Goleadores;
  Equipos/Elo pueden seguir si hay datos.
- Sin player_factor/roster → Goleadores degrada (F20/F21). Sin Elo → sub-pestaña Elo avisa.

## Decisiones

1. **Espejo del tab Calendario** — consistencia de UX (el usuario pidió "como en grupos").
2. **Matriz neutral promediada** — knockouts en sede neutral; promediar orientaciones evita el
   sesgo de local del 1X2/heatmap/top-10.
3. **MatchPrediction sintético** — reusar `fig_1x2`/`fig_heatmap` sin tocar `figures.py`.
4. **Absorber F20/F21 al detalle** — markets/scorers pasan del expander al sub-tab,
   centralizando la "página por partido".

## Fuera de alcance

- No cambia el modelo, el factor de forma ni el roster (los consume).
- No añade páginas Streamlit multipage (es un detalle in-tab, como Calendario).
- No modifica `figures.py` ni el tab Calendario.
