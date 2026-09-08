# -*- coding: utf-8 -*-
"""盤前／盤後自動功能：GHA cron、Render 角色、程式時槽、說明書必須同一套。"""
from __future__ import annotations

import os
import re

from bot_servers import HELP_TOPICS
from config import scheduled_job_kind
from picture_guide import page_copy_blob

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _read(rel: str) -> str:
    with open(os.path.join(ROOT, rel), encoding="utf-8") as fh:
        return fh.read()


def test_gha_daily_run_owns_morning_and_fuse_only():
    text = _read(".github/workflows/daily_run.yml")
    crons = re.findall(r"cron:\s*'([^']+)'", text)
    assert "30 8 * * 1-5" in crons  # UTC 08:30＝台北 16:30 盤後融合
    assert "45 8 * * 1-5" in crons  # UTC 08:45＝台北 16:45 盤後補跑，不是海選
    assert "30 22 * * 0-4" in crons  # UTC 22:30 日～四＝台北週一～五 06:30
    assert crons.count("30 22 * * 0-4") == 1
    assert not any(c != "30 22 * * 0-4" and " 22 " in f" {c} " for c in crons)
    assert '*22*' not in text
    assert '"$SCHED" = "30 22 * * 0-4"' in text
    assert scheduled_job_kind("30 8 * * 1-5") == "increment"
    assert scheduled_job_kind("45 8 * * 1-5") == "increment"
    assert scheduled_job_kind("30 22 * * 0-4") == "morning_screen"
    assert "increment" in text and "morning_screen" in text
    assert "WAYNE_FAMILY_CHAT_IDS" in text
    assert "run_midday_review" not in text
    assert "run_evening_screen" not in text


def test_render_data_role_does_not_push_morning(monkeypatch):
    import config

    yaml = _read("render.yaml")
    assert "WAYNE_SCHEDULER_ROLE" in yaml
    assert "value: data" in yaml
    monkeypatch.setenv("WAYNE_SCHEDULER_ROLE", "data")
    assert config.scheduler_owns("morning") is False
    assert config.scheduler_may_push("morning") is False
    assert config.scheduler_owns("midday") is True
    assert config.scheduler_may_push("midday") is True
    assert config.scheduler_owns("fuse") is True
    assert config.scheduler_may_push("fuse") is False
    assert config.scheduler_owns("evening") is True
    assert config.scheduler_may_push("evening") is False


def test_main_scheduler_slots_match_help_clocks():
    src = _read("main.py")
    assert '(6, 30, "morning")' in src
    assert '(12, 45, "midday")' in src
    assert '(16, 30, "fuse")' in src
    assert '(20, 0, "evening")' in src
    assert '(5, 10, "typhoon")' in src
    assert '(22, 15, "typhoon")' in src
    header = _read("main_runner.py")[:2500]
    assert "Render WAYNE_SCHEDULER_ROLE=data 不跑 morning" in header
    assert "Render 常駐 06:30" not in header
    guide = HELP_TOPICS["guide"]
    blob = page_copy_blob()
    for clock in ("06:30", "12:45", "16:30", "20:00"):
        assert clock in guide
        assert clock in blob
    assert "人事行政總處" in HELP_TOPICS["market"]
    assert "19:00" in HELP_TOPICS["market"] and "22:00" in HELP_TOPICS["market"]
    assert "04:30" in HELP_TOPICS["market"]
    assert "人事行政總處" in HELP_TOPICS["row2"]
    assert "19:00" in HELP_TOPICS["row2"]
    assert "22:00 前公告" not in HELP_TOPICS["row2"]
    assert "不寄 06:30 海選" in HELP_TOPICS["guide"]
    assert "不寄今早海選" in HELP_TOPICS["screen"]
    assert "台股休市當日" in HELP_TOPICS["screen"]
    assert "台股休市" in HELP_TOPICS["daytrade"]
    assert "齊了發一則" in guide
    assert "不是海選" in _read("main_runner.py")
    assert "不寄" in guide or "不推播" in HELP_TOPICS["ai"]


def test_evening_ai_is_silent_and_uses_official_close():
    src = _read("main_runner.py")
    assert "notify=False" in src
    assert 'session="evening"' in src
    assert "apply_us=False" in src
    assert "apply_us=True, session=\"morning\"" in src or 'session="morning"' in src
    ai = HELP_TOPICS["ai"]
    assert "不推播" in ai
    assert "16:30" in ai and "20:00" in ai
