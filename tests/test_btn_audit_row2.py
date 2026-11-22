# -*- coding: utf-8 -*-
"""第二排七鍵巡檢 B：接線／畫面不能沉默／非買訊口徑。"""
from __future__ import annotations

import asyncio
import inspect
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from bot_servers import (
    MENU_BTN_CHONG,
    MENU_BTN_DONGZHU,
    MENU_BTN_LEAVE_ZERO,
    MENU_BTN_PRESSURE,
    MENU_BTN_STREAK,
    MENU_BTN_UNDERVALUE,
    MENU_BTN_WAVE_STATUS,
    MENU_ROW2,
    WayneTelegramBot,
)


ROW2_LABELS = (
    MENU_BTN_WAVE_STATUS,
    MENU_BTN_CHONG,
    MENU_BTN_PRESSURE,
    MENU_BTN_UNDERVALUE,
    MENU_BTN_STREAK,
    MENU_BTN_LEAVE_ZERO,
    MENU_BTN_DONGZHU,
)


def test_menu_row2_seven_keys_order():
    assert len(MENU_ROW2) == 7
    assert MENU_ROW2 == ROW2_LABELS


def test_wave_status_wait_before_preflight_not_silent():
    """波浪位階：流水線前必須先出「進行中」泡泡（畫面不能沉默）。"""
    src = inspect.getsource(WayneTelegramBot.wave_status_cmd)
    assert "_start_plain_wait" in src
    assert "波浪位階進行中" in src
    assert src.index("_start_plain_wait") < src.index(
        "run_teach_trio_preflight_pipeline"
    )
    assert src.index("_start_plain_wait") < src.index("format_teach_brief")
    assert 'wait_title="波浪位階進行中"' in src


def test_wave_charts_accept_wait_title():
    src = inspect.getsource(WayneTelegramBot._send_market_wave_charts)
    assert "wait_title" in src
    assert "大盤圖進行中" in src


def test_row2_heavy_paths_have_wait_bubble():
    """重活入口必須有進行中泡泡；純中樞（沖區／壓撐 hub／連買 hub）即時回文即可。"""
    undervalue = inspect.getsource(WayneTelegramBot._send_undervalue_view)
    assert "低估名單進行中" in undervalue
    assert "_start_plain_wait" in undervalue

    leave = inspect.getsource(WayneTelegramBot._run_leave_zero_now)
    assert "剛脫離零進行中" in leave
    assert "_start_plain_wait" in leave

    dongzhu = inspect.getsource(WayneTelegramBot._send_dongzhu_page)
    assert "洞燭先機進行中" in dongzhu
    assert "_start_plain_wait" in dongzhu

    pressure = inspect.getsource(WayneTelegramBot._run_pressure_support)
    assert "壓撐觀察進行中" in pressure
    assert "_start_plain_wait" in pressure

    chong = inspect.getsource(WayneTelegramBot.chong_zone_cmd)
    assert "非黃金買點" in chong
    assert "_chong_zone_keyboard" in chong

    streak = inspect.getsource(WayneTelegramBot._streak_show_kind)
    assert "連買區" in streak


def test_row2_non_buy_wording_guards():
    from pressure_support_watch import PRESSURE_HUB_LEAD

    wave = inspect.getsource(WayneTelegramBot.wave_status_cmd)
    assert "非買訊" in wave
    assert "不是買訊" in PRESSURE_HUB_LEAD or "只觀察" in PRESSURE_HUB_LEAD
    undervalue = inspect.getsource(WayneTelegramBot._send_undervalue_view)
    assert "不是買訊" in undervalue


def _msg(uid: int = 1001, text: str = ""):
    user = SimpleNamespace(id=uid, first_name="u")
    chat = SimpleNamespace(id=99)
    message = MagicMock()
    message.chat_id = 99
    message.chat = chat
    message.from_user = user
    message.text = text
    message.reply_text = AsyncMock(return_value=MagicMock(delete=AsyncMock()))
    message.reply_html = AsyncMock(return_value=MagicMock(delete=AsyncMock()))
    return message


def _bot():
    bot = WayneTelegramBot.__new__(WayneTelegramBot)
    bot.db_path = ":memory:"
    bot.charts_dir = "data/charts"
    bot._pending = {}
    bot._wave_locks = {}
    bot._last_card = {}
    bot._lookup_ctx = {}
    bot._menu_fade_msgs = {}
    bot._lookup_fade_msgs = {}
    bot._screening_msgs = {}
    bot._line_pack_status_msgs = {}
    bot._help_msgs = {}
    bot._lookup_locks = {}
    bot._pending_locks = {}
    bot._screening_running = set()
    bot._menu_fade_gen = {}
    bot._menu_layout_ok = MagicMock(return_value=True)
    bot._touch_user = MagicMock()
    bot._keyboard = MagicMock(return_value=None)
    bot._reply_menu = MagicMock(return_value=None)
    bot._actor_key = MagicMock(return_value="99:1001")
    bot._uid_from_message = MagicMock(return_value="1001")
    bot._start_plain_wait = AsyncMock(
        return_value=(MagicMock(), None, None)
    )
    bot._stop_plain_wait = AsyncMock()
    bot._wait_bubble = MagicMock(
        side_effect=lambda title, s, **kw: f"⏳ LOADING\n{title}"
    )
    bot._send_market_wave_charts = AsyncMock()
    return bot


def test_wave_status_cmd_starts_wait_before_pipeline():
    bot = _bot()
    order: list = []

    async def track_wait(message, *, text_fn, **_kw):
        order.append("wait")
        order.append(text_fn(0))
        return MagicMock(), None, None

    bot._start_plain_wait = AsyncMock(side_effect=track_wait)
    bot.wave_status_cmd = WayneTelegramBot.wave_status_cmd.__get__(
        bot, WayneTelegramBot
    )

    def _pipe(_db):
        order.append("pipe")
        return {"ok": True, "pack": {"x": 1}, "fail_bits": []}

    def _brief(_db, _pack):
        order.append("brief")
        return "<b>波浪位階（預估・非買訊）</b>"

    msg = _msg()
    upd = SimpleNamespace(
        effective_message=msg,
        message=msg,
        effective_user=msg.from_user,
    )
    with patch(
        "biaoke_level_learn.run_teach_trio_preflight_pipeline", side_effect=_pipe
    ), patch("biaoke_digest.format_teach_brief", side_effect=_brief):
        asyncio.run(bot.wave_status_cmd(upd, MagicMock()))

    assert order[0] == "wait"
    assert "波浪位階進行中" in order[1]
    assert "pipe" in order and order.index("wait") < order.index("pipe")
    assert "brief" in order and order.index("wait") < order.index("brief")
    bot._send_market_wave_charts.assert_awaited()
    kwargs = bot._send_market_wave_charts.await_args.kwargs
    assert kwargs.get("wait_title") == "波浪位階進行中"
    bot._stop_plain_wait.assert_awaited()
