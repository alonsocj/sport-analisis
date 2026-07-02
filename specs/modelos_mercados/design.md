# design.md — Feature 4: modelos_mercados (solo goles)

## Arquitectura

Paquete nuevo `src/markets/` (capa de derivación pura sobre la feature 3) + dos
integraciones mínimas: subcomando `markets` en `src/cli.py` (feature 6) y
sub-pestaña `Mercados` en `src/app/tabs/calendario.py` (feature 9, hueco reservado
por diseño). Cero dependencias nuevas; cero datos nuevos: todo se deriva de la
matriz `P(X=x, Y=y)` ya renormalizada de `predict_match`/`score_matrix`.

| Módulo                          | Responsabilidad                                                | Requisitos |
|---------------------------------|----------------------------------------------------------------|------------|
| `src/markets/__init__.py`       | Marca de paquete (docstring, sin imports).                     | R1, R10 |
| `src/markets/goals.py`          | Funciones puras: O/U, BTTS, totales, `market_summary`.         | R1–R6, R9 |
| `src/cli.py` (extensión mínima) | Subcomando `markets` (parser + handler, patrón de `predict`).  | R7 |
| `src/app/tabs/calendario.py` (extensión mínima) | Cuarta sub-pestaña `Mercados` en el detalle. | R8 |

## API (firmas orientativas)

- `DEFAULT_TOTAL_LINES: tuple[float, ...] = (0.5, 1.5, 2.5, 3.5, 4.5)` (R2);
  `DEFAULT_TEAM_LINES: tuple[float, ...] = (0.5, 1.5, 2.5)` (R4).
- `_validate_line(line: float) -> None` — `ValueError` si `line - 0.5` no es entero
  ≥ 0 (mensaje: formato `k + 0.5`) (R2, R4).
- `prob_over(matrix, line) -> float` — `sum(M[x, y] for x+y > line)`. Con líneas
  `.5` no hay push: la desigualdad estricta equivale a `x+y >= ceil(line)` (R2).
- `prob_btts(matrix) -> float` — `M[1:, 1:].sum()` (R3).
- `prob_team_over(matrix, side: Literal["home","away"], line) -> float` —
  marginal por filas (`home`) o columnas (`away`) (R4).
- `@dataclass(frozen=True) MarketLine`: `line: float, over: float, under: float`.
- `@dataclass(frozen=True) MarketSummary`: `home_code, away_code, prob_home,
  prob_draw, prob_away, totals: tuple[MarketLine, ...], btts_yes, btts_no,
  home_totals: tuple[MarketLine, ...], away_totals: tuple[MarketLine, ...]`.
- `market_summary(params, home_code, away_code, total_lines=DEFAULT_TOTAL_LINES,
  team_lines=DEFAULT_TEAM_LINES) -> MarketSummary` — llama `predict_match` UNA vez
  y deriva todo de `pred.matrix`; `UnknownTeamError` se propaga (R5). Líneas de
  salida en orden ascendente (R9).

Numpy permitido (la matriz ya es `np.ndarray` del contrato feature 3); resultados
casteados a `float` nativo (serializables a JSON sin sorpresas).

## CLI (R7)

`python -m src.cli markets HOME AWAY [--json] [--lines 0.5,1.5,2.5]`

- Parser hermano de `predict` (mismo patrón de subparsers existente; `--lines`
  parsea CSV de floats y aplica `_validate_line` → error argparse exit `2` si
  malformado, `error: <mensaje>` exit `1` si línea inválida de formato).
- Salida humana: bloque 1X2 (formato de `predict`) + tabla `O/U` por línea +
  `BTTS sí/no` + totales por equipo, todos los % con 1 decimal.
- `--json`: `json.dumps` del `MarketSummary` (dataclasses → dict).
- Errores: params ausentes → mismo mensaje accionable de `predict` (`train`),
  exit `1`; `UnknownTeamError` → mensaje claro, exit `1`. Reutiliza los helpers de
  error existentes del CLI; los subcomandos previos no cambian (suite previa verde).

## App (R8)

En `src/app/tabs/calendario.py`, dentro del detalle de partido predecible: las
sub-pestañas pasan de `["Predicción", "Equipos", "Historial Elo"]` a
`[..., "Mercados"]` (constante extendida). La pestaña renderiza con `st.dataframe`
o tabla markdown: O/U por línea, BTTS, totales por equipo — datos de
`market_summary` (cacheado con el mismo patrón `@st.cache_data` por
`(home_code, away_code)` de `main.py`). Misma fuente de verdad que el CLI (R8).
NO se tocan `src/app/data.py`, `figures.py`, `main.py`, `selecciones.py`,
`modelo.py`.

## Manejo de errores

| Situación                         | Comportamiento                                  | Requisito |
|-----------------------------------|--------------------------------------------------|-----------|
| Línea no `k + 0.5`                | `ValueError` con formato esperado               | R2, R4 |
| Código desconocido                | `UnknownTeamError` propagada (capa pura); CLI la traduce a `error:` + exit 1 | R5, R7 |
| Params ausentes (CLI)             | Mensaje accionable `train`, exit 1              | R7 |
| Partido no predecible (app)       | Sin sub-pestaña Mercados (degradación feature 9) | R8 |
| Excepción no listada (bug)        | Se propaga                                       | — |

## Testing (R<n> → test, ver tasks.md)

- `tests/test_markets.py` — capa pura: oráculo 3×3 a mano (R6), validación de
  líneas (R2/R4), sumas a 1 (R2/R3), `market_summary` con params sintéticos de
  fixture (R5), determinismo (R9), pureza de imports (R1, R10).
- `tests/test_cli_markets.py` — subcomando: éxito humano y `--json` (parsea),
  errores accionables y exit codes, `--lines` custom (R7).
- `tests/test_app_markets_ui.py` — `AppTest`: sub-pestaña `Mercados` presente en
  detalle predecible con porcentajes; ausente si no predecible (R8). Archivo NUEVO
  (no se toca `tests/test_app_ui.py`).

## Decisiones y justificación

- **Solo líneas `k + 0.5`** → sin push (probabilidad de empate de la apuesta);
  líneas enteras y asiáticas requieren reglas de reembolso — no-objetivo v1.
- **Derivar de la matriz renormalizada (truncada a `max_goals=10`)** → coherente
  con 1X2 y top-k del CLI/app (una sola fuente de verdad); el error de truncado es
  despreciable (masa fuera de 10 goles ~0 en fútbol) y ya está asumido por la
  feature 3.
- **Extender `src/cli.py` y `calendario.py` en vez de módulos paralelos** → el
  hueco de la pestaña Mercados quedó reservado por diseño en la feature 9 y el CLI
  es la superficie natural; la extensión es aditiva y la suite previa protege
  contra regresiones (R7, R10).
- **`UnknownTeamError` se propaga sin envolver** → mismo contrato que feature 3;
  los consumidores (CLI/app) ya saben traducirla.
- **Sin pandas en la capa pura** → operaciones de matriz puras con numpy ya
  presente; tablas solo en la capa de presentación.

## No-objetivos (explícitos)

- Córners y tarjetas (sin datos; exigiría ingesta API real — decisión usuario
  2026-06-09). La extensión futura reutilizará `MarketLine`/patrón de `goals.py`.
- Líneas enteras/asiáticas (push/reembolso), hándicaps.
- Comparación contra cuotas de casas y value bets (feature 5, backtesting/ROI).
- Marcador exacto (ya lo dan `top_scores` y el heatmap de las features 3/9).
