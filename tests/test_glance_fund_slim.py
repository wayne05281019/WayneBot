# -*- coding: utf-8 -*-
"""介紹卡基本面 slim＝一瞥；dense＝改版前長表。"""
from __future__ import annotations

import sqlite3

from fundamentals import ensure_fundamentals_tables, glance_fundamentals_plain
from wayne_db import ensure_core_schema, init_database


def _seed(db: str) -> None:
    init_database(db)
    ensure_core_schema(db)
    ensure_fundamentals_tables(db)
    con = sqlite3.connect(db)
    try:
        con.execute(
            "INSERT OR REPLACE INTO stock_universe "
            "(stock_id, stock_name, market_type, is_active, asset_type, updated_at) "
            "VALUES ('6416','瑞祺電通','TW',1,'STOCK','t')"
        )
        for mm, rev, mom, yoy in (
            ("202607", 451310, -32.4, 73.5),
            ("202608", 548128, 21.5, 109.3),
            ("202609", 707131, 29.0, 59.2),
            ("202610", 567160, -19.8, 126.8),
        ):
            con.execute(
                "INSERT OR REPLACE INTO monthly_revenue "
                "(stock_id, yyyymm, stock_name, market, industry, revenue, "
                "revenue_prev_month, revenue_prev_year, mom_pct, yoy_pct, "
                "ytd_revenue, ytd_prev_year, ytd_yoy_pct, published_roc, updated_at) "
                "VALUES ('6416',?,?, 'TW', '', ?, 0, 0, ?, ?, 0, 0, 0, '', 't')",
                (mm, "瑞祺電通", rev, mom, yoy),
            )
        con.execute(
            "INSERT OR REPLACE INTO quarterly_income "
            "(stock_id, year, season, stock_name, market, revenue, cogs, "
            "gross_profit, gross_margin_pct, operating_income, non_operating, "
            "net_income, eps, published_roc, updated_at) "
            "VALUES ('6416',2026,3,'瑞祺電通','TW',4097464,0,1010670,24.67,"
            "503785,24265,399116,5.40,'','t')"
        )
        con.execute(
            "INSERT OR REPLACE INTO daily_valuation "
            "(stock_id, date, pe, pb, dividend_yield, source, updated_at) "
            "VALUES ('6416','20261119',16.86,2.22,2.45,'twse_bwibbu','t')"
        )
        con.commit()
    finally:
        con.close()


def test_slim_keeps_glance_drops_dense_margins(tmp_path):
    db = str(tmp_path / "slim.db")
    _seed(db)
    dense = glance_fundamentals_plain("6416", db, skip_ensure=True, dense=True)
    slim = glance_fundamentals_plain("6416", db, skip_ensure=True, dense=False)
    d_labs = [a for a, _ in dense]
    s_labs = [a for a, _ in slim]
    assert d_labs.count("7月營收") + sum(1 for x in d_labs if x.endswith("月營收")) >= 4
    assert sum(1 for x in s_labs if x.endswith("月營收")) == 2
    assert "毛利" in d_labs and "營益率" in d_labs and "淨利率" in d_labs
    # slim 對齊價值總覽：毛利率＋營益率＋EPS；仍無毛利金額／淨利率（長表走價值三圖）
    assert "毛利" not in s_labs and "淨利率" not in s_labs
    assert "毛利率" in s_labs and "營益率" in s_labs and "EPS" in s_labs and "估值" in s_labs
    assert "價值" in s_labs and "價值" not in d_labs
    tip = dict(slim).get("價值") or ""
    assert "打橫" in tip
