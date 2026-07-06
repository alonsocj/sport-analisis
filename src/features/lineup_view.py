"""src/features/lineup_view.py — Vista de alineación + jugador destacado (Feature 31).

Lógica PURA (sin streamlit): lee el bronze de lineups (F28), elige el jugador destacado por
`market_value` y arma el XI ordenado por posición. La UI (knockouts.py) solo pinta.
"""

from __future__ import annotations

import json
import logging
import unicodedata
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

DEFAULT_BRONZE_LINEUPS_DIR = Path("data") / "bronze" / "lineups"

# usualPlayingPositionId → etiqueta (verificado F28: 0=GK,1=DEF,2=MID,3=ATT)
POS_LABELS: dict[int, str] = {0: "POR", 1: "DEF", 2: "MED", 3: "DEL"}
# Orden de presentación del XI (portero primero, delanteros al final)
_POS_ORDER: dict[int, int] = {0: 0, 1: 1, 2: 2, 3: 3}


def _norm(name: str) -> str:
    """Normaliza un nombre para cruce: minúsculas, sin acentos, sin espacios extra."""
    if not name:
        return ""
    nfkd = unicodedata.normalize("NFKD", name)
    stripped = "".join(c for c in nfkd if not unicodedata.combining(c))
    return " ".join(stripped.lower().split())


def _neighbors(date: str) -> list[str]:
    try:
        base = datetime.strptime(date, "%Y-%m-%d")
    except ValueError:
        return [date]
    return [date] + [(base + timedelta(days=k)).strftime("%Y-%m-%d") for k in (-1, 1)]


def find_lineup_doc(
    bronze_dir: Path | str,
    date: str,
    home_code: str,
    away_code: str,
) -> dict | None:
    """Localiza el doc de lineup del partido por (date±1, {home_code, away_code}) (R4).

    Devuelve el dict del JSON o None si no hay coincidencia. Robusto a inversión
    home/away (clave por conjunto de códigos) y a desfase de ±1 día (UTC vs local).
    """
    lineups_dir = Path(bronze_dir) / "lineups" if (Path(bronze_dir) / "lineups").is_dir() else Path(bronze_dir)
    if not lineups_dir.is_dir():
        return None
    want_pair = frozenset({home_code, away_code})
    want_dates = set(_neighbors(date))
    for path in sorted(lineups_dir.glob("*.json")):
        if path.name.endswith(".meta.json"):
            continue
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        pair = frozenset({doc.get("home_code"), doc.get("away_code")})
        if pair == want_pair and (doc.get("date") in want_dates):
            return doc
    return None


def _rating(player: dict) -> float | None:
    r = player.get("match_rating")
    return r if isinstance(r, (int, float)) else player.get("season_rating")


def _goal_share(name: str, scorers: list[tuple[str, float]]) -> float | None:
    """Cruza `name` contra scorers (name, share) por nombre normalizado o apellido (R3)."""
    if not scorers:
        return None
    target = _norm(name)
    if not target:
        return None
    last = target.split()[-1]
    best: float | None = None
    for sc_name, share in scorers:
        n = _norm(sc_name)
        if n == target or (last and (n.endswith(" " + last) or n == last)):
            if best is None or share > best:
                best = float(share)
    return best


def pick_crack(starters: list[dict], scorers: list[tuple[str, float]]) -> dict | None:
    """Elige el titular con mayor market_value; adjunta goal_share y rating (R2, R3).

    Devuelve None si ningún titular tiene market_value.
    """
    with_value = [p for p in starters if isinstance(p.get("market_value"), int)]
    if not with_value:
        return None
    crack = max(with_value, key=lambda p: (p["market_value"], _norm(p.get("name", ""))))
    return {
        "name": crack.get("name", ""),
        "club": crack.get("club"),
        "market_value": crack.get("market_value"),
        "rating": _rating(crack),
        "goal_share": _goal_share(crack.get("name", ""), scorers),
    }


def _build_xi(starters: list[dict], crack_name: str | None) -> list[dict]:
    """XI ordenado por posición (POR→DEL) y dorsal; marca al crack (R4)."""
    def _key(p: dict) -> tuple:
        pos = p.get("usual_position_id")
        order = _POS_ORDER.get(pos if isinstance(pos, int) else 99, 99)
        shirt = p.get("shirt_number")
        return (order, shirt if isinstance(shirt, int) else 999)

    out: list[dict] = []
    for p in sorted(starters, key=_key):
        pos = p.get("usual_position_id")
        out.append({
            "name": p.get("name", ""),
            "shirt_number": p.get("shirt_number"),
            "pos_label": POS_LABELS.get(pos if isinstance(pos, int) else -1, "—"),
            "is_crack": bool(crack_name) and p.get("name") == crack_name,
        })
    return out


def build_lineup_view(
    doc: dict,
    home_code: str,
    away_code: str,
    scorers_home: list[tuple[str, float]],
    scorers_away: list[tuple[str, float]],
) -> dict:
    """Construye la vista por equipo, orientada al home/away de la LLAVE (R2, R4).

    Returns:
        ``{"home": {crack, xi, lineup_type}, "away": {...}}``. Cada lado puede tener
        ``crack=None`` o ``xi=[]`` si el doc no trae titulares para ese equipo.
    """
    lineup_type = doc.get("lineup_type", "")
    # Orientar: qué lado del doc corresponde al home_code de la llave
    if doc.get("home_code") == home_code:
        home_starters, away_starters = doc.get("home") or [], doc.get("away") or []
    elif doc.get("away_code") == home_code:
        home_starters, away_starters = doc.get("away") or [], doc.get("home") or []
    else:
        # No matchea el home_code de la llave; usar orden del doc como fallback
        home_starters, away_starters = doc.get("home") or [], doc.get("away") or []

    crack_h = pick_crack(home_starters, scorers_home)
    crack_a = pick_crack(away_starters, scorers_away)
    return {
        "lineup_type": lineup_type,
        "home": {"crack": crack_h, "xi": _build_xi(home_starters, crack_h["name"] if crack_h else None)},
        "away": {"crack": crack_a, "xi": _build_xi(away_starters, crack_a["name"] if crack_a else None)},
    }
