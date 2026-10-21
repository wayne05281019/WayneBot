# -*- coding: utf-8 -*-
"""功能交叉：家人同時按選單／說明／海選閘門；AI 永遠留現金。"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from bot_servers import (
    HELP_TOPICS,
    MENU_BTN_AI,
    MENU_BTN_LEAVE_ZERO,
    MENU_BTN_MARKET,
    MENU_BTN_DONGZHU,
    MENU_BTN_STREAK,
    WayneTelegramBot,
)


def _msg(uid: int, text: str = ""):
    user = SimpleNamespace(id=uid, first_name="u")
    chat = SimpleNamespace(id=uid)
    message = MagicMock()
    message.chat_id = uid
    message.chat = chat
    message.from_user = user
    message.text = text
    message.reply_text = AsyncMock(return_value=MagicMock(delete=AsyncMock(), edit_text=AsyncMock()))
    message.reply_html = AsyncMock(return_value=MagicMock(delete=AsyncMock()))
    message.reply_photo = AsyncMock()
    return message


def _bot():
    bot = WayneTelegramBot.__new__(WayneTelegramBot)
    bot.db_path = "data/isolated.db"
    bot.charts_dir = "data/charts"
    bot._pending = {}
    bot._last_card = {}
    bot._lookup_ctx = {}
    bot._menu_fade_msgs = {}
    bot._lookup_fade_msgs = {}
    bot._screening_msgs = {}
    bot._line_pack_status_msgs = {}
    bot._help_msgs = {}
    bot._lookup_locks = {}
    bot._pending_locks = {}
    bot._lookup_op_state = {}
    bot._screening_running = set()
    bot._screening_gate = asyncio.Lock()
    bot._screening_global_owner = ""
    bot._menu_fade_gen = {}
    bot._menu_pin_msgs = {}
    bot._menu_pin_at = {}
    bot._touch_user = MagicMock()
    bot._dismiss_menu_transients = AsyncMock()
    bot._dismiss_help_msgs = AsyncMock()
    bot._transient_status = AsyncMock(return_value=MagicMock())
    bot._delete_message = AsyncMock()
    bot.screener = MagicMock()
    bot.portfolio_engine = MagicMock()
    return bot


def test_twenty_users_menu_and_help_do_not_share_state():
    bot = _bot()

    async def one(uid: int):
        msg = _msg(uid, "說明")
        kb = bot._reply_menu()
        row2 = [b.text for b in kb.keyboard[1]]
        assert row2[-2] == MENU_BTN_LEAVE_ZERO
        assert row2[-1] == MENU_BTN_DONGZHU
        await bot._reply_help_topic(msg, "guide")
        await bot._reply_help_topic(msg, "row2")
        return uid, bot._actor_key(msg)

    async def run():
        rows = await asyncio.gather(*[one(9000 + i) for i in range(20)])
        keys = [k for _, k in rows]
        assert len(set(keys)) == 20
        assert MENU_BTN_AI in [b.text for b in bot._reply_menu().keyboard[1]]
        assert MENU_BTN_MARKET in [b.text for b in bot._reply_menu().keyboard[0]]

    asyncio.run(run())
    assert HELP_TOPICS == {}


def test_screening_gate_blocks_second_family_member():
    bot = _bot()
    bot._screening_build_task = None
    bot._screening_global_owner = "111:9001"
    bot._screening_running.add("111:9001")

    async def run():
        # 偉權已佔閘：哥哥按海選→第一則仍 LOADING，改口家人忙，不准開第二輪全掃。
        other = _msg(9002, "海選")
        other.chat_id = 111
        await bot._run_manual_screening(other)
        texts = []
        for call in other.reply_text.await_args_list + other.reply_html.await_args_list:
            args = call.args or ()
            texts.append(str(args[0] if args else call.kwargs.get("text") or ""))
        status = other.reply_text.return_value
        for call in getattr(status, "edit_text", MagicMock()).await_args_list or []:
            args = call.args or ()
            texts.append(str(args[0] if args else ""))
        blob = "\n".join(texts)
        assert "LOADING" in blob or "海選進行中" in blob
        assert "海選正在掃描全市場" in blob
        bot.screener.run_full_screening.assert_not_called()

    asyncio.run(run())


def test_ai_deploy_cap_is_max_three_active_names():
    """操作桶最多 3 檔；抄底動保留額、不另開無限槽。不准牽連其他鈕。"""
    from ai_trader import ACTIVE_BUDGET, DIP_RESERVE, MAX_ACTIVE_NAMES, TOTAL_CAPITAL, market_deploy_cap

    assert TOTAL_CAPITAL == ACTIVE_BUDGET + DIP_RESERVE
    assert market_deploy_cap("x.db", "20261013", {}) == MAX_ACTIVE_NAMES
    assert (
        market_deploy_cap(
            "x.db",
            "20261013",
            {"leave_zero": [{"stock_id": "2330"}], "golden_buy": [{"stock_id": "2303"}]},
        )
        == MAX_ACTIVE_NAMES
    )


def test_picture_guide_gone_but_phone_stubs_remain():
    import importlib.util

    assert importlib.util.find_spec("picture_guide") is None
    bot = WayneTelegramBot.__new__(WayneTelegramBot)
    assert not bot._picture_guide_keyboard(0, 9).inline_keyboard
    src = open("bot_servers.py", encoding="utf-8").read()
    assert "_send_picture_guide" in src
    assert 'startswith("pg:")' in src
