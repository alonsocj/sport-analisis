# tasks.md — Feature 30: app_r16_r8

Cada R<n> con ≥1 test (AppTest offline). Reusa render_knockouts. Sin libs nuevas.

## Implementación

- [x] T1. `knockouts.py`: `DEFAULT_KO_CSV`→r16, `+DEFAULT_R8_CSV`, `state_key` en
      `render_knockouts`/`_render_tarjeta_ko` (slider/btn/session namespaceados) — R1, R2, R3.
- [x] T2. `main.py`: `TAB_KNOCKOUTS`="Round of 16", `+TAB_ROUND8`="Round of 8", quinto tab — R1, R2.
- [ ] T3. Tests `tests/test_app_r16_r8.py` — ver tabla.

## Tests (mapeo R<n> → test)

| Req | Test |
|-----|------|
| R1  | `test_app_r16_r8.py::test_tab_round16_presente_y_octavos` |
| R2  | `test_app_r16_r8.py::test_tab_round8_presente` |
| R3  | `test_app_r16_r8.py::test_dos_tabs_ko_sin_colision` (AppTest no lanza; sliders con key distinta) |
| R4  | `test_app_r16_r8.py::test_tabs_previos_intactos` + suite existente de knockouts |

## Cierre

- [ ] QA R1–R4 trazables, AppTest verde, no-regresión de tabs existentes.
- [ ] Registrar feature 30 done → v3-octavos COMPLETO (30/30).
