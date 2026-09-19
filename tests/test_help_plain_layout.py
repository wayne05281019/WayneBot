# -*- coding: utf-8 -*-
"""說明頁已取消；第一次用三步仍在 /start。"""
from __future__ import annotations

from bot_servers import HELP_TOPICS, LOOKUP_CODE_EXAMPLES_HTML, WayneTelegramBot


def test_help_topics_cancelled():
    assert HELP_TOPICS == {}
    bot = WayneTelegramBot.__new__(WayneTelegramBot)
    assert not bot._help_nav_keyboard().inline_keyboard


def test_start_cmd_leads_with_three_steps():
    import inspect

    src = inspect.getsource(WayneTelegramBot.start_cmd)
    assert "第一次用，先做這三步" in src
    assert "直接打代號" in src
    assert "LOOKUP_CODE_EXAMPLES_HTML" in src
    assert "00981A" in LOOKUP_CODE_EXAMPLES_HTML
    assert "圖下" in src
    assert "回報" not in src
    assert "刷新" not in src
    assert "給家人用" not in src
    assert "對方用自己的帳號按開始" not in src
    assert "不必再分享邀請" in src
