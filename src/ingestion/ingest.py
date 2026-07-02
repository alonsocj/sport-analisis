"""Orquestación de la ingesta a la capa bronze.

Por cada selección: recupera sus últimos 15 partidos (R2), las estadísticas por partido
(R3) y las cuotas (R4), y lo persiste crudo en bronze (R5). Los errores de una selección
no abortan el lote (R9).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from .bronze import write_bronze
from .client import ApiFootballClient
from .teams import Team, all_teams

# Mapeo de tipos de estadística de API-Football → esquema interno (R3).
_STAT_MAP = {
    "Corner Kicks": "corners",
    "Total Shots": "shots",
    "Shots on Goal": "shots_on_target",
    "Ball Possession": "possession",
}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def fetch_last_fixtures(
    client: ApiFootballClient,
    team_id: int,
    last: int = 15,
    fetched_at: str | None = None,
) -> list[dict[str, Any]]:
    """Últimos ``last`` partidos finalizados de una selección (R2). Persiste en bronze (R5)."""
    params = {"team": team_id, "last": last}
    data = client.get("fixtures", params)
    write_bronze(
        client.settings.BRONZE_DIR, "fixtures", params, data, fetched_at or _now_iso()
    )
    return data.get("response", [])


def normalize_statistics(raw: dict[str, Any], goals: dict[str, int] | None = None) -> dict[str, Any]:
    """Normaliza /fixtures/statistics a {home, away} con el esquema interno (R3).

    Cada lado: goals, corners, cards, shots, shots_on_target, possession.
    ``goals`` (por lado) se inyecta desde el fixture, ya que /statistics no lo incluye.
    """
    sides = raw.get("response", [])
    out: dict[str, Any] = {}
    labels = ("home", "away")
    for i, side in enumerate(sides[:2]):
        stats = {v: None for v in ("corners", "cards", "shots", "shots_on_target", "possession")}
        yellow = red = 0
        for item in side.get("statistics", []):
            t = item.get("type")
            val = item.get("value")
            if t in _STAT_MAP:
                stats[_STAT_MAP[t]] = val
            elif t == "Yellow Cards":
                yellow = val or 0
            elif t == "Red Cards":
                red = val or 0
        stats["cards"] = yellow + red
        label = labels[i] if i < len(labels) else f"team_{i}"
        stats["goals"] = (goals or {}).get(label)
        out[label] = stats
    return out


def fetch_fixture_statistics(
    client: ApiFootballClient,
    fixture_id: int,
    goals: dict[str, int] | None = None,
    fetched_at: str | None = None,
) -> dict[str, Any]:
    """Estadísticas normalizadas de un partido (R3). Persiste crudo en bronze (R5)."""
    params = {"fixture": fixture_id}
    data = client.get("fixtures/statistics", params)
    write_bronze(
        client.settings.BRONZE_DIR, "fixtures/statistics", params, data, fetched_at or _now_iso()
    )
    return normalize_statistics(data, goals)


def fetch_odds(
    client: ApiFootballClient,
    fixture_id: int,
    fetched_at: str | None = None,
) -> Any | None:
    """Cuotas de un partido (R4). DONDE no existan, devuelve None sin fallar."""
    params = {"fixture": fixture_id}
    data = client.get("odds", params)
    write_bronze(
        client.settings.BRONZE_DIR, "odds", params, data, fetched_at or _now_iso()
    )
    response = data.get("response", [])
    if not response:
        return None
    return response


def ingest_team(
    client: ApiFootballClient,
    team_id: int,
    last: int = 15,
    fetched_at: str | None = None,
) -> dict[str, Any]:
    """Ingiere los últimos partidos de una selección. No captura errores (lo hace el lote)."""
    fixtures = fetch_last_fixtures(client, team_id, last, fetched_at)
    return {"team_id": team_id, "fixtures": len(fixtures)}


def ingest_all(
    client: ApiFootballClient,
    team_ids: dict[str, int],
    last: int = 15,
    fetched_at: str | None = None,
) -> dict[str, Any]:
    """Ingiere todas las selecciones. Un error en una no aborta el resto (R9).

    ``team_ids``: mapa code → id de API-Football.
    Devuelve resumen {ok: [...], errores: [{code, error}]}.
    """
    ok: list[str] = []
    errores: list[dict[str, str]] = []
    for code, team_id in team_ids.items():
        try:
            ingest_team(client, team_id, last, fetched_at)
            ok.append(code)
        except Exception as exc:  # R9: registrar y continuar
            errores.append({"code": code, "error": f"{type(exc).__name__}: {exc}"})
    return {"ok": ok, "errores": errores}
