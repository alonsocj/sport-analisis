# requirements.md — Feature 30: app_r16_r8 (tabs Round of 16 / Round of 8)

Objetivo: renombrar el tab "Knockouts" (que mostraba R32) a **"Round of 16"** (octavos) y
añadir un tab **"Round of 8"** (cuartos), leyendo los CSV generados en F27
(`r16_fixtures.csv`, `r8_fixtures.csv`). Reusa el motor de predicción neutral existente
(forma-xG γ=0.2, re-fit F29). R32 pasa a ser sólo dato histórico de training.

Notación EARS. Tests en `tests/test_app_r16_r8.py` (AppTest offline) + no-regresión de los tabs
existentes.

---

**R1 — Tab "Round of 16".** La app DEBE mostrar un tab "Round of 16" que renderice los 8
partidos de octavos desde `r16_fixtures.csv` (2 jugados + 6 por jugar) con 1X2/P(avanza)
neutral y el slider γ (default 0.2). Reemplaza al antiguo "Knockouts".

**R2 — Tab "Round of 8".** La app DEBE añadir un tab "Round of 8" que renderice los cuartos
desde `r8_fixtures.csv` (FRA-MAR + los que se resuelvan). Si un cruce aún no tiene equipos
(TBD) no aparece (F27 no lo escribe).

**R3 — Aislamiento entre tabs.** Los dos tabs de KO NO DEBEN colisionar en widgets ni estado:
slider y session_state de detalle namespaceados por `state_key` ("r16"/"r8"). Sin
`DuplicateWidgetID`.

**R4 — No-regresión.** Calendario/Selecciones/Modelo intactos; la app no lanza excepción; el
motor de predicción y los sub-paneles (Mercados/Goleadores/Equipos/Elo) siguen funcionando.
