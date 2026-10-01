# -*- coding: utf-8 -*-
"""12:45 雙時段比價：剛離零＋還在零；開盤 vs 現價。"""
from __future__ import annotations

from unittest.mock import patch

from midday_review import (
    format_midday_html,
    format_midday_stock_line,
    load_midday_bucket_rows,
    run_midday_review,
)
from screen_sessions import save_screen_session
from wayne_db import ensure_core_schema


def test_midday_stock_line_shows_open_price_and_diff():
    row = {"stock_id": "4915", "stock_name": "致伸", "pick_close": 60.8, "entry_price": 59.0}
    live = {"close": 62.1, "open": 60.8}
    line = format_midday_stock_line(row, live)
    assert line.startswith("4915 致伸　現在 62.1　開盤 60.8　")
    assert "比開盤 +1.3 元" in line
    assert "+2.1%" in line
    assert "+2.14%" not in line
    assert "今早" not in line
    assert " 現 " not in line


def test_midday_stock_line_down_from_open():
    row = {"stock_id": "2330", "stock_name": "台積電", "pick_close": 100.0}
    line = format_midday_stock_line(row, {"close": 97.5, "open": 100.0})
    assert "現在 97.5　開盤 100" in line
    assert "比開盤 -2.5 元" in line
    assert "-2.5%" in line


def test_midday_html_dual_period_buckets():
    html = format_midday_html(
        "20260908",
        {
            "leave_zero": [
                '<a href="https://tw.stock.yahoo.com/quote/4915.TW">4915 致伸</a>'
                "　現在 62.1　開盤 60.8　比開盤 +1.3 元（+2.1%）"
            ],
            "golden_buy": [],
            "no_quote": [],
        },
    )
    assert "LINE" not in html
    assert "轉貼" not in html
    assert "複製" not in html
    assert "12:45 雙時段比價" in html
    assert "剛離零" in html
    assert "還在零" in html
    assert "開盤＝今日開盤價" in html
    assert "tw.stock.yahoo.com/quote/4915.TW" in html
    assert "現在 62.1　開盤 60.8　比開盤 +1.3 元（+2.1%）" in html
    assert "現在要做的事" not in html
    assert "已靠近 20 日高" not in html
    assert "建議切入" not in html


def test_run_midday_review_only_leave_zero_and_golden_buy(tmp_path):
    db = str(tmp_path / "mid.db")
    ensure_core_schema(db)
    save_screen_session(
        db,
        "20260908",
        "morning",
        {
            "leave_zero": [
                {
                    "stock_id": "4915",
                    "stock_name": "致伸",
                    "close": 60.8,
                    "hi20_close": 80.0,
                    "entry_price": 59.0,
                }
            ],
            "golden_buy": [
                {
                    "stock_id": "2330",
                    "stock_name": "台積電",
                    "close": 900.0,
                    "hi20_close": 950.0,
                    "entry_price": 880.0,
                }
            ],
            "day_trade": [
                {
                    "stock_id": "2317",
                    "stock_name": "鴻海",
                    "close": 100.0,
                    "hi20_close": 110.0,
                    "entry_price": 99.0,
                }
            ],
            "overnight": [
                {
                    "stock_id": "2454",
                    "stock_name": "聯發科",
                    "close": 1000.0,
                    "hi20_close": 1100.0,
                    "entry_price": 990.0,
                }
            ],
        },
    )
    rows = load_midday_bucket_rows(db, "20260908")
    ids = {r["stock_id"] for r in rows}
    assert ids == {"4915", "2330"}
    assert "2317" not in ids
    assert "2454" not in ids

    live = {
        "4915": {"close": 62.1, "open": 60.8},
        "2330": {"close": 905.0, "open": 900.0},
        "2317": {"close": 105.0, "open": 100.0},
    }
    with patch("midday_review.fetch_mis_batch", return_value=live) as mocked:
        out = run_midday_review(db, "20260908")
        called_ids = set(mocked.call_args[0][0])
        assert called_ids == {"4915", "2330"}
        assert "2317" not in called_ids
    assert out["line_share"] == ""
    assert out["n"] == 2
    assert out["leave_zero_n"] == 1
    assert out["golden_buy_n"] == 1
    assert "LINE" not in (out["html"] or "")
    assert "12:45 雙時段比價" in out["html"]
    assert "現在 62.1　開盤 60.8" in out["html"]
    assert "比開盤 +1.3 元" in out["html"]
    assert "現在 905　開盤 900" in out["html"]
    assert "鴻海" not in out["html"]
    assert "聯發科" not in out["html"]
    assert 'href="https://tw.stock.yahoo.com/quote/4915.TW"' in out["html"]
    assert ">4915 致伸</a>" in out["html"]
    assert "現在要做的事" not in out["html"]
    assert "已靠近 20 日高" not in out["html"]


