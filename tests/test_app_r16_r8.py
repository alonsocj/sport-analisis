"""tests/test_app_r16_r8.py — Feature 30: tabs Round of 16 / Round of 8. AppTest offline.

Reusa el andamiaje de test_app_knockouts (mismos insumos gold sintéticos).
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


def _run_app(monkeypatch, tmp_path: Path):
    """AppTest con r16 (DEFAULT_KO_CSV) y r8 (DEFAULT_R8_CSV) inyectados a tmp."""
    from streamlit.testing.v1 import AppTest
    import src.app.main as main_mod
    import src.app.tabs.knockouts as ko_mod

    ko_csv = tk._make_ko_csv(tmp_path)  # sirve de r16 (fixtures válidas)
    r8_csv = tmp_path / "data" / "knockouts" / "r8_fixtures.csv"
    r8_csv.write_text(_R8_CSV, encoding="utf-8")
    # F33: la app añade el tab Semifinal (r4); inyectar un r4 vacío mantiene el test hermético.
    r4_csv = tmp_path / "data" / "knockouts" / "r4_fixtures.csv"
    r4_csv.write_text("draw_order,date,stage,home_code,away_code,source\n", encoding="utf-8")
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


def test_tab_round16_y_round8_presentes(tmp_path: Path, monkeypatch) -> None:
    """R1/R2: los tabs Round of 16 y Round of 8 están presentes; sin excepción (R4)."""
    from src.app.main import TAB_KNOCKOUTS, TAB_ROUND8

    at = _run_app(monkeypatch, tmp_path)
    assert not at.exception, f"AppTest lanzó excepción: {at.exception}"
    labels = [t.label for t in at.tabs]
    assert TAB_KNOCKOUTS in labels and "Round of 16" in TAB_KNOCKOUTS
    assert TAB_ROUND8 in labels and "Round of 8" in TAB_ROUND8


def test_tabs_previos_intactos(tmp_path: Path, monkeypatch) -> None:
    """R4: Calendario/Selecciones/Modelo siguen presentes (no-regresión)."""
    from src.app.main import TAB_CALENDARIO, TAB_SELECCIONES, TAB_MODELO

    at = _run_app(monkeypatch, tmp_path)
    labels = [t.label for t in at.tabs]
    for tab in (TAB_CALENDARIO, TAB_SELECCIONES, TAB_MODELO):
        assert tab in labels, f"Falta {tab!r} en {labels}"
    assert len(at.tabs) == 6  # 3 previos + Round of 16 + Round of 8 + Semifinal (F33)


def test_dos_tabs_ko_sin_colision(tmp_path: Path, monkeypatch) -> None:
    """R3: dos tabs KO → sliders γ con key distinta (namespaced), sin DuplicateWidgetID."""
    at = _run_app(monkeypatch, tmp_path)
    assert not at.exception, f"AppTest lanzó excepción: {at.exception}"
    slider_keys = {s.key for s in at.slider}
    assert "gamma_r16" in slider_keys and "gamma_r8" in slider_keys, slider_keys


def test_r16_es_default_ko_csv():
    """R1: DEFAULT_KO_CSV apunta a r16; existe DEFAULT_R8_CSV separado."""
    from src.app.tabs.knockouts import DEFAULT_KO_CSV, DEFAULT_R8_CSV

    assert DEFAULT_KO_CSV.name == "r16_fixtures.csv"
    assert DEFAULT_R8_CSV.name == "r8_fixtures.csv"
