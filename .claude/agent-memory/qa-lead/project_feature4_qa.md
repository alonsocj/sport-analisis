---
name: project-feature4-qa
description: QA findings for Feature 4 modelos_mercados — patterns and decisions to carry forward
metadata:
  type: project
---

Feature 4 (modelos_mercados, goles only) reviewed 2026-06-09. 191 tests, init.sh green.

Key findings:

1. **test_cinco_subcomandos modification pattern**: Implementer changed `==` to `<=` in test_cli.py when adding a 6th subcommand. The preferred alternative is to update the exact expected set to include the new subcommand. The `<=` approach weakens structural upper-bound protection. Future features should update to exact set equality.

2. **R2 oracle dependency**: test_over_under_lineas_default_y_suma_1 is structurally weak in isolation (passes with constant 0.5 output). The design intentionally relies on R6 (test_oraculo_matriz_3x3_a_mano) for closed-form oracle protection. This pairing is by spec design.

3. **Lazy imports in calendar.py**: src.markets.goals is imported inside the cached function `_cached_market_summary`, not at module level. This is correct and intentional to avoid circular imports.

**Why:** Feature adds 6th CLI subcommand and 4th app sub-tab. The `<=` issue is a minor ongoing debt.
**How to apply:** In future CLI extension features, require the exact set assertion to be updated, not liberalized to subset.
