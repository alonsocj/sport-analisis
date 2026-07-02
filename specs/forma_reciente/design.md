# design.md — Feature 16: forma_reciente

## Arquitectura

Capa nueva `src/form/` que NO reentrena ni modifica la fuerza del Dixon-Coles; calcula
un **factor de forma** por equipo y lo aplica como multiplicador sobre las λ en
inferencia. Flujo:

```
silver/matches.csv ─┐
gold/external_elo.csv ─┤→ form.window(team, as_of) → form.metrics() → form.factor(γ)
                       └→ predict/backtest/simulate aplican λ' = λ_DC · exp(γ·f)
```

Punto de extensión limpio: el predictor (Feature 3/13) acepta un callable opcional
`form_factor(home_code, away_code) -> (mult_home, mult_away)`; si no se pasa o `γ=0`,
devuelve `(1.0, 1.0)` → comportamiento v1 idéntico.

## Contratos de datos

- **Ventana** (`form/window.py`): `build_window(matches, team, as_of, k_pre=5) ->
  list[MatchInWindow]` con campos `date, is_group_wc(bool), gf, ga, opp_code, result`.
  Orden por fecha ascendente; filtro estricto `date < as_of`; ≤3 grupo + ≤K pre-WC.
- **Métricas** (`form/metrics.py`): `team_form(window, elo) -> FormMetrics` con
  `gf_w, ga_w, gd_w, ppg_w, streak` (sufijo `_w` = agregado ponderado).
- **Factor** (`form/factor.py`): estandariza `gd_w` (u otra componente elegida y
  documentada) a z entre las 48 selecciones → `f_team`; `factor(z, γ) = exp(γ·z)`.

## Parámetros (explícitos, versionados en `form/config.py`)

| Parámetro        | Default | Justificación |
|------------------|---------|---------------|
| `k_pre`          | 5       | últimos 5 pre-WC (pedido del usuario) |
| `decay`          | 0.85    | peso recencia `w_i = decay^(rank_reciente)`; suave, no colapsa a 1 partido |
| `tier_ratio`     | 2.0     | partido de grupo WC pesa 2× un amistoso pre-WC (competitivo > friendly) |
| `gamma` (`γ`)    | 0.0     | **default OFF**; no-regresión exacta vs v1 |
| `opp_elo_pivot`  | 1500    | referencia Elo; ajuste `1 + λ_opp·(elo_opp−pivot)/scale` |
| `opp_scale`      | 400     | escala Elo estándar |

## Agregación ponderada (R2, R3)

Para cada partido `i` de la ventana, peso combinado:
`W_i = decay^(rank_i) · tier_i · q_i`, con `tier_i ∈ {1.0 (pre-WC), tier_ratio (grupo)}`
y `q_i` el ajuste de calidad de rival (R3): `q_i = clip(1 + (elo_opp_i − pivot)/scale,
0.5, 2.0)`. Métrica ponderada: `gd_w = Σ(W_i·gd_i)/ΣW_i`. Determinista; sin reloj.

## No-regresión y anti-fuga (R4)

- `γ=0` ⇒ `factor=exp(0)=1.0` ⇒ λ inalteradas ⇒ predicción idéntica a v1 (test tol 1e-9).
- La ventana solo contiene partidos con `date < as_of`; el partido predicho queda fuera
  → no hay fuga. La estandarización z usa solo equipos/datos `< as_of`.
- La fuerza base del Dixon-Coles NO se toca: la forma es un multiplicador de inferencia,
  reversible y aislado.

## Estandarización (R4)

`f_team = (gd_w_team − μ) / σ`, con μ,σ sobre las 48 selecciones del torneo a `as_of`.
SI σ=0 (degenerado) → `f_team=0` para todos (factor 1.0). Equipo sin ventana → `f_team=0`.

## Errores / degradación (R7)

- Equipo sin partidos en ventana → `f_team=0`, factor `1.0` (v1).
- Rival sin Elo en `external_elo.csv` → `q_i=1.0` (peso neutro), warning agregado.
- Sin red: todo lee de silver/gold ya en disco; tests con fixtures.

## CLI (R6)

`--form-weight <γ>` (float, default 0) en `predict`, `backtest`, `simulate`. Pasa el
callable `form_factor` al predictor. Subcomandos previos intactos (test de set exacto).

## Decisiones y justificación

1. **Multiplicador en inferencia, no reentrenar** — preserva v1 como baseline exacto y
   hace la mejora reversible/medible aisladamente (cultura del repo: medir vs v1).
2. **`gd_w` como componente de forma** — diferencia de goles ponderada es robusta y
   ya validada como señal; evita sobre-parametrizar con muestra chica.
3. **Ajuste por Elo del rival** — sin él, una goleada a un rival débil en amistoso
   inflaría la forma; es el riesgo #1 de la ventana corta.
4. **Default `γ=0`** — la feature no puede degradar producción; se adopta solo si F10
   demuestra que bate a v1 (igual que Features 14/15).

## Fuera de alcance

- No predice los 12 partidos de grupo NA hasta que martj42 los publique (o se carguen
  manualmente). No deriva el bracket R32 (eso es `simulate`/`bracket.py`, ya existente).
- No añade stats avanzadas (no hay cobertura WC2026).
