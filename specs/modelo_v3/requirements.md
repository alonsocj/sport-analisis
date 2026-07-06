# requirements.md — Feature 29: modelo_v3 (re-fit + medición, sin jugadores)

Objetivo: aprovechar el refresh de datos de F27 (R32/R16 con xG real) para mejorar la
precisión en octavos, **midiendo honestamente** contra el baseline forma-xG/v1, y emitir
predicciones actualizadas de los octavos por jugar. Decisión del usuario (2026-07-04, tras el
hallazgo de F28): **NO integrar jugadores** (seasonRating esparso); la ganancia viene del dato.

Notación EARS. Trazabilidad a comandos/artefactos reproducibles (no nuevo módulo; usa
`train`, `backtest`, `predict` existentes).

---

**R1 — Re-fit sobre el silver actualizado.**
`train --as-of-date 2026-07-05` DEBE reajustar `gold/dixon_coles_params.json` incluyendo las
18 filas KO (as_of pasa de 2026-06-28 a 2026-07-05). Verificable: `load_params().as_of_date`.

**R2 — Medición out-of-sample vs baseline.**
`backtest` walk-forward (refit semanal) sobre la ventana fresca (2026-06-28→07-05, incluye los
18 KO) DEBE comparar v1 vs forma-xG (γ, --form-xg). Resultado DEBE registrarse. **MEDIDO:**
v1 log-loss 0.7457 / Brier 0.4219 / 72% → forma-xG γ=0.2 **0.6996 / 0.3934 / 76%** (−6.2% /
−6.8% / +4pp). forma-xG BATE a v1 en datos frescos.

**R3 — Elegir config sin overfit.**
El grid de γ DEBE evitar sobreajuste al tamaño de muestra. **MEDIDO:** γ=0.3→0.687, γ=0.4→0.680
mejoran monótonamente = señal de overfit (ventana donde ganaron favoritos; γ alto sobreconfía,
ya documentado FRA 98% con γ=0.5). **DECISIÓN: producción γ=0.2–0.3 (medido-seguro), NO 0.4+.**

**R4 — Predicciones de octavos por jugar.**
El sistema DEBE emitir, en sede neutral, las probabilidades 1X2 + P(avanza) de los 6 octavos
por jugar con forma-xG γ=0.2 sobre los params re-fit. **EMITIDO:** ESP 64%, BEL 74%, BRA 78%,
ENG 66%, ARG 87%, COL 61% (avanza). CAVEAT operativo (calibración R32 medida): forma-xG
sobrevalora al favorito y subestima underdogs → templar favoritos extremos vs mercado.

**R5 — Sin regresión, sin mecanismo nuevo adoptado.**
No se introduce mecanismo nuevo al modelo (consistente con F12/F14/F15: importancia/elo/xg-proxy
NO batieron). La mejora = dato fresco + forma-xG (ya el mejor modelo). Suite verde.
