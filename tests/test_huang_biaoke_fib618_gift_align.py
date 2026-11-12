"""黃0.618禮物 × 飆大兩區間 × 上週五低——皆須有憑據（非買訊）。"""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LAB = ROOT / "docs" / "expert_notes" / "飆客" / "decade_lab"


def _load(name: str) -> dict:
    return json.loads((LAB / name).read_text(encoding="utf-8"))


def test_biaoke_two_ranges_have_evidence():
    d = _load("huang_biaoke_fib618_gift_align_20261112.json")
    assert d.get("not_buy_signal") is True
    ranges = {r["id"]: r for r in d["biaoke_two_ranges_today"]}
    assert ranges["R1_path_below_43000"]["level"] == 43000.0
    assert ranges["R2_bottom_band_419_427"]["lo"] == 41900.0
    assert ranges["R2_bottom_band_419_427"]["hi"] == 42700.0
    assert "絕對會到43000" in ranges["R1_path_below_43000"]["he_said_zh"]
    assert "41900~42700" in ranges["R2_bottom_band_419_427"]["he_said_zh"]


def test_fib618_lands_in_named_band():
    d = _load("huang_biaoke_fib618_gift_align_20261112.json")
    calc = d["huang_fib618_gift"]["reproducible_calc"]
    lvl = float(calc["level"])
    assert calc["wave_high"] == 49968.0
    assert abs(calc["wave_low"] - 37837.05) < 0.01
    expected = 49968.0 - 0.618 * (49968.0 - 37837.05)
    assert abs(lvl - expected) < 0.2
    assert 41900.0 <= lvl <= 42700.0
    assert d["biaoke_friday_low"]["level"] == 37837.05
