"""已破主大量區畫圖升格：黃帶改下一層，已破改淡帶；近窗不加浪段大底色。"""

from __future__ import annotations

import inspect

from biaoke_level_learn import (
    _display_teach_vol_sr_for_paint,
    _paint_window_dual_zones,
    _render_twii_live_dark,
    _resolve_teach_vol_sr,
    _ymd,
)


def test_display_promote_when_broke_support_has_next():
    rows = [
        {
            "date": "20260304",
            "open": 33000,
            "high": 34444,
            "low": 32834,
            "close": 34000,
            "volume": 90000,
        },
        {
            "date": "20260306",
            "open": 33500,
            "high": 33799,
            "low": 32000,
            "close": 32500,
            "volume": 95000,
        },
        {
            "date": "20260610",
            "open": 44700,
            "high": 45073,
            "low": 42334,
            "close": 43878,
            "volume": 121791,
        },
        {
            "date": "20261105",
            "open": 41990,
            "high": 42298,
            "low": 38799,
            "close": 38936,
            "volume": 89277,
        },
    ]
    raw = _resolve_teach_vol_sr(rows, lookback=80)
    assert bool((raw.get("primary") or {}).get("broke_support")) is True
    assert raw.get("next")
    disp = _display_teach_vol_sr_for_paint(raw)
    assert disp.get("paint_promoted") is True
    assert _ymd((disp.get("primary") or {}).get("date")) == _ymd(
        (raw.get("next") or {}).get("date")
    )
    assert _ymd((disp.get("broken_primary") or {}).get("date")) == _ymd(
        (raw.get("primary") or {}).get("date")
    )
    assert not (disp.get("next") or {})
    # raw 語意不變
    assert float((raw["primary"] or {}).get("low") or 0) == 42334.0


def test_display_no_promote_when_preview_only():
    sr = {
        "primary": {
            "date": "20261015",
            "high": 48000,
            "low": 47000,
            "broke_support": False,
            "broke_press": False,
        },
        "next": {
            "date": "20261106",
            "high": 40436,
            "low": 37837,
            "preview": True,
        },
        "i_primary": 1,
        "i_next": 2,
    }
    disp = _display_teach_vol_sr_for_paint(sr)
    assert not disp.get("paint_promoted")
    assert _ymd((disp.get("primary") or {}).get("date")) == "20261015"
    assert bool((disp.get("next") or {}).get("preview")) is True


def test_paint_window_dual_zones_uses_promote_helper():
    src = inspect.getsource(_paint_window_dual_zones)
    assert "_display_teach_vol_sr_for_paint" in src
    assert "_paint_broken_vol_zone" in src


def test_near_window_no_macro_axvspan_blocks():
    src = inspect.getsource(_render_twii_live_dark)
    assert "ax.axvspan(i5s" not in src
    assert "近窗亦不加權浪段大底色" in src or "不加權浪段大底色" in src
