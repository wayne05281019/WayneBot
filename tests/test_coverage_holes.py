# -*- coding: utf-8 -*-
"""冷門／KY 缺列交易日：整日檔數夠也不准跳過 9/2、9/3。"""
from __future__ import annotations

import inspect
import sqlite3

from data_fetcher import DataFetcher
from wayne_db import ensure_core_schema


def _quote(conn, date, sid, name, market="TWO"):
    conn.execute(
        """
        INSERT INTO daily_quotes(
            date, stock_id, stock_name, market, open, high, low, close,
            volume, turnover_k, pct_change, avg_price, foreign_net, trust_net, dealer_net
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        (date, sid, name, market, 18.1, 18.1, 18.1, 18.1, 2, 36.2, -1.09, 18.1, 0, 0, 0),
    )


def test_list_coverage_hole_dates_finds_middle_gap(tmp_path, monkeypatch):
    monkeypatch.setattr(DataFetcher, "_ensure_database_ready", lambda self: None)
    db = str(tmp_path / "holes.db")
    ensure_core_schema(db)
    conn = sqlite3.connect(db)
    conn.execute(
        "INSERT INTO stock_universe(stock_id, stock_name, market_type, asset_type, updated_at) VALUES (?,?,?,?,?)",
        ("5276", "達輝-KY", "TWO", "KY", "2026-09-04"),
    )
    _quote(conn, "20260901", "5276", "達輝-KY")
    _quote(conn, "20260904", "5276", "達輝-KY")
    conn.commit()
    conn.close()

    holes = DataFetcher(db_path=db)._list_coverage_hole_dates(lookback=10)
    assert "20260902" not in holes  # 這顆迷你庫沒有 0902 這一天的任何列
    # 沒有 0902／0903 這兩個 date group，抓洞只看已存在的交易日。
    # 補上「有日期列但缺這檔」：
    conn = sqlite3.connect(db)
    _quote(conn, "20260902", "6488", "環球晶", "TWO")
    conn.execute(
        "INSERT INTO stock_universe(stock_id, stock_name, market_type, asset_type, updated_at) VALUES (?,?,?,?,?)",
        ("6488", "環球晶", "TWO", "STOCK", "2026-09-04"),
    )
    _quote(conn, "20260903", "6488", "環球晶", "TWO")
    conn.commit()
    conn.close()

    holes = DataFetcher(db_path=db)._list_coverage_hole_dates(lookback=10)
    assert "20260902" in holes
    assert "20260903" in holes
    assert "20260904" not in holes
    assert "20260901" not in holes


def test_fill_missing_calls_coverage_hole_refill():
    src = inspect.getsource(DataFetcher.fill_missing_market_days)
    assert "refill_coverage_holes" in src
    assert "patch_missing_equity_quotes" in src


def test_parse_twse_keeps_thin_print_and_limit_up_lock():
    fetcher = DataFetcher.__new__(DataFetcher)
    rows = [
        ["1470", "大統新創", "1,176", "8", "29,161", "24.85", "24.85", "24.85", "24.85", "<p style= color:red>+</p>", "0.80"],
        ["2454", "聯發科", "4,931,652", "54322", "21280078380", "4315.00", "4315.00", "4315.00", "4315.00", "<p style= color:red>+</p>", "390.00"],
    ]
    recs, halts = DataFetcher._parse_twse_close_rows(fetcher, rows, "20260901")
    by_id = {r["stock_id"]: r for r in recs}
    assert by_id["1470"]["close"] == 24.85
    assert by_id["1470"]["volume"] == 1
    assert by_id["2454"]["close"] == 4315.0
    assert by_id["2454"]["open"] == 4315.0
    assert halts == []


def test_parse_twse_halt_dash_ohlc_is_halt_not_quote():
    fetcher = DataFetcher.__new__(DataFetcher)
    rows = [
        ["1470", "大統新創", "20", "1", "486", "--", "--", "--", "--", "<p> </p>", "0.00"],
    ]
    recs, halts = DataFetcher._parse_twse_close_rows(fetcher, rows, "20260903")
    assert recs == []
    assert halts == [("1470", "大統新創", 0)]


def test_list_missing_equities_finds_thin_gap(tmp_path, monkeypatch):
    monkeypatch.setattr(DataFetcher, "_ensure_database_ready", lambda self: None)
    db = str(tmp_path / "miss.db")
    ensure_core_schema(db)
    conn = sqlite3.connect(db)
    conn.execute(
        "INSERT INTO stock_universe(stock_id, stock_name, market_type, asset_type, updated_at) VALUES (?,?,?,?,?)",
        ("1470", "大統新創", "TW", "STOCK", "2026-09-04"),
    )
    _quote(conn, "20260902", "1470", "大統新創", "TW")
    _quote(conn, "20260904", "1470", "大統新創", "TW")
    _quote(conn, "20260901", "2330", "台積電", "TW")
    _quote(conn, "20260904", "2330", "台積電", "TW")
    conn.execute(
        "INSERT INTO stock_universe(stock_id, stock_name, market_type, asset_type, updated_at) VALUES (?,?,?,?,?)",
        ("2330", "台積電", "TW", "STOCK", "2026-09-04"),
    )
    conn.commit()
    conn.close()
    miss = DataFetcher(db_path=db)._list_missing_equities("20260901", "20260904")
    assert "1470" in miss
    assert "2330" not in miss


def test_patch_missing_writes_halt_from_prev_close(tmp_path, monkeypatch):
    monkeypatch.setattr(DataFetcher, "_ensure_database_ready", lambda self: None)
    db = str(tmp_path / "halt.db")
    ensure_core_schema(db)
    conn = sqlite3.connect(db)
    for sid, name in (("1470", "大統新創"), ("2330", "台積電")):
        conn.execute(
            "INSERT INTO stock_universe(stock_id, stock_name, market_type, asset_type, updated_at) VALUES (?,?,?,?,?)",
            (sid, name, "TW", "STOCK", "2026-09-04"),
        )
    _quote(conn, "20260902", "1470", "大統新創", "TW")
    conn.execute(
        "UPDATE daily_quotes SET close=24.3, open=23.75, high=24.3, low=23.7 WHERE stock_id='1470' AND date='20260902'"
    )
    _quote(conn, "20260904", "1470", "大統新創", "TW")
    _quote(conn, "20260903", "2330", "台積電", "TW")
    _quote(conn, "20260904", "2330", "台積電", "TW")
    conn.commit()
    conn.close()

    fetcher = DataFetcher(db_path=db)

    class _Resp:
        status_code = 200

        def json(self):
            return {
                "stat": "OK",
                "tables": [
                    {
                        "title": "115年09月03日 每日收盤行情(全部(不含權證、牛熊證、可展延牛熊證))",
                        "data": [
                            ["1470", "大統新創", "20", "1", "486", "--", "--", "--", "--", "<p> </p>", "0.00"],
                            ["2330", "台積電", "1000", "1", "1000", "2410", "2410", "2410", "2410", "<p> </p>", "0.00"],
                        ],
                    }
                ],
            }

    monkeypatch.setattr(fetcher.session, "get", lambda *a, **k: _Resp())
    monkeypatch.setattr(fetcher, "_fetch_tpex_daily", lambda *a, **k: [])
    n = fetcher._upsert_named_quotes("20260903", {"1470"}, ref_date="20260904")
    assert n == 1
    conn = sqlite3.connect(db)
    row = conn.execute(
        "SELECT close, volume, open, high, low FROM daily_quotes WHERE stock_id='1470' AND date='20260903'"
    ).fetchone()
    conn.close()
    assert row is not None
    assert float(row[0]) == 24.3
    assert int(row[1]) == 0


def test_decision_card_table_keeps_halt_days():
    from wayne_navigator import NavigatorEngine

    src = inspect.getsource(NavigatorEngine.get_decision_card)
    assert "table_src = df" in src
    assert "高低／均線略過無量日" in src
