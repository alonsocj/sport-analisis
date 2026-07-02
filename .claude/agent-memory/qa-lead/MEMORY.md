# MEMORY.md

- [Feature 4 QA findings](project_feature4_qa.md) — test_cli.py subset weakening pattern; R2 oracle dependency on R6; lazy import pattern in calendario.py
- [Feature 5 QA findings](project_feature5_qa.md) — R10 test sin assertions (patrón recurrente CLI sin --silver); R2 gap boundary < vs <=; R12 enmienda OK; 211 passed
- [Feature 10 QA findings](project_feature10_qa.md) — 3 desviaciones: guarda R11 solo en evaluate, grep R2 frágil, marginal 1/3 inocua para calibración; imports no usados en test; 227 passed
- [Feature 13 QA findings](project_feature13_qa.md) — APROBADO CON OBSERVACIONES; test_roster_sim vacuo (22 SEs tolerancia); suite 50s por 12 calls a 1000 sims; bracket simplificado documentado; 337 passed
- [Feature 14 QA findings](project_feature14_qa.md) — APROBADO CON OBSERVACIONES; degradación silenciosa sin warn en prediction_log cuando falta elo_history (patrón recurrente); todos los criterios críticos superados; 367 passed
- [Feature 15 QA findings](project_feature15_qa.md) — APROBADO CON OBSERVACIONES; parser Wikipedia frágil silencioso (deuda declarada); test CLI sin cobertura de degradación xg_weight>0 sin bronze; criterios críticos no-regresión y anti-fuga superados con mutación; 406 passed
