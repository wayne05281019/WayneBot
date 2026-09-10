# -*- coding: utf-8 -*-
"""12:45 尾盤：現在／今早價分開寫；開頭先講現在要做什麼。"""
from __future__ import annotations

from unittest.mock import patch

from midday_review import (
    format_midday_html,
    format_midday_stock_line,
    run_midday_review,
)
from screen_sessions import save_screen_session
from wayne_db import ensure_core_schema


def test_midday_stock_line_shows_morning_price_and_diff():
    row = {"stock_id": "4915", "stock_name": "致伸", "pick_close": 60.8, "entry_price": 59.0}
    live = {"close": 62.1}
    line = format_midday_stock_line(row, live)
    assert line.startswith("4915 致伸　現在 62.1　今早 60.8　")
    assert "比今早 +1.3 元" in line
    assert "+2.1%" in line
    assert "+2.14%" not in line
    assert " 現 " not in line
    assert " 早 " not in line


def test_midday_stock_line_down_from_morning():
    row = {"stock_id": "2330", "stock_name": "台積電", "pick_close": 100.0}
    line = format_midday_stock_line(row, {"close": 97.5})
    assert "現在 97.5　今早 100" in line
    assert "比今早 -2.5 元" in line
    assert "-2.5%" in line


def test_midday_html_has_no_line_share_hint():
    html = format_midday_html(
        "20260908",
        {
            "ok": ["4915 致伸　現在 62.1　今早 60.8　比今早 +1.3 元（+2.1%）"],
            "chase": [],
            "above_entry": [],
            "no_quote": [],
        },
    )
    assert "LINE" not in html
    assert "轉貼" not in html
    assert "複製" not in html
    assert "現在要做的事" in html
    assert "沒買：只看第一區" in html
    assert "現在＝此刻成交價" in html
    assert "現在還能看" in html
    assert "4915 致伸　現在 62.1　今早 60.8　比今早 +1.3 元（+2.1%）" in html
    assert "建議切入" not in html
    assert "現價旁＝" not in html


def test_run_midday_review_uses_pick_close_and_skips_line_share(tmp_path):
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
            ]
        },
    )
    live = {"4915": {"close": 62.1}}
    with patch("midday_review.fetch_mis_batch", return_value=live):
        out = run_midday_review(db, "20260908")
    assert out["line_share"] == ""
    assert "LINE" not in (out["html"] or "")
    assert "現在 62.1　今早 60.8" in out["html"]
    assert "比今早 +1.3 元" in out["html"]
    assert "現在要做的事" in out["html"]


def test_main_runner_midday_does_not_send_copy_paste():
    src = open("main_runner.py", encoding="utf-8").read()
    assert "下面這一則可整段複製" not in src
    assert "要轉 LINE 自己選聯絡人" not in src
    assert "現在／今早價分開寫，先講現在要做什麼，不轉 LINE" in src
