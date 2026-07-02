#!/usr/bin/env bash
# init.sh — Verificacion ejecutable del proyecto (SDD harness).
#  1) Valida que toda feature con sdd:true tenga sus 3 specs.
#  2) Corre la suite de tests (pytest).
# Sale != 0 si algo falla. Usa el venv local .venv si existe.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

# Elegir interprete: preferir el venv local.
if [ -x ".venv/bin/python" ]; then
  PY=".venv/bin/python"
else
  PY="$(command -v python3 || command -v python)"
  echo "AVISO: no se encontro .venv. Usando $PY del sistema."
  echo "       Recomendado: python3 -m venv .venv && .venv/bin/pip install -r requirements.txt"
fi

echo "== 1/2 Validando specs SDD =="
"$PY" - <<'PYEOF'
import json, sys, pathlib
root = pathlib.Path(".")
data = json.loads((root / "feature_list.json").read_text(encoding="utf-8"))
required = ("requirements.md", "design.md", "tasks.md")
errors = []
for f in data.get("features", []):
    if not f.get("sdd"):
        continue
    name = f["name"]
    if f.get("status") == "backlog":
        # backlog aun no requiere specs escritas
        continue
    base = root / "specs" / name
    for fname in required:
        if not (base / fname).is_file():
            errors.append(f"  FALTA: specs/{name}/{fname} (status={f.get('status')})")
if errors:
    print("Validacion de specs FALLIDA:")
    print("\n".join(errors))
    sys.exit(1)
print("  OK: toda feature SDD activa/done tiene sus 3 specs.")
PYEOF

echo "== 2/2 Ejecutando tests (pytest) =="
"$PY" -m pytest -q

echo "OK: init.sh verde."
