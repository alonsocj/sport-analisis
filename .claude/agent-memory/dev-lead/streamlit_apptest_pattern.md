---
name: streamlit-apptest-import-pattern
description: AppTest.from_file ejecuta el script como standalone sin package context; imports relativos fallan. Usar sys.path guard + imports absolutos en main.py.
metadata:
  type: feedback
---

`streamlit.testing.v1.AppTest.from_file()` ejecuta el script con `exec` en un entorno sin `__package__`, por lo que los imports relativos (`from .data import ...`) fallan con "attempted relative import with no known parent package".

**Solución:** En `src/app/main.py`, agregar antes de los imports del paquete:

```python
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))
```

Luego usar imports absolutos (`from src.app.data import ...` en lugar de `from .data import ...`). Los módulos de tabs pueden seguir usando imports relativos porque son importados desde main.py, que ya registró el paquete.

**Why:** AppTest ejecuta el script de forma aislada para simular `streamlit run`. El sys.path en ese contexto no incluye la raíz del proyecto.

**How to apply:** Siempre en el script de entrada Streamlit (`main.py`) que se pasa a `AppTest.from_file`. Los módulos internos del paquete (tabs, data, figures) pueden seguir usando imports relativos normalmente.
