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


def test_help_evolve_does_not_inject_broker():
    from bot_servers import HELP_TOPICS

    ai = HELP_TOPICS["ai"]
    assert "進化" in ai
    assert "量化積木" in ai
    assert "不能把這支程式塞進" in ai
    assert "不會自動改程式" in ai
    assert "高低卡" in ai