def test_midday_prefers_leave_zero_when_in_both_buckets(tmp_path):
    db = str(tmp_path / "mid2.db")
    ensure_core_schema(db)
    save_screen_session(
        db,
        "20260908",
        "morning",
        {
            "leave_zero": [{"stock_id": "4915", "stock_name": "致伸", "close": 60.0}],
            "golden_buy": [{"stock_id": "4915", "stock_name": "致伸", "close": 60.0}],
        },
    )
    rows = load_midday_bucket_rows(db, "20260908")
    assert len(rows) == 1
    assert rows[0]["bucket"] == "leave_zero"


def test_midday_stock_line_html_uses_two_for_otc(monkeypatch):
    from midday_review import format_midday_stock_line_html

    monkeypatch.setattr("stock_links.yahoo_exchange", lambda *_a, **_k: "TWO")
    monkeypatch.setattr(
        "stock_links.html_stock_anchor",
        lambda sid, name="", db_path=None: (
            f'<a href="https://tw.stock.yahoo.com/quote/{sid}.TWO">{sid} {name}</a>'
        ),
    )
    row = {"stock_id": "3105", "stock_name": "穩懋", "pick_close": 100.0}
    html = format_midday_stock_line_html(
        row, {"close": 101.0, "open": 100.0}, db_path="unused.db"
    )
    assert "tw.stock.yahoo.com/quote/3105.TWO" in html
    assert ">3105 穩懋</a>" in html
    assert "現在 101　開盤 100" in html


def test_main_runner_midday_keeps_once_claim():
    src = open("main_runner.py", encoding="utf-8").read()
    assert "allow_stale_running=False" in src
    assert "try_claim_pipeline" in src
    assert "midday-" in src
    assert "下面這一則可整段複製" not in src
    assert "要轉 LINE 自己選聯絡人" not in src


def test_fetch_mis_batch_skips_network_in_pytest(monkeypatch, tmp_path):
    from midday_review import fetch_mis_batch

    calls = []

    def boom(*_a, **_k):
        calls.append(1)
        raise AssertionError("pytest 不准打 MIS")

    monkeypatch.setattr("midday_review._SESSION.get", boom)
    assert fetch_mis_batch(["2330"], str(tmp_path / "x.db")) == {}
    assert calls == []


def test_fetch_mis_batch_includes_open(monkeypatch, tmp_path):
    from midday_review import fetch_mis_batch
    from wayne_db import ensure_core_schema
    import sqlite3

    db = str(tmp_path / "mis.db")
    ensure_core_schema(db)
    conn = sqlite3.connect(db)
    conn.execute(
        "INSERT INTO daily_quotes("
        "date, stock_id, stock_name, market, open, high, low, close, volume, "
        "turnover_k, pct_change, avg_price"
        ") VALUES ('20260908','2330','台積電','TW',100,110,99,105,1,0,0,105)"
    )
    conn.commit()
    conn.close()

    class FakeResp:
        def json(self):
            return {
                "msgArray": [
                    {
                        "c": "2330",
                        "n": "台積電",
                        "z": "108",
                        "y": "105",
                        "o": "106",
                        "v": "1000",
                        "t": "12:45:00",
                    }
                ]
            }

    monkeypatch.setenv("WAYNE_ALLOW_MIS", "1")
    monkeypatch.setattr("midday_review._SESSION.get", lambda *a, **k: FakeResp())
    monkeypatch.setattr("live_quote.mis_ex_ch", lambda sid, m: f"tse_{sid}.tw")
    monkeypatch.setattr("time.sleep", lambda *_a, **_k: None)
    out = fetch_mis_batch(["2330"], db)
    assert out["2330"]["open"] == 106.0
    assert out["2330"]["close"] == 108.0
