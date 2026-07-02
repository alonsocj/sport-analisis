# design.md — Feature 17: knockouts_app

## Arquitectura

Pestaña nueva `src/app/tabs/knockouts.py` registrada en `src/app/main.py` como cuarta
pestaña. Reusa: `predict_match` (Feature 3), `make_form_factor_fn` (Feature 16), el
`AppData` ya cargado. NO toca `src/cli.py`, `src/simulation/*`, bronze ni silver.

```
data/knockouts/r32_fixtures.csv ─┐
data/silver/matches.csv          ├→ render_knockouts(app_data, fixtures_csv, form_builder)
data/gold/external_elo.csv       │     ├ slider γ (st)
data/gold/dixon_coles_params.json┘     ├ por llave: neutral 1X2 (v1 o forma)
                                       └ agrupado por fecha
```

## Contratos

- `load_knockout_fixtures(path) -> list[KnockoutFixture]` con campos
  `draw_order:int, date:str, stage:str, home_code:str, away_code:str`. Ordena por
  `(date, draw_order)`. Archivo ausente/vacío → `[]` (la pestaña avisa).
- `neutral_prediction(params, home, away, form_factor) -> dict` con `p_home, p_draw,
  p_away, p_adv_home` (= `p_home + 0.5·p_draw`), promediando ambas orientaciones y
  renormalizando.
- `render_knockouts(app_data, fixtures_csv=DEFAULT_KO_CSV, form_builder=make_form_factor_fn)`
  — `form_builder` inyectable para tests (sin red, determinista).

## Factor de forma (R2)

Slider `st.slider("Peso forma (γ)", 0.0, 1.0, 0.0, 0.05)`. Construcción del factor UNA
vez por render (no por llave) para eficiencia, y cacheada por γ con `st.cache_data`:
`form_factor = None if γ==0 else form_builder(silver_df, as_of, elo_df, γ, teams_48)`.
`as_of = app_data.params.as_of_date`. Con γ=0 → `None` → `predict_match` ramo v1 exacto.

NOTA de deuda (de Feature 16): `make_form_factor_fn` es O(n) sobre el silver; aquí se
llama 1 sola vez por render (no por llave ni por fecha) y se cachea, evitando el patrón
patológico. No se barre sobre fechas.

## Render (R3, R4)

- Agrupar llaves por `date`; encabezado por día.
- Por llave: `COD_A vs COD_B`, barra/píldoras con `P(A) / X / P(B)`, pick por `p_adv_home`.
- Si una llave tiene un código no resoluble en params → se omite con aviso (degradación).

## main.py (R4)

Añadir `TAB_KNOCKOUTS = "Knockouts"` a la lista `st.tabs([...])` y un bloque
`with tabs[k]: render_knockouts(app_data)`. Las otras tres pestañas quedan idénticas.

## Decisiones y justificación

1. **CSV de datos, no bronze** — evita romper `derive_groups`/`simulate` (12×4) y mantiene
   el bronze como fiel reflejo de la fuente pública.
2. **Predicción en vivo con slider** — el usuario compara v1↔forma sin regenerar archivos;
   reusa F16 sin reentrenar.
3. **Neutralización por promedio de orientaciones** — los knockouts son en sede neutral;
   aplicar la ventaja de local sesga al equipo nominalmente "home".
4. **`form_builder` inyectable** — permite tests deterministas sin tocar disco/silver real.

## Fuera de alcance

- No simula el avance del bracket (R16→Final) con ganadores reales (eso es `simulate`).
- No persiste predicciones (eso es `predict-log`/el CSV ya generado).
- No añade rondas posteriores hasta que se jueguen (el CSV solo trae R32 hoy).
