# -*- coding: utf-8 -*-
"""興櫃營收／綜合損益：櫃買 OpenAPI＋觀測站 rotc／ajax_t163sb04。"""
import sqlite3

from fundamentals import (
    emerging_income_seasons,
    ensure_fundamentals_tables,
    glance_fundamentals_plain,
    monthly_revenue_window_rows,
    parse_mops_income_html,
    parse_monthly_row,
    parse_t21sc03_html,
    quarterly_revenue_from_monthly,
    revenue_trend_label,
)
from wayne_db import ensure_core_schema


FIXTURE_ROTC_INCOME_7853 = """
<html><body>
<table>
<tr><td>公司代號</td><td>公司名稱</td><td>營業收入</td><td>營業成本</td>
<td>營業毛利（毛損）</td><td>未實現銷貨（損）益</td><td>已實現銷貨（損）益</td>
<td>營業毛利（毛損）淨額</td><td>營業費用</td><td>其他收益及費損淨額</td>
<td>營業利益（損失）</td><td>營業外收入及支出</td><td>稅前淨利（淨損）</td>
<td>所得稅費用（利益）</td><td>繼續營業單位本期淨利（淨損）</td>
<td>本期淨利（淨損）</td><td>基本每股盈餘（元）</td></tr>
<tr><td>7853</td><td>政美應用</td><td>185,166</td><td>104,999</td>
<td>80,167</td><td>0</td><td>0</td><td>80,167</td><td>122,365</td><td>--</td>
<td>-42,198</td><td>-12,061</td><td>-54,259</td><td>-60</td>
<td>-54,199</td><td>-54,199</td><td>-1.37</td></tr>
</table>
</body></html>
"""

FIXTURE_ROTC_MONTHLY_7853 = """
<html><table>
<tr><th class=tt align=left >產業別：半導體業</th></tr>
<tr align=right><td align=center>7853</td><td align=left>政美應用</td>
<td nowrap>30300</td><td nowrap>95049</td><td nowrap>27329</td>
<td nowrap>-68.12</td><td nowrap>10.87</td>
<td nowrap>372826</td><td nowrap>252701</td><td nowrap>47.5</td>
<td align=left></td></tr>
</table></html>
"""


def test_revenue_trend_label_buckets():
    assert "越來越好" in revenue_trend_label(25.0, kind="yoy")
    assert "較去年同月改善" == revenue_trend_label(8.0, kind="yoy")
    assert "較上月持平" == revenue_trend_label(1.0, kind="mom")
    assert "較上月走弱" == revenue_trend_label(-8.0, kind="mom")
    assert "較去年同月大減" == revenue_trend_label(-30.0, kind="yoy")
    assert "較去年同季" in revenue_trend_label(10.0, kind="yoy_q")
    assert revenue_trend_label(None) == "—"


def test_monthly_revenue_window_rows_one_line():
    rows = monthly_revenue_window_rows(
        [
            {
                "yyyymm": "202608",
                "revenue": 30300,
                "mom_pct": -68.12,
                "yoy_pct": 10.87,
                "ytd_yoy_pct": 47.5,
            }
        ]
    )
    assert len(rows) == 1
    lab, val = rows[0]
    assert lab == "月營收近窗"
    assert "0.30億元" in val
    assert "月增-68.1%" in val
    assert "年增+10.9%" in val
    assert "累年增+47.5%" in val
    assert "較上月大減" in val
    assert "較去年同月改善" in val


def test_quarterly_from_monthly_needs_three_months():
    partial = [
        {"yyyymm": "202607", "revenue": 100},
        {"yyyymm": "202608", "revenue": 200},
    ]
    assert quarterly_revenue_from_monthly(partial) == []
    full_q2 = [
        {"yyyymm": "202604", "revenue": 100},
        {"yyyymm": "202605", "revenue": 150},
        {"yyyymm": "202606", "revenue": 200},
        {"yyyymm": "202501", "revenue": 50},
        {"yyyymm": "202502", "revenue": 50},
        {"yyyymm": "202503", "revenue": 50},
    ]
    qs = quarterly_revenue_from_monthly(full_q2)
    assert len(qs) == 2
    assert qs[0]["year"] == 2026 and qs[0]["season"] == 2
    assert qs[0]["revenue"] == 450
    assert qs[1]["year"] == 2025 and qs[1]["season"] == 1


