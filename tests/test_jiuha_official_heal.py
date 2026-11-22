# -*- coding: utf-8 -*-
"""啾哈官方欄補洞：解析／覆蓋率／缺源標 unavailable（非買訊）。"""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from jiuha_official_heal import (
    OPTIONAL_UNAVAILABLE,
    coverage_report,
    heal_usdtwd,
    optional_fields_status,
    parse_taifex_fut_contracts_csv,
    upsert_futures_inst_oi,
    _upsert_index_bar,
)


CSV_SAMPLE = """日期,商品名稱,身份別,多方交易口數,多方交易契約金額(千元),空方交易口數,空方交易契約金額(千元),多空交易口數淨額,多空交易契約金額淨額(千元),多方未平倉口數,多方未平倉契約金額(千元),空方未平倉口數,空方未平倉契約金額(千元),多空未平倉口數淨額,多空未平倉契約金額淨額(千元)
2026/11/05,臺股期貨,自營商,1,1,1,1,0,0,10,1,20,1,-10,1
2026/11/05,臺股期貨,外資及陸資,98413,1,101388,1,-2975,1,13388,1,109039,1,-95651,1
2026/11/04,臺股期貨,外資及陸資,1,1,1,1,0,0,12000,1,100000,1,-88000,1
"""


def _mk_market(tmp_path: Path) -> str:
    db = tmp_path / "m.db"
    con = sqlite3.connect(str(db))
    con.executescript(
        """
        CREATE TABLE index_daily (
            date TEXT NOT NULL,
            symbol TEXT NOT NULL DEFAULT 'TWII',
            close REAL,
            volume REAL,
            pct_change REAL,
            regime TEXT,
            updated_at TEXT,
            open REAL,
            high REAL,
            low REAL,
            PRIMARY KEY (date, symbol)
        );
        CREATE TABLE market_margin_daily (
            date TEXT PRIMARY KEY,
            margin_bal_prev_k INTEGER,
            margin_bal_k INTEGER,
            margin_delta_k INTEGER,
            source TEXT,
            updated_at TEXT
        );
        CREATE TABLE futures_inst_oi (
            date TEXT NOT NULL,
            contract TEXT NOT NULL,
            item TEXT NOT NULL,
            oi_long INTEGER NOT NULL,
            oi_short INTEGER NOT NULL,
            oi_net INTEGER NOT NULL,
            source TEXT NOT NULL DEFAULT 'taifex',
            updated_at TEXT NOT NULL,
            PRIMARY KEY (date, contract, item)
        );
        """
    )
    # 三根完整加權柱
    for day, o, h, l, c in [
        ("20261103", 40000, 40500, 39800, 40100),
        ("20261104", 40100, 41000, 40000, 40800),
        ("20261105", 40800, 41200, 39000, 39500),
    ]:
        con.execute(
            "INSERT INTO index_daily(date,symbol,open,high,low,close,volume) VALUES (?,?,?,?,?,?,?)",
            (day, "TWII", o, h, l, c, 1e7),
        )
    con.commit()
    con.close()
    return str(db)


def test_parse_taifex_csv_foreign_only_keeps_numbers():
    rows = parse_taifex_fut_contracts_csv(CSV_SAMPLE)
    assert len(rows) == 3
    foreign = [r for r in rows if r["item"] == "外資及陸資"]
    assert len(foreign) == 2
    f = next(r for r in foreign if r["date"] == "20261105")
    assert f["oi_long"] == 13388
    assert f["oi_short"] == 109039
    assert f["oi_net"] == -95651


def test_upsert_futures_and_coverage(tmp_path):
    db = _mk_market(tmp_path)
    rows = parse_taifex_fut_contracts_csv(CSV_SAMPLE)
    n = upsert_futures_inst_oi(db, rows)
    assert n == 3
    # 融資只補兩日
    con = sqlite3.connect(db)
    con.execute(
        "INSERT INTO market_margin_daily(date,margin_bal_prev_k,margin_bal_k,margin_delta_k,source,updated_at) VALUES (?,?,?,?,?,?)",
        ("20261105", 100, 90, -10, "twse", "t"),
    )
    con.execute(
        "INSERT INTO market_margin_daily(date,margin_bal_prev_k,margin_bal_k,margin_delta_k,source,updated_at) VALUES (?,?,?,?,?,?)",
        ("20261104", 110, 100, -10, "twse", "t"),
    )
    con.commit()
    con.close()
    # USDTWD 戳兩日
    _upsert_index_bar(
        db, day="20261105", symbol="USDTWD", open_=32.0, high=32.1, low=31.9, close=32.05, volume=None, pct_change=None, regime="yahoo_twd_x"
    )
    _upsert_index_bar(
        db, day="20261104", symbol="USDTWD", open_=32.1, high=32.2, low=32.0, close=32.1, volume=None, pct_change=None, regime="yahoo_twd_x"
    )
    # OTC 一日完整＋一日戳記
    _upsert_index_bar(
        db, day="20261105", symbol="OTC", open_=280.0, high=285.0, low=260.0, close=263.0, volume=1e6, pct_change=-6.0, regime="mis_otc_o00"
    )
    _upsert_index_bar(
        db, day="20261104", symbol="OTC", open_=300.0, high=300.0, low=300.0, close=300.0, volume=1e6, pct_change=None, regime="tpex_trading_index"
    )
    rep = coverage_report(db, sessions_n=3)
    assert rep["ok"]
    assert rep["futures_foreign_oi"]["covered"] == 2  # 04+05；03 缺
    assert rep["market_margin"]["covered"] == 2
    assert rep["usdtwd"]["covered"] == 2
    assert rep["otc_any"]["covered"] == 2
    assert rep["otc_full_ohlc"]["covered"] == 1
    assert rep["not_buy_signal"] is True


def test_optional_unavailable_honest():
    st = optional_fields_status()
    assert st["open15_vol"]["status"] == "unavailable"
    assert st["etf_gov_buy"]["status"] == "unavailable"
    assert "open15_vol" in OPTIONAL_UNAVAILABLE


def test_incomplete_csv_rejected():
    assert parse_taifex_fut_contracts_csv("") == []
    assert parse_taifex_fut_contracts_csv("<html>error</html>") == []
    # 缺未平倉欄
    bad = "日期,商品名稱,身份別\n2026/11/05,臺股期貨,外資及陸資\n"
    assert parse_taifex_fut_contracts_csv(bad) == []


def test_usdtwd_heal_marks_unavailable_when_yahoo_empty(tmp_path, monkeypatch):
    db = _mk_market(tmp_path)
    monkeypatch.setattr(
        "jiuha_official_heal.fetch_yahoo_usdtwd_bars", lambda **_k: []
    )
    res = heal_usdtwd(db)
    assert res["ok"] is False
    assert res["status"] == "unavailable"
