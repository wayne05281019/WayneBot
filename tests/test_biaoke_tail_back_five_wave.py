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


def test_start_prefers_near_structure_not_older_abs_high():
    """台光電型：更早絕對高 6470 不准當起；本段起＝較近的 6325。"""
    bars: list[dict] = []
    # 舊段絕對高（應被跳過）
    path_px = (
        [6400, 6470, 6200, 5800, 5200, 4800, 4635]  # 舊下跌
        + [5000, 5500, 6000, 6200, 6325]  # 拉回本段起
        + [6000, 5600, 5200, 4930]  # 1
        + [5100, 5300, 5485]  # 2
        + [5000, 4500, 4000, 3690]  # 3
        + [4000, 4300, 4565]  # 4
        + [4000, 3500, 3000, 2560]  # 5
        + [2700, 2900, 3100, 3300]  # 離低上漲
    )
    for i, c in enumerate(path_px):
        bars.append(
            {
                "date": f"{20260101 + i}",
                "open": c - 20,
                "high": c + 30,
                "low": c - 40,
                "close": c,
                "volume": 2000.0,
            }
        )
    # 釘住關鍵高低，對齊教法點位
    def _pin(i: int, *, high: float | None = None, low: float | None = None) -> None:
        if high is not None:
            bars[i]["high"] = high
            bars[i]["close"] = min(bars[i]["close"], high)
        if low is not None:
            bars[i]["low"] = low
            bars[i]["close"] = max(bars[i]["close"], low)

    # 找合成路徑上的近似 index
    for i, b in enumerate(bars):
        if abs(b["close"] - 6470) < 1:
            _pin(i, high=6470)
        if abs(b["close"] - 6325) < 1:
            _pin(i, high=6325)
        if abs(b["close"] - 2560) < 1:
            _pin(i, low=2560)
    bars[-1]["open"] = bars[-1]["close"] - 80
    bars[-1]["high"] = bars[-1]["close"] + 20
    r = analyze_bars(bars)
    assert r.ok_five is True
    assert r.five_points
    assert abs(r.five_points[0].price - 6325) < 1.0
    assert r.five_points[0].price < 6400  # 不准吃到 6470
    assert abs(r.five_points[-1].price - 2560) < 1.0
