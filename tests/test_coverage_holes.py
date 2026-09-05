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


def test_decision_card_table_keeps_halt_days():
    from wayne_navigator import NavigatorEngine

    src = inspect.getsource(NavigatorEngine.get_decision_card)
    assert "table_src = df" in src
    assert "高低／均線略過無量日" in src
