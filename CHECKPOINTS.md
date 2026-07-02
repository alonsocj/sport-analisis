# CHECKPOINTS.md — Criterios de "estado final correcto" por feature

Una feature solo pasa a `done` cuando cumple TODOS sus criterios y `bash init.sh` está verde.

## 1. ingesta_datos  (capa bronze)

- [ ] Specs completas: `specs/ingesta_datos/{requirements,design,tasks}.md`.
- [ ] Cada `R<n>` de requirements.md tiene ≥1 test en `tests/` (ver tabla en tasks.md).
- [ ] API key leída SOLO desde env `API_FOOTBALL_KEY`; ninguna key literal en el repo.
- [ ] Recupera, por selección, los últimos 15 partidos finalizados.
- [ ] Recupera estadísticas por partido: goles, córners, tarjetas, tiros, tiros a puerta, posesión.
- [ ] Recupera cuotas (odds) cuando existen.
- [ ] Persiste crudo en capa bronze con esquema/partición definido.
- [ ] Caché local: una respuesta cacheada NO repite llamada.
- [ ] Rate limit: ante 429 aplica backoff/throttle configurable.
- [ ] Cubre las 48 selecciones del Mundial 2026 (lista parametrizada; anfitrionas marcadas).
- [ ] Errores HTTP / payload inválido se manejan sin abortar el lote.
- [ ] Todos los tests corren offline (mocks/fixtures); cero red real.

## 2. feature_store  (silver/gold)   — backlog

- [ ] Normalización de la capa bronze a silver.
- [ ] Medias móviles de últimos 15 partidos por equipo y métrica.
- [ ] Ratings Elo por selección como feature (gold).

## 3. modelo_resultado  (1X2 + marcador)   — backlog

- [ ] Poisson bivariado con ajuste Dixon-Coles y decaimiento temporal.
- [ ] Fuerzas ofensiva/defensiva por selección.
- [ ] Localía parametrizada (ventaja solo para anfitrionas MEX/USA/CAN).
- [ ] Salidas: prob. 1X2 y distribución de marcadores.

## 4. modelos_mercados  (over/under, córners, tarjetas)   — backlog

- [ ] Over/Under de goles derivado de la Poisson conjunta.
- [ ] Córners y tarjetas: Poisson / Binomial Negativo sobre tasas (medias móviles 15).
- [ ] Clasificación de umbrales (p. ej. +9.5 córners) con prob. de superar la línea.
- [ ] Detección de valor: prob. estimada vs cuota.

## 5. backtesting  (métricas + ROI)   — backlog

- [ ] log-loss, Brier score, curva de calibración.
- [ ] ROI simulado contra cuotas de cierre (football-data.co.uk).

## 6. cli_prediccion  (CLI)   — backlog

- [ ] `src/cli.py` predice un partido del Mundial 2026 y sus mercados.

## 8. dashboard_visual  (HTML interactivo)   — pending (solicitado por el usuario 2026-06-09)

- [ ] Comando explícito genera un HTML autocontenido (abrible en navegador, sin servidor ni red).
- [ ] Ranking Elo de las 48 selecciones (barras) + evolución temporal Elo (líneas, selección de equipos).
- [ ] Dispersión fuerzas ataque vs defensa de las 48 (desde dixon_coles_params.json).
- [ ] Forma reciente (gf_ma15 / ga_ma15) desde team_features.csv.
- [ ] Por cada próximo partido WC2026 (bronze público, scores no jugados): heatmap de la matriz
      de marcadores y barras 1X2 del modelo Dixon-Coles.
- [ ] Cero red en generación y tests (plotly.js embebido); insumos parametrizables; tests offline
      con datos sintéticos en tmp_path.
- [ ] No modifica módulos de otras features (src/cli.py intacto; integración como subcomando queda
      como extensión futura tras cerrar feature 6).

## 7. ingesta_publica  (scraper fuente pública)   — pending (paralelo a feature 2, autorizado)

- [ ] Descarga resultados internacionales desde fuente pública fiable y versionada
      (martj42/international_results, CC0; URL/columnas verificadas 2026-06-09).
- [ ] Persiste crudo en bronze siguiendo el patrón existente (ruta determinista + metadatos
      `fetched_at`, URL, hash de contenido).
- [ ] Valida esquema de columnas y tipos; SI el esquema cambia, falla con error claro.
- [ ] Filtra/expone partidos de las 48 selecciones del Mundial 2026 (mapa de alias de
      nombres → códigos FIFA de `teams.py`).
- [ ] Cero red real en tests (fixtures con muestra del CSV).
- [ ] Descarga real ejecutable por comando explícito (transport inyectable).
