# design.md — Feature 3: modelo_resultado

## Arquitectura

Un **único módulo nuevo**: `src/models/dixon_coles.py`. Los módulos de features
anteriores se usan **solo en lectura** y NO se modifican: `src/ingestion/teams.py`
(`is_host`, anfitrionas MEX/USA/CAN) y el silver de la feature 2
(`data/silver/matches.csv`, contrato en `specs/feature_store/design.md`). Todo es
**offline**: no hay red, no se usa `API_FOOTBALL_KEY` ni `Settings` de `config.py`
(mismo razonamiento que features 2 y 7).

| Módulo                       | Responsabilidad                                                              | Requisitos |
|------------------------------|------------------------------------------------------------------------------|------------|
| `src/models/dixon_coles.py`  | Carga silver, recorte temporal, pesos de decaimiento, MLE ponderada (L-BFGS-B, objetivo vectorizado), identificabilidad, persistencia JSON, predicción (matriz conjunta, 1X2, top-k). | R1–R18 |
| `src/ingestion/teams.py` (lectura) | `is_host(code)` para la localía en predicción.                          | R13        |

Flujo:

```
data/silver/matches.csv ──filtro [from_date, as_of_date)──► arrays numpy ──L-BFGS-B──► DixonColesParams
                                                                                          │ save/load
                                                              data/gold/dixon_coles_params.json
                                                                                          │
                              predict_match(params, home, away) ──► {matriz conjunta, 1X2, lambdas, top-k}
```

## Entrada: contrato silver consumido (R1)

De `data/silver/matches.csv` (feature 2) se usan SOLO estas columnas; el resto
(nombres, stats, `tournament`, `source`) se ignora:

| Columna      | Uso                                                        |
|--------------|------------------------------------------------------------|
| `match_id`   | desempate determinista al ordenar `(date, match_id)`       |
| `date`       | recorte temporal y pesos de decaimiento (`YYYY-MM-DD`)     |
| `home_code`  | índice de equipo local (FIFA 3 letras o slug)              |
| `away_code`  | índice de equipo visitante                                 |
| `home_goals` | `x_i` observado                                            |
| `away_goals` | `y_i` observado                                            |
| `neutral`    | `h_i = 1 − neutral` en entrenamiento (R4)                  |

SI el archivo no existe o falta alguna de estas columnas → `SilverNotFoundError`
con ruta/columna en el mensaje (R1). Lectura con `pandas.read_csv`; los tests no
dependen de la implementación de la feature 2: escriben un CSV sintético con este
esquema en `tmp_path`.

## Especificación del modelo (R4, R5)

Para el partido `i` con local `H` y visitante `A`:

```
X_i ~ Poisson(lambda_home_i)        lambda_home_i = exp(mu + att_H − def_A + gamma·h_i)
Y_i ~ Poisson(lambda_away_i)        lambda_away_i = exp(mu + att_A − def_H)
```

- `mu`: log-tasa base de goles. `gamma`: ventaja de localía en escala log (solo en
  `lambda_home`, nunca en `lambda_away`).
- Convención de signos: `att` mayor → más goles a favor; `def` mayor → **mejor**
  defensa (resta a la tasa del rival).
- `h_i` en **entrenamiento**: `1` si `neutral = False`, `0` si `neutral = True` (R4).
  En **predicción** Mundial 2026: `1` SOLO si `is_host(home_code)` (MEX/USA/CAN),
  `0` para cualquier otro local (sede neutral) (R13). La asimetría es deliberada:
  el histórico contiene localías reales de cualquier selección (de ahí se estima una
  `gamma` genérica); en el Mundial 2026 solo las anfitrionas juegan de verdad en casa.

Corrección Dixon-Coles (Dixon & Coles, 1997, *Modelling Association Football Scores
and Inefficiencies in the Football Betting Market*, JRSS-C 46(2)) sobre los cuatro
marcadores bajos (R5):

