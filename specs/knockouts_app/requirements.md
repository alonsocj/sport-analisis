# requirements.md — Feature 17: knockouts_app

Objetivo: añadir una pestaña **"Knockouts"** a la app Streamlit (Feature 9) que muestre
los cruces de eliminación del Mundial 2026 (R32 → Final) con su **predicción 1X2**, y un
control para activar el **factor de forma reciente** (Feature 16) de forma interactiva
(`slider` de peso γ). Permite VER en la app lo que ya producimos por CLI: el bracket con
predicción v1 y con forma, comparables en vivo.

Decisión de diseño clave (anti-rotura): las llaves se leen desde un **CSV de datos
propio** (`data/knockouts/r32_fixtures.csv`), NUNCA inyectando fixtures de knockout al
bronze. Inyectar al bronze rompería `simulate`/`load_wc2026_fixtures` (su `derive_groups`
exige 12 grupos de 4; aristas cruzadas de knockout lo invalidan). Esta feature deja
intactos bronze, silver, el CLI y la simulación.

Principio de no-regresión: con γ=0 la predicción de cada llave es IDÉNTICA a v1 (reusa el
fast-path de Feature 16). Las pestañas existentes (Calendario, Selecciones, Modelo) no se
modifican en su comportamiento.

Notación EARS. Cada `R<n>` mapea a ≥1 test en `tests/test_app_knockouts.py` (ver `tasks.md`).

---

**R1 — Carga de fixtures del bracket desde CSV de datos.**
El sistema DEBE leer las llaves desde `data/knockouts/r32_fixtures.csv` (columnas:
`draw_order, date, stage, home_code, away_code, source`), ordenadas por `date` y
`draw_order`. SI el archivo no existe o está vacío → la pestaña muestra un aviso
accionable y NO rompe la app (degradación elegante).

**R2 — Control de peso de forma (slider γ).**
El sistema DEBE exponer un control `slider` de peso de forma γ ∈ [0, 1] (paso 0.05,
default `0.0`). MIENTRAS γ=0, la predicción mostrada DEBE ser v1 exacta. CUANDO γ>0, el
sistema DEBE aplicar el factor de forma de Feature 16 (`make_form_factor_fn`) con `as_of`
= fecha de corte del modelo (anti-fuga).

**R3 — Predicción neutral por llave.**
El sistema DEBE calcular cada llave en **sede neutral**: promedio de las dos orientaciones
(`predict_match(A,B)` y `predict_match(B,A)`), renormalizado, devolviendo `P(A)`, `P(empate)`,
`P(B)` y `P(avanza)` (= `P(ganar) + ½·P(empate)`). El equipo favorito se marca por `P(avanza)`.

**R4 — Render por fecha/ronda + no-rotura de tabs existentes.**
El sistema DEBE renderizar las llaves agrupadas por fecha, mostrando equipos, 1X2 y pick.
La pestaña nueva DEBE integrarse en `src/app/main.py` SIN alterar el comportamiento de las
pestañas Calendario, Selecciones y Modelo (sus tests previos siguen verdes).

**R5 — Determinismo, sin red, sin tocar bronze/CLI/simulate.**
Tests 100% offline con fixtures CSV; sin red; `as_of` inyectado; la feature NO escribe en
bronze ni modifica `src/cli.py`, `src/simulation/*` ni los datos de grupos; sin dependencias
nuevas (Streamlit + stack actual).
