# -*- coding: utf-8 -*-
"""ETF 查股卡：類型徽章、藏公司本益／月營收、官方淨值才上折溢價。"""
from __future__ import annotations

import inspect
import sqlite3

import pytest

from bot_servers import WayneTelegramBot
from fundamentals import format_fundamentals_html, glance_fundamentals_plain
from official_snapshots import (
    _fmt_etf_div_amt,
    _upsert_etf_div,
    ensure_schema,
    etf_div_cadence_label,
    etf_div_plain_rows,
    etf_nav_plain_rows,
    etf_price_nav,
    parse_etf_div,
    parse_mis_etf_nav,
    previous_open_calendar_day,
    valuation_plain_rows,
)
from universe import etf_card_kind_label, is_etf_asset
from wayne_db import ensure_core_schema


def test_etf_card_kind_labels():
    assert etf_card_kind_label("ETF_PASSIVE") == "被動"
    assert etf_card_kind_label("ETF_ACTIVE") == "主動"
    assert etf_card_kind_label("ETF_LEVERAGED") == "正2"
    assert etf_card_kind_label("ETF_INVERSE") == "反1"
    assert etf_card_kind_label(stock_id="0050") == "被動"
    assert etf_card_kind_label(stock_id="00981A") == "主動"
    assert etf_card_kind_label(stock_id="00631L") == "正2"
    assert etf_card_kind_label(stock_id="00632R") == "反1"
    assert etf_card_kind_label(stock_id="2330") == ""
    assert is_etf_asset(stock_id="0050")
    assert is_etf_asset(stock_id="00631L")
    assert not is_etf_asset(stock_id="2330")


def test_parse_mis_etf_nav_keeps_prev_nav_drops_estimate():
    payload = {
        "a1": [
            {
                "msgArray": [
                    {
                        "a": "0050",
                        "b": "元大台灣50",
                        "e": 109.65,
                        "f": 999.99,
                        "g": 12.34,
                        "h": 109.40,
                        "i": "20260909",
                        "j": "17:01:15",
                        "k": "1",
                    },
                    {
                        "a": "00631L",
                        "h": 37.80,
                        "f": 38.00,
                        "g": -0.5,
                        "i": "20260909",
                    },
                    {"a": "empty", "h": 0, "i": "20260909"},
                    {"a": "nodate", "h": 10.0, "i": ""},
                ]
            }
        ]
    }
    rows = parse_mis_etf_nav(payload)
    by_id = {r["stock_id"]: r for r in rows}
    assert by_id["0050"]["nav"] == 109.40
    assert by_id["0050"]["date"] == previous_open_calendar_day("20260909")
    assert by_id["0050"]["source"] == "twse_mis_prev_nav"
    assert by_id["00631L"]["nav"] == 37.80
    assert "empty" not in by_id
    assert "nodate" not in by_id
    blob = str(rows)
    assert "999.99" not in blob
    assert "12.34" not in blob


