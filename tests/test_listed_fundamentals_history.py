# -*- coding: utf-8 -*-
"""上市櫃月／季歷史：MOPS 缺口列與季節窗。"""
import sqlite3

from fundamentals import (
    ensure_fundamentals_tables,
    listed_income_gap_seasons,
    listed_income_seasons,
    listed_monthly_gap_months,
    parse_mops_income_html,
)
from wayne_db import ensure_core_schema


def test_listed_income_seasons_covers_value_window():
    seasons = listed_income_seasons("20261121", n=12)
    assert len(seasons) == 12
    assert seasons[0] == (2026, 3)  # 11 月已過 Q3 申報門檻
    assert (2025, 4) in seasons
    assert (2024, 4) in seasons


def test_listed_income_gap_and_monthly_gap(tmp_path):
    db = str(tmp_path / "hist.db")
    ensure_core_schema(db)
    ensure_fundamentals_tables(db)
    con = sqlite3.connect(db)
    try:
        # 只有最新季 TW 夠量、TWO 不夠 → 仍算缺口
        for i in range(450):
            con.execute(
                "INSERT INTO quarterly_income"
                "(stock_id,year,season,stock_name,market,revenue,cogs,gross_profit,"
                "gross_margin_pct,operating_income,net_income,eps,published_roc,updated_at)"
                " VALUES (?,?,3,'x','TW',1,0,0,0,0,0,0,'', '')",
                (f"T{i:04d}", 2026),
            )
        gaps = listed_income_gap_seasons(con, [(2026, 3), (2025, 4)])
        assert (2026, 3) in gaps  # TWO 不足
        assert (2025, 4) in gaps
        # 月營收：TW 夠、TWO 不夠
        for i in range(900):
            con.execute(
                "INSERT INTO monthly_revenue"
                "(stock_id,yyyymm,stock_name,market,industry,revenue,revenue_prev_month,"
                "revenue_prev_year,mom_pct,yoy_pct,ytd_revenue,ytd_prev_year,ytd_yoy_pct,"
                "published_roc,updated_at)"
                " VALUES (?, '202609','x','TW','',1,0,0,0,0,0,0,0,'','')",
                (f"M{i:04d}",),
            )
        mg = listed_monthly_gap_months(con, "202610", months=3)
        assert "202609" in mg
    finally:
        con.close()


def test_parse_mops_income_keeps_non_operating():
    html = """
    <html><body><table>
    <tr><td>公司代號</td><td>公司名稱</td><td>營業收入</td><td>營業成本</td>
    <td>營業毛利（毛損）</td><td>未實現銷貨（損）益</td><td>已實現銷貨（損）益</td>
    <td>營業毛利（毛損）淨額</td><td>營業費用</td><td>其他收益及費損淨額</td>
    <td>營業利益（損失）</td><td>營業外收入及支出</td><td>稅前淨利（淨損）</td>
    <td>所得稅費用（利益）</td><td>繼續營業單位本期淨利（淨損）</td>
    <td>本期淨利（淨損）</td><td>基本每股盈餘（元）</td></tr>
    <tr><td>2330</td><td>台積電</td><td>1,000</td><td>400</td>
    <td>600</td><td>0</td><td>0</td><td>600</td><td>100</td><td>--</td>
    <td>500</td><td>12</td><td>512</td><td>10</td>
    <td>502</td><td>502</td><td>1.23</td></tr>
    </table></body></html>
    """
    rows = parse_mops_income_html(html, year=2026, season=3, market="TW")
    assert len(rows) == 1
    assert rows[0]["stock_id"] == "2330"
    assert rows[0]["non_operating"] == 12.0
    assert rows[0]["eps"] == 1.23
