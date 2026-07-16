# design.md — Feature 34: final_tercer_puesto

Decisiones técnicas para cerrar el torneo: Final (R2) + 3er puesto (3P) en pipeline y app,
más un simulador Monte Carlo de un cruce fijo. Aditivo y aislado (ver `requirements.md`).

## Alcance y no-alcance

- SÍ: fixtures r2/r3p, detección 3P, dampening dead-rubber, simulador de un enfrentamiento,
  artefactos de predicción, CLI `simulate-match`, pestaña `🏆 Final`.
- NO: tocar `montecarlo.py` (torneo completo), el 1X2/marcador base, mercados existentes,
  ni las 6 pestañas actuales. NO re-scrape masivo per-mitad. NO nuevas dependencias.

## Arquitectura (por unidad)

### U1 — Writer de fixtures (`src/ingestion/fotmob_ko.py`, extensión)
- `_FIXTURE_FILES[5] = ("Final", "r2_fixtures.csv")`.
- 3er puesto: NO cabe en el mapeo ordinal→archivo (comparte ronda con la Final). Se añade
  `_THIRD_PLACE_FILE = ("3P", "r3p_fixtures.csv")` y en `write_ko_fixtures` un paso que filtra
  los `KoMatch` con `stage == "3P"` hacia ese archivo (mismo esquema, `draw_order` propio).
- **Qué hace / interfaz / depende de**: entrada = `list[KoMatch]`; salida = dict `stage→Path`;
  depende sólo de `KoMatch` y csv. Sin red.

### U2 — Detección 3P (`src/ingestion/fotmob_ko.py`, `parse_playoff_bracket`)
- Regla: en la última ronda de `playoff.rounds`, si hay >1 matchup, el matchup del 3er puesto
  se marca `stage="3P"` (ordinal 5, `is_third_place=True`) y el otro queda `stage="Final"`.
- Clasificación determinista y en cascada:
  1. Etiqueta fotmob: si el matchup/round trae nombre que contiene "3rd"/"third"/"third-place"
     (case-insensitive) → 3P.
  2. Fallback por emparejamiento: se calculan los 2 perdedores de semis (de los `KoMatch`
     SF finalizados); el matchup cuyos dos equipos son ambos perdedores de SF → 3P; el de los
     dos ganadores → Final.
  3. Si no se puede desambiguar (semis sin marcador) → ninguno se marca 3P y sólo se escribe la
     Final cuando sus dos códigos existan (comportamiento conservador; no inventa el 3P).
- Se añade campo opcional `is_third_place: bool = False` a `KoMatch` (retrocompatible;
  default preserva el comportamiento previo). `stage` se deriva de él.

### U3 — Dead-rubber (`src/models/dead_rubber.py`, nuevo)
- `shrink_strengths(attack, defense, mean_a, mean_d, delta) -> (a', d')`:
  `a' = mean_a + (1-delta)*(attack-mean_a)`, idem defensa. `delta=0` → identidad.
- `apply_dead_rubber(lambda_h, lambda_a, kappa) -> (λ_h*, λ_a*)`: `λ* = λ*kappa`. `kappa=1` →
  identidad. (El aplanado de fuerza va vía `shrink_strengths` sobre los coef antes de `match_rates`;
  el bump κ va sobre las λ resultantes.)
- Config `DeadRubber(delta: float, kappa: float)` inyectable. **Defaults**: `delta=0.45`,
  `kappa=1.12`. Justificación histórica documentada en el módulo: los partidos por el 3er puesto
  de Mundiales promedian ~3.4 goles/partido vs ~2.6 en finales (más abiertos, menos presión);
  `delta` aplana la ventaja del favorito por menor motivación del que "debería" ganar.
- **Interfaz / depende de**: funciones puras sobre floats/coeficientes; sin estado, sin red.
- No-regresión: `DeadRubber(0.0, 1.0)` == baseline byte-idéntico.

### U4 — Simulador de cruce fijo (`src/simulation/match_sim.py`, nuevo)
- `@dataclass MatchSimResult`: `home, away, n, seed, p_home, p_away, p_reg, p_et, p_pens,
  modal_score:(int,int), top_scores:list[((int,int),float)], e_goals, markets:dict, std_err:dict`.
