# -*- coding: utf-8 -*-
"""官方快照：估值／資券餘額／暫停當沖／加權量／產業代碼。沒有真數不上欄。"""
from __future__ import annotations

import sqlite3

from official_snapshots import (
    drop_paused_daytrade,
    ensure_schema,
    industry_name,
    overlay_fmtqik,
    overlay_industry,
    parse_bwibbu,
    parse_fmtqik,
    parse_tpex_margin,
    parse_tpex_pe,
    parse_twse_margin,
    parse_twtb4u,
    paused_daytrade_ids,
    roc_to_ymd,
    sync_official_snapshots,
    valuation_plain_rows,
)
from wayne_db import ensure_core_schema


def test_roc_and_industry_codes():
    assert roc_to_ymd("1150904") == "20260904"
    assert industry_name("24") == "半導體業"
    assert industry_name("28") == "電子零組件業"
    assert industry_name("半導體業") == "半導體業"
    assert industry_name("") == ""


def test_bwibbu_skips_empty_pe_keeps_yield_and_pb():
    rows = parse_bwibbu(
        [
            {"Date": "1150904", "Code": "1101", "Name": "台泥", "PEratio": "", "DividendYield": "3.25", "PBratio": "0.80"},
            {"Date": "1150904", "Code": "2330", "Name": "台積電", "PEratio": "27.94", "DividendYield": "0.91", "PBratio": "9.72"},
            {"Date": "1150904", "Code": "9999", "Name": "空", "PEratio": "", "DividendYield": "", "PBratio": ""},
        ]
    )
    by_id = {r["stock_id"]: r for r in rows}
    assert "9999" not in by_id
    assert by_id["1101"]["pe"] is None
    assert by_id["1101"]["pb"] == 0.80
    assert by_id["1101"]["dividend_yield"] == 3.25
    assert by_id["2330"]["pe"] == 27.94


def test_tpex_pe_and_margin_fields():
    pe = parse_tpex_pe(
        [
            {
                "Date": "1150904",
                "SecuritiesCompanyCode": "6488",
                "PriceEarningRatio": "18.50",
                "PriceBookRatio": "2.10",
                "YieldRatio": "1.20",
            }
        ]
    )
    assert pe[0]["stock_id"] == "6488"
    assert pe[0]["pe"] == 18.5
    mar = parse_tpex_margin(
        [
            {
                "Date": "1150904",
                "SecuritiesCompanyCode": "6488",
                "MarginPurchaseBalance": "1234",
                "MarginPurchaseQuota": "10000",
                "MarginPurchaseUtilizationRate": "12.34",
                "ShortSaleBalance": "10",
                "ShortSaleQuota": "10000",
                "ShortSaleUtilizationRate": "0.10",
            }
        ]
    )
    assert mar[0]["margin_bal"] == 1234
    assert mar[0]["margin_util"] == 12.34


def test_twse_margin_util_from_limit_not_cost():
    rows = parse_twse_margin(
        [
            {
                "股票代號": "2330",
                "融資今日餘額": "28381",
                "融資限額": "6483092",
                "融券今日餘額": "25",
                "融券限額": "6483092",
            }
        ],
        fallback_date="20260904",
    )
    r = rows[0]
    assert r["date"] == "20260904"
    assert r["margin_bal"] == 28381
    assert abs(r["margin_util"] - 28381 / 6483092 * 100) < 0.05
    src = __import__("inspect").getsource(parse_twse_margin)
    assert "成本" not in src


def test_twtb4u_suspension_flag():
    rows = parse_twtb4u(
        [
            {"Date": "1150907", "Code": "2330", "Name": "台積電", "Suspension": ""},
            {"Date": "1150907", "Code": "0053", "Name": "元大電子", "Suspension": "Y"},
        ]
    )
    by_id = {r["stock_id"]: r for r in rows}
    assert by_id["2330"]["suspended"] == 0
    assert by_id["0053"]["suspended"] == 1


def test_fmtqik_shares_to_lots():
    rows = parse_fmtqik(
        [
            {
                "Date": "1150904",
                "TradeVolume": "9267046831",
                "TradeValue": "858244966564",
                "TAIEX": "46551.13",
                "Change": "693.47",
            }
        ]
    )
    assert rows[0]["date"] == "20260904"
    assert rows[0]["volume"] == 9267047
    assert rows[0]["close"] == 46551.13