| (x, y) | `tau(x, y; lambda_h, lambda_a, rho)`  |
|--------|----------------------------------------|
| (0, 0) | `1 − lambda_h · lambda_a · rho`        |
| (0, 1) | `1 + lambda_h · rho`                   |
| (1, 0) | `1 + lambda_a · rho`                   |
| (1, 1) | `1 − rho`                              |
| resto  | `1`                                    |

`rho < 0` aumenta la probabilidad de 0-0 y 1-1 (dependencia negativa observada en
fútbol); `rho = 0` recupera el Poisson independiente.

## Decaimiento temporal (R3)

```
w_i = exp(−xi · dias(date_i, as_of_date) / 365.25)
```

`dias()` = `(as_of_date − date_i).days` con `datetime.date.fromisoformat` (ambas
fechas `YYYY-MM-DD`; el recorte estricto garantiza `dias ≥ 1`).

**Default `xi = 0.65` (por año), configurable.** Justificación: Dixon & Coles (1997)
estiman empíricamente `ξ = 0.0065` por **media semana** maximizando la capacidad
predictiva en ligas inglesas. Anualizado: `0.0065 × (365.25 / 3.5) ≈ 0.678` →
redondeado a `0.65` (half-life `ln 2 / 0.65 ≈ 1.07` años ≈ 13 meses). Se descarta el
ejemplo `xi = 1.0` (half-life ~8.3 meses) por agresivo para fútbol de selecciones
(~10 partidos/año por equipo frente a ~50 de clubes: conviene conservar algo más de
historia efectiva). Revisable con el backtesting (feature 5). Pesos resultantes:

| Antigüedad | 6 meses | 1 año | 2 años | 4 años | 8 años |
|------------|---------|-------|--------|--------|--------|
| `w_i`      | 0.72    | 0.52  | 0.27   | 0.074  | 0.006  |

## Recorte temporal y universo de equipos (R2, R8)

- **Ventana de entrenamiento**: `from_date <= date < as_of_date` (estricto, R2;
  mismo anti-leakage que R9 de la feature 2). `as_of_date` SIEMPRE inyectada.
- **`from_date` default `2018-01-01`**. Justificación: con `xi = 0.65`, un partido de
  8 años pesa `≈ 0.006` — la información perdida por el recorte es despreciable (el
  decaimiento ya la anula) y a cambio se acota el universo de equipos del CSV público
  (silver llega a 1872) y con él el número de parámetros (`3 + 2(n−1)`), mejorando el
  condicionamiento y el coste del optimizador. Configurable.
- **Universo de equipos**: TODOS los códigos presentes en el recorte (las 48 + slugs
  fuera de las 48). Mismo argumento de red que el Elo global de la feature 2: las
  fuerzas se estiman contra oponentes cuyos parámetros también deben existir; recortar
  a las 48 sesgaría las estimaciones.
- **Equipos con `< min_matches` partidos (default 5)**: se cuentan los partidos
  (sin ponderar) del equipo en el recorte (como local o visitante). Decisión:
  **incluir igualmente + shrinkage hacia 0** vía penalización L2 (abajo), y listarlos
  en `low_data_teams` (orden alfabético) en los parámetros persistidos para
  transparencia. Justificación: excluirlos rompería la red de oponentes (descartar sus
  partidos quita información de equipos bien muestreados); el ridge acota la varianza
  de sus coeficientes contrayéndolos hacia el equipo medio (`att = def = 0` bajo la
  restricción de suma cero) con sesgo despreciable para equipos bien muestreados
  (ver curvatura abajo).

## Ajuste por máxima verosimilitud ponderada (R6, R7, R8, R10)

### Vector de parámetros e identificabilidad (R7)

El modelo es invariante a `att → att + c`, `def → def + c'`, `mu → mu − c + c'`:
se impone `sum(att) = 0` y `sum(def) = 0` por **reparametrización** (no penalización):

