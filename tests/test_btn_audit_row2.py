# -*- coding: utf-8 -*-
"""第二排七鍵巡檢 B：接線／畫面不能沉默／非買訊口徑／舊日警告。"""
from __future__ import annotations

import asyncio
import inspect
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from bot_servers import (
    MENU_BTN_CHONG,
    MENU_BTN_DONGZHU,
    MENU_BTN_LEAVE_DONGZHU,
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


def test_wave_charts_accept_wait_title_no_market_clash():
    """波浪鍵用「波浪位階進行中」；大盤頁不附三窗（改導向波浪位階）。"""
    charts = inspect.getsource(WayneTelegramBot._send_market_wave_charts)
    assert "wait_title" in charts
    assert "大盤圖進行中" in charts
    market = inspect.getsource(WayneTelegramBot.market_cmd)
    assert "_send_market_wave_charts" not in market
    page = inspect.getsource(WayneTelegramBot._send_market_page)
    assert "_send_market_wave_charts" not in page
    assert "波浪位階" in page


def test_chong_zone_subkeys_daytrade_overnight():
    kb = inspect.getsource(WayneTelegramBot._chong_zone_keyboard)
    assert 'callback_data="daytrade"' in kb
    assert 'callback_data="overnight"' in kb
    chong = inspect.getsource(WayneTelegramBot.chong_zone_cmd)
    assert "非黃金買點" in chong
    day = inspect.getsource(WayneTelegramBot.daytrade_cmd)
    over = inspect.getsource(WayneTelegramBot.overnight_cmd)
    assert "screen_daytrade" in day
    assert "screen_overnight" in over


def test_pressure_three_tags_and_trio_non_buy():
    from pressure_support_watch import (
        PRESSURE_HUB_LEAD,
        TAG_LABELS,
        TAG_ORDER,
        TAG_SUBTITLES,
    )

    assert TAG_ORDER == ("sideways", "test_press", "stand_support")
    assert TAG_LABELS["sideways"] == "壓力橫盤"
    assert TAG_LABELS["test_press"] == "測壓未破"
    assert TAG_LABELS["stand_support"] == "剛站上撐"
    assert "不是買訊" in PRESSURE_HUB_LEAD
    for tag in TAG_ORDER:
        assert "不是買訊" in TAG_SUBTITLES[tag] or "只觀察" in TAG_SUBTITLES[tag]
    hub = inspect.getsource(WayneTelegramBot._show_pressure_hub)
    assert "不是買訊" in hub or "PRESSURE_HUB_LEAD" in hub
    trio = inspect.getsource(WayneTelegramBot._send_pressure_stock_trio)
    assert "三張" in trio or "壓力區" in trio
    assert "psk:" in inspect.getsource(WayneTelegramBot._pressure_pick_row)


def test_undervalue_empty_hard_gate_note():
    from undervalue_sync import empty_note_for_button

    src = inspect.getsource(empty_note_for_button)
    assert "硬閘" in src or "0 檔" in src
    assert "買訊" in src
    uv = inspect.getsource(WayneTelegramBot._send_undervalue_view)
    assert "empty_note" in uv
    assert "估值≠買訊" in uv or "不是買訊" in uv
    assert "uv:page" in inspect.getsource(WayneTelegramBot._handle_undervalue_page_callback)


def test_streak_chip_stale_warn_and_paging():
    from buy_streak import (
        PAGE_SIZE,
        chip_stale_vs_desk,
        chip_stale_warn_html,
        format_list_html,
    )
    from buy_streak import StreakSnapshot

    assert PAGE_SIZE >= 1
    assert chip_stale_vs_desk("20261110", "20261120") is True
    assert chip_stale_vs_desk("20261120", "20261120") is False
    assert chip_stale_vs_desk("20261121", "20261120") is False
    warn = chip_stale_warn_html(
        "20261110", desk_as_of="20261120", db_path=None
    )
    assert "籌碼舊日" in warn
    assert "只觀察" in warn
    snap = StreakSnapshot(
        as_of="20261110", kind="foreign", market="ALL", by_days={}, max_days=0
    )
    # 空名單也要能帶舊日警告（desk 由參數／helper 注入）
    with patch("buy_streak.desk_quote_ymd", return_value="20261120"):
        html = format_list_html(snap, 3, db_path="/tmp/x.db")
    assert "籌碼舊日" in html
    days_src = inspect.getsource(WayneTelegramBot._streak_show_days)
    assert "chip_stale_warn_html" in days_src
    pick = inspect.getsource(WayneTelegramBot._streak_pick_inline)
    assert "上一頁" in pick and "下一頁" in pick


def test_leave_zero_face_not_screen_bucket_mislead():
    src = inspect.getsource(WayneTelegramBot._run_leave_zero_now)
    assert "screen_leave_zero_pick" in src
    assert "昨零今離" in src
    assert "剛脫離零進行中" in src
    # 空名單話筒句不准叫人去按海選（註解可寫「不准誤說」）
    assert 'empty = (' in src
    assert '"此刻沒有昨零今離的檔。"' in src
    assert '"最近完整收沒有昨零今離的檔。"' in src
    assert "不靠海選" in src
    closed = open("trading_calendar.py", encoding="utf-8").read()
    assert "不限海選桶" in closed


def test_dongzhu_enter_leave_and_hold_path():
    page = inspect.getsource(WayneTelegramBot._send_dongzhu_page)
    assert "dongzhu_picks" in page
    assert "dongzhu_page" in page
    assert "離開洞燭先機" in page or "_dongzhu_reply_menu" in page
    hold = inspect.getsource(WayneTelegramBot._send_dongzhu_hold)
    assert "dongzhu_hold_page" in hold
    leave = inspect.getsource(WayneTelegramBot._leave_dongzhu)
    assert "已離開" in leave
    assert MENU_BTN_LEAVE_DONGZHU == "離開洞燭先機"
    menu = inspect.getsource(WayneTelegramBot._dongzhu_reply_menu)
    assert MENU_BTN_LEAVE_DONGZHU in menu


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
