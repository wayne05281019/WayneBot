"""海選：黃金買點桶與型態／下坡過濾。"""
from datetime import datetime, timedelta

import pandas as pd

from screening_engine import (
    ScreeningEngine,
    _golden_buy_ok,
    _is_downtrend_no_touch,
    _pattern_tag,
)


def _bars(closes, *, stock_id="2330", vol=12000):
    rows = []
    start = datetime(2026, 1, 5)
    for i, c in enumerate(closes):
        prev = closes[i - 1] if i else c
        pct = round((c - prev) / prev * 100.0, 2) if prev else 0
        d = (start + timedelta(days=i)).strftime("%Y%m%d")
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
                "volume": vol,
                "turnover_k": vol * c,
                "pct_change": pct,
                "avg_price": c,
                "foreign_net": 0,
                "trust_net": 0,
                "dealer_net": 0,
            }
        )
    return pd.DataFrame(rows)


def test_golden_buy_bucket_matches_decision_card_fields():
    closes = [70.0] * 45 + [62.0] * 8 + [55.0] * 7 + [48.0] * 5 + [42.0] * 10
    out = ScreeningEngine(db_path=":memory:").execute_all_strategies({"2330": _bars(closes)})
    assert out["golden_buy"], "應進黃金買點桶"
    item = out["golden_buy"][0]
    assert item.get("at_60_low") is True
    assert -1.5 <= float(item["profit_pct"]) <= 2.5
    assert float(item["bias_monthly"]) < -10.0
    assert item.get("golden_buy") is True


def test_golden_buy_rejects_uptrend_far_from_zero():
    closes = [40.0] * 50 + [55.0] * 25
    out = ScreeningEngine(db_path=":memory:").execute_all_strategies({"2330": _bars(closes)})
    assert out["golden_buy"] == []


def test_downtrend_excluded_from_layout_buckets():
    slide = [100.0 - i * 0.8 for i in range(70)]
    bounce = slide + [slide[-1] * 1.004, slide[-1] * 1.012]
    out = ScreeningEngine(db_path=":memory:").execute_all_strategies({"2330": _bars(bounce)})
    assert out["leave_zero"] == []
    assert out["golden_buy"] == []
    assert out["select_01"] == []


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
    assert _golden_buy_ok(
        {**bear, "stock_id": "2330", "at_60_low": True, "profit_pct": 0.5, "bias_monthly": -12}
    )


def test_golden_buy_in_screen_push_order():
    from screening_engine import SCREEN_PUSH_SPECS

    keys = [k for k, *_ in SCREEN_PUSH_SPECS]
    assert keys.index("golden_buy") == keys.index("leave_zero") + 1