- `simulate_fixture(home, away, params, n=DEFAULT_N, seed=DEFAULT_SEED, form_factor=None,
  dead_rubber=None) -> MatchSimResult`:
  1. Computa `MatchParams` del cruce reusando `_compute_single_match_params` (DC + forma +
     roster opcional). Si `dead_rubber`: aplica `shrink_strengths` a los coef del cruce y
     `apply_dead_rubber` (κ) a las λ **antes** de `score_matrix`.
  2. N iteraciones: `sample_score` (90'); si empate → ET fresco (`score_matrix` con λ×1/3,
     re-muestreo) ; si sigue empate → penales Bernoulli ponderada. Cuenta camino (reg/ET/pens)
     y ganador.
  3. Marcador modal y top-k de 90' desde el **histograma muestreado** (no de la matriz
     analítica, para que el error MC sea reportable y coherente con las probs).
  4. Mercados O/U 1.5/2.5/3.5 + BTTS del marcador de 90'. `e_goals` = media muestreada.
  5. `std_err[m] = sqrt(p(1-p)/n)` por métrica de proporción.
- Determinismo: `np.random.default_rng(seed)`. `n≥MIN_N_SIMULATIONS` (reusa constante) salvo
  `_allow_small_n`.
- **Cross-check**: `p_home`/`p_away` muestreados deben caer dentro de ±3·errorMC de las probs
  analíticas de la matriz (test), validando el muestreo.
- **Depende de**: `dixon_coles`, `montecarlo` (`_compute_single_match_params`, `sample_score`,
  `MAX_GOALS`, `MIN_N_SIMULATIONS`), `dead_rubber`. Sin red, sin reloj.

### U5 — Writer de artefactos (`src/simulation/match_sim.py`)
- `write_sim_result(res: MatchSimResult, path) -> Path`: serializa a CSV plano (una fila
  resumen + top_scores en columnas o JSON embebido en una celda). Sólo bajo `data/`.

### U6 — CLI (`src/cli.py`, subcomando `simulate-match`)
- Flags: `--fixture {r2,r3p}` (lee el csv y toma la fila 1) o `--home/--away`; `--n`, `--seed`,
  `--gamma` (forma), `--dead-rubber` (activa `DeadRubber` defaults; sólo tiene efecto si se pasa).
  `--out` (default `data/predictions/{fixture}_sim.csv`).
- Carga params entrenados (`load_params`) + `form_factor` como en las rondas KO previas.
- Imprime tabla: P(ganador), reparto camino, top-5 marcadores, mercados. `✅` al terminar.
- No-regresión: el `argparse` previo intacto; sólo se AÑADE el subparser.

### U7 — App (`src/app/main.py` + `src/app/tabs/knockouts.py` o helper)
- `TAB_FINAL = "🏆 Final"`; `tabs[6]`. Contenido: dos `st.subheader` (Final / 3er puesto).
  - Final: `render_knockouts(..., state_key="r2", default_csv=r2_fixtures.csv)` + panel MC.
  - 3er puesto: `render_knockouts(..., state_key="r3p", default_csv=r3p_fixtures.csv)` + panel MC
    con `dead_rubber` activado.
- Panel MC (`render_sim_panel`): llama `simulate_fixture` (o lee el artefacto R6 si existe) y
  pinta P(ganador) (metric/gauge), tabla top marcadores, reparto 90'/ET/penales, mercados.
- Aditivo: las 6 pestañas previas y `render_knockouts` no cambian su firma (se añaden
  `state_key` nuevos r2/r3p, ya soportados por el patrón namespaced de F30/F33).

## Flujo de datos (operativo, pre-requisito — regla STOP)

1. `ingest-ko` + `ingest-lineups` de semis (scrape fotmob real → **STOP, pedir aprobación**).
   Resuelve marcadores SF → aparecen Final (r2) y 3er puesto (r3p) con códigos.
2. `build-features` → silver/gold/player_factor actualizados.
3. `train --as-of-date 2026-07-15` → params.
4. `simulate-match --fixture r2` y `--fixture r3p --dead-rubber` → artefactos R6.
5. App lee fixtures + artefactos.

## Manejo de errores

- Fixture inexistente / vacío → error claro en CLI; la app muestra "pendiente" (patrón KO).
- Equipo fuera de `params` → λ fallback 1.0 (igual que `montecarlo`).
- Semis sin marcador → no se inventa 3P (U2 regla 3); Final sólo si códigos resueltos.

## Testing (resumen; detalle en tasks.md)

- Unidad: U1 escritura r2/r3p; U2 detección 3P (mock JSON: etiqueta y fallback por perdedores);
  U3 shrink/κ (OFF idéntico, ON sube goles y baja P(favorito), acotado); U4 determinismo,
  suma de probs, cross-check vs analítico, efecto dead-rubber; U5 esquema artefacto; U6 CLI +
  subcomandos intactos; U7 app 7 pestañas, ambos bloques, dead-rubber sólo en 3P.
- No-regresión: flag OFF byte-idéntico; suite previa 686 verde.