def test_parse_emerging_monthly_row():
    item = {
        "出表日期": "1150917",
        "資料年月": "11508",
        "公司代號": "7853",
        "公司名稱": "政美應用",
        "產業別": "半導體業",
        "營業收入-當月營收": "30300",
        "營業收入-上月營收": "95049",
        "營業收入-去年當月營收": "27329",
        "營業收入-上月比較增減(%)": "-68.12",
        "營業收入-去年同月增減(%)": "10.87",
        "累計營業收入-當月累計營收": "372826",
        "累計營業收入-去年累計營收": "252701",
        "累計營業收入-前期比較增減(%)": "47.5",
    }
    row = parse_monthly_row(item, "EM")
    assert row["stock_id"] == "7853"
    assert row["yyyymm"] == "202608"
    assert row["market"] == "EM"
    assert row["revenue"] == 30300.0
    assert abs(row["yoy_pct"] - 10.87) < 0.01


def test_parse_rotc_monthly_html():
    rows = parse_t21sc03_html(FIXTURE_ROTC_MONTHLY_7853, "202608", "EM")
    assert len(rows) == 1
    assert rows[0]["stock_id"] == "7853"
    assert rows[0]["market"] == "EM"
    assert rows[0]["revenue"] == 30300
    assert rows[0]["industry"] == "半導體業"


def test_parse_rotc_income_html_7853():
    rows = parse_mops_income_html(
        FIXTURE_ROTC_INCOME_7853, year=2025, season=2, market="EM"
    )
    assert len(rows) == 1
    r = rows[0]
    assert r["stock_id"] == "7853"
    assert r["stock_name"] == "政美應用"
    assert r["year"] == 2025 and r["season"] == 2
    assert r["revenue"] == 185166
    assert r["gross_profit"] == 80167
    assert abs(r["gross_margin_pct"] - 43.29) < 0.02
    assert r["operating_income"] == -42198
    assert r["net_income"] == -54199
    assert r["eps"] == -1.37


def test_emerging_income_seasons_skip_unfiled_q4():
    seasons = emerging_income_seasons("20260927")
    assert (2026, 4) not in seasons  # 當年 Q4 還沒
    assert (2026, 2) in seasons  # 9 月已過 8 月門檻
    assert (2025, 4) in seasons


def test_glance_shows_eps_when_rotc_income(tmp_path):
    db = str(tmp_path / "em.db")
    ensure_core_schema(db)
    ensure_fundamentals_tables(db)
    conn = sqlite3.connect(db)
    conn.execute(
        "INSERT INTO stock_universe(stock_id,stock_name,market_type,asset_type,industry,is_active,updated_at) "
        "VALUES (?,?,?,?,?,1,?)",
        ("7853", "政美應用", "EMERGING", "STOCK", "半導體業", "2026-09-27"),
    )
    conn.execute(
        "INSERT INTO monthly_revenue(stock_id,yyyymm,stock_name,market,industry,revenue,mom_pct,yoy_pct,ytd_yoy_pct) "
        "VALUES (?,?,?,?,?,?,?,?,?)",
        ("7853", "202608", "政美應用", "EM", "半導體業", 30300, -68.12, 10.87, 47.5),
    )
    conn.execute(
        "INSERT INTO quarterly_income(stock_id,year,season,stock_name,market,revenue,cogs,"
        "gross_profit,gross_margin_pct,operating_income,net_income,eps) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        ("7853", 2025, 2, "政美應用", "EM", 185166, 104999, 80167, 43.29, -42198, -54199, -1.37),
    )
    conn.commit()
    conn.close()
    rows = glance_fundamentals_plain("7853", db)
    blob = " ".join(f"{a} {b}" for a, b in rows)
    assert "無免驗證" not in blob
    assert "EPS" in blob and "-1.37" in blob
    assert "毛利率" in blob and "43.3%" in blob
    assert "淨利率" in blob
