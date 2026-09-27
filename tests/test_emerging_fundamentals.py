# -*- coding: utf-8 -*-
"""興櫃營收：櫃買 OpenAPI 月營收＋月彙季；無漲跌停洗底見 test_fmt_price。"""
from fundamentals import (
    quarterly_revenue_from_monthly,
    revenue_trend_label,
    parse_monthly_row,
)


def test_revenue_trend_label_buckets():
    assert "越來越好" in revenue_trend_label(25.0, kind="yoy")
    assert "較去年同月改善" == revenue_trend_label(8.0, kind="yoy")
    assert "較上月持平" == revenue_trend_label(1.0, kind="mom")
    assert "較上月走弱" == revenue_trend_label(-8.0, kind="mom")
    assert "較去年同月大減" == revenue_trend_label(-30.0, kind="yoy")
    assert "較去年同季" in revenue_trend_label(10.0, kind="yoy_q")
    assert revenue_trend_label(None) == "—"


def test_monthly_revenue_window_rows_one_line():
    from fundamentals import monthly_revenue_window_rows

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
    # 只有兩個月＝不造假季
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