- Equipos ordenados alfabéticamente por código → mapeo determinista código → índice.
- `theta = [mu, gamma, rho, att_1..att_{n−1}, def_1..def_{n−1}]` (dimensión `3 + 2(n−1)`).
- `att_n = −sum(att_1..att_{n−1})` y `def_n = −sum(def_1..def_{n−1})` (el equipo
  "absorbido" es el último en orden alfabético; se reconstruye con `np.append`).

Justificación frente a penalización: la restricción se cumple de forma **exacta** (no
aproximada según un peso de penalización que habría que calibrar), elimina 2 grados de
libertad redundantes (mejor condicionamiento de L-BFGS-B) y no introduce
hiperparámetros nuevos.

### Función objetivo (vectorizada — contrato del Leader)

Negativa de la log-verosimilitud ponderada, **sin bucles Python por partido**
(restricción dura; el reviewer la verifica por inspección):

```
NLL(theta) = − Σ_i w_i · [ x_i·log(lh_i) − lh_i + y_i·log(la_i) − la_i + log(tau_i) ]
             + reg_lambda · ( Σ_j att_j² + Σ_j def_j² )
```

- Precomputados como arrays numpy (una sola vez, fuera del objetivo): `x, y, w, h`
  (float64) e índices enteros `hi, ai` (posición de local/visitante en el orden
  alfabético de equipos).
- Dentro del objetivo: `lh = exp(mu + att[hi] − def_[ai] + gamma·h)`,
  `la = exp(mu + att[ai] − def_[hi])` por **fancy indexing**; `tau` con máscaras
  booleanas / `np.where` sobre las 4 celdas bajas; `tau` se recorta a
  `max(tau, 1e−10)` antes del `log` (protección de dominio).
- Las constantes `log(x_i!) + log(y_i!)` se **omiten** (no dependen de `theta`); el
  `neg_log_lik` reportado en `convergencia` las excluye (documentado).
- La penalización ridge incluye los coeficientes reconstruidos (`att_n`, `def_n`),
  por lo que la suma cero se mantiene exacta.

**`reg_lambda` default `1.0`**, configurable (`0` desactiva). Calibración: la
curvatura de la NLL respecto a `att_j` es `≈ Σ w_i·lambda_i` sobre los partidos del
equipo (≈ 1.3 por partido efectivo) y la del ridge es `2·reg_lambda`. Con
`reg_lambda = 1`: un equipo con 2 partidos efectivos se contrae ≈ 40–45 %; uno con
≥ 30, < 5 % (sesgo despreciable). Revisable con backtesting.

### Optimizador y determinismo (R6, R10)

- `scipy.optimize.minimize(method="L-BFGS-B")` con:
  - **Punto inicial fijo y determinista**: `mu0 = log(media ponderada de goles por
    equipo y partido)` (calculada de los datos, recortada a `≥ 0.1` antes del log),
    `gamma0 = 0.2`, `rho0 = 0.0`, `att = def = 0`.
  - **Cotas**: `rho ∈ [−0.9, 0.9]` (la región válida exacta de `tau > 0` depende de
    `lambda_h·lambda_a`; caja amplia + clip de `tau` es la salvaguarda práctica
    estándar; los valores ajustados típicos son `|rho| < 0.2`). Resto sin cotas.
  - **Opciones fijas**: `maxiter = config.max_iter` (default 1000),
    `maxfun = max_iter·(dim+1)` donde `dim = 3 + 2(n−1)`, `ftol = 1e−12`,
    `gtol = 1e−8`. Justificación de `maxfun`: sin `jac`, el gradiente numérico por
    diferencias finitas consume `dim+1` evaluaciones de la función por iteración,
    así que escalar `maxfun` con la dimensión mantiene a `maxiter` como límite
    efectivo (el default de scipy, 15000, agotaba las evaluaciones en ~26
    iteraciones con los 569 parámetros del entrenamiento real).
- **Convergencia**: se registra `convergencia = {success, n_iter, message,
  neg_log_lik}` del `OptimizeResult`. SI `success = False` → `warnings.warn` (o
  `logging.warning`) y se devuelven los parámetros con el flag visible, sin abortar
  (R6); forzable en tests con `maxiter = 1` inyectable vía configuración.
