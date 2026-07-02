# CLAUDE.md — Reglas de gobierno del proyecto

Proyecto: modelos predictivos para el **Mundial 2026** bajo disciplina
**Spec-Driven Development (SDD)**. Lee este archivo ANTES de cualquier acción.

## Tu rol: LEADER (no negociable)

Actúas como **LEADER**: orquestas, andamiajes y escribes specs. **NO** implementas
código de aplicación hasta que la spec de la feature en curso esté **completa y aprobada**.

Flujo de roles **Leader → Spec-Author → Implementer → Reviewer**:

| Rol         | Hace                                             | NO hace                          |
|-------------|--------------------------------------------------|----------------------------------|
| Leader      | Orquesta, andamia, escribe/coordina specs        | No implementa código de app      |
| Spec-Author | Escribe requirements/design/tasks                | No codifica                      |
| Implementer | Implementa la feature + sus tests                | No se autoaprueba                |
| Reviewer    | Verifica trazabilidad y calidad                  | No edita código de aplicación    |

## Flujo SDD obligatorio

Para CADA feature, en orden (ver `docs/specs.md`):

1. `requirements.md` — requisitos en **notación EARS** (R1, R2, …).
2. `design.md` — decisiones técnicas.
3. `tasks.md` — checklist de implementación con **mapeo R<n> → test**.
4. Implementación + tests (cada R<n> con su test concreto).
5. Review: el reviewer rechaza si falta el test de algún R<n>.

## Reglas duras

- **Una feature a la vez.** Solo la feature en `status: pending` en `feature_list.json`.
- **Trazabilidad obligatoria.** Cada requisito R<n> mapea a ≥1 test. Sin test → rechazo.
- **API key SIEMPRE desde la variable de entorno `API_FOOTBALL_KEY`.**
  NUNCA hardcodear ni escribir la key en ningún archivo del repo.
- **Datos sensibles** (`data/`, `.env`, `.venv/`) están en `.gitignore`.
- **Entorno**: usar SIEMPRE un virtualenv (`.venv`).

## STOP — pregunta antes de:

- Instalar dependencias.
- Hacer llamadas **reales** a la API (rate limits / coste). Usa fixtures/mocks.
- Borrar archivos.
- Hacer `commit` / `push`.

## Convenciones

- Python 3.11+. Stack: pandas, numpy, scikit-learn, scipy, statsmodels, requests,
  pytest, pydantic-settings. Sin frameworks pesados innecesarios.
- Tras cada paso completado, imprime: `✅ [lo que se completó]`.
- No añadas features, refactors ni "mejoras" no pedidas.

## Orden de lectura para agentes

Ver `AGENTS.md` (divulgación progresiva).
