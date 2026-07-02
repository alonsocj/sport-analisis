# requirements.md — Feature 7: ingesta_publica

Objetivo: descargar resultados de partidos internacionales desde una **fuente pública fiable
y versionada** (dataset `martj42/international_results`, licencia CC0) y persistirlos crudos
en la **capa bronze**, complementando API-Football **sin consumir su cuota**. Esta feature
también expone el parseo tolerante del CSV, el mapa de alias nombre-dataset → código FIFA y
el filtro por las 48 selecciones del Mundial 2026, que la feature `feature_store` consumirá.

Fuente verificada por el Leader (2026-06-09, HTTP 200):
`https://raw.githubusercontent.com/martj42/international_results/master/results.csv`
Encabezado verificado: `date,home_team,away_team,home_score,away_score,tournament,city,country,neutral`.

Notación EARS. Cada `R<n>` es verificable y mapea a ≥1 test (ver `tasks.md`).

---

**R1 — Fuente pública sin credenciales.**
El sistema DEBE descargar el dataset desde la URL pública verificada (parametrizable, con la
URL anterior como default) **sin emplear credencial alguna**: esta fuente NO usa
`API_FOOTBALL_KEY` y el flujo completo de ingesta pública DEBE funcionar aunque esa variable
de entorno no esté definida. El sistema NO DEBE escribir ningún secreto en archivos del repo
(la regla de no-secretos de `CLAUDE.md` sigue aplicando).

**R2 — Transporte inyectable y descarga real solo explícita.**
El sistema DEBE realizar la descarga a través de un **transporte inyectable**
(callable `url → texto CSV`). MIENTRAS se usa un transporte inyectado (caso de los tests),
el sistema NO DEBE realizar ninguna conexión de red real. La descarga real (transporte por
defecto con `requests`) DEBE ejecutarse únicamente mediante una invocación explícita
(función/CLI dedicada), nunca como efecto colateral de importar el módulo.

**R3 — Validación de esquema (encabezado).**
SI el encabezado del CSV descargado difiere del esperado
`date,home_team,away_team,home_score,away_score,tournament,city,country,neutral`
(nombres y orden exactos), ENTONCES el sistema DEBE fallar con un error claro que incluya el
encabezado esperado y el recibido, y NO DEBE persistir nada en la capa bronze.

**R4 — Persistencia en capa bronze (crudo + metadatos).**
CUANDO el encabezado es válido, el sistema DEBE persistir el CSV crudo **tal cual** (byte a
byte) en `data/bronze/public_results/results.csv` y un sidecar de metadatos
`data/bronze/public_results/results.meta.json` con `url`, `fetched_at` (timestamp **inyectado**
como argumento, no reloj interno), `sha256` del contenido, `n_rows` (filas de datos, sin
encabezado) y `header`.

**R5 — Validación de filas tolerante (con reporte).**
SI una fila de datos contiene goles no numéricos o una fecha inválida (no parseable como
`YYYY-MM-DD`), ENTONCES el sistema DEBE descartar esa fila, contarla en un reporte de
descartes (totales y por motivo) y continuar con el resto del lote sin abortar.

**R6 — Normalización de tipos por fila válida.**
CUANDO una fila supera la validación, el sistema DEBE normalizarla a un registro tipado:
`date` como `YYYY-MM-DD` (str ISO), `home_score`/`away_score` como `int`, `neutral` como
booleano (`TRUE` → `True`, `FALSE` → `False`) y el resto de campos (`home_team`, `away_team`,
`tournament`, `city`, `country`) como `str`.

**R7 — Mapa de alias nombre-dataset → código FIFA (48 selecciones).**
El sistema DEBE exponer un mapa de alias que traduzca los nombres usados por el dataset a los
códigos FIFA de 3 letras de las **48 selecciones** de `src/ingestion/teams.py`
(ejemplos: `'South Korea'` → `KOR`, `'United States'` → `USA`, `'Ivory Coast'` → `CIV`).
El mapa DEBE cubrir los 48 códigos (ninguna selección sin alias) y DEBE ser importable por
features posteriores (`feature_store`).

**R8 — Filtro por las 48 selecciones.**
El sistema DEBE proveer una función que, dada la colección de registros parseados, devuelva
solo los partidos donde **al menos una** de las dos selecciones pertenezca a las 48 del
Mundial 2026 (resolución de nombres vía el mapa de alias de R7), descartando el resto.

**R9 — Recorte temporal opcional (`from_date`).**
DONDE se proporcione el parámetro opcional `from_date` (`YYYY-MM-DD`), el sistema DEBE excluir
de la vista consumida los partidos con fecha **estrictamente anterior** a `from_date`.
SI no se proporciona, ENTONCES el sistema DEBE conservar la historia completa (default; el
decaimiento temporal lo aplicará el modelo, feature 3). El recorte NO DEBE alterar el CSV
crudo persistido en bronze.
