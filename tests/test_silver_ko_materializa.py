"""tests/test_silver_ko_materializa.py — Feature 27: materialización de KO en silver.

Offline: bronze en tmp_path, sin red.

Mapeo de trazabilidad:
- test_materializa_filas_ko            → R4 (KO fotmob sin fila martj42 → fila nueva con stats)
- test_grupos_no_regresion             → R4 (grupos siguen enriqueciendo; sin fila extra)
- test_ko_con_fila_existente_no_duplica→ R5 (partido ya en martj42 no se duplica)
- test_build_all_incluye_ko            → R7 (build_all offline incluye KO en gold)
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

from src.features.build import build_all
from src.features.silver import build_silver


# ---------------------------------------------------------------------------
# Helpers bronze
# ---------------------------------------------------------------------------


def _write_public(bronze: Path, rows: list[dict]) -> None:
    d = bronze / "public_results"
    d.mkdir(parents=True, exist_ok=True)
    fn = ["date", "home_team", "away_team", "home_score", "away_score",
          "tournament", "city", "country", "neutral"]
    with (d / "results.csv").open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=fn)
        w.writeheader()
        w.writerows(rows)


def _pub_row(date, home, away, hg, ag, neutral="TRUE", tournament="FIFA World Cup"):
    return {"date": date, "home_team": home, "away_team": away,
            "home_score": str(hg), "away_score": str(ag), "tournament": tournament,
            "city": "C", "country": "K", "neutral": neutral}


def _write_fotmob(bronze: Path, docs: list[dict]) -> None:
    d = bronze / "fotmob_stats"
    d.mkdir(parents=True, exist_ok=True)
    for doc in docs:
        slug = doc["page_url"].rsplit("/", 1)[-1].split("#")[0]
        (d / f"{slug}.json").write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")


def _fm_doc(home, away, date, slug, hg=None, ag=None, has_stats=True, xg=(1.5, 0.8)):
    stats = {"possession": 55.0, "xg": None, "shots": 12.0, "shots_on_target": 4.0,
             "corners": 6.0, "cards": 2.0}
    home_stats = {**stats, "xg": xg[0]}
    away_stats = {**stats, "xg": xg[1]}
    return {
        "match_id": slug, "page_url": f"/matches/{home}-vs-{away}/{slug}#{slug}",
        "home_name": home, "away_name": away, "date": date, "has_stats": has_stats,
        "home_goals": hg, "away_goals": ag,
        "home": home_stats if has_stats else {}, "away": away_stats if has_stats else {},
    }


# ---------------------------------------------------------------------------
# R4 — materialización
# ---------------------------------------------------------------------------


def test_materializa_filas_ko(tmp_path: Path):
    bronze = tmp_path / "bronze"
    # martj42: sólo un partido de grupos
    _write_public(bronze, [_pub_row("2026-06-26", "Spain", "Uruguay", 1, 0)])
    # fotmob: un KO (Germany vs Paraguay 1-1) que NO está en martj42, con stats
    _write_fotmob(bronze, [_fm_doc("Germany", "Paraguay", "2026-06-29", "aaa111",
                                   hg=1, ag=1, xg=(2.3, 0.9))])
    df = build_silver(bronze)
    ko = df[(df["home_code"] == "GER") & (df["away_code"] == "PAR")]
    assert len(ko) == 1, "el KO debe materializarse como fila nueva"
    r = ko.iloc[0]
    assert (int(r["home_goals"]), int(r["away_goals"])) == (1, 1)
    assert r["source"] == "fotmob"
    assert abs(float(r["home_xg"]) - 2.3) < 1e-9  # stats pobladas por _apply_fotmob_stats
    assert abs(float(r["away_xg"]) - 0.9) < 1e-9
    assert float(r["home_corners"]) == 6.0


def test_grupos_no_regresion(tmp_path: Path):
    bronze = tmp_path / "bronze"
    _write_public(bronze, [_pub_row("2026-06-26", "Spain", "Uruguay", 1, 0)])
    # fotmob del MISMO partido de grupos SIN goles (JSON estilo viejo) → enriquece, no materializa
    _write_fotmob(bronze, [_fm_doc("Spain", "Uruguay", "2026-06-26", "grp001",
                                   hg=None, ag=None, xg=(1.1, 0.4))])
    df = build_silver(bronze)
    esp = df[(df["home_code"] == "ESP") & (df["away_code"] == "URU")]
    assert len(esp) == 1, "el partido de grupos no debe duplicarse"
    assert esp.iloc[0]["source"] == "public_csv"  # sigue siendo martj42
    assert abs(float(esp.iloc[0]["home_xg"]) - 1.1) < 1e-9  # enriquecido con xG fotmob
    assert len(df) == 1  # cero filas materializadas


def test_ko_con_fila_existente_no_duplica(tmp_path: Path):
    bronze = tmp_path / "bronze"
    # martj42 YA tiene el partido (raro, pero posible si martj42 se pone al día)
    _write_public(bronze, [_pub_row("2026-06-29", "Germany", "Paraguay", 1, 1)])
    # fotmob con goles y orientación INVERTIDA (Paraguay como home)
    _write_fotmob(bronze, [_fm_doc("Paraguay", "Germany", "2026-06-29", "aaa111",
                                   hg=1, ag=1, xg=(0.9, 2.3))])
    df = build_silver(bronze)
    pair = df[df["home_code"].isin(["GER", "PAR"]) & df["away_code"].isin(["GER", "PAR"])]
    assert len(pair) == 1, "no debe duplicar un partido ya presente en martj42 (R5)"
    assert pair.iloc[0]["source"] == "public_csv"


# ---------------------------------------------------------------------------
# R7 — build_all incluye KO
# ---------------------------------------------------------------------------


def test_build_all_incluye_ko(tmp_path: Path):
    bronze = tmp_path / "bronze"
    _write_public(bronze, [_pub_row("2026-06-26", "Spain", "Uruguay", 1, 0)])
    _write_fotmob(bronze, [_fm_doc("Germany", "Paraguay", "2026-06-29", "aaa111", hg=1, ag=1)])
    summary = build_all("2026-07-05", bronze_dir=bronze,
                        silver_dir=tmp_path / "silver", gold_dir=tmp_path / "gold")
    assert summary["n_matches_silver"] == 2  # grupo + KO
    silver = (tmp_path / "silver" / "matches.csv").read_text(encoding="utf-8")
    assert "GER" in silver and "PAR" in silver
