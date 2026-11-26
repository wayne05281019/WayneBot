# -*- coding: utf-8 -*-
"""由尾回推五波（觀察）單元測。"""
from __future__ import annotations

from scripts.biaoke_tail_back_five_wave import analyze_bars, find_new_start_low


def _bars_down_five_then_up() -> list[dict]:
    """合成：五波下跌後今日上漲離低。"""
    # 點位大致：高100 → 低90 → 高95 → 低80 → 高88 → 低70，再漲
    path = []
    # wave scaffolding via piecewise
    segments = [
        (100, 90, 5),
        (90, 95, 4),
        (95, 80, 6),
        (80, 88, 4),
        (88, 70, 6),
    ]
    px = 100.0
    for a, b, n in segments:
        for j in range(n):
            t = (j + 1) / n
            px = a + (b - a) * t
            path.append(px)
    # 前幾日在低附近、今日上漲
    path.extend([71, 70.5, 70.0, 72.0, 74.5])
    bars = []
    for i, c in enumerate(path):
        o = c - 0.3
        h = c + 1.0
        l = c - 1.0
        bars.append(
            {
                "date": f"{20260101 + i}",
                "open": o,
                "high": h,
                "low": l,
                "close": c,
                "volume": 1000.0,
            }
        )
    # 強制今日紅K
    bars[-1]["open"] = bars[-1]["close"] - 2.0
    bars[-1]["low"] = min(bars[-1]["low"], 70.0)
    # 窗內最低鎖在倒數第3根
    bars[-3]["low"] = 69.0
    bars[-3]["close"] = 70.0
    return bars


def test_new_start_on_up_day():
    bars = _bars_down_five_then_up()
    ns = find_new_start_low(bars, lookback_days=8)
    assert ns is not None
    assert ns.kind == "L"
    assert ns.price <= 70.0 + 1e-9


def test_analyze_marks_new_start():
    bars = _bars_down_five_then_up()
    r = analyze_bars(bars)
    assert r.today_up is True
    assert r.ok_new_start is True
    assert r.new_start is not None


def test_down_day_no_new_start():
    bars = _bars_down_five_then_up()
    bars[-1]["open"] = 80.0
    bars[-1]["close"] = 70.0
    r = analyze_bars(bars)
    assert r.ok_new_start is False
    assert "上漲" in r.fail_reason_zh or "非上漲" in r.fail_reason_zh
