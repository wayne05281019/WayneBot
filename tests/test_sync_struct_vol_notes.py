# -*- coding: utf-8 -*-
"""SYNC-STRUCT-VOL 圖註：開關、偵測、他位、非買訊。"""
from __future__ import annotations

import inspect

from sync_struct_vol_notes import (
    PHONE_WARNING_FIXED,
    RULE_FAKE_BREAK,
    RULE_PRESS_TO_SUP,
    RULE_VOL_NO_STAB,
    append_notes_to_caption,
    detect_struct_vol_notes,
    extract_his_named_levels,
    format_notes_caption,
    maybe_paint_struct_vol_notes,
    notes_enabled,
)


def _bars_flat(n: int = 20, *, base: float = 100.0, vol: float = 2000.0):
    out = []
    for i in range(n):
        c = base + i * 0.2
        out.append(
            {
                "date": f"202601{i+1:02d}" if i < 28 else f"202602{i-27:02d}",
                "open": c - 0.5,
                "high": c + 1.0,
                "low": c - 1.0,
                "close": c,
                "volume": vol,
            }
        )
    return out


def test_notes_default_off(monkeypatch):
    monkeypatch.delenv("WAYNE_STRUCT_VOL_NOTES", raising=False)
    assert notes_enabled() is False
    assert notes_enabled({"struct_vol_notes": True}) is True
    assert notes_enabled({"struct_vol_notes": False}) is False
    monkeypatch.setenv("WAYNE_STRUCT_VOL_NOTES", "1")
    assert notes_enabled() is True


def test_fake_breakdown_and_press_to_support():
    bars = _bars_flat(12, base=100.0)
    # pierce 95 then reclaim
    bars[-2] = {
        "date": "20260111",
        "open": 100,
        "high": 102,
        "low": 94,
        "close": 96,
        "volume": 1800,
    }
    bars[-1] = {
        "date": "20260112",
        "open": 96,
        "high": 101,
        "low": 95.5,
        "close": 100,
        "volume": 1700,
    }
    notes = detect_struct_vol_notes(
        bars, hold=95.0, press=110.0, card={"struct_vol_notes": True}
    )
    kinds = {n["kind"] for n in notes}
    assert "fake_breakdown" in kinds
    assert all(n.get("buy_signal") is False for n in notes)
    assert all(n.get("rule_id") for n in notes)
    assert any(n["rule_id"] == RULE_FAKE_BREAK for n in notes)

    # press-to-support: two closes above 100 after prior under
    bars2 = _bars_flat(14, base=96.0)
    for i in range(10):
        bars2[i]["close"] = 97.0
        bars2[i]["high"] = 99.5
        bars2[i]["low"] = 95.0
    bars2[-2].update({"close": 101.0, "high": 102.0, "low": 99.0, "open": 100.0})
    bars2[-1].update({"close": 102.0, "high": 103.0, "low": 100.5, "open": 101.0})
    notes2 = detect_struct_vol_notes(
        bars2, press=100.0, hold=90.0, card={"struct_vol_notes": True}
    )
    assert any(n["kind"] == "resist_to_support" for n in notes2)
    assert any(n["rule_id"] == RULE_PRESS_TO_SUP for n in notes2)


def test_vol_dry_and_no_chip():
    bars = _bars_flat(20, base=100.0, vol=3000.0)
    bars[-1].update(
        {
            "close": 95.0,
            "open": 99.0,
            "high": 99.5,
            "low": 94.0,
            "volume": 800.0,  # thin vs median
        }
    )
    notes = detect_struct_vol_notes(
        bars, hold=96.0, press=110.0, card={"struct_vol_notes": True}
    )
    kinds = {n["kind"] for n in notes}
    assert "vol_dry_decline" in kinds or "no_chip_exchange" in kinds
    assert any(n["rule_id"] == RULE_VOL_NO_STAB for n in notes)


def test_his_levels_only_when_named():
    assert extract_his_named_levels({}) == []
    assert extract_his_named_levels({"his_named_levels": []}) == []
    got = extract_his_named_levels(
        {
            "his_named_levels": [
                {"price": 37837, "label": "週五低", "pot": "他說"},
                {"price": 0, "label": "無效"},
                {"price": 999, "label": "亂標"},  # no pot/his → skip
            ]
        }
    )
    assert len(got) == 1
    assert got[0]["price"] == 37837.0
    assert got[0]["pot"] == "他說"


def test_caption_and_warning():
    notes = detect_struct_vol_notes(
        _bars_flat(12)
        + [
            {
                "date": "20260113",
                "open": 100,
                "high": 102,
                "low": 94,
                "close": 96,
                "volume": 1000,
            },
            {
                "date": "20260114",
                "open": 96,
                "high": 101,
                "low": 95.5,
                "close": 100,
                "volume": 900,
            },
        ],
        hold=95.0,
        card={"struct_vol_notes": True},
    )
    block = format_notes_caption(notes)
    assert PHONE_WARNING_FIXED in block
    cap = append_notes_to_caption("結構圖（非買訊）", notes, card={"struct_vol_notes": True})
    assert "結構圖（非買訊）" in cap
    assert "〔" in cap
    # 關閉時不追加
    assert (
        append_notes_to_caption("結構圖（非買訊）", notes, card={"struct_vol_notes": False})
        == "結構圖（非買訊）"
    )


def test_paint_noop_when_disabled():
    out = maybe_paint_struct_vol_notes(
        None, _bars_flat(10), None, card={"struct_vol_notes": False}
    )
    assert out["enabled"] is False
    assert out["n_notes"] == 0
    assert out["buy_signal"] is False


def test_hooks_present_in_paint_paths():
    from biaoke_chart import render_biaoke_structure_png
    from three_in_one_chart import render_lookup_structure_result
    from vol_zone_chart import _paint_volume_zone, render_volume_zone_result

    assert "maybe_paint_struct_vol_notes" in inspect.getsource(render_biaoke_structure_png)
    assert "maybe_paint_struct_vol_notes" in inspect.getsource(_paint_volume_zone)
    assert "detect_struct_vol_notes" in inspect.getsource(render_lookup_structure_result)
    assert "detect_struct_vol_notes" in inspect.getsource(render_volume_zone_result)


def test_rules_doc_present():
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    md = root / "docs" / "expert_notes" / "飆客" / "observe_manual" / "struct_vol_notes_rules.md"
    js = root / "docs" / "expert_notes" / "飆客" / "observe_manual" / "struct_vol_notes_rules.json"
    assert md.is_file()
    assert js.is_file()
    text = md.read_text(encoding="utf-8")
    assert "WR-OPS-EFF-PIERCE" in text
    assert "無量" in text
    assert "沒爆量" in text