def _etf_db(tmp_path, *, with_close: bool = True) -> str:
    db = str(tmp_path / "etf.db")
    ensure_core_schema(db)
    ensure_schema(db)
    from fundamentals import ensure_fundamentals_tables

    ensure_fundamentals_tables(db)
    conn = sqlite3.connect(db)
    conn.executemany(
        "INSERT OR REPLACE INTO stock_universe(stock_id,stock_name,market_type,asset_type,industry,is_active,updated_at) VALUES (?,?,?,?,?,1,'t')",
        [
            ("0050", "元大台灣50", "上市", "ETF_PASSIVE", "ETF"),
            ("00878", "國泰永續高股息", "上市", "ETF_PASSIVE", "ETF"),
            ("00919", "群益台灣精選高息", "上市", "ETF_PASSIVE", "ETF"),
            ("00940", "元大台灣價值高息", "上市", "ETF_PASSIVE", "ETF"),
            ("00981A", "統一台灣高息動能", "上市", "ETF_ACTIVE", "ETF"),
            ("00631L", "元大台灣50正2", "上市", "ETF_LEVERAGED", "ETF"),
            ("2330", "台積電", "上市", "STOCK", "半導體業"),
        ],
    )
    conn.execute(
        """INSERT INTO monthly_revenue
           (stock_id, yyyymm, stock_name, market, industry, revenue)
           VALUES ('0050','202607','元大台灣50','TW','ETF',999999)"""
    )
    conn.execute(
        """INSERT INTO quarterly_income
           (stock_id, year, season, stock_name, market, revenue, gross_profit, gross_margin_pct, eps)
           VALUES ('0050',2026,2,'元大台灣50','TW',999999,888888,88.8,9.9)"""
    )
    now = "2026-09-08T16:00:00Z"
    conn.execute(
        "INSERT INTO daily_valuation VALUES ('0050','20260908',99.99,1.11,2.22,'twse_bwibbu',?)",
        (now,),
    )
    conn.execute(
        "INSERT INTO daily_valuation VALUES ('2330','20260908',27.94,9.72,0.91,'twse_bwibbu',?)",
        (now,),
    )
    conn.execute(
        "INSERT INTO etf_nav_snapshot VALUES ('0050','20260908',109.40,'twse_mis_prev_nav',?)",
        (now,),
    )
    conn.execute(
        "INSERT INTO etf_nav_snapshot VALUES ('00631L','20260908',37.80,'twse_mis_prev_nav',?)",
        (now,),
    )
    conn.execute(
        "INSERT INTO etf_nav_snapshot VALUES ('00981A','20260908',16.71,'twse_mis_prev_nav',?)",
        (now,),
    )
    divs = [
        ("0050", "20260122", 0.7),
        ("0050", "20260721", 3.8),
        ("00878", "20260519", 0.40),
        ("00878", "20260818", 1.01),
        ("00878", "20261118", None),
        ("00940", "20260908", 0.055),
        ("00940", "20261008", 0.06),
        ("00919", "20260818", 0.18),
        ("00919", "20260918", None),
    ]
    for sid, ex, amt in divs:
        conn.execute(
            """INSERT INTO etf_div_event
               (stock_id, ex_date, amount, pay_date, record_date, source, updated_at)
               VALUES (?, ?, ?, '', '', 'twse_etfDiv', ?)""",
            (sid, ex, amt, now),
        )
    if with_close:
        conn.execute(
            """INSERT OR REPLACE INTO daily_quotes
               (date, stock_id, stock_name, market, open, high, low, close, volume,
                turnover_k, pct_change, avg_price)
               VALUES ('20260908','0050','元大台灣50','TW',109,110,108,109.65,1000,0,0,109.65)"""
        )
        conn.execute(
            """INSERT OR REPLACE INTO daily_quotes
               (date, stock_id, stock_name, market, open, high, low, close, volume,
                turnover_k, pct_change, avg_price)
               VALUES ('20260908','00631L','元大台灣50正2','TW',37,38,37,37.49,1000,0,0,37.49)"""
        )
    conn.commit()
    conn.close()
    return db


def test_etf_glance_hides_company_pe_and_revenue(tmp_path):
    db = _etf_db(tmp_path)
    rows50 = glance_fundamentals_plain("0050", db)
    labs50 = [a for a, _ in rows50]
    blob50 = " ".join(f"{a} {b}" for a, b in rows50)
    assert "類型 被動" in blob50
    assert dict(rows50)["配息"] == "半年配"
    assert "淨值" not in labs50
    assert "折溢價" not in labs50
    assert "殖利率" not in labs50
    assert "本益" not in blob50
    assert "月營收" not in blob50
    assert "毛利" not in blob50
    assert "99.99" not in blob50
    html = format_fundamentals_html("0050", db)
    assert "被動 ETF" in html
    assert "沒有公司月營收" in html
    assert "公司本益不上卡" in html
    assert "折溢價看收盤旁" in html
    assert "本益 99" not in html
    assert "88.8" not in html
    assert "999999" not in html

    blob_l = " ".join(f"{a} {b}" for a, b in glance_fundamentals_plain("00631L", db))
    assert "類型 正2" in blob_l
    assert "本益" not in blob_l
    assert "淨值" not in blob_l
    blob_a = " ".join(f"{a} {b}" for a, b in glance_fundamentals_plain("00981A", db))
    assert "類型 主動" in blob_a
    assert "淨值" not in blob_a

    tsmc = " ".join(f"{a} {b}" for a, b in valuation_plain_rows("2330", db))
    assert "本益 27.94" in tsmc
    assert "淨值 9.72" in tsmc


def test_etf_premium_blank_without_same_day_close(tmp_path):
    db = _etf_db(tmp_path, with_close=False)
    rows = etf_nav_plain_rows("0050", db)
    labs = [a for a, _ in rows]
    blob = " ".join(f"{a} {b}" for a, b in rows)
    assert "淨值 109.40（09/08）" in blob
    assert "折溢價" not in labs


