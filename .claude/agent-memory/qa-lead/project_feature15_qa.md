---
name: feature-15-qa-findings
description: QA findings for Feature 15 xg_proxy_wikipedia — APROBADO CON OBSERVACIONES; parser frágil silencioso; 406 passed
metadata:
  type: project
---

Feature 15 xg_proxy_wikipedia — APROBADO CON OBSERVACIONES (2026-06-17)

## Veredicto: APROBADO CON OBSERVACIONES

## Estado
- Suite: 406 passed, 0 failed, 0 warnings (incluso con -W error)
- Tests nuevos: 38 en {test_ingest_wiki.py, test_xg_proxy.py, test_cli_xg.py}
- Subcomandos CLI: 14 exactos (13 previos + ingest-wiki-stats)

## Criterios críticos superados

1. NO-REGRESIÓN: test_v0_equivale_v1 y test_v0_nll_identica_a_v1 son efectivos.
   Mutación confirmada: con v=0.5, td.x difiere → el test habría fallado.
   xg_target_map=None → x/y = goles exactos (tol 1e-9). OK.

2. ANTI-FUGA: el filtro `fecha < as_of_date` en load_training_data excluye partidos
   del día de corte aunque estén en xg_target_map. Test efectivo: verifica td.x.size
   y los valores concretos. La guardia está en load_training_data (correcto).

3. PARSER SEGURO: pd.read_html(flavor='lxml') — sin etree.fromstring sobre HTML crudo.
   UA identificable con email (requerido por política Wikipedia, aprobado security-lead).
   Rate-limit default=5s, inyectable (desactivado en tests). fetched_at siempre inyectado.

4. DEGRADACIÓN ELEGANTE: artículo sin stats → has_stats=False, no aborta, persiste JSON.
   xg_table sin directorio bronze → coverage_pct=0, sin cobertura. Correcto.

5. TRAZABILIDAD R1–R7: todos los requisitos tienen ≥1 test mapeado en tasks.md.

## Observaciones (no bloquean aprobación)

OBS-1 (Severidad MEDIA): Fallo silencioso del parser cuando Wikipedia cambia
estructura de tabla. Si columnas se renombran (p.ej. "Disparos" en lugar de "Shots"),
devuelve [] sin log ni warning. La cobertura baja a 0% sin aviso.
Deuda declarada en requirements.md y design.md. El riesgo es aceptado.
Recomendación: añadir log.debug cuando se encuentran tablas pero sin columnas reconocidas.

OBS-2 (Severidad BAJA): No hay test explícito de la degradación del CLI cuando
xg_weight>0 pero no existe el bronze de Wikipedia (líneas 291-308 de cli.py).
El path de degradación silenciosa (warning en stderr + xg_target_map=None) no está
cubierto. Patrón recurrente de degradación silenciosa sin cobertura de test.

## Patrones recurrentes confirmados
- Degradación silenciosa sin test de cobertura (feature 14, 15): patrón consistente.
- Parser de fuentes externas frágil (feature 14 elo, feature 15 wikipedia): ambos
  tienen deuda declarada de parseo silencioso al cambiar estructura.

**Why:** Feature 15 completa el bloque v3. 406 tests verdes, criterios críticos
no-regresión y anti-fuga superados con mutación verificada.

**How to apply:** En futuras revisiones vigilar el patrón "degradación silenciosa
sin test" — preguntar siempre si hay test del path de fallback cuando falta el
archivo o directorio externo.
