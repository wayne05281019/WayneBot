# -*- coding: utf-8 -*-
"""最近重點標的樣張：營收單位／季EPS拆累計／前方壓力優先。"""
from __future__ import annotations

from scripts.paint_focus_target_sample import (
    _dodge_right_ys,
    _eps_singles_cum,
    _rev_yi,
    drop_measure_points,
    drop_measure_triangle_verts,
    pick_forward_pressure_zone,
)


def test_drop_measure_triangle_lin_style():
    """林款倒三角：左高→右同高→右低；點差＝高−低。"""
    verts = drop_measure_triangle_verts(10.0, 284.0, 40.0, 146.0)
    assert verts == [(10.0, 284.0), (40.0, 284.0), (40.0, 146.0)]
    assert drop_measure_points(284.0, 146.0) == 138.0
    assert drop_measure_triangle_verts(40.0, 284.0, 10.0, 146.0) is None
    assert drop_measure_points(100.0, 100.0) is None


def test_paint_source_has_lin_green_drop_measure():
    import inspect

    from scripts import paint_focus_target_sample as m

    src = inspect.getsource(m.paint)
    assert "跌幅量尺" in src
    assert "drop_measure_triangle_verts" in src
    assert 'edgecolor="none"' in src or "edgecolor='none'" in src
    # 點差不准寫進三角蓋K；只准進圖例字串
    assert "drop_legend" in src
    # 不准再畫大菱形／圖內「新起漲」浮字蓋K
    assert 'marker="D"' not in src
    assert 'annotate(\n                "新起漲"' not in src
    assert '"新起漲"' not in src or "黃線＝新起漲" in src
    # 浪序圓圈；量標掛量圖上方縫隙，不准進柱區
    assert 'boxstyle="circle,pad=0.28"' in src
    assert "transform=axv.transAxes" in src
    assert "1.12" in src
    assert "壓力來源量（橘）" in src
    assert '"5"' in src  # 終點也標⑤圈


def test_rev_yi_thousand_to_yi():
    # 庫內千元 → 億（與介紹卡／100000 同）
    assert _rev_yi(24472758.0) == "244.73"
    assert _rev_yi(100000) == "1.00"


def test_right_tags_dodge_close_vs_zone_edge():
    # 收 3660 貼壓下緣 3690 → 顯示 Y 必須拉開
    ys = _dodge_right_ys([4565.0, 3920.0, 3690.0, 3660.0], y_lo=2500.0, y_hi=6500.0)
    assert len(ys) == 4
    # 高→低顯示序仍對應原 index 價序；相鄰顯示間距夠
    ordered = sorted(ys, reverse=True)
    gaps = [ordered[i] - ordered[i + 1] for i in range(3)]
    assert min(gaps) >= (6500.0 - 2500.0) * 0.055 - 1e-6
    assert abs(ys[3] - ys[2]) >= (6500.0 - 2500.0) * 0.055 - 1e-6


def test_eps_singles_from_cumulative():
    singles, cum = _eps_singles_cum(
        [(2026, 1, 14.9), (2026, 2, 42.46), (2026, 3, 82.92)], 2026
    )
    assert abs(singles[1] - 14.9) < 1e-9
    assert abs(singles[2] - 27.56) < 1e-6
    assert abs(singles[3] - 40.46) < 1e-6
    assert abs(cum - 82.92) < 1e-9


def test_forward_zone_prefers_above_close():
    # 現價 100；區內大量 overlapping；真正上方次大量 low=110
    bars = []
    for i in range(40):
        ymd = f"202602{i + 1:02d}" if i < 28 else f"202603{i - 27:02d}"
        bars.append(
            {
                "date": ymd,
                "open": 100.0,
                "high": 105.0,
                "low": 95.0,
                "close": 100.0,
                "volume": 1000.0,
            }
        )
    # 重疊區：量大但含現價
    bars[10] = {
        "date": "20260211",
        "open": 98.0,
        "high": 108.0,
        "low": 92.0,
        "close": 100.0,
        "volume": 9000.0,
    }
    # 前方區：下緣 > 收
    bars[20] = {
        "date": "20260221",
        "open": 112.0,
        "high": 120.0,
        "low": 110.0,
        "close": 115.0,
        "volume": 8000.0,
    }
    bars[-1]["close"] = 100.0
    bars[-1]["high"] = 102.0
    bars[-1]["low"] = 98.0
    z = pick_forward_pressure_zone(bars, close=100.0)
    assert z is not None
    assert z.get("zone_role") == "forward"
    assert float(z["low"]) > 100.0
    assert str(z.get("date")) == "20260221"