def test_etf_hub_omits_revenue_stock_keeps_it():
    bot = WayneTelegramBot.__new__(WayneTelegramBot)
    etf = [b.text for r in bot._hub_keyboard("0050").inline_keyboard for b in r]
    lev = [b.text for r in bot._hub_keyboard("00631L").inline_keyboard for b in r]
    stk = [b.text for r in bot._hub_keyboard("2330").inline_keyboard for b in r]
    assert "營收" not in etf
    assert "營收" not in lev
    assert "籌碼" in etf
    assert "產業" in etf
    assert "營收" in stk
    assert "籌碼" in stk


def test_etf_price_nav_beside_close_not_in_fundamentals(tmp_path):
    db = _etf_db(tmp_path)
    info = etf_price_nav("0050", db, close=109.65)
    assert info["nav"] == pytest.approx(109.40)
    assert info["premium"] == pytest.approx(0.2285, abs=0.001)
    assert info["date"] == "20260908"
    labs = [a for a, _ in glance_fundamentals_plain("0050", db)]
    assert "淨值" not in labs
    assert "折溢價" not in labs
    from wayne_navigator import _paint_close_right, session_price_label

    src = inspect.getsource(_paint_close_right)
    assert 'C["up"]' in src
    assert 'C["down"]' in src
    assert "折溢價" in src
    assert "_draw_mini_candle" in src
    assert "session_price_label" in src
    assert "今K" in src
    lab_src = inspect.getsource(session_price_label)
    assert "現價" in lab_src
    assert "收盤" in lab_src


def test_etf_div_last_and_next_amount_only_when_announced(tmp_path):
    db = _etf_db(tmp_path)
    by_lab = dict(etf_div_plain_rows("00878", db, today="20260909"))
    assert by_lab["配息"] == "季配"
    assert by_lab["上次配"] == "1.01（08/18）"
    assert by_lab["下次除息"] == "11/18"
    assert "1.10" not in by_lab.get("下次除息", "")

    by_lab = dict(etf_div_plain_rows("00940", db, today="20260909"))
    assert by_lab["配息"] == "月配"
    assert by_lab["上次配"] == "0.055（09/08）"
    assert by_lab["下次除息"] == "10/08 配 0.06"

    by_lab = dict(etf_div_plain_rows("00919", db, today="20260909"))
    assert by_lab["下次除息"] == "09/18"
    assert "配" not in by_lab["下次除息"]


def test_parse_etf_div_skips_null_amount_keeps_ex_date():
    payload = {
        "stat": "OK",
        "date": "20260909",
        "fields": ["證券代號", "證券簡稱", "除息交易日", "收益分配金額 (每1受益權益單位)"],
        "data": [
            ["00919", "群益台灣精選高息", "20260918", None],
            ["00940", "元大台灣價值高息", "20261008", 0.06],
            ["0056", "元大高股息", None, None],
        ],
    }
    rows = parse_etf_div(payload)
    by_id = {(r["stock_id"], r["ex_date"]): r for r in rows}
    assert by_id[("00919", "20260918")]["amount"] is None
    assert by_id[("00940", "20261008")]["amount"] == pytest.approx(0.06)
    assert all(r["ex_date"] for r in rows)


def test_etf_div_fmt_and_cadence():
    assert _fmt_etf_div_amt(0.6) == "0.60"
    assert _fmt_etf_div_amt(0.055) == "0.055"
    assert _fmt_etf_div_amt(1.01) == "1.01"
    assert etf_div_cadence_label(["20260122", "20260721"]) == "半年配"
    assert etf_div_cadence_label(["20260519", "20260818"]) == "季配"
    assert etf_div_cadence_label(["20260908", "20261008"]) == "月配"
    assert etf_div_cadence_label(["20260908"]) == ""


def test_upsert_etf_div_keeps_amount_when_new_is_null(tmp_path):
    db = str(tmp_path / "keep.db")
    ensure_schema(db)
    conn = sqlite3.connect(db)
    _upsert_etf_div(
        conn,
        [{"stock_id": "00919", "ex_date": "20260918", "amount": 0.07, "pay_date": "", "record_date": ""}],
        "t1",
    )
    _upsert_etf_div(
        conn,
        [{"stock_id": "00919", "ex_date": "20260918", "amount": None, "pay_date": "", "record_date": ""}],
        "t2",
    )
    conn.commit()
    amt = conn.execute("SELECT amount FROM etf_div_event WHERE stock_id='00919'").fetchone()[0]
    conn.close()
    assert amt == pytest.approx(0.07)
