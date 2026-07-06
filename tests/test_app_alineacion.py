"""tests/test_app_alineacion.py — Feature 31: sub-pestaña Alineación en el detalle KO. AppTest."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(__file__))
import test_app_knockouts as tk  # noqa: E402 — helpers AppTest compartidos


def _write_lineup(tmp_path: Path) -> Path:
    """Bronze lineup para ARG-BRA (fixture del _KO_CSV_CONTENT, 2026-06-29)."""
    d = tmp_path / "data" / "bronze" / "lineups"
    d.mkdir(parents=True, exist_ok=True)
    doc = {
        "date": "2026-06-29", "lineup_type": "predicted",
        "home_code": "ARG", "away_code": "BRA",
        "home": [
            {"name": "Dibu", "usual_position_id": 0, "market_value": 20_000_000,
             "shirt_number": 23, "club": "Aston Villa", "season_rating": 7.0, "match_rating": None},
            {"name": "Messi", "usual_position_id": 3, "market_value": 30_000_000,
             "shirt_number": 10, "club": "Inter Miami", "season_rating": 8.5, "match_rating": None},
        ],
        "away": [
            {"name": "Raphinha", "usual_position_id": 3, "market_value": 90_000_000,
             "shirt_number": 11, "club": "Barcelona", "season_rating": 8.1, "match_rating": None},
        ],
    }
    (d / "argbra.json").write_text(json.dumps(doc), encoding="utf-8")
    return d


def test_subpestana_alineacion_presente(tmp_path: Path, monkeypatch) -> None:
    """R5: con detalle abierto y bronze de lineup, la sub-pestaña Alineación renderiza el crack."""
    from streamlit.testing.v1 import AppTest
    import src.app.main as main_mod
    import src.app.tabs.knockouts as ko_mod

    ko_csv = tk._make_ko_csv(tmp_path)
    paths = tk._write_apptest_inputs(tmp_path, ko_csv)
    lineups_dir = _write_lineup(tmp_path)

    main_mod._cached_load_app_data.clear()
    main_mod._cached_predict_for.clear()
    tk._patch_app_defaults(monkeypatch, paths)
    monkeypatch.setattr(ko_mod, "_DEFAULT_LINEUPS_DIR", lineups_dir)

    app_path = Path(__file__).parent.parent / "src" / "app" / "main.py"
    at = AppTest.from_file(str(app_path), default_timeout=25.0)
    at.session_state["selected_ko_r16"] = ("2026-06-29", "ARG", "BRA")
    at.run()

    assert not at.exception, f"AppTest lanzó excepción: {at.exception}"
    # El crack de BRA (mayor valor) es Raphinha; st.markdown/st.write se exponen como markdown
    texts = " ".join(m.value for m in at.markdown)
    assert "Raphinha" in texts, "El jugador destacado no aparece en la sub-pestaña Alineación"
