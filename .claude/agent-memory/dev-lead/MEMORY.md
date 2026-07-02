# MEMORY.md

- [Streamlit AppTest import pattern](streamlit_apptest_pattern.md) — AppTest ejecuta scripts como standalone; usar imports absolutos con guarda sys.path en main.py.
- [Feature 9 app_streamlit completada](feature9_completada.md) — T4-T7 implementadas, 10 tests UI, 171 total, smoke OK.
- [Feature 5 backtesting completada](feature5_backtest_completada.md) — T2-T6, 20 tests nuevos, 211 total, backtest real 7.5s, modelo bate baselines.
- [Enmienda hiperparámetros 2026-06-11](enmienda_hiperparametros_20260611.md) — xi 0.65→0.35, reg_lambda 1.0→0.25; modelo requiere reentrenamiento.
- [Feature 10 registro_y_evaluacion completada](feature10_completada.md) — predict-log+evaluate, 34 tests nuevos, 227 total, 9 subcomandos CLI.
- [Feature 11 players completada](feature11_completada.md) — ingest-goalscorers+scorers, 46 tests nuevos, 273 total, 11 subcomandos CLI.
- [Feature 12 modelo_v2 completada](feature12_completada.md) — importance weighting, 23 tests nuevos, 296 total, equivalencia v1 verificada tol 1e-9.
- [Feature 13 simulacion_montecarlo completada](feature13_completada.md) — Monte Carlo WC2026, 41 tests nuevos, 337 total, 12 subcomandos CLI. Roadmap v2 cerrado.
- [Feature 14 elo_externo_ensemble completada](feature14_completada.md) — ensemble DC+Elo, 27 tests nuevos, 364 total, 13 subcomandos CLI (ingest-elo).
- [Feature 15 xg_proxy_wikipedia completada](feature15_completada.md) — proxy xG Wikipedia, 38 tests nuevos, 406 total, 14 subcomandos CLI (ingest-wiki-stats). Bloque v3 cerrado.
- [Feature 16 forma_reciente completada](feature16_completada.md) — exp(γ·z) multiplicador λ DC, 45 tests nuevos, 458 total, 14 subcomandos intactos (--form-weight en predict/backtest/simulate).
- [Feature 21 roster_fotmob completada](feature21_completada.md) — scraper fotmob R32, ingest-roster, filtro bajas en knockouts, 25 tests nuevos, 519 total, 15 subcomandos CLI.
- [Feature 23 fotmob_stats completada](feature23_fotmob_stats_completada.md) — ingesta stats fotmob + silver merge xG/corners/cards/shots, 24 tests nuevos, 556 total, 16 subcomandos CLI (ingest-fotmob-stats).
- [Feature 26 forma_xg completada](feature26_completada.md) — xG-diff en ventana forma + use_xg + --form-xg CLI, 18 tests nuevos, 622 total, 18 subcomandos intactos. Pendiente: veredicto LEADER (backtest).
