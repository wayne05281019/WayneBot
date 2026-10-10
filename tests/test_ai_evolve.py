# -*- coding: utf-8 -*-
"""AI 模擬倉進化：存編碼、週五才寄週報、不改高低卡、不注入下單 App。"""
from __future__ import annotations

import os
import sqlite3

from ai_trader import (
    current_ai_encoding,
    format_evolve_report_html,
    persist_ai_lesson,
    should_send_weekly_evolve,
    mark_weekly_evolve_sent,
)
from wayne_db import ensure_core_schema


def test_persist_lesson_and_encoding_roundtrip(tmp_path):
    path = str(tmp_path / "e.db")
    ensure_core_schema(path)
    persist_ai_lesson(path, "ai_1", "20260904", "縮小單筆倉位")
    enc = current_ai_encoding(path, "ai_1")
    assert enc["entry"] == "leave_zero"
    assert enc["observe"] == "golden_buy"
    assert enc["not_entry"] == "red_arrow"
    assert enc["cash_slots"] == 1
    assert 0.4 <= float(enc["size_mult"]) <= 1.2
    html = format_evolve_report_html(path, "ai_1")
    assert "黃金買點" in html
    assert "縮小單筆倉位" in html
    assert "2026/09/04" in html
    assert "量化積木" in html
    assert "不能塞進" in html
    assert "紅箭頭不是買訊" in html
    conn = sqlite3.connect(path)
    n = conn.execute("SELECT COUNT(*) FROM ai_lessons").fetchone()[0]
    conn.close()
    assert n == 1


def test_weekly_evolve_only_friday_once(tmp_path):
    path = str(tmp_path / "w.db")
    ensure_core_schema(path)
    assert should_send_weekly_evolve(path, "ai_1", "20260907") is False  # Monday
    assert should_send_weekly_evolve(path, "ai_1", "20260904") is True  # Friday
    mark_weekly_evolve_sent(path, "ai_1", "20260904")
    assert should_send_weekly_evolve(path, "ai_1", "20260904") is False


def test_evening_desk_stays_silent_and_digest_is_separate():
    import inspect

    from main_runner import MainRunner

    src = inspect.getsource(MainRunner.run_evening_screen)
    assert "notify=False" in src
    assert "_maybe_send_evolve_digest" in src
    desk = inspect.getsource(MainRunner._run_ai_desk)
    assert "notify: bool = True" in desk
    # 成交後才凍 AI倉；海選 snapshot 常在 AI 前，不准只靠按鈕才記
    assert "snapshot_ai_desk" in desk


def test_core_candidates_are_leave_zero_only():
    import inspect

    from ai_trader import _candidates

    src = inspect.getsource(_candidates)
    assert 'keys = (("leave_zero", "黃金買點：獲利離零"),)' in src
    assert '("golden_buy"' not in src
    assert "revenue_cross" not in src
    assert "select_01" not in src
    assert '"overnight"' not in src
    assert "buy_star" in src
    cands = _candidates(
        {
            "leave_zero": [{"stock_id": "2330", "stock_name": "台積電", "close": 100.0, "buy_star": False}],
            "select_01": [{"stock_id": "2412", "stock_name": "中華電", "close": 120.0}],
        }
    )
    assert [x["stock_id"] for x in cands] == ["2330"]
    dip = _candidates(
        {
            "leave_zero": [{"stock_id": "2330", "stock_name": "台積電", "close": 100.0}],
            "golden_buy": [{"stock_id": "4127", "stock_name": "天鈺", "close": 50.0}],
            "select_01": [{"stock_id": "2412", "stock_name": "中華電", "close": 120.0}],
        },
        dip_only=True,
    )
    # 第二份超跌槽也不准買還在零（golden_buy）
    assert [x["stock_id"] for x in dip] == ["2330"]
    assert all(x.get("ai_bucket") == "leave_zero" for x in dip)
    only_gb = _candidates(
        {"golden_buy": [{"stock_id": "4127", "stock_name": "天鈺", "close": 50.0}]},
        dip_only=True,
    )
    assert only_gb == []


def test_evolve_report_second_slot_leave_zero_only(tmp_path):
    path = str(tmp_path / "e2.db")
    ensure_core_schema(path)
    html = format_evolve_report_html(path, "ai_1")
    assert "還在零只觀察" in html
    assert "不開槽" in html
    assert "買進不得吃保留額" in html
    assert "重點觀察／黃金買點" not in html
    assert "紅箭頭不是買訊" in html


def test_cash_reserve_and_buy_budget():
    from ai_trader import buy_budget, cash_reserve_floor, slot_notional

    assert cash_reserve_floor(500_000) == 500_000 / 3
    # 倍數拉高也不能吃進第 3 份
    assert buy_budget(500_000, 500_000, 1.2) == slot_notional(500_000, 1.2)
    assert buy_budget(200_000, 500_000, 1.2) == max(0.0, 200_000 - 500_000 / 3)
    assert buy_budget(100_000, 500_000, 1.0) == 0.0


def test_encoding_marks_cash_reserve(tmp_path):
    path = str(tmp_path / "enc.db")
    ensure_core_schema(path)
    enc = current_ai_encoding(path, "ai_1")
    assert enc["cash_reserve"] is True
    assert enc["dip_open"] == "leave_zero"
    assert enc["entry"] == "leave_zero"
    assert enc["not_entry"] == "red_arrow"


def test_help_topics_cancelled():
    from bot_servers import HELP_TOPICS

    assert HELP_TOPICS == {}
