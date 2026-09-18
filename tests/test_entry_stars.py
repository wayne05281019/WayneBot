# -*- coding: utf-8 -*-
"""海選切入五角星：滿五星＝黃金買點且高低卡欄對齊。"""
from __future__ import annotations

from screening_engine import (
    ENTRY_STAR_N,
    _stock_card_html,
    entry_star_count,
    entry_star_glyphs,
    stamp_entry_stars,
)


def test_glyphs_always_five_and_three_filled():
    assert ENTRY_STAR_N == 5
    assert entry_star_glyphs(3) == "★★★☆☆"
    assert entry_star_glyphs(5) == "★★★★★"
    assert entry_star_glyphs(0) == "☆☆☆☆☆"
    assert entry_star_glyphs(9) == "★★★★★"
    assert entry_star_glyphs(-1) == "☆☆☆☆☆"


def test_five_stars_only_leave_zero_aligned():
    must = {
        "stock_id": "2330",
        "profit_pct": 1.2,
        "is_s_tier": True,
        "sector_inflow": True,
        "leave_l20": True,
    }
    assert entry_star_count(must, bucket_key="leave_zero") == 5
    chased = dict(must, chase_warning=True)
    assert entry_star_count(chased, bucket_key="leave_zero") <= 4
    assert entry_star_count(chased, bucket_key="leave_zero") < 5
    watch = dict(must)
    assert entry_star_count(watch, bucket_key="golden_buy") <= 4
    late = dict(must, profit_pct=12.0)
    assert entry_star_count(late, bucket_key="leave_zero") <= 4
    beta = dict(must, beta_downweighted=True)
    assert entry_star_count(beta, bucket_key="leave_zero") <= 4


def test_leave_zero_without_s_or_inflow_is_four():
    n = entry_star_count({"profit_pct": 0.8}, bucket_key="leave_zero")
    assert n == 4
    assert entry_star_glyphs(n) == "★★★★☆"


def test_chase_week_volume_not_a_buy():
    n = entry_star_count(
        {"profit_pct": 20.0, "chase_warning": True, "q60r": 3.0},
        bucket_key="select_01",
    )
    assert n <= 1


def test_stock_card_shows_mixed_stars():
    html = _stock_card_html(
        {
            "stock_id": "2330",
            "stock_name": "台積電",
            "close": 100.0,
            "profit_pct": 1.2,
            "is_s_tier": True,
            "sector_inflow": True,
        },
        1,
        bucket_label="黃金買點",
    )
    assert "★★★★★" in html
    assert "不同步就直接減碼" in html
    assert "切入" in html and "100" in html
    lines = [
        ln
        for ln in html.replace("<blockquote>", "").replace("</blockquote>", "").split("\n")
        if ln.strip()
    ]
    assert "2330" in lines[0] and "台積電" in lines[0]
    assert "★" not in lines[0] and "☆" not in lines[0]
    assert lines[1] == "★★★★★"
    watch = _stock_card_html(
        {"stock_id": "1101", "stock_name": "台泥", "close": 50.2, "golden_buy": True},
        2,
        bucket_label="重點觀察",
    )
    assert "★★★★★" not in watch
    assert "不同步就直接減碼" not in watch


def test_entry_watch_merged_one_list_two_tags():
    from screening_engine import format_screening_payload, merge_entry_stage_rows

    buy = {
        "stock_id": "2330",
        "stock_name": "台積電",
        "close": 100.0,
        "profit_pct": 1.2,
        "is_s_tier": True,
        "sector_inflow": True,
        "leave_l20": True,
    }
    watch = {
        "stock_id": "1101",
        "stock_name": "台泥",
        "close": 50.2,
        "golden_buy": True,
        "profit_pct": 0.0,
    }
    rows = merge_entry_stage_rows(
        {"leave_zero": [buy], "golden_buy": [watch, dict(buy)]},
        buy_cap=8,
        watch_cap=8,
    )
    assert [r["stock_id"] for r in rows] == ["2330", "1101"]
    assert rows[0]["entry_stage_label"] == "買點"
    assert rows[1]["entry_stage_label"] == "還在零"
    payload = format_screening_payload(
        {"leave_zero": [buy], "golden_buy": [watch], "select_01": []},
        "20260904",
        morning=True,
    )
    keys = [p.get("mark_key") for p in payload]
    assert keys == ["leave_zero"]
    html = payload[0]["html"]
    assert "＝＝重點觀察" not in html
    assert "買點" in html and "還在零" in html
    assert "不同步就直接減碼" in html
    assert html.index("台積電") < html.index("台泥")
    assert "減碼" not in html.split("台泥", 1)[1]


def test_stamp_sets_buy_star_only_for_five():
    rows = stamp_entry_stars(
        [
            {"stock_id": "1", "profit_pct": 1.0, "is_s_tier": True},
            {"stock_id": "2", "profit_pct": 1.0},
        ],
        "leave_zero",
    )
    assert rows[0]["entry_stars"] == 5 and rows[0]["buy_star"] is True
    assert rows[1]["entry_stars"] == 4 and rows[1]["buy_star"] is False


def test_nav_trade_marks_buy_up_sell_down_from_card():
    import pandas as pd
    from wayne_navigator import _NAV_TRADE_BUY, _NAV_TRADE_SELL, _nav_trade_marks

    work = pd.DataFrame(
        {
            "close": [10.0, 11.0],
            "high": [10.5, 11.2],
            "low": [9.8, 10.8],
            "ma20": [10.0, 10.5],
        }
    )
    b, s = _nav_trade_marks(work, {"relative_buy_kind": "just_left"})
    assert b == 1 and s is None
    b, s = _nav_trade_marks(work, {"sell_action": "直接減碼"})
    assert s == 1 and b is None
    b, s = _nav_trade_marks(
        work, {"relative_buy_kind": "just_left", "entry_stage": "watch"}
    )
    assert b is None and s is None
    b, s = _nav_trade_marks(work, None)
    assert b is None and s is None
    assert _NAV_TRADE_BUY.startswith("#15")
    assert _NAV_TRADE_SELL.startswith("#E6")
