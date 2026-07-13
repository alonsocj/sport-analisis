"""tests/test_app_semifinal.py — Feature 33: tab Semifinal (r4). AppTest offline.

Espejo de test_app_r16_r8 (Feature 30): reusa el andamiaje de test_app_knockouts.
Trazabilidad F33:
- R1 (tab Semifinal presente + r4 default)      → test_tab_semifinal_presente / test_r4_default
- R2 (aditivo: 6 tabs, previos intactos)        → test_seis_tabs_previos_intactos
- R3 (slider γ namespaced, sin DuplicateWidget)  → test_slider_r4_sin_colision
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(__file__))
import test_app_knockouts as tk  # noqa: E402 — helpers de AppTest compartidos

_R8_CSV = (
    "draw_order,date,stage,home_code,away_code,source\n"
    "1,2026-07-09,QF,ARG,BRA,fotmob_official\n"
)
_R4_CSV = (
    "draw_order,date,stage,home_code,away_code,source\n"
    "1,2026-07-14,SF,FRA,ESP,fotmob_official\n"
    "2,2026-07-15,SF,ENG,ARG,fotmob_official\n"
)


def _run_app(monkeypatch, tmp_path: Path):
    """AppTest con r16 (DEFAULT_KO_CSV), r8 (DEFAULT_R8_CSV) y r4 (DEFAULT_R4_CSV) a tmp."""
    from streamlit.testing.v1 import AppTest
    import src.app.main as main_mod
    import src.app.tabs.knockouts as ko_mod

    ko_csv = tk._make_ko_csv(tmp_path)  # sirve de r16 (fixtures válidas)
    r8_csv = tmp_path / "data" / "knockouts" / "r8_fixtures.csv"
    r8_csv.write_text(_R8_CSV, encoding="utf-8")
    r4_csv = tmp_path / "data" / "knockouts" / "r4_fixtures.csv"
    r4_csv.write_text(_R4_CSV, encoding="utf-8")
    paths = tk._write_apptest_inputs(tmp_path, ko_csv)

    main_mod._cached_load_app_data.clear()
    main_mod._cached_predict_for.clear()
    tk._patch_app_defaults(monkeypatch, paths)  # patchea DEFAULT_KO_CSV → r16
    monkeypatch.setattr(ko_mod, "DEFAULT_R8_CSV", r8_csv)
    monkeypatch.setattr(ko_mod, "DEFAULT_R4_CSV", r4_csv)

    app_path = Path(__file__).parent.parent / "src" / "app" / "main.py"
    at = AppTest.from_file(str(app_path), default_timeout=20.0)
    at.run()
    return at


def test_tab_semifinal_presente(tmp_path: Path, monkeypatch) -> None:
    """R1: el tab Semifinal está presente; sin excepción."""
    from src.app.main import TAB_SEMIFINAL

    at = _run_app(monkeypatch, tmp_path)
    assert not at.exception, f"AppTest lanzó excepción: {at.exception}"
    labels = [t.label for t in at.tabs]
    assert TAB_SEMIFINAL in labels and "Semifinal" in TAB_SEMIFINAL


def test_r4_default() -> None:
    """R1: existe DEFAULT_R4_CSV apuntando a r4_fixtures.csv."""
    from src.app.tabs.knockouts import DEFAULT_R4_CSV

    assert DEFAULT_R4_CSV.name == "r4_fixtures.csv"


def test_seis_tabs_previos_intactos(tmp_path: Path, monkeypatch) -> None:
    """R2: aditivo — 6 tabs de contenido; previos intactos (no-regresión)."""
    from src.app.main import (
        TAB_CALENDARIO,
        TAB_SELECCIONES,
        TAB_MODELO,
        TAB_KNOCKOUTS,
        TAB_ROUND8,
        TAB_SEMIFINAL,
    )

    at = _run_app(monkeypatch, tmp_path)
    labels = [t.label for t in at.tabs]
    for tab in (TAB_CALENDARIO, TAB_SELECCIONES, TAB_MODELO, TAB_KNOCKOUTS, TAB_ROUND8, TAB_SEMIFINAL):
        assert tab in labels, f"Falta {tab!r} en {labels}"
    assert len(at.tabs) == 6  # 3 previos + Round of 16 + Round of 8 + Semifinal


def test_slider_r4_sin_colision(tmp_path: Path, monkeypatch) -> None:
    """R3: tres tabs KO → sliders γ con key distinta (namespaced), sin DuplicateWidgetID."""
    at = _run_app(monkeypatch, tmp_path)
    assert not at.exception, f"AppTest lanzó excepción: {at.exception}"
    slider_keys = {s.key for s in at.slider}
    assert {"gamma_r16", "gamma_r8", "gamma_r4"} <= slider_keys, slider_keys
