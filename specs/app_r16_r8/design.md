# design.md — Feature 30: app_r16_r8

## Decisiones

1. **Reusar `render_knockouts`, no duplicar.** Ya está parametrizado por `fixtures_csv`. Se
   añade `state_key` para namespacear el slider (`key=f"gamma_{state_key}"`) y el
   session_state de detalle (`selected_ko_{state_key}`) → dos tabs KO sin colisión.
2. **`DEFAULT_KO_CSV` pasa a `r16_fixtures.csv`** (el tab principal ahora es octavos;
   monkeypatcheable en AppTest como antes). Nuevo `DEFAULT_R8_CSV = r8_fixtures.csv`.
3. **R32 sale de la UI** (queda como training data F27). Sin migración de datos.

## Cambios

- `src/app/tabs/knockouts.py`: `DEFAULT_KO_CSV`→r16, `+DEFAULT_R8_CSV`; `render_knockouts` y
  `_render_tarjeta_ko` reciben `state_key` (slider key, btn key, session key namespaceados).
- `src/app/main.py`: `TAB_KNOCKOUTS`="🏟️ Round of 16", `+TAB_ROUND8`="🥊 Round of 8"; quinto
  tab con `render_knockouts(fixtures_csv=DEFAULT_R8_CSV, state_key="r8")`.

## Riesgos

- Colisión de widgets entre tabs → resuelto con state_key.
- TBD en cuartos (equipos sin definir) → F27 no los escribe; el tab R8 muestra sólo cruces
  resueltos (hoy FRA-MAR).
