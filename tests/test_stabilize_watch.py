# -*- coding: utf-8 -*-
"""止穩觀察標：規則可重算、永遠不是買訊。"""
from __future__ import annotations

import inspect

import pandas as pd

from stabilize_watch import (
    HOLD_N,
    RULE_ID,
    _l60_first_touch_indices,
    frame_from_bars,
    is_buy_entry_path,
    stabilize_bar_indices,
    stabilize_detail,
    stabilize_fires_today,
)


def _ohlc_stabilize(*, extra_hold: int = 4) -> pd.DataFrame:
    """60 根橫盤偏高 → 單日落底首觸 → 再走 hold 根未破底站上。"""
    rows = []
    # 0..59：高位橫盤（低約 100），不會連觸新低
    for i in range(60):
        rows.append((100.0 + (i % 3) * 0.2, 101.5, 99.5, 100.5))
    # 60：跌一段但尚未是最終底
    rows.append((99.0, 99.5, 97.0, 97.5))
    # 61：反彈離開 60 低（was_60l → False）
    rows.append((98.0, 99.0, 97.2, 98.5))
    # 62：明確新低＝60 低首觸 T0
    t0_low = 94.0
    rows.append((96.0, 96.5, t0_low, 95.0))
    # 之後 hold：低不破 t0_low、收在上方
    for j in range(extra_hold):
        rows.append((95.5 + j * 0.3, 97.0 + j * 0.3, t0_low + 0.4, 96.0 + j * 0.3))
    n = len(rows)
    dates = []
    y, m, d = 2025, 1, 1
    for _ in range(n):
        dates.append(f"{y}{m:02d}{d:02d}")
        d += 1
        if d > 28:
            d = 1
            m += 1
            if m > 12:
                m = 1
                y += 1
    opens, highs, lows, closes = zip(*rows)
    return pd.DataFrame(
        {
            "date": dates,
            "open": list(opens),
            "high": list(highs),
            "low": list(lows),
            "close": list(closes),
            "volume": [1000.0] * n,
            "is_halt": [False] * n,
        }
    )


def test_l60_first_touch_and_stabilize_fires():
    df = _ohlc_stabilize(extra_hold=4)
    touches = _l60_first_touch_indices(df)
    assert 62 in touches
    assert stabilize_fires_today(df, hold_n=HOLD_N)
    idxs = stabilize_bar_indices(df)
    assert idxs == [len(df) - 1]
    detail = stabilize_detail(df)
    assert detail is not None
    assert detail["buy_signal"] is False
    assert detail["rule"] == RULE_ID
    assert detail["touch_i"] == 62
    assert detail["bars_held"] >= HOLD_N


def test_broke_low_does_not_fire():
    df = _ohlc_stabilize(extra_hold=4)
    tagged = float(df["low"].iloc[62])
    df.loc[df.index[-1], "low"] = tagged - 1.0
    df.loc[df.index[-1], "close"] = tagged - 0.5
    assert not stabilize_fires_today(df)


def test_too_soon_after_touch_no_fire():
    df = _ohlc_stabilize(extra_hold=1)  # T0 後只 1 根 < HOLD_N=3
    assert len(df) - 1 - 62 < HOLD_N
    assert not stabilize_fires_today(df)


def test_paint_path_not_buy_entry():
    assert is_buy_entry_path("_paint_stabilize_marks") is False
    assert is_buy_entry_path("paint_buy_entry_indices") is True
    assert is_buy_entry_path("_nav_trade_marks") is True
    import wayne_navigator as wn

    src = inspect.getsource(wn._paint_stabilize_marks)
    assert "paint_buy_entry" not in src
    assert "leave_zero" not in src
    overlay = inspect.getsource(wn.overlay_nav_marks_on_zone)
    assert "_paint_stabilize_marks" in overlay
    marks = inspect.getsource(wn._nav_trade_marks)
    assert "stabilize" not in marks


def test_frame_from_bars():
    bars = [
        {
            "date": "20260101",
            "open": 1,
            "high": 2,
            "low": 0.5,
            "close": 1.5,
            "volume": 10,
        }
    ]
    df = frame_from_bars(bars)
    assert len(df) == 1
    assert float(df["close"].iloc[0]) == 1.5
