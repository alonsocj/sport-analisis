# tasks.md — Feature 29: modelo_v3 (re-fit + medición)

Feature de MEDICIÓN: sin módulo nuevo. Reusa `train`/`backtest`/`predict`/`neutral_prediction`.
Cada R<n> mapea a un comando reproducible y/o test existente.

## Ejecución (reproducible)

- [x] T1. `train --as-of-date 2026-07-05` → re-fit (R1). Verificado: params.as_of_date=2026-07-05.
- [x] T2. `backtest --from-date 2026-06-28 --to-date 2026-07-05 --refit-every week` (v1) y con
      `--form-weight 0.2 --form-xg` (forma-xG) (R2). Medido: 0.7457→0.6996 log-loss.
- [x] T3. Grid γ∈{0.2,0.3,0.4} en la ventana → decisión γ=0.2–0.3 (R3, overfit ≥0.4).
- [x] T4. `neutral_prediction` de los 6 octavos por jugar, forma-xG γ=0.2 (R4). Emitido.

## Tests (mapeo R<n> → test)

| Req | Cobertura |
|-----|-----------|
| R1  | `train` real (params.as_of_date verificado) + `tests/test_cli.py` (train despacha) |
| R2/R3 | comandos `backtest` reproducibles; `tests/test_backtest*.py` (anti-fuga walk-forward) |
| R4  | `tests/test_app_knockouts.py` (neutral_prediction: promedia orientaciones, P(adv)=p_win+½·p_draw, normaliza) |
| R5  | suite completa verde (sin regresión; sin mecanismo nuevo) |

## Cierre

- [ ] Regenerar/registrar el resultado medido en la nota de feature_list y memoria.
- [ ] F30 mostrará las predicciones en vivo (mismo motor + r16/r8_fixtures.csv).
