# -*- coding: utf-8 -*-
"""6669 大額除權後：獲利欄不得假顯 0%；2383 29.1% 公式仍過。"""
from __future__ import annotations

import sqlite3

import pytest

from decision_card_signals import format_profit_pct
from wayne_navigator import NavigatorEngine, frame_for_cal60_profit


@pytest.mark.production_db
def test_2383_formula_5295_vs_4100_still_29_1():
    pct = (5295.0 - 4100.0) / 4100.0 * 100.0
    assert abs(pct - 29.1) < 0.05
    assert format_profit_pct(pct) == "29.1%"


@pytest.mark.production_db
def test_6669_profit_not_fake_zero_after_split():
    """20260902 ×0.3353 後：獲利跟還原收盤同一套，不准表上 0.5% 對上方距60低 +36%。"""
    from config import get_db_path

    db = get_db_path()
    conn = sqlite3.connect(db)
    n = conn.execute(
        "SELECT COUNT(*) FROM daily_quotes WHERE stock_id='6669' AND date='20260924'"
    ).fetchone()[0]
    conn.close()
    if not n:
        pytest.skip("no 6669 20260924 quotes")

    nav = NavigatorEngine(db)
    card = nav.get_decision_card("6669", as_of="20260924", merge_live=False)
    assert float(card["close"]) == 2115.0
    gain = float(card["gain_pct"])
    cal60 = float(card["cal60_low"])
    # 未還原假地板 2105 → 0.5%；還原後 cal60 應明顯低於現價
    assert gain > 5.0, f"fake near-zero profit after split: {gain}"
    assert abs(gain - round((2115.0 / cal60 - 1.0) * 100.0, 1)) < 0.05
    # 獲利＝60曆日；距60根低＝60根 — 可以不同，但都不能是未還原假 0.5
    dist = float(card["dist_l60"])
    assert dist > 5.0
    assert abs(gain - 0.5) > 0.05


@pytest.mark.production_db
def test_6669_sep1_to_sep2_no_profit_cliff():
    """9/1→9/2 不是 60 曆日窗滾掉舊低，是除權面額；還原後獲利應連續。"""
    from config import get_db_path

    db = get_db_path()
    conn = sqlite3.connect(db)
    rows = conn.execute(
        "SELECT date, close FROM daily_quotes WHERE stock_id='6669' "
        "AND date IN ('20260901','20260902')"
    ).fetchall()
    conn.close()
    if len(rows) < 2:
        pytest.skip("no 6669 sep quotes")

    nav = NavigatorEngine(db)
    c1 = nav.get_decision_card("6669", as_of="20260901", merge_live=False)
    c2 = nav.get_decision_card("6669", as_of="20260902", merge_live=False)
    g1, g2 = float(c1["gain_pct"]), float(c2["gain_pct"])
    assert g1 > 50.0
    assert g2 > 50.0, f"split-day fake zero: {g2}"
    assert abs(g1 - g2) < 5.0


@pytest.mark.production_db
def test_frame_for_cal60_profit_matches_card_on_6669():
    import pandas as pd
    from config import get_db_path
    from decision_card_signals import cal60_profit_bundle

    db = get_db_path()
    conn = sqlite3.connect(db)
    df = pd.read_sql_query(
        "SELECT stock_id, date, open, high, low, close, volume FROM daily_quotes "
        "WHERE stock_id='6669' AND date<='20260924' ORDER BY date",
        conn,
    )
    conn.close()
    if df.empty:
        pytest.skip("no 6669")
    profit_df = frame_for_cal60_profit(df, db)
    _floors, pct = cal60_profit_bundle(profit_df)
    card = NavigatorEngine(db).get_decision_card("6669", as_of="20260924", merge_live=False)
    assert abs(float(pct.iloc[-1]) - float(card["gain_pct"])) < 0.05
