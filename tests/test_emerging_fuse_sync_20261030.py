# -*- coding: utf-8 -*-
"""2026-10-30：盤後融合興櫃與上市櫃同一趟必跑；缺日不准假 success。"""
from __future__ import annotations

import inspect
import os
import sqlite3
import tempfile

from import_health import MIN_EM, MIN_TWO, MIN_TW, increment_health_ok
from wayne_db import ensure_core_schema


def _seed_listed_half(conn: sqlite3.Connection, ymd: str) -> None:
    """上市櫃半套（不够完整日閘）。"""
    for i in range(5):
        conn.execute(
            """INSERT INTO daily_quotes
            (date,stock_id,stock_name,market,open,high,low,close,volume,turnover_k,pct_change,avg_price,foreign_net,trust_net,dealer_net)
            VALUES (?,?,?,?,10,11,9,10,1000,10,0.5,10,10,0,0)""",
            (ymd, f"{1000+i:04d}", "TW", "TW"),
        )
    for i in range(4):
        conn.execute(
            """INSERT INTO daily_quotes
            (date,stock_id,stock_name,market,open,high,low,close,volume,turnover_k,pct_change,avg_price,foreign_net,trust_net,dealer_net)
            VALUES (?,?,?,?,10,11,9,10,1000,10,0.5,10,50,0,0)""",
            (ymd, f"{6000+i:04d}", "上櫃", "TWO"),
        )


def _seed_listed_full(conn: sqlite3.Connection, ymd: str) -> None:
    for i in range(MIN_TW):
        conn.execute(
            """INSERT INTO daily_quotes
            (date,stock_id,stock_name,market,open,high,low,close,volume,turnover_k,pct_change,avg_price,foreign_net,trust_net,dealer_net)
            VALUES (?,?,?,?,10,11,9,10,1000,10,0.5,10,10,0,0)""",
            (ymd, f"{1000+i:04d}", "TW", "TW"),
        )
    for i in range(MIN_TWO):
        conn.execute(
            """INSERT INTO daily_quotes
            (date,stock_id,stock_name,market,open,high,low,close,volume,turnover_k,pct_change,avg_price,foreign_net,trust_net,dealer_net)
            VALUES (?,?,?,?,10,11,9,10,1000,10,0.5,10,50,0,0)""",
            (ymd, f"{6000+i:04d}", "上櫃", "TWO"),
        )


def _seed_emerging(conn: sqlite3.Connection, ymd: str, n: int = MIN_EM) -> None:
    for i in range(int(n)):
        conn.execute(
            """INSERT INTO emerging_quotes
            (date,stock_id,stock_name,market,open,high,low,close,volume,turnover_k,pct_change,avg_price,source)
            VALUES (?,?,?,?,10,11,9,10,100,10,0.5,10,'test')""",
            (ymd, f"{7000+i:04d}", "興櫃", "EM"),
        )


def test_sync_emerging_required_helper_exists():
    from main_runner import MainRunner

    assert callable(MainRunner._sync_emerging_required)
    src = inspect.getsource(MainRunner._sync_emerging_required)
    assert "sync_emerging_quotes" in src
    assert "emerging_rows_on" in src
    assert "MIN_EM" in src
    assert "不准假 success" in src


def test_open_day_fuse_never_skips_emerging_as_warning():
    """開市日融合不准「興櫃…略過」當成功；必走 _sync_emerging_required。"""
    from main_runner import MainRunner

    daily = inspect.getsource(MainRunner.run_daily_increment)
    job = inspect.getsource(MainRunner.run_increment_job)
    assert "_sync_emerging_required" in daily
    assert "興櫃日均價同步略過" not in daily
    assert "_sync_emerging_required" in job
    # 開市日 busy_window 本體不准略過興櫃（休市日側車略過仍可）
    open_fuse = job.split('busy_window("fuse"')[1]
    assert "興櫃收盤再寫略過" not in open_fuse
    assert "興櫃補齊略過" not in open_fuse
    assert "_sync_emerging_required" in open_fuse
    # 成功前必再過興櫃閘
    assert "融合興櫃閘" in open_fuse
    assert open_fuse.index("融合興櫃閘") < open_fuse.index('"success"')