- **Determinismo** (R10): no hay RNG ni reloj en el ajuste; datos ordenados por
  `(date, match_id)`; equipos ordenados alfabéticamente; init y opciones fijas. En un
  entorno fijo (mismas versiones de numpy/scipy/BLAS) dos ajustes son idénticos; el
  test compara con tolerancia `1e−12` por coeficiente (margen frente a reducciones
  en coma flotante).

### Sanidad estadística (R9)

Test de recuperación con datos **generados desde el propio modelo**: se fijan
parámetros verdaderos (p. ej. 16 equipos, `att/def ~ Normal(0, 0.35)` centrados a suma
cero con `np.random.default_rng(semilla fija)`, `mu = 0.1`, `gamma = 0.25`,
`rho = −0.1`), se construye la matriz conjunta de cada partido con `score_matrix` y se
muestrea el marcador de sus celdas (`rng.choice` sobre la matriz aplanada) para un
calendario round-robin ida/vuelta repetido (~1900+ partidos, fechas dentro de la
ventana). El ajuste usa `xi = 0` y `reg_lambda = 0` para aislar la MLE. Tolerancias
holgadas: `|Δmu| ≤ 0.05`, `|Δgamma| ≤ 0.05`, `|Δrho| ≤ 0.1`,
`max|Δatt| ≤ 0.15`, `max|Δdef| ≤ 0.15`.

## Persistencia — `data/gold/dixon_coles_params.json` (R11, R12)

`json.dump` con `sort_keys=True, indent=2` (bytes deterministas; round-trip de float64
exacto en el `json` de stdlib). Claves (contrato del Leader + refinamientos):

```json
{
  "as_of_date": "2026-06-01",
  "from_date": "2018-01-01",
  "xi": 0.65,
  "mu": 0.12,
  "home_advantage": 0.27,
  "rho": -0.08,
  "attack": {"ARG": 0.41, "MEX": 0.15},
  "defense": {"ARG": 0.33, "MEX": 0.05},
  "n_matches": 3120,
  "n_teams": 180,
  "min_matches": 5,
  "reg_lambda": 1.0,
  "low_data_teams": ["scotland"],
  "convergencia": {"success": true, "n_iter": 187, "message": "...", "neg_log_lik": 8123.45}
}
```

- `home_advantage` es `gamma`. `attack`/`defense`: dict código → float con TODOS los
  equipos del recorte (48 + slugs).
- **Carga sin reentrenar**: `load_params(path)` reconstruye el objeto de parámetros.
  SI el archivo no existe o falta alguna clave del contrato → `NotFittedError` con
  ruta y motivo (R12).

## Predicción (R13–R18)

### Matriz conjunta (R14, R15) — expuesta para la feature 4

`score_matrix(lambda_home, lambda_away, rho, max_goals=10) -> np.ndarray` (función
pura, reutilizable por `modelos_mercados`):

1. `px = poisson.pmf(0..max_goals, lambda_home)`, `py = poisson.pmf(0..max_goals,
   lambda_away)` (`scipy.stats`, vectorizado); `M = np.outer(px, py)` —
   `M[x, y] = P(X=x, Y=y)` independiente, forma `(max_goals+1, max_goals+1)`.
2. Corrección τ multiplicando SOLO las 4 celdas bajas (tabla de R5); valores
   negativos → recorte a 0 (solo posible con `rho` extremo).
3. **Renormalización**: `M /= M.sum()`. Justificación: el truncado a `max_goals = 10`
   pierde una masa diminuta (`P(X > 10) < 1e−3` con `lambda ≤ 4`) y τ solo preserva
   la suma sobre el soporte infinito; renormalizar garantiza `M.sum() == 1`
   (tolerancia 1e−9) y que los mercados derivados (1X2, over/under en feature 4)
   sean coherentes. `max_goals` configurable hacia arriba para tasas extremas.

### 1X2, lambdas y top-k (R16, R17)

