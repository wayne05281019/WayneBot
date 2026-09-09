# -*- coding: utf-8 -*-
"""已公告月營收：OpenAPI 全市場同一期時，改對公開資訊觀測站 NAS 彙總表。"""
from __future__ import annotations

import sqlite3

from fundamentals import (
    get_latest_monthly,
    mops_monthly_urls,
    parse_t21sc03_html,
    previous_calendar_yyyymm,
    sync_fundamentals,
)
from industry_brief import industry_snapshot
from wayne_db import ensure_core_schema

# 緯穎 2026/08：144,311,808 千元＝1,443.12 億（2026-09-08 已公告）
FIXTURE_6669_AUG = """
<html><table>
<tr><th class=tt align=left >產業別：電腦及週邊設備業</th></tr>
<tr align=right><td align=center>6669</td><td align=left>緯穎</td>
<td nowrap>            144,311,808</td><td nowrap>            117,685,530</td>
<td nowrap>             95,978,718</td><td nowrap>                 22.62</td>
<td nowrap>                 50.35</td><td nowrap>            816,657,663</td>
<td nowrap>            571,906,228</td><td nowrap>                 42.79</td>
<td align=left>主要係客戶需求強勁</td></tr>
</table></html>
"""


def test_previous_calendar_month_is_august_on_sep9():
    assert previous_calendar_yyyymm("20260909") == "202608"
    assert previous_calendar_yyyymm("20260105") == "202512"


def test_mops_urls_cover_listed_otc_and_ky():
    urls = mops_monthly_urls("202608")
    blob = " ".join(u for u, _m in urls)
    assert "t21sc03_115_8_0.html" in blob
    assert "/sii/" in blob and "/otc/" in blob
    assert any(m == "TW" for _u, m in urls) and any(m == "TWO" for _u, m in urls)


def test_parse_t21sc03_huatong_august():
    rows = parse_t21sc03_html(FIXTURE_6669_AUG, "202608", "TW")
    assert len(rows) == 1
    r = rows[0]
    assert r["stock_id"] == "6669"
    assert r["stock_name"] == "緯穎"
    assert r["yyyymm"] == "202608"
    assert r["industry"] == "電腦及週邊設備業"
    assert r["revenue"] == 144311808
    assert r["mom_pct"] == 22.62
    assert r["yoy_pct"] == 50.35
    assert r["ytd_revenue"] == 816657663


def test_sync_merges_mops_when_openapi_still_july(tmp_path, monkeypatch):
    db = str(tmp_path / "f.db")
    monkeypatch.setattr(
        "fundamentals._get",
        lambda url: [
            {
                "公司代號": "6669",
                "公司名稱": "緯穎",
                "資料年月": "11507",
                "產業別": "電腦及週邊設備業",
                "營業收入-當月營收": "117685530",
                "營業收入-上月營收": "111000000",
                "營業收入-去年當月營收": "84500000",
                "營業收入-上月比較增減(%)": "5.67",
                "營業收入-去年同月增減(%)": "39.23",
                "累計營業收入-當月累計營收": "672345855",
                "累計營業收入-去年累計營收": "476000000",
                "累計營業收入-前期比較增減(%)": "41.2",
                "出表日期": "1150817",
            }
        ]
        if "t187ap05" in url or "mopsfin_t187ap05" in url
        else [],
    )
    monkeypatch.setattr("fundamentals.previous_calendar_yyyymm", lambda today_ymd="": "202608")
    monkeypatch.setattr(
        "fundamentals.fetch_mops_monthly_filings",
        lambda yyyymm: (parse_t21sc03_html(FIXTURE_6669_AUG, yyyymm, "TW"), []),
    )
    stats = sync_fundamentals(db)
    assert stats["mops_rows"] == 1
    latest = get_latest_monthly(db, "6669")
    assert latest["yyyymm"] == "202608"
    assert latest["revenue"] == 144311808


def test_industry_peers_use_this_stock_month_not_global_max(tmp_path):
    db = str(tmp_path / "ind.db")
    ensure_core_schema(db)
    from fundamentals import ensure_fundamentals_tables

    ensure_fundamentals_tables(db)
    conn = sqlite3.connect(db)
    now = "2026-09-09T00:00:00"
    conn.execute(
        "INSERT INTO stock_universe(stock_id,stock_name,market_type,asset_type,industry,is_active,updated_at) VALUES (?,?,?,?,?,1,?)",
        ("6669", "緯穎", "TWSE", "STOCK", "電腦及週邊設備業", now),
    )
    conn.execute(
        "INSERT INTO stock_universe(stock_id,stock_name,market_type,asset_type,industry,is_active,updated_at) VALUES (?,?,?,?,?,1,?)",
        ("2382", "廣達", "TWSE", "STOCK", "電腦及週邊設備業", now),
    )
    conn.execute(
        "INSERT INTO monthly_revenue(stock_id,yyyymm,stock_name,market,industry,revenue,mom_pct,yoy_pct,ytd_yoy_pct) VALUES (?,?,?,?,?,?,?,?,?)",
        ("2382", "202607", "廣達", "TW", "電腦及週邊設備業", 1000, 1.0, 10.0, 10.0),
    )
    conn.execute(
        "INSERT INTO monthly_revenue(stock_id,yyyymm,stock_name,market,industry,revenue,mom_pct,yoy_pct,ytd_yoy_pct) VALUES (?,?,?,?,?,?,?,?,?)",
        ("6669", "202607", "緯穎", "TW", "電腦及週邊設備業", 900, 1.0, 20.0, 20.0),
    )
    conn.execute(
        "INSERT INTO monthly_revenue(stock_id,yyyymm,stock_name,market,industry,revenue,mom_pct,yoy_pct,ytd_yoy_pct) VALUES (?,?,?,?,?,?,?,?,?)",
        ("6669", "202608", "緯穎", "TW", "電腦及週邊設備業", 144311808, 22.62, 50.35, 42.79),
    )
    conn.commit()
    conn.close()
    snap = industry_snapshot(db, "6669")
    assert snap["month"] == "202608"
    # 同業 8 月還沒公告的不該拿 7 月來比 8 月
    assert snap["yoy_n"] == 1
    late = industry_snapshot(db, "2382")
    assert late["month"] == "202607"
    assert late["yoy_n"] == 2


def test_morning_still_confirms_fundamentals_when_quotes_complete():
    src = open("main_runner.py", encoding="utf-8").read()
    assert "仍對官方側車" in src
    assert "_refresh_official_sidecars" in src
    i_skip = src.find("略過再抓行情，仍對官方側車")
    i_sync = src.find("_refresh_official_sidecars()", i_skip)
    assert i_skip != -1 and i_sync != -1 and i_sync - i_skip < 400
    helper = src[src.find("def _refresh_official_sidecars") :]
    assert "sync_fundamentals" in helper
    assert "sync_company_events" in helper
    assert "sync_ex_preview" in helper
    assert "sync_official_snapshots" in helper
