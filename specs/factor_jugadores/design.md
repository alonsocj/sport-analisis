# design.md — Feature 11: factor_jugadores

## Arquitectura

Reusa el patrón de ingesta CC0 (`src/ingestion/public_data.py`) y el modelo
(`src/models/dixon_coles.py`). Paquete nuevo `src/players/` para la lógica pura.
NO se instala nada nuevo (pandas/numpy/requests ya presentes).

| Módulo                              | Responsabilidad                                                        | Requisitos |
|-------------------------------------|-----------------------------------------------------------------------|------------|
| `src/ingestion/goalscorers.py`      | Descarga CC0 (transporte inyectable), valida encabezado, bronze+meta. | R1         |
| `src/players/__init__.py`           | Paquete vacío.                                                         | —          |
| `src/players/normalize.py`          | bronze goalscorers → silver de eventos (excluye own goals, mapea equipos). | R2     |
| `src/players/factor.py`             | Tabla de cuotas/tasas por jugador (decaimiento, anti-fuga); anytime-scorer; multiplicador por roster; artefacto gold. | R3–R6 |
| `src/cli.py` (extensión)            | Subcomandos `ingest-goalscorers`, `scorers`; extensión de `build-features` para construir el artefacto de jugadores si hay bronze de goleadores. | R7 |

Flujo:

```
ingest-goalscorers ─► bronze/goalscorers/goalscorers.csv (+meta, fetched_at inyectado)   (R1)
build-features (as_of) ─► normalize ─► silver eventos ─► factor.build(as_of, xi)
                                         ─► gold/player_factor.csv  (cuotas por jugador)   (R2,R3,R6)
scorers --home --away [--as-of] [--roster]
   λ_equipo (Dixon-Coles predict_match) × cuota_jugador ─► P(marca) = 1−exp(−λ_jugador)    (R4)
   [--roster] multiplicador de ataque (Σ cuotas disponibles) ─► ajusta λ_equipo           (R5)
```

## Contrato de datos

- **bronze** `data/bronze/goalscorers/goalscorers.csv` + `.meta.json`
  (`url, fetched_at(inyectado), sha256, n_rows, header`). Encabezado exacto:
  `date, home_team, away_team, team, scorer, minute, own_goal, penalty`.
- **silver eventos** (en memoria/temporal, no necesariamente persistido):
  `date, team_code, scorer, penalty` tras excluir `own_goal == TRUE` y mapear
  `team` → código.
- **gold** `data/gold/player_factor.csv`, columnas ordenadas:
  `as_of_date, team_code, scorer, goals_weighted, share`. Orden determinista por
  (`team_code`, `share` desc, `scorer`). `share` = goals_weighted_jugador /
  Σ goals_weighted_equipo (suma por equipo ≈ 1, tol 1e-9).

## Cálculo del factor (R3, R4)

- Decaimiento: `w = exp(−ξ · Δaños(fecha, as_of))` con el mismo ξ del modelo
  (default `DCConfig.xi = 0.35`), parametrizable. Solo eventos `fecha < as_of`
  (anti-fuga; test de mutación con eventos posteriores).
- `goals_weighted(team, scorer) = Σ w` sobre eventos de gol (sin own goals) de ese
  jugador para ese equipo. `share = goals_weighted / Σ_equipo goals_weighted`.
- **anytime-scorer** (R4): para un partido, `λ_equipo` = goles esperados del equipo
  según `predict_match` (Dixon-Coles). `λ_jugador = share · λ_equipo`;
  `P(marca ≥ 1) = 1 − exp(−λ_jugador)`. Supuesto documentado: sin minutos ni
  alineaciones, la cuota histórica de goles aproxima la participación ofensiva del
  jugador; no distingue titular/suplente ni lesionados (eso requeriría API).

## Ajuste de ataque por roster (R5)

- `roster.csv`: `team_code, scorer` (jugadores DISPONIBLES). Multiplicador del
  equipo = `min(1.0, Σ share de los disponibles)`; si el roster no se provee,
  multiplicador = 1.0 (identidad estricta → modelo intacto). Se aplica como factor
  sobre `λ_equipo` antes de derivar anytime-scorer y queda disponible para que las
  features 12/13 lo usen al construir λ. Decisión: identidad por defecto evita
  corromper el baseline cuando no hay datos de disponibilidad reales.

## CLI (R7)

- `ingest-goalscorers` (CC0; segundo subcomando con red, documentado). Patrón de
  `ingest-public`.
- `scorers --home <cod> --away <cod> [--as-of <fecha>] [--top-k N] [--roster <csv>]`:
  carga `player_factor` (o lo construye al vuelo con `--as-of`), calcula λ_equipo
  vía Dixon-Coles y lista top-k por equipo. Exit `0/1/2`. Aserción de subcomandos
  endurecida al conjunto exacto.
- `build-features`: si existe bronze de goleadores, construye `gold/player_factor.csv`
  con el `as_of_date` del comando; si no, lo omite con aviso (no rompe el flujo
  existente).

## Decisiones y justificación

- **CC0 only, sin tocar el 1X2 por defecto**: la λ de equipo del Dixon-Coles ya
  modela los goles del equipo; derivar anytime-scorer por thinning evita doble
  conteo. El único acoplamiento al modelo es el multiplicador por roster, y es
  identidad sin datos → cero regresión en 1X2/backtest.
- **Eventos, no per-90**: limitación honesta de la fuente; documentada en R4 y en la
  salida del CLI.
- **Determinismo**: cuotas y artefacto reproducibles (decaimiento sobre fechas del
  dataset, sin reloj).

## Fuera de alcance

Ratings/xG/minutos/lesiones (API real → STOP); mercados de córners/tarjetas
(excluidos por decisión usuario); integración del multiplicador en el refit del
modelo (feature 12) y en la simulación (feature 13) — aquí solo se entrega el hook.