- `prob_home = np.tril(M, −1).sum()` (x > y), `prob_draw = np.trace(M)`,
  `prob_away = np.triu(M, 1).sum()` (x < y) — suman 1 por la renormalización.

  Nota de orientación: `M[x, y]` tiene goles del local en filas, por lo que `x > y`
  es el triángulo **inferior** (`tril`).
- `lambda_home`, `lambda_away` del partido se exponen en la salida.
- Top-k (default `k = 5`): celdas ordenadas por probabilidad descendente con desempate
  `(home_goals, away_goals)` ascendente (orden total determinista); lista de
  `(home_goals, away_goals, prob)`.

### Localía y errores (R13, R18)

- `h = 1` si `is_host(home_code)` (import en lectura de `src/ingestion/teams.py`),
  `0` en cualquier otro caso. Sin parámetro de override en v1 (alcance: partidos del
  Mundial 2026; YAGNI).
- Código no presente en `attack`/`defense` → `UnknownTeamError` con el código (R18).

## Firmas orientativas (sin código de app)

- `@dataclass(frozen=True) DCConfig`: `xi=0.65, from_date="2018-01-01",
  min_matches=5, reg_lambda=1.0, max_iter=1000` (inyectable; `max_iter` permite
  forzar no-convergencia en tests).
- `fit_dixon_coles(as_of_date, silver_path="data/silver/matches.csv",
  config=DCConfig()) -> DixonColesParams` — R1–R10.
- `@dataclass DixonColesParams`: campos = claves del JSON.
- `save_params(params, path="data/gold/dixon_coles_params.json") -> Path` /
  `load_params(path) -> DixonColesParams` — R11, R12.
- `decay_weights(dates, as_of_date, xi) -> np.ndarray` — pura, testeable (R3).
- `match_rates(mu, gamma, att_home, def_home, att_away, def_away, h) ->
  tuple[float, float]` — pura; única fuente de la fórmula de R4, usada por ajuste y
  predicción.
- `tau_low_scores(x, y, lambda_h, lambda_a, rho)` — pura, vectorizable (R5).
- `score_matrix(lambda_home, lambda_away, rho, max_goals=10) -> np.ndarray` — R14, R15.
- `predict_match(params, home_code, away_code, max_goals=10, top_k=5) ->
  MatchPrediction` — dataclass con `lambda_home, lambda_away, matrix, prob_home,
  prob_draw, prob_away, top_scores` (R13–R18).
- CLI opcional: `python -m src.models.dixon_coles --as-of-date YYYY-MM-DD
  [--from-date ...] [--xi ...]` — entrena desde silver y escribe el JSON; sin red
  (no aplica la regla STOP de llamadas reales).

## Manejo de errores

| Situación                                         | Comportamiento                                       | Requisito |
|---------------------------------------------------|------------------------------------------------------|-----------|
| Silver inexistente o sin columnas requeridas      | `SilverNotFoundError` con ruta/columna; no escribe.  | R1        |
| `as_of_date`/`from_date` mal formadas             | `ValueError` con formato esperado.                   | R2        |
| 0 partidos tras el recorte                        | Error claro (ventana/fechas en el mensaje).          | R2        |
| Optimizador no converge                           | Warning + `convergencia.success = False`; no aborta. | R6        |
| `tau ≤ 0` durante la optimización                 | Clip a `1e−10` antes del log; no aborta.             | R6 (robustez) |
| Params inexistentes / JSON sin claves del contrato| `NotFittedError` con ruta y motivo.                  | R12       |
| Código de equipo desconocido en predicción        | `UnknownTeamError` con el código.                    | R18       |

## Configuración

Sin variables de entorno nuevas y **sin** `API_FOOTBALL_KEY` (offline; no se usa
`Settings`/`get_settings`, igual que features 2 y 7). Todos los parámetros son
argumentos con defaults de módulo: rutas (`silver_path`, `params_path`), `DCConfig`
(`xi`, `from_date`, `min_matches`, `reg_lambda`, `max_iter`) y los de predicción
(`max_goals`, `top_k`). Dependencias inyectables → tests deterministas con `tmp_path`.

