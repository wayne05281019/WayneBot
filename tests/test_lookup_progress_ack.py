# -*- coding: utf-8 -*-
"""查股進度泡泡：MIS 現價前就要開始跳秒，冷啟／盤中才不像當掉。"""
from __future__ import annotations

import inspect

from bot_servers import WayneTelegramBot


def test_lookup_progress_starts_before_mis_wait():
    src = inspect.getsource(WayneTelegramBot._send_card_to_locked)
    tick_i = src.index("progress_task = asyncio.create_task(_progress_tick())")
    mis_i = src.index("live_rt = await _fetch_mis()")
    assert tick_i < mis_i, "進度跳秒必須在等 MIS 現價之前啟動"
    assert 'current": "quote"' in src or "current\": \"quote\"" in src or 'current": "quote"' in src
    assert 'st0["current"] = "table"' in src or "st0['current'] = 'table'" in src


def test_chart_progress_has_quote_stage():
    text = WayneTelegramBot._chart_progress_text(3, current="quote")
    assert "現價" in text
    assert "查股進行中" in text
    both = WayneTelegramBot._chart_progress_text(1, current="both")
    assert "介紹圖" in both or "高低" in both


def test_send_card_to_acks_with_quote_stage():
    src = inspect.getsource(WayneTelegramBot._send_card_to)
    assert 'current="quote"' in src
    assert "send_action" in src
