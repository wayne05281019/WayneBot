# -*- coding: utf-8 -*-
"""2026-10-28：結構／大量區主壓撐同源＋表頭現／低不互壓＋右軸刻度入鏡。"""
from __future__ import annotations

import math
import re

import pytest


def test_volume_first_skips_nan_is_live_not_today():
    """盤中疊臉後歷史 is_live=nan 不准整窗略過；爆大量仍是過去最大量日。"""
    from biaoke_brain import _flag_is_true, _volume_first_bar_skippable, volume_first_price

    assert _flag_is_true(True) is True
    assert _flag_is_true(False) is False
    assert _flag_is_true(None) is False
    assert _flag_is_true(float("nan")) is False
    assert _volume_first_bar_skippable({"is_live": float("nan"), "volume": 100, "high": 10, "low": 9}) is False

    bars = []
    for i in range(45):
        bars.append(
            {
                "date": f"20260{100 + i}",
                "high": 100.0,
                "low": 90.0,
                "close": 95.0,
                "volume": 1000 + i,
                "is_live": float("nan"),  # 疊臉後歷史列
            }
        )
    # 過去爆大量（不含末日）
    bars[20]["volume"] = 99999
    bars[20]["high"] = 5330.0
    bars[20]["low"] = 4980.0
    bars[20]["date"] = "20261015"
    # 盤中今日量也很大，但不准當爆大量
    bars[-1]["date"] = "20261028"
    bars[-1]["is_live"] = True
    bars[-1]["volume"] = 88888
    bars[-1]["high"] = 5065.0
    bars[-1]["low"] = 4830.0
    bars[-1]["close"] = 5008.0
    st = volume_first_price(bars, lookback=40)
    assert str(st["spike_date"]).replace("-", "")[:8] == "20261015"
    assert st["spike_high"] == 5330.0
    assert st["spike_low"] == 4980.0


def test_ink_close_t_matches_live_xian():
    """墨線表頭要認「現xxxx」，不准只認收而把現價字留在置中位壓低。"""
    import inspect

    import ink_chart_theme as ink

    src = inspect.getsource(ink.vol_masthead)
    assert r"[收現]" in src or "收現" in src
    assert re.fullmatch(r"[收現][\d,.]+", "現5,008")
    assert re.fullmatch(r"[收現][\d,.]+", "收4750")


def test_vol_panel_right_margin_leaves_ytick_gutter():
    """大量區右緣不准拉滿 0.982，否則價／量軸數字出畫布。"""
    import inspect

    import ink_chart_theme as ink

    src = inspect.getsource(ink.align_vol_panel_margins)
    assert "0.928" in src
    assert "target_x1 = 0.982" not in src


def test_lift_ex_div_wired_in_apply_vol():
    import inspect

    import ink_chart_theme as ink

    src = inspect.getsource(ink.apply_vol)
    assert "lift_ex_div_off_press" in src
    assert "lift_ex_div_off_press" in inspect.getsource(ink)


def test_structure_face_rows_clears_nan_is_live():
    from biaoke_chart import _structure_face_rows

    rows = [
        {"date": "20261015", "open": 1, "high": 5330, "low": 4980, "close": 5120, "volume": 5904, "is_live": math.nan},
        {"date": "20261027", "open": 1, "high": 2, "low": 1, "close": 4750, "volume": 100, "is_live": math.nan},
    ]
    out = _structure_face_rows(rows, sid="2383", card=None)
    assert out[0]["is_live"] is False
    assert out[1]["is_live"] is False
