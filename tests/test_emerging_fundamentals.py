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


def test_month_quarter_split_rows_aligns_right():
    from fundamentals import month_quarter_split_rows, quarterly_revenue_from_monthly

    months = [
        {"yyyymm": "202608", "revenue": 30300, "mom_pct": -68.12},
        {"yyyymm": "202607", "revenue": 95049, "mom_pct": 149.3},
        {"yyyymm": "202606", "revenue": 38125, "mom_pct": -9.2},
        {"yyyymm": "202605", "revenue": 42009, "mom_pct": 100.0},
        {"yyyymm": "202604", "revenue": 1787, "mom_pct": -90.0},
        {"yyyymm": "202603", "revenue": 129541, "mom_pct": 200.0},
        {"yyyymm": "202602", "revenue": 34905, "mom_pct": 10.0},
        {"yyyymm": "202601", "revenue": 1110, "mom_pct": -5.0},
    ]
    qs = quarterly_revenue_from_monthly(months)
    rows = month_quarter_split_rows(months, qs)
    assert [r["yyyymm"] for r in rows] == [
        "202608", "202607", "202606", "202605", "202604", "202603", "202602", "202601"
    ]
    assert "月營收" not in rows[0]["left"]
    assert rows[0]["left"].startswith("8月'26")
    assert rows[0]["mom_tone"] == "down"
    assert "月減68.1%" in rows[0]["mom_phrase"]
    assert rows[1]["mom_tone"] == "up"
    assert "月增+149.3%" in rows[1]["mom_phrase"]
    # 右欄掛在該季最上方月：Q2→6月、Q1→3月
    by = {r["yyyymm"]: r["right"] for r in rows}
    assert "第2季合計" in by["202606"] and "0.82億元" in by["202606"]
    assert by["202605"] == "" and by["202604"] == ""
    assert "第1季合計" in by["202603"] and "1.66億元" in by["202603"]
    assert by["202608"] == ""  # Q3 未滿三個月


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
    for ym, rev, mom, yoy, ytd in (
        ("202608", 30300, -68.12, 10.87, 47.5),
        ("202607", 95049, 149.3, 136.4, 52.0),
        ("202606", 38125, -9.2, -31.9, 33.6),
        ("202605", 42009, 100.0, 39.7, 62.1),
        ("202604", 1787, -90.0, -97.2, 68.9),
        ("202603", 129541, 200.0, 100.0, 382.1),
        ("202602", 34905, 10.0, 10.0, 100.0),
        ("202601", 1110, -5.0, 10.0, 10.0),
    ):
        conn.execute(
            "INSERT INTO monthly_revenue(stock_id,yyyymm,stock_name,market,industry,revenue,mom_pct,yoy_pct,ytd_yoy_pct) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            ("7853", ym, "政美應用", "EM", "半導體業", rev, mom, yoy, ytd),
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
    assert "月營收近窗" not in blob
    assert "月營收2" not in blob
    assert "8月'26" in blob and "月減68.1%" in blob
    assert "第2季合計" in blob
    assert "EPS" in blob
    assert "無免驗證" not in blob