def test_roundtrip_and_plain_rows_omit_empty(tmp_path):
    db = str(tmp_path / "off.db")
    ensure_core_schema(db)
    ensure_schema(db)
    conn = sqlite3.connect(db)
    now = "2026-09-04T16:00:00Z"
    conn.execute(
        "INSERT INTO daily_valuation VALUES ('2330','20260904',27.94,9.72,0.91,'twse_bwibbu',?)",
        (now,),
    )
    conn.execute(
        "INSERT INTO daily_valuation VALUES ('1101','20260904',NULL,0.80,3.25,'twse_bwibbu',?)",
        (now,),
    )
    conn.execute(
        "INSERT INTO daily_margin VALUES ('2330','20260904',18185,5516875,0.33,585,5516875,0.01,'twse_margn',?)",
        (now,),
    )
    conn.execute(
        "INSERT INTO daytrade_status VALUES ('9999','20260907',1,'twse_twtb4u',?)",
        (now,),
    )
    conn.commit()
    conn.close()
    tsmc = " ".join(f"{a} {b}" for a, b in valuation_plain_rows("2330", db))
    assert "本益 27.94" in tsmc
    assert "淨值 9.72" in tsmc
    assert "殖利率 0.91%" in tsmc
    assert "融資 18,185張" in tsmc
    assert "成本" not in tsmc
    cement = " ".join(f"{a} {b}" for a, b in valuation_plain_rows("1101", db))
    assert "本益" not in cement
    assert "淨值 0.80" in cement
    assert "殖利率 3.25%" in cement
    assert paused_daytrade_ids(db) == {"9999"}
    out = drop_paused_daytrade(
        {"day_trade": [{"stock_id": "2330"}, {"stock_id": "9999"}], "overnight": [{"stock_id": "9999"}]},
        db,
    )
    assert [x["stock_id"] for x in out["day_trade"]] == ["2330"]
    assert [x["stock_id"] for x in out["overnight"]] == ["9999"]


def test_overlay_fmtqik_and_industry(tmp_path):
    db = str(tmp_path / "ix.db")
    from taiwan_market import ensure_index_daily_table

    ensure_index_daily_table(db)
    conn = sqlite3.connect(db)
    conn.execute(
        "INSERT INTO index_daily(date,symbol,close,volume,pct_change,ma20,ma60,regime,updated_at) VALUES (?,?,?,?,?,?,?,?,?)",
        ("20260904", "TWII", 46000.0, 0.0, 1.0, 0, 0, "unknown", "t"),
    )
    conn.execute(
        "CREATE TABLE stock_universe (stock_id TEXT PRIMARY KEY, stock_name TEXT, market_type TEXT, asset_type TEXT, industry TEXT, is_active INT, updated_at TEXT)"
    )
    conn.execute(
        "INSERT INTO stock_universe VALUES ('2330','台積電','TW','STOCK','電子工業',1,'t')"
    )
    conn.commit()
    conn.close()
    n = overlay_fmtqik(db, parse_fmtqik([{"Date": "1150904", "TradeVolume": "9267046831", "TAIEX": "46551.13", "Change": "693.47"}]))
    assert n == 1
    conn = sqlite3.connect(db)
    vol, close = conn.execute("SELECT volume, close FROM index_daily WHERE date='20260904'").fetchone()
    conn.close()
    assert int(vol) == 9267047
    assert close == 46551.13
    overlay_industry(db, [("2330", "半導體業")])
    conn = sqlite3.connect(db)
    assert conn.execute("SELECT industry FROM stock_universe WHERE stock_id='2330'").fetchone()[0] == "半導體業"
    conn.close()


def test_increment_and_glance_wire_official():
    import inspect

    from main_runner import MainRunner
    from wayne_navigator import render_first_glance_png
    from screening_engine import execute_full_screening

    src = inspect.getsource(MainRunner.run_daily_increment)
    assert "sync_official_snapshots" in src
    glance = inspect.getsource(render_first_glance_png)
    assert "fmt_lots_align" not in glance
    assert "lots_right" not in glance
    assert 'ha="left"' in glance
    scan = inspect.getsource(execute_full_screening)
    assert "drop_paused_daytrade" in scan


def test_help_does_not_promise_main_cost():
    from bot_servers import HELP_TOPICS

    guide = HELP_TOPICS["guide"]
    stock = HELP_TOPICS["stock"]
    assert "就不會出現主力成本" in stock
    assert "會畫主力成本" not in guide + stock
    assert "本益" in stock
    assert "融資融券餘額" in stock
