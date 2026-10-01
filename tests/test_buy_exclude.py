# -*- coding: utf-8 -*-
"""買點排除層：鎖跌停／空頭排列／連破低／同根賣點警告。不准改黃金買點公式。"""
from __future__ import annotations

import pandas as pd

from buy_exclude import (
    KIND_EXCLUDE,
    KIND_EXCLUDE_NEXT,
    REASON_BEAR_BREAK_LOW,
    REASON_BEAR_MA,
    REASON_LIMIT_DOWN_LOCK,
    REASON_LIMIT_DOWN_OPEN,
    REASON_SAME_BAR_SELL,
    REASON_SAME_BAR_WARN,
    REASON_THIN_VOL,
    buy_exclude_reasons,
    filter_leave_zero_rows,
    is_bear_break_lows,
    is_bear_ma_stack,
    is_locked_limit_down,
    is_open_locked_limit_down,
    is_same_bar_sell_or_warn,
    is_thin_volume,
    sample_exclude_stats,
    should_exclude_buy,
)


def _ohlc_df(
    closes,
    *,
    opens=None,
    highs=None,
    lows=None,
    start="20260101",
):
    n = len(closes)
    dates = pd.bdate_range(start=start, periods=n).strftime("%Y%m%d").tolist()
    closes = [float(x) for x in closes]
    if opens is None:
        opens = list(closes)
    if highs is None:
        highs = [max(o, c) for o, c in zip(opens, closes)]
    if lows is None:
        lows = [min(o, c) for o, c in zip(opens, closes)]
    return pd.DataFrame(
        {
            "date": dates,
            "open": [float(x) for x in opens],
            "high": [float(x) for x in highs],
            "low": [float(x) for x in lows],
            "close": closes,
            "volume": [1000.0] * n,
        }
    )


def test_locked_limit_down_excludes():
    closes = [100.0] * 5 + [90.0]
    opens = [100.0] * 5 + [90.0]
    df = _ohlc_df(closes, opens=opens, highs=opens, lows=opens)
    assert is_locked_limit_down(df) is True
    assert REASON_LIMIT_DOWN_LOCK in buy_exclude_reasons(df)
    assert should_exclude_buy(df) is True


def test_open_limit_down_still_board():
    closes = [100.0] * 5 + [90.0]
    opens = [100.0] * 5 + [90.0]
    highs = [100.0] * 5 + [90.5]
    lows = [100.0] * 5 + [90.0]
    df = _ohlc_df(closes, opens=opens, highs=highs, lows=lows)
    assert is_open_locked_limit_down(df) is True
    assert REASON_LIMIT_DOWN_OPEN in buy_exclude_reasons(df) or REASON_LIMIT_DOWN_LOCK in buy_exclude_reasons(
        df
    )


def test_emerging_skips_limit_down_only():
    """興櫃無漲跌停：跌停條不套；結構破底仍套。"""
    closes = [100.0] * 5 + [90.0]
    df = _ohlc_df(closes, opens=closes, highs=closes, lows=closes)
    assert is_locked_limit_down(df, emerging=True) is False
    assert REASON_LIMIT_DOWN_LOCK not in buy_exclude_reasons(df, emerging=True)


def test_clean_midrange_not_excluded():
    closes = [80.0 + i * 0.1 for i in range(60)]
    closes += [
        86, 87, 88, 89, 90, 91, 92, 93, 94, 95,
        94, 93, 92, 91, 90, 89.5, 89, 88.5, 88, 87.5,
    ]
    highs = [c + 1.0 for c in closes]
    lows = [c - 1.0 for c in closes]
    df = _ohlc_df(closes, highs=highs, lows=lows)
    assert is_bear_break_lows(df) is False
    assert is_locked_limit_down(df) is False
    assert buy_exclude_reasons(df) == []
    assert should_exclude_buy(df) is False


def test_flat_near_60_low_not_warn_only():
    closes = [50.0] * 80
    df = _ohlc_df(closes)
    hit, _why = is_same_bar_sell_or_warn(df)
    assert hit is False


def test_same_bar_sell_via_hl_temp_columns():
    closes = [80.0 + i * 0.2 for i in range(25)]
    df = _ohlc_df(closes)
    df["高低"] = ["No"] * (len(df) - 1) + ["20高"]
    df["升降"] = ["升溫"] * (len(df) - 1) + ["升溫"]
    hit, why = is_same_bar_sell_or_warn(df)
    assert hit is True
    assert why == REASON_SAME_BAR_SELL