def test_half_listed_full_emerging_as_of_uses_emerging_day(tmp_path):
    """上市櫃半套、興櫃全日 → 3595 類仍吃興櫃完整日。"""
    from emerging_quotes import ensure_emerging_table
    from import_health import latest_complete_emerging_date, latest_complete_quote_date
    from vol_zone_chart import load_official_ohlc

    path = str(tmp_path / "em.db")
    ensure_core_schema(path)
    ensure_emerging_table(path)
    conn = sqlite3.connect(path)
    # 前一日上市櫃＋興櫃都齊
    _seed_listed_full(conn, "20261028")
    _seed_emerging(conn, "20261028")
    # 當日：上市櫃半套、興櫃全日；3595 有真柱
    _seed_listed_half(conn, "20261029")
    _seed_emerging(conn, "20261029")
    conn.execute(
        """INSERT OR REPLACE INTO emerging_quotes
        (date,stock_id,stock_name,market,open,high,low,close,volume,turnover_k,pct_change,avg_price,source)
        VALUES (?,?,?,?,824.21,812.0,395.5,651.61,4284.586,0,-20.94,651.61,'test')""",
        ("20261029", "3595", "山太士", "EM"),
    )
    conn.commit()
    conn.close()

    assert latest_complete_quote_date(path, cap="20261029") == "20261028"
    assert latest_complete_emerging_date(path, cap="20261029") == "20261029"

    df = load_official_ohlc("3595", path, days=40)
    assert not df.empty
    last = str(df.iloc[-1]["date"]).replace("-", "")[:8]
    assert last == "20261029"
    assert abs(float(df.iloc[-1]["close"]) - 651.61) < 1e-6


def test_missing_emerging_blocks_increment_ok():
    """興櫃缺日 → 健康閘失敗（不准當 fuse success）。"""
    health = {
        "total": 2000,
        "tw": max(MIN_TW, 900),
        "two": max(MIN_TWO, 700),
        "chips_nonzero": 500,
        "em": 0,
    }
    assert increment_health_ok(health) is False


def test_sync_emerging_required_marks_thin_incomplete(tmp_path, monkeypatch):
    from main_runner import MainRunner

    path = str(tmp_path / "thin.db")
    ensure_core_schema(path)
    runner = MainRunner.__new__(MainRunner)
    runner.db_path = path

    monkeypatch.setattr(
        "emerging_quotes.sync_emerging_quotes",
        lambda *a, **k: {"n": 0},
    )
    monkeypatch.setattr(
        "emerging_quotes.emerging_rows_on",
        lambda *a, **k: 12,
    )
    out = runner._sync_emerging_required("20261029", label="測")
    assert out["ok"] is False
    assert out["em"] == 12
    assert "未齊" in out["error"]


def test_sync_emerging_required_exception_is_not_ok(tmp_path, monkeypatch):
    from main_runner import MainRunner

    path = str(tmp_path / "boom.db")
    ensure_core_schema(path)
    runner = MainRunner.__new__(MainRunner)
    runner.db_path = path

    def _boom(*a, **k):
        raise RuntimeError("network down")

    monkeypatch.setattr("emerging_quotes.sync_emerging_quotes", _boom)
    out = runner._sync_emerging_required("20261029", label="測")
    assert out["ok"] is False
    assert "失敗" in out["error"]


def test_load_official_ohlc_does_not_pretend_today_when_em_missing(tmp_path):
    """興櫃缺當日 → 圖停在既有完整日，不准裝今天。"""
    from emerging_quotes import ensure_emerging_table
    from vol_zone_chart import load_official_ohlc

    path = str(tmp_path / "miss.db")
    ensure_core_schema(path)
    ensure_emerging_table(path)
    conn = sqlite3.connect(path)
    _seed_listed_full(conn, "20261028")
    _seed_emerging(conn, "20261028")
    conn.execute(
        """INSERT OR REPLACE INTO emerging_quotes
        (date,stock_id,stock_name,market,open,high,low,close,volume,turnover_k,pct_change,avg_price,source)
        VALUES (?,?,?,?,900,910,800,824.21,1000,0,0,824.21,'test')""",
        ("20261028", "3595", "山太士", "EM"),
    )
    # 當日上市櫃半套、興櫃完全沒進
    _seed_listed_half(conn, "20261029")
    conn.commit()
    conn.close()

    df = load_official_ohlc("3595", path, days=40)
    assert not df.empty
    last = str(df.iloc[-1]["date"]).replace("-", "")[:8]
    assert last == "20261028"
    assert abs(float(df.iloc[-1]["close"]) - 824.21) < 1e-6
