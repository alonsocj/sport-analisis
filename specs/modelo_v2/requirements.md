# requirements.md — Feature 12: modelo_v2

Objetivo: mejorar la precisión del modelo Dixon-Coles incorporando **peso por
importancia de partido** (los oficiales valen más que los amistosos, hoy solo se
pondera por tiempo), **refit intra-torneo** (incorporar las jornadas ya jugadas
para predecir las siguientes) y un **re-grid de hiperparámetros** (ξ, reg_lambda,
escala de importancia) con datos del torneo. La mejora se mide contra v1 con el
harness de la feature 10. DONDE exista el factor jugadores (feature 11), su
multiplicador de ataque por roster puede alimentar la λ.

Principio de no-regresión: TODO añadido DEBE tener un default que reproduzca v1
exactamente, para que los tests y la calibración previos sigan válidos.

Notación EARS. Cada `R<n>` mapea a ≥1 test en `tests/test_modelo_v2.py`,
`tests/test_dixon_coles_importance.py` o `tests/test_cli_train_v2.py` (ver `tasks.md`).

---

**R1 — Peso por importancia de partido.**
El sistema DEBE ponderar cada partido de entrenamiento por un factor de importancia
según su `tournament`, combinado multiplicativamente con el decaimiento temporal:
`w = decay × importance(tournament)`. El mapa de importancia DEBE ser inyectable.
El DEFAULT DEBE ser identidad (todas las importancias = 1.0) → ajuste y
predicciones IDÉNTICAS a v1 (test de equivalencia con tolerancia 1e-9).

**R2 — Niveles de importancia documentados.**
El sistema DEBE clasificar cada `tournament` del dataset en un tier de importancia
(p.ej. amistoso < clasificatorios/Nations League < finales continentales <
Copa Mundial) con valores v2 propuestos y justificados en el design, y un fallback
determinista para torneos no mapeados.

**R3 — Anti-fuga preservada.**
El refit con importancia DEBE mantener el filtro `fecha < as_of_date` de la
feature 3. Un test DEBE verificar que la ponderación por importancia NO rompe la
propiedad anti-fuga (mutar partidos posteriores no cambia el ajuste).

**R4 — Re-grid walk-forward con datos del torneo.**
El sistema DEBE permitir una búsqueda walk-forward (reusa `src/backtest/`) sobre
(ξ, reg_lambda, escala de importancia) incluyendo los partidos del torneo, y
reportar la mejor configuración v2 frente a v1 (log-loss, Brier, exactitud) de
forma reproducible.

**R5 — Refit intra-torneo (rolling, out-of-sample).**
El sistema DEBE producir predicciones por jornada entrenando con
`fecha < inicio_de_jornada` (incorporando las jornadas previas, incluidos los
resultados del torneo), consumibles por el log de la feature 10 con
`model_version = "dc-v2"`. Anti-fuga estricta por jornada.

**R6 — Persistencia v2 diferenciada.**
Los parámetros v2 DEBEN persistirse identificando la versión (`model_version =
"dc-v2"`) SIN pisar los de v1. El CLI DEBE permitir entrenar y seleccionar la
versión/config de importancia.

**R7 — Comparación v1 vs v2 reproducible.**
El sistema DEBE producir una comparación v1 vs v2 sobre el slate del torneo usando
el harness de la feature 10 (mismas métricas), determinista y documentada.

**R8 — Determinismo, sin red, sin librería nueva.**
Sin fechas del reloj; tests offline con fixtures; sin dependencias nuevas.
