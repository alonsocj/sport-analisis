# design.md — Feature 14: elo_externo_ensemble

## Arquitectura

Reusa el patrón de ingesta CC0 (`public_data`), el `elo_history` de la feature 2,
el modelo Dixon-Coles y el harness de backtest. Paquete nuevo `src/elo_ext/`. Única
dep nueva: `lxml` (aprobada security-lead 2026-06-17, con parser seguro).

| Módulo                        | Responsabilidad                                                       | Requisitos |
|-------------------------------|----------------------------------------------------------------------|------------|
| `src/ingestion/elo_ratings.py`| Descarga eloratings (transporte inyectable), parser seguro lxml, validación de columnas, bronze+meta, caché TTL. | R1, R2 |
| `src/elo_ext/model.py`        | Sub-modelo Elo→1X2 (fórmula estándar + param empate); fuente de Elo as-of (elo_history) o snapshot (externo); artefacto gold. | R3, R4, R7 |
| `src/elo_ext/ensemble.py`     | Mezcla `p=(1−w)·p_DC + w·p_Elo`; default w=0 = v1; ajuste de w por backtest. | R5, R6 |
| `src/cli.py` (extensión)      | `ingest-elo`; flags `--elo-weight` en predict/predict-log/simulate; ajuste w en backtest. | R8 |

Flujo:

```
ingest-elo ─► bronze/elo/eloratings_<fecha>.html (+meta) ─► gold/external_elo.csv   (R1-R3)
elo_model(elo_a, elo_b, neutral) ─► p_Elo (1X2)                                      (R4)
   fuente Elo: backtest → elo_history as-of (<fecha, leak-free); live → externo      (R7)
ensemble: p = (1−w)·p_DC + w·p_Elo   (w=0 ⇒ idéntico DC)                              (R5)
backtest walk-forward (elo_history as-of) ─► w* que minimiza log-loss; v1 vs ensemble (R6)
predict/predict-log/simulate --elo-weight w ─► usa ensemble (Elo externo si --as-of=hoy)
```

## Parser seguro (R1, security-lead)

- `pandas.read_html(html, flavor="lxml")` para la tabla de eloratings (usa
  `lxml.html.HTMLParser` interno, no el XMLParser vulnerable). NUNCA pasar HTML crudo
  a `etree.fromstring`/`parse`. Si se requiere parseo directo, usar
  `etree.HTMLParser(no_network=True, huge_tree=False)`.
- Validar columnas esperadas (selección, rating) tras el parseo; si no están →
  `EloParseError` ruidoso (no DataFrame vacío silencioso).
- Caché: si `data/bronze/elo/eloratings_<fetched_date>.html` existe y < TTL (7d) → no
  re-descargar. UA identificable inyectado en la request real.

## Sub-modelo Elo→1X2 (R4, R7)

- `expected_score(ΔElo, H) = 1/(1+10^(−(ΔElo+H)/400))`; `H` = ventaja local en puntos
  Elo, 0 si `neutral`. Parámetros `H` y escala inyectables.
- De expected score (continuo 0..1) a 1X2: usa un parámetro de empate `d` (banda de
  probabilidad de empate documentada, p.ej. `p_draw = d·(1 − |2·E − 1|)` con
  `p_home/p_away` repartiendo el resto según `E`). Fórmula exacta documentada en el
  módulo; `d` se calibra junto con `w` en R6.
- **Fuente de Elo (R7)**: en backtest, `elo_history` con el valor as-of `< fecha`
  (leak-free). En live (`--as-of` = hoy), opcionalmente el Elo externo de eloratings
  (snapshot). El código DEBE rechazar el Elo externo en rutas de backtest.

## Ensemble y ajuste (R5, R6)

- `ensemble(p_dc, p_elo, w) = (1−w)·p_dc + w·p_elo`, renormalizado (suma 1). `w=0` ⇒
  `p_dc` exacto (test de equivalencia v1).
- Ajuste: rejilla pequeña de `w ∈ {0,0.1,…,0.5}` × `d` sobre el backtest walk-forward
  (reusa `src/backtest/`), elige el de menor log-loss; reporta DC vs mejor ensemble.

## CLI (R8)

- `ingest-elo [--url ...] [--ttl-days 7] [--out ...]` (red real; test con transporte
  inyectado). UA identificable.
- `--elo-weight <w>` (default 0.0) en `predict` y `predict-log` (nivel 1X2, donde el
  ensemble está bien definido). `w=0` no cambia comportamiento. En `predict-log` el
  `model_version` se etiqueta `dc-ens` cuando `w>0`, y el Elo es `elo_history` as-of
  (leak-free) → así el ensemble se MIDE con el harness de la feature 10.
- **`simulate` queda EXCLUIDO del ensemble** (decisión 2026-06-17): la simulación
  trabaja a nivel de marcador (muestrea scorelines para puntos/diferencia de goles),
  y el ensemble es a nivel de probabilidad 1X2; inyectarlo exigiría muestrear el
  desenlace del 1X2 ensamblado y luego un marcador condicional — fuera de alcance.
  `simulate` usa DC puro (o dc-v2). Extensión futura documentada.
- `backtest`: opción para barrer `w` y reportar el óptimo.
- Conjunto de subcomandos: previos + `ingest-elo` (aserción exacta endurecida).

## Decisiones y justificación

- **Ensemble a nivel de probabilidad**, no refit conjunto: robusto, no desestabiliza
  el MLE de DC, y `w=0` garantiza cero regresión.
- **Elo histórico propio para medir, externo para live**: única forma honesta dada la
  limitación de eloratings (snapshot). El beneficio del Elo externo se argumenta
  (mejor calibrado, más historia), no se backtestea — documentado.
- **lxml con parser seguro**: cumple el dictamen security-lead (XXE/billion-laughs).

## Fuera de alcance

xG (feature 15); blend con cuotas de mercado (no hay cuotas free de Mundial);
refit conjunto Elo+DC en un único likelihood; series históricas de Elo externo
(eloratings no las publica).