def test_sample_exclude_stats_shape():
    head = [150.0 - i * 0.5 for i in range(40)]
    base = [120.0] * 40 + [118.0, 117.0, 116.0, 115.0, 114.0]
    closes = head + base + [112.0, 110.0, 108.0]
    lows = [c - 0.3 for c in closes]
    lows[-1], lows[-2], lows[-3] = 107.0, 109.0, 111.0
    closes[-1], closes[-2], closes[-3] = 107.5, 109.5, 111.5
    highs = [max(c, l) + 0.5 for c, l in zip(closes, lows)]
    frames = {
        "A": _ohlc_df(closes, lows=lows, highs=highs),
        "B": _ohlc_df(
            [80.0 + i * 0.1 for i in range(60)]
            + [86, 87, 88, 89, 90, 91, 92, 93, 94, 95, 94, 93, 92, 91, 90, 89.5, 89, 88.5, 88, 87.5],
            highs=[c + 1 for c in (
                [80.0 + i * 0.1 for i in range(60)]
                + [86, 87, 88, 89, 90, 91, 92, 93, 94, 95, 94, 93, 92, 91, 90, 89.5, 89, 88.5, 88, 87.5]
            )],
            lows=[c - 1 for c in (
                [80.0 + i * 0.1 for i in range(60)]
                + [86, 87, 88, 89, 90, 91, 92, 93, 94, 95, 94, 93, 92, 91, 90, 89.5, 89, 88.5, 88, 87.5]
            )],
        ),
    }
    st = sample_exclude_stats(frames, leave_zero_sids=["A", "B"])
    assert st["kind"] == KIND_EXCLUDE
    assert st["next_kind"] == KIND_EXCLUDE_NEXT
    assert st["n_leave_zero"] == 2
    assert st["n_excluded"] >= 1
    assert isinstance(st["by_reason"], dict)


def test_screening_engine_imports_exclude_hook():
    import inspect
    import screening_engine as se

    src = inspect.getsource(se.ScreeningEngine._screen_leave_zero_from_profit)
    assert "should_exclude_buy" in src
    assert "buy_exclude" in src


def test_thin_volume_excludes():
    # 前 20 日量 1000，今日量 400 → <0.5x 均量
    closes = [80.0 + i * 0.1 for i in range(25)]
    df = _ohlc_df(closes)
    df["volume"] = [1000.0] * 24 + [400.0]
    assert is_thin_volume(df) is True
    assert REASON_THIN_VOL in buy_exclude_reasons(df)


def test_thin_volume_ok_when_at_least_half_avg():
    closes = [80.0 + i * 0.1 for i in range(25)]
    df = _ohlc_df(closes)
    df["volume"] = [1000.0] * 24 + [500.0]
    assert is_thin_volume(df, mult=0.5) is False
    assert REASON_THIN_VOL not in buy_exclude_reasons(df)


def test_kind_is_v2():
    assert KIND_EXCLUDE == "buy_exclude_v2"
    assert "v3" in KIND_EXCLUDE_NEXT


def test_paint_indices_drop_excluded_bars():
    from buy_exclude import paint_leave_zero_indices

    head = [150.0 - i * 0.5 for i in range(40)]
    base = [120.0] * 40 + [118.0, 117.0, 116.0, 115.0, 114.0]
    closes = head + base + [112.0, 110.0, 108.0]
    lows = [c - 0.3 for c in closes]
    lows[-1], lows[-2], lows[-3] = 107.0, 109.0, 111.0
    closes[-1], closes[-2], closes[-3] = 107.5, 109.5, 111.5
    highs = [max(c, l) + 0.5 for c, l in zip(closes, lows)]
    df = _ohlc_df(closes, lows=lows, highs=highs)
    # 結構破底日不准進畫標
    assert should_exclude_buy(df) is True
    assert (len(df) - 1) not in set(paint_leave_zero_indices(df))


def test_nav_trade_marks_uses_paint_exclude():
    import inspect
    import wayne_navigator as wn

    src = inspect.getsource(wn._nav_trade_marks)
    assert "paint_leave_zero_indices" in src
    assert "should_exclude_buy" in src


def test_winrate_scan_mentions_exclude():
    import inspect
    import winrate_buypoint as wr

    src = inspect.getsource(wr.scan_winrate_leave_zero)
    assert "buy_exclude" in src or "filter_leave_zero_rows" in src

