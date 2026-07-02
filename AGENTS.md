# AGENTS.md — Mapa para agentes (divulgación progresiva)

Lee SOLO lo necesario, en este orden. No saltes pasos.

## Orden de lectura

1. **`CLAUDE.md`** — tu rol (LEADER), flujo SDD, reglas duras y STOP.
2. **`AGENTS.md`** (este archivo) — cómo navegar el repo.
3. **`docs/specs.md`** — el flujo SDD detallado (EARS, plantillas, gate de aprobación).
4. **`feature_list.json`** — alcance. Trabaja SOLO la feature en `status: pending`.
5. **`specs/<feature activa>/`** — `requirements.md` → `design.md` → `tasks.md`.
6. **`progress/current.md`** — estado de la sesión activa y siguiente paso.
7. **`CHECKPOINTS.md`** — criterios de "estado final correcto" de la feature.

## Mapa del repo

```
src/ingestion/   Extracción cruda (capa bronze)         [feature 1]
src/features/    Limpieza + feature store (silver/gold)  [feature 2]
src/models/      Modelos estadísticos y de mercados      [features 3-4]
src/backtest/    Backtesting y métricas                  [feature 5]
src/cli.py       Punto de entrada (predecir un partido)  [feature 6]
data/            bronze/ silver/ gold/   (en .gitignore)
tests/           Tests reales por requisito
tests/fixtures/  Respuestas mock de la API (sin red real)
```

## Verificación

Ejecuta `bash init.sh`:
- Corre `pytest`.
- Valida que toda feature con `sdd: true` tenga sus 3 specs.

## Fuentes de datos

- **Primaria (ingesta)**: API-Football (api-sports.io / RapidAPI). Key en env `API_FOOTBALL_KEY`.
- **Complementaria / real-time**: https://www.worldsoccerdata.com/ (data pública del torneo en
  vivo) — uso para validación cruzada y backtesting, no es la fuente primaria de ingesta.
- **Histórica (backtest)**: CSV de football-data.co.uk (cuotas de cierre, over/under).
