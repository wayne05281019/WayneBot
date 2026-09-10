"""海選：重點觀察桶（golden_buy）與型態／下坡過濾。"""
from datetime import datetime, timedelta

import pandas as pd

from screening_engine import (
    ScreeningEngine,
    _golden_buy_ok,
    _is_downtrend_no_touch,
    _pattern_tag,
    _screen_trend_up_ok,
)


def _bars(closes, *, stock_id="2330", vol=12000, last_vol=None):
    rows = []
    start = datetime(2026, 1, 5)
    n = len(closes)
    for i, c in enumerate(closes):
        prev = closes[i - 1] if i else c
        pct = round((c - prev) / prev * 100.0, 2) if prev else 0
        d = (start + timedelta(days=i)).strftime("%Y%m%d")
        v = last_vol if last_vol is not None and i == n - 1 else vol
        rows.append(
            {
                "date": d,
                "stock_id": stock_id,
                "stock_name": "測試",
                "market": "TW",
                "open": c - 0.2,
                "high": c + 0.5,
                "low": c - 0.5,
                "close": c,
                "volume": v,
                "turnover_k": v * c,
                "pct_change": pct,
                "avg_price": c,
                "foreign_net": 0,
                "trust_net": 0,
                "dealer_net": 0,
            }
        )
    return pd.DataFrame(rows)


def test_golden_buy_downtrend_oversold_not_in_bucket():
    """60低超跌公式仍可能成立，但整份海選不收空頭，下坡不進桶。"""
    closes = [70.0] * 45 + [62.0] * 8 + [55.0] * 7 + [48.0] * 5 + [42.0] * 10
    out = ScreeningEngine(db_path=":memory:").execute_all_strategies({"2330": _bars(closes)})
    assert out["golden_buy"] == []
    assert out["leave_zero"] == []
    assert out["select_03"] == []


def test_golden_buy_rejects_uptrend_far_from_zero():
    closes = [40.0] * 50 + [55.0] * 25
    out = ScreeningEngine(db_path=":memory:").execute_all_strategies({"2330": _bars(closes)})
    assert out["golden_buy"] == []


def test_downtrend_excluded_from_layout_buckets():
    slide = [100.0 - i * 0.8 for i in range(70)]
    bounce = slide + [slide[-1] * 1.004, slide[-1] * 1.012]
    out = ScreeningEngine(db_path=":memory:").execute_all_strategies(
        {"2330": _bars(bounce, last_vol=24000)}
    )
    assert out["leave_zero"] == []
    assert out["golden_buy"] == []
    assert out["select_01"] == []
    assert out["select_02"] == []
    assert out["select_03"] == []
    assert out["day_trade"] == []
    assert out["overnight"] == []
    assert out["half_year_high"] == []


def test_uptrend_volume_break_still_enters_select_01():
    # 箱型多頭小突破：不要大到被半年高整檔帶走。
    closes = [100.0] * 80 + [100.0, 100.0, 100.0, 101.0, 102.0]
    out = ScreeningEngine(db_path=":memory:").execute_all_strategies(
        {"2330": _bars(closes, vol=3000, last_vol=8000)}
    )
    assert out["select_01"]
    assert out["half_year_high"] == []


def test_uptrend_near_20_low_can_enter_select_03():
    """多頭排列、月低附近翻紅、離 20 高夠遠：止跌仍可進。"""
    closes = [90.0] * 40 + [100.0] * 25 + [105.0, 99.4, 100.6]
    out = ScreeningEngine(db_path=":memory:").execute_all_strategies({"2330": _bars(closes)})
    assert out["select_03"]


def test_pattern_tag_helpers():
    uphill = {
        "close": 105,
        "ma20": 100,
        "ma60": 95,
        "ma60_prev": 94,
        "ma5_hook_up": True,
        "d20": 8,
        "low20": 90,
        "pct_change": 2,
    }
    assert _pattern_tag(uphill) == "上坡"
    assert not _is_downtrend_no_touch(uphill)
    bear = {
        "close": 80,
        "ma20": 95,
        "ma60": 100,
        "ma60_prev": 101,
        "ma5_hook_up": False,
        "d20": 1,
        "low20": 79,
        "pct_change": 0.5,
    }
    assert _pattern_tag(bear) == "下坡"
    assert _is_downtrend_no_touch(bear)
    assert not _screen_trend_up_ok(bear)
    assert _golden_buy_ok(
        {**bear, "stock_id": "2330", "at_60_low": True, "profit_pct": 0.5, "bias_monthly": -12}
    )
    # 6949 型：均線還停在減資前高價，或中間缺很多根 → 不進重點觀察
    assert not _golden_buy_ok(
        {
            "stock_id": "6949",
            "at_60_low": True,
            "profit_pct": 0.5,
            "bias_monthly": -93.3,
            "close": 67.1,
            "ma20": 1004.1,
        }
    )
    assert not _golden_buy_ok(
        {
            "stock_id": "6949",
            "at_60_low": True,
            "profit_pct": 0.5,
            "bias_monthly": -12,
            "close": 67.1,
            "ma20": 65.0,
            "prev_close": 1490.0,
        }
    )


def test_golden_buy_in_screen_push_order():
    from screening_engine import SCREEN_PUSH_SPECS
    from line_share_format import LINE_BUCKET_META

    keys = [k for k, *_ in SCREEN_PUSH_SPECS]
    assert keys.index("golden_buy") == keys.index("leave_zero") + 1
    specs = {k: hint for k, _, _, hint, *_ in SCREEN_PUSH_SPECS}
    assert "不收空頭" in specs["golden_buy"]
    assert "可收" not in specs["golden_buy"]
    assert "不收空頭" in LINE_BUCKET_META["golden_buy"][1]
