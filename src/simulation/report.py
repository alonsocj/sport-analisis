"""src/simulation/report.py — Reporte determinista de la simulación Monte Carlo (R7).

Responsabilidades:
- ``write_simulation_report``: escribe ``summary.json`` (sort_keys) y
  ``advancement.csv`` bajo ``data/reports/simulacion/``.
- Orden determinista: por P(título) desc, luego código FIFA asc.
- Escritura solo bajo ``data/`` — usa ``_assert_under_data`` de la feature 10 (R7).
- Misma seed/entrada → mismo contenido byte a byte.
"""

from __future__ import annotations

import csv
import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

from ..eval.evaluate import _assert_under_data
from .montecarlo import SimulationResult, ROUNDS

# Directorio de salida por defecto
DEFAULT_REPORT_DIR = Path("data/reports/simulacion")


def write_simulation_report(
    result: SimulationResult,
    out_dir: Path | str = DEFAULT_REPORT_DIR,
) -> tuple[Path, Path]:
    """Escribe el reporte de simulación Monte Carlo (R7).

    Genera dos artefactos deterministas:
    1. ``summary.json``: JSON con ``sort_keys=True, indent=2``, contiene metadatos
       de la simulación y las probabilidades por equipo ordenadas por P(título) desc.
    2. ``advancement.csv``: CSV con una fila por equipo ordenada por P(título) desc.

    Ambos archivos son byte a byte idénticos si la ``SimulationResult`` es idéntica
    (misma seed + misma entrada → mismo resultado de la simulación → mismo reporte).

    La escritura se confina bajo ``data/`` vía ``_assert_under_data`` (R7).

    Args:
        result: Aggregated Monte Carlo simulation result.
        out_dir: Output directory (must be under ``data/``).

    Returns:
        Tuple ``(json_path, csv_path)`` with the paths of the written files.

    Raises:
        ValueError: If ``out_dir`` is not under ``data/``.
    """
    out_path = Path(out_dir)
    _assert_under_data(out_path)
    out_path.mkdir(parents=True, exist_ok=True)

    # Ordenar equipos: P(título) desc, luego código FIFA asc (determinista)
    teams_sorted = sorted(
        result.probabilities.keys(),
        key=lambda t: (-result.probabilities[t].get("champion", 0.0), t),
    )

    # --- summary.json ---
    teams_data: list[dict[str, Any]] = []
    for team in teams_sorted:
        probs = result.probabilities[team]
        ses = result.std_errors[team]
        teams_data.append({
            "team": team,
            "p_group": probs.get("group", 0.0),
            "p_group_se": ses.get("group", 0.0),
            "p_r32": probs.get("r32", 0.0),
            "p_r32_se": ses.get("r32", 0.0),
            "p_r16": probs.get("r16", 0.0),
            "p_r16_se": ses.get("r16", 0.0),
            "p_qf": probs.get("qf", 0.0),
            "p_qf_se": ses.get("qf", 0.0),
            "p_sf": probs.get("sf", 0.0),
            "p_sf_se": ses.get("sf", 0.0),
            "p_final": probs.get("final", 0.0),
            "p_final_se": ses.get("final", 0.0),
            "p_champion": probs.get("champion", 0.0),
            "p_champion_se": ses.get("champion", 0.0),
        })

    summary: dict[str, Any] = {
        "n_simulations": result.n_simulations,
        "rounds": list(ROUNDS),
        "teams": teams_data,
    }

    json_path = out_path / "summary.json"
    json_path.write_text(
        json.dumps(summary, sort_keys=True, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    # --- advancement.csv ---
    csv_path = out_path / "advancement.csv"
    fieldnames = [
        "team",
        "p_group", "p_group_se",
        "p_r32", "p_r32_se",
        "p_r16", "p_r16_se",
        "p_qf", "p_qf_se",
        "p_sf", "p_sf_se",
        "p_final", "p_final_se",
        "p_champion", "p_champion_se",
    ]

    with csv_path.open(mode="w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        for entry in teams_data:
            writer.writerow(entry)

    return json_path, csv_path
