"""tests/test_app_final.py — Feature 34: tab Final (r2) + 3er puesto (r3p). AppTest offline.

Espejo de test_app_semifinal (F33). Trazabilidad F34/R9:
- R9 tab Final presente + 7 tabs aditivo   → test_tab_final_presente / test_siete_tabs_aditivo
- R9 dos bloques (Final + 3er puesto)       → test_final_dos_bloques
- R9 dead-rubber SÓLO en el 3er puesto      → test_dead_rubber_solo_en_3p
- R9 panel de simulación renderiza          → test_sim_panel_render
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
_R2_CSV = (
    "draw_order,date,stage,home_code,away_code,source\n"
    "1,2026-07-19,Final,FRA,ARG,fotmob_official\n"
)
_R3P_CSV = (
    "draw_order,date,stage,home_code,away_code,source\n"
    "1,2026-07-18,3P,ESP,ENG,fotmob_official\n"
)


def _run_app(monkeypatch, tmp_path: Path):
    from streamlit.testing.v1 import AppTest
    import src.app.main as main_mod
    import src.app.tabs.knockouts as ko_mod

    ko_csv = tk._make_ko_csv(tmp_path)  # r16
    kdir = tmp_path / "data" / "knockouts"
    kdir.mkdir(parents=True, exist_ok=True)
    (kdir / "r8_fixtures.csv").write_text(_R8_CSV, encoding="utf-8")
    (kdir / "r4_fixtures.csv").write_text(_R4_CSV, encoding="utf-8")
    (kdir / "r2_fixtures.csv").write_text(_R2_CSV, encoding="utf-8")
    (kdir / "r3p_fixtures.csv").write_text(_R3P_CSV, encoding="utf-8")
    paths = tk._write_apptest_inputs(tmp_path, ko_csv)

    main_mod._cached_load_app_data.clear()
    main_mod._cached_predict_for.clear()
    tk._patch_app_defaults(monkeypatch, paths)
    monkeypatch.setattr(ko_mod, "DEFAULT_R8_CSV", kdir / "r8_fixtures.csv")
    monkeypatch.setattr(ko_mod, "DEFAULT_R4_CSV", kdir / "r4_fixtures.csv")
    monkeypatch.setattr(ko_mod, "DEFAULT_R2_CSV", kdir / "r2_fixtures.csv")
    monkeypatch.setattr(ko_mod, "DEFAULT_R3P_CSV", kdir / "r3p_fixtures.csv")

    app_path = Path(__file__).parent.parent / "src" / "app" / "main.py"
    at = AppTest.from_file(str(app_path), default_timeout=30.0)
    at.run()
    return at


def _all_md(at) -> str:
    return " ".join(m.value for m in at.markdown)


def test_tab_final_presente(tmp_path: Path, monkeypatch) -> None:
    from src.app.main import TAB_FINAL

    at = _run_app(monkeypatch, tmp_path)
    assert not at.exception, f"AppTest lanzó excepción: {at.exception}"
    labels = [t.label for t in at.tabs]
    assert TAB_FINAL in labels and "Final" in TAB_FINAL


def test_siete_tabs_aditivo(tmp_path: Path, monkeypatch) -> None:
    from src.app.main import (
        TAB_CALENDARIO, TAB_SELECCIONES, TAB_MODELO,
        TAB_KNOCKOUTS, TAB_ROUND8, TAB_SEMIFINAL, TAB_FINAL,
    )

    at = _run_app(monkeypatch, tmp_path)
    labels = [t.label for t in at.tabs]
    for tab in (TAB_CALENDARIO, TAB_SELECCIONES, TAB_MODELO,
                TAB_KNOCKOUTS, TAB_ROUND8, TAB_SEMIFINAL, TAB_FINAL):
        assert tab in labels, f"Falta {tab!r} en {labels}"
    assert len(at.tabs) == 7  # 6 previos + Final


def test_final_dos_bloques(tmp_path: Path, monkeypatch) -> None:
    at = _run_app(monkeypatch, tmp_path)
    assert not at.exception, f"AppTest lanzó excepción: {at.exception}"
    md = _all_md(at)
    assert "Final" in md
    assert "Tercer puesto" in md


def test_dead_rubber_solo_en_3p(tmp_path: Path, monkeypatch) -> None:
    """La amortiguación dead-rubber se anuncia exactamente una vez (bloque 3er puesto)."""
    at = _run_app(monkeypatch, tmp_path)
    md = _all_md(at)
    assert md.count("dead-rubber") == 1


def test_sim_panel_render(tmp_path: Path, monkeypatch) -> None:
    """El panel de simulación Monte Carlo se renderiza (en ambos bloques)."""
    at = _run_app(monkeypatch, tmp_path)
    md = _all_md(at)
    assert "Simulación Monte Carlo" in md
    slider_keys = {s.key for s in at.slider}
    assert {"gamma_r2", "gamma_r3p"} <= slider_keys, slider_keys