## Decisiones y justificación

- **`xi = 0.65`/año** → anualización del óptimo empírico de Dixon & Coles 1997
  (`0.0065` por media semana × `365.25/3.5 ≈ 104.4` ≈ `0.68`); más conservador que
  `1.0` por el calendario de selecciones (~10 partidos/año). Configurable y revisable
  con la feature 5.
- **`from_date = 2018-01-01`** → con ese `xi`, lo anterior a 8 años pesa < 1 %: el
  decaimiento ya minimiza lo viejo y el recorte acota equipos y parámetros.
- **Reparametrización (no penalización) para suma cero** → restricción exacta, sin
  hiperparámetro de peso, menos dimensiones para L-BFGS-B.
- **Incluir equipos con pocos partidos + ridge `reg_lambda = 1.0`** → conserva la red
  completa de oponentes (coherente con el Elo global de la feature 2) y acota la
  varianza de sus coeficientes con sesgo < 5 % para equipos con ≥ 30 partidos
  efectivos; `low_data_teams` da transparencia.
- **`gamma` genérica en entrenamiento, `h` restringido a anfitrionas en predicción**
  → el histórico tiene localías reales (señal para estimar `gamma`); en el Mundial
  2026 solo MEX/USA/CAN juegan en casa (CHECKPOINTS § 3).
- **Objetivo vectorizado con fancy indexing y máscaras** → contrato del Leader;
  ajusta en milisegundos-segundos y evita el coste O(n) de Python por evaluación.
- **Constantes factoriales omitidas en la NLL** → no dependen de `theta`; mismo
  argmax, menos cómputo (documentado en `neg_log_lik`).
- **`rho` en caja `[−0.9, 0.9]` + clip de `tau`** → la región de validez exacta
  depende de las lambdas de cada partido; caja + clip es la salvaguarda práctica
  estándar y los valores ajustados reales son pequeños.
- **`maxfun = max_iter·(dim+1)` y gradiente numérico** → el gradiente analítico
  (`jac`) queda diferido como optimización futura (revisar con la feature 5).
- **Renormalizar la matriz truncada** → suma exactamente 1; coherencia de 1X2 y de
  los mercados de la feature 4.
- **Persistencia JSON (no pickle)** → legible, diffable, estable entre versiones de
  Python, round-trip exacto de float64; coherente con el stack mínimo (CSV/JSON).
- **`as_of_date` inyectada** → mismo principio que features 1, 2 y 7: nada de reloj
  interno; anti-leakage y reproducibilidad verificables en tests.

## Enmienda 2026-06-11: hiperparámetros

**Decisión:** los defaults de producción de `DCConfig` se actualizan de `xi=0.65, reg_lambda=1.0`
a `xi=0.35, reg_lambda=0.25`.

**Evidencia — grid walk-forward feature 5** (17 configs, 2 510 partidos, `from_date=2018-01-01`):

| xi   | reg_lambda | log-loss |
|------|------------|----------|
| 0.65 | 1.0        | 0.8943   |
| 0.50 | 0.5        | 0.8744   |
| 0.35 | 0.25       | 0.8641   |
| 0.20 | 0.1        | 0.8606   |

**Decisión del usuario:** se eligió `xi=0.35 / reg_lambda=0.25` (log-loss 0.8641) sobre la
esquina mínima `0.2/0.1` (log-loss 0.8606) por ser más robusta: la diferencia es de
0.0035 (< 0.4 %), mientras que con `xi=0.35` los datos de 2018 pesan ~6 %
(`exp(−0.35×8) ≈ 0.06`) aportando contexto histórico sin sobreponderar el pasado remoto.

`from_date=2018-01-01` se conserva (la evidencia del grid se midió con esa ventana).
El modelo necesita reentrenarse para que los parámetros en disco reflejen los nuevos defaults.
