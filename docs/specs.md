# docs/specs.md — Flujo Spec-Driven Development (SDD)

Este documento impone CÓMO se especifica e implementa cada feature.
El orden es estricto: **requirements → design → tasks → implementación → review**.

## 1. requirements.md (notación EARS)

Cada requisito se numera `R1`, `R2`, … y usa una plantilla **EARS**:

- **Ubicua**: "El sistema DEBE <capacidad>."
- **Event-driven**: "CUANDO <evento>, el sistema DEBE <respuesta>."
- **State-driven**: "MIENTRAS <estado>, el sistema DEBE <respuesta>."
- **Unwanted**: "SI <condición indeseada>, ENTONCES el sistema DEBE <mitigación>."
- **Opcional**: "DONDE <característica presente>, el sistema DEBE <respuesta>."

Reglas:
- Un requisito = una capacidad verificable. Nada ambiguo.
- Cada `R<n>` debe ser testeable (mapeará a ≥1 test en `tasks.md`).

## 2. design.md (decisiones técnicas)

Contiene: arquitectura de la feature, contratos/esquemas de datos, endpoints
externos y parámetros, estrategia de errores/caché/rate-limit, configuración
(variables de entorno), y decisiones con su justificación. No incluye código de app.

## 3. tasks.md (checklist + trazabilidad)

- Checklist de implementación (casillas `[ ]`).
- **Tabla de trazabilidad obligatoria**: `R<n>` → archivo de test concreto.
- Si un `R<n>` no tiene test asociado, el **reviewer rechaza**.

## 4. Implementación

- Solo tras specs completas. Implementer escribe código de app **y** sus tests.
- Tests usan **fixtures/mocks**; NUNCA red real sin aprobación (rate limits / coste).
- Sin red real = los tests corren offline y son deterministas.

## 5. Review (gate de aprobación)

El reviewer valida y aprueba/rechaza:
- [ ] Todos los `R<n>` tienen test mapeado en `tasks.md`.
- [ ] Tests verdes (`bash init.sh`).
- [ ] Diseño respetado; sin features/refactors fuera de alcance.
- [ ] Reglas duras de `CLAUDE.md` (API key por env, STOP, etc.).
- [ ] Criterios de `CHECKPOINTS.md` para la feature satisfechos.

El reviewer **no edita** código de aplicación; solo aprueba o devuelve con motivos.

## Una feature a la vez

Solo se trabaja la feature en `status: pending` de `feature_list.json`.
Al terminar y aprobar: `pending → done` y se promueve la siguiente (`backlog → pending`).
