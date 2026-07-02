# requirements.md — Feature 1: ingesta_datos

Objetivo: recuperar, para cada una de las 48 selecciones del Mundial 2026, sus **últimos 15
partidos** (eliminatorias + amistosos + competitivos recientes), con estadísticas por partido
y cuotas, y persistirlos crudos en la **capa bronze**. Fuente primaria: **API-Football**.

Notación EARS. Cada `R<n>` es verificable y mapea a ≥1 test (ver `tasks.md`).

---

**R1 — API key por entorno.**
El sistema DEBE leer la API key desde la variable de entorno `API_FOOTBALL_KEY`.
SI la variable no está definida o está vacía, ENTONCES el sistema DEBE fallar con un error
claro y NO realizar ninguna llamada.

**R2 — Últimos 15 partidos.**
Dado el identificador de una selección, el sistema DEBE recuperar sus últimos 15 partidos
**finalizados** (más recientes primero).

**R3 — Estadísticas por partido.**
Para cada partido recuperado, el sistema DEBE obtener las estadísticas: goles, córners,
tarjetas, tiros, tiros a puerta y posesión, normalizadas a un esquema por equipo (local/visitante).

**R4 — Cuotas.**
DONDE existan cuotas (odds) para un partido, el sistema DEBE recuperarlas y asociarlas al partido.
SI no hay cuotas, ENTONCES el sistema DEBE continuar sin fallar (campo vacío/None).

**R5 — Persistencia en capa bronze.**
El sistema DEBE persistir las respuestas crudas en la capa bronze (`data/bronze/`) siguiendo un
esquema de particionado determinista por endpoint y parámetros (un archivo JSON por respuesta).

**R6 — Caché local.**
CUANDO se solicite un recurso ya presente en caché local, el sistema DEBE servirlo desde caché
y NO realizar la llamada HTTP (para no consumir la cuota).

**R7 — Rate limiting.**
SI la API responde 429 (rate limit), ENTONCES el sistema DEBE reintentar con backoff
configurable (nº de reintentos y espera), y abortar el recurso tras agotar los reintentos.

**R8 — Cobertura de 48 selecciones.**
El sistema DEBE exponer una lista parametrizada de las 48 selecciones del Mundial 2026, con las
anfitrionas (México, USA, Canadá) marcadas como `home` para la localía parametrizada y el resto
como sede neutral.

**R9 — Robustez ante errores.**
SI una respuesta es un error HTTP (≠ 429, ≠ 2xx) o tiene payload inválido para un partido/selección,
ENTONCES el sistema DEBE registrar el error y continuar con el resto del lote sin abortar todo el proceso.
