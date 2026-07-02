# design.md — Feature 19: forma_vs_v1_panel

## Arquitectura

Una sección nueva en `src/app/tabs/modelo.py`, llamada al final de `render_modelo`.
Reusa el patrón de `_render_backtest_section` (leer JSON → degradar si falta → render).
No toca otros módulos.

```
data/reports/forma_vs_v1.json ──→ _render_forma_vs_v1(path) ──→ tabla + verdict + caveat
```

## Schema del artefacto (R1)

```json
{
  "titulo": "str", "from_date": "YYYY-MM-DD", "to_date": "YYYY-MM-DD",
  "n_eval": int, "baseline": "dc-v1 (gamma=0)", "caveat": "str",
  "rows": [ {"gamma": float, "log_loss": float, "brier": float,
             "accuracy": float, "is_baseline": bool}, ... ],
  "verdict": "str", "fuente": "str"
}
```
El artefacto ya existe (`data/reports/forma_vs_v1.json`), generado consolidando
`backtest --form-weight {0,0.2,0.3}` sobre la ventana WC. Esta feature solo lo LEE.

## Cambios en `src/app/tabs/modelo.py`

- Constante `DEFAULT_FORMA_VS_V1 = Path("data/reports/forma_vs_v1.json")`.
- `_render_forma_vs_v1(path: Path) -> None`:
  - `st.subheader("Forma reciente vs v1")`.
  - Si `not path.is_file()` o JSON inválido / schema inesperado → `st.info(...)` con cómo
    regenerarlo, y `return` (degradación, R1).
  - Tabla: una fila por `row`, columnas log-loss/Brier/exactitud; calcular Δ vs la fila
    baseline (`is_baseline=True`): para log-loss/Brier `valor − base` (negativo = mejora),
    para exactitud `valor − base` (positivo = mejora). Render con `st.dataframe` o tabla
    de markdown; marcar la fila baseline (etiqueta "v1").
  - `st.success(verdict)` (o `st.metric` del mejor Δ); `st.caption` con ventana
    (`from_date`–`to_date`), `n_eval` y `caveat`.
- En `render_modelo`, tras `_render_backtest_section(...)`, llamar
  `_render_forma_vs_v1(DEFAULT_FORMA_VS_V1)`.

## Render del Δ (R2)

- log-loss, Brier: menor es mejor → Δ negativo se muestra como mejora (p.ej. verde/“▼”).
- exactitud: mayor es mejor → Δ positivo es mejora.
- Mostrar el % relativo opcional (ya viene resumido en `verdict`).

## Degradación (R1, R4)

Archivo ausente/JSON inválido/`rows` vacío o sin baseline → `st.info` accionable, sin
excepción. Sin red, sin recálculo. Cualquier `row` con claves faltantes se omite con aviso.

## Decisiones y justificación

1. **Leer artefacto, no recalcular** — el backtest con refit DC es caro; la app debe ser
   responsiva. El artefacto se regenera fuera de la app (documentado en `fuente`).
2. **En el tab Modelo** — es donde ya vive el panel Backtest; el veredicto forma-vs-v1 es su
   complemento natural.
3. **Caveat visible** — honestidad: el número es indicativo (continuación de grupos, muestra
   chica), no prueba para knockouts.

## Fuera de alcance

- No ejecuta backtest desde la app. No regenera el artefacto (proceso externo documentado).
- No añade un subcomando CLI (el set de 14 subcomandos queda intacto).
