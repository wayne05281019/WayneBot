# -*- coding: utf-8 -*-
"""依使用者傳過的高低卡範本列（OCR 校準）— 海選驗收用。"""
import os

import pytest

from decision_card_signals import (
    alert_tag,
    card_regime_label,
    card_row_leave_zero,
    compute_card_temperature,
    leave_zero_screen_ok,
    parse_profit_display,
    profit_left_zero_highlight,
    profit_pct_series,
)


def test_parse_profit_display():
    assert parse_profit_display("0.0%") == 0.0
    assert parse_profit_display("10.0%") == 10.0
    assert parse_profit_display("No") is None


def test_template_2420_8_28_not_leave_zero():
    """範本卡：獲利已 10.0% — 不是起漲（你回饋的誤收型）。"""
    ok, _ = leave_zero_screen_ok(9.5, 10.0)
    assert not ok


def test_template_profit_green_cell():
    """色票範本：昨 0.0% → 今 0.9% 實綠。"""
    assert profit_left_zero_highlight(0.0, 0.9)
    hit, tag = card_row_leave_zero(0.0, 0.9)
    assert hit and "實綠" in tag
    ok, _ = leave_zero_screen_ok(0.0, 0.9)
    assert ok


def test_template_not_green_after_step():
    """色票範本：昨 0.9% → 今 1.5% 白底，不算剛離零。"""
    assert not profit_left_zero_highlight(0.9, 1.5)
    hit, _ = card_row_leave_zero(0.9, 1.5)
    assert not hit


def test_profit_pct_series_per_day_not_global():
    """9925 範本：盤整期應出現多個 0.0% 列（逐日 cal60 + 未回推收盤）。"""
    db = os.path.join(os.path.dirname(__file__), "..", "data", "wayne_market.db")
    if not os.path.isfile(db):
        pytest.skip("no market db")
    from wayne_navigator import NavigatorEngine

    tbl = NavigatorEngine(db).get_decision_card("9925")["table"]
    zeros = sum(1 for _, r in tbl.iterrows() if float(r["profit_pct"]) <= 0.05)
    assert zeros >= 6, f"expected many 0.0% rows, got {zeros}"


def test_template_2530_leave_zero_row():
    """華建範本：8/31 獲利 0.0% → 起漲故事起點。"""
    db = os.path.join(os.path.dirname(__file__), "..", "data", "wayne_market.db")
    if not os.path.isfile(db):
        pytest.skip("no market db")
    from wayne_navigator import NavigatorEngine

    card = NavigatorEngine(db).get_decision_card("2530")
    tbl = card["table"]
    row = tbl[tbl["date"].astype(str) == "20260831"]
    assert not row.empty
    assert float(row.iloc[0]["profit_pct"]) <= 0.05


def test_template_2633_8_11_profit_zero():
    """高鐵範本：8/11 貼 20 日低仍顯示 0.0%（地板取 max(60曆日低,20日低)）。"""
    db = os.path.join(os.path.dirname(__file__), "..", "data", "wayne_market.db")
    if not os.path.isfile(db):
        pytest.skip("no market db")
    from wayne_navigator import NavigatorEngine

    tbl = NavigatorEngine(db).get_decision_card("2633")["table"]
    row = tbl[tbl["date"].astype(str) == "20260811"]
    assert not row.empty
    assert float(row.iloc[0]["profit_pct"]) <= 0.05


def test_profit_floor_max_cal60_and_l20():
    import sqlite3

    import pandas as pd
    from decision_card_signals import profit_floor_at

    db = os.path.join(os.path.dirname(__file__), "..", "data", "wayne_market.db")
    if not os.path.isfile(db):
        pytest.skip("no market db")
    conn = sqlite3.connect(db)
    df = pd.read_sql_query(
        "SELECT date, close FROM daily_quotes WHERE stock_id='2633' ORDER BY date", conn
    )
    conn.close()
    idx = df.index[df["date"].astype(str) == "20260811"][0]
    floor = profit_floor_at(df, idx)
    assert floor == 25.7


def test_alert_tag_rsv_no_false_k20_high_on_bias_only():
    """南亞型：月乖離高但 RSV 未過熱 → 不標 K20高。"""
    assert alert_tag(100.0, low60=90, high20=102, low20=95, bias_monthly=4.5, rsv=55.0) == "No"
    assert alert_tag(101.5, low60=90, high20=102, low20=95, bias_monthly=2.0, rsv=72.0) == "K20高"


def test_template_regime_narrow_range_is_consolidation():
    """2633/2530 範本：60日區間過小時標整理格局，不是多頭。"""
    assert card_regime_label(26.25, 26.0, 25.8, space_60=7) == "整理格局"
    assert card_regime_label(19.75, 19.4, 19.0, space_60=14) == "整理格局"


def test_template_temperature_cold_stock_scale():
    """9925 範本：冷股溫度應在個位數～十幾度，不是 50°C+。"""
    t = compute_card_temperature(39.3, 40.15, 39.3, -0.2, high60=41.5, low60=39.3)
    assert t < 15.0
    t_hot = compute_card_temperature(40.05, 40.15, 39.3, 0.5, high60=41.5, low60=39.3)
    assert t_hot < 20.0
