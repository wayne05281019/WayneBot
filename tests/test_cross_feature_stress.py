# -*- coding: utf-8 -*-
"""功能交叉：家人同時按選單／說明／海選閘門；AI 永遠留現金。"""
from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from bot_servers import (
    HELP_TOPICS,
    MENU_BTN_AI,
    MENU_BTN_MARKET,
    MENU_BTN_REPORT,
    MENU_BTN_STREAK,
    WayneTelegramBot,
)
from picture_guide import PAGE_HEIGHT, PAGE_WIDTH, PAGES, render_page


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
        assert row2[-3:] == [MENU_BTN_STREAK, "說明", MENU_BTN_REPORT]
        await bot._reply_help_topic(msg, "guide")
        await bot._reply_help_topic(msg, "row2")
        return uid, bot._actor_key(msg)

    async def run():
        rows = await asyncio.gather(*[one(9000 + i) for i in range(20)])
        keys = [k for _, k in rows]
        assert len(set(keys)) == 20
        assert MENU_BTN_AI in [b.text for b in bot._reply_menu().keyboard[0]]
        assert MENU_BTN_MARKET in [b.text for b in bot._reply_menu().keyboard[1]]

    asyncio.run(run())
    assert "④ 連買區" in HELP_TOPICS["row2"]


def test_screening_gate_blocks_second_family_member():
    bot = _bot()
    bot._screening_global_owner = "111:9001"
    bot._screening_running.add("111:9001")

    async def run():
        busy = _msg(9001, "海選")
        busy.chat_id = 111
        other = _msg(9002, "海選")
        other.chat_id = 111
        await bot._run_manual_screening(busy)
        await bot._run_manual_screening(other)
        texts = []
        for m in (busy, other):
            for call in m.reply_text.await_args_list + m.reply_html.await_args_list:
                args = call.args or ()
                texts.append(str(args[0] if args else call.kwargs.get("text") or ""))
        blob = "\n".join(texts)
        assert "海選進行中" in blob
        assert "海選正在掃描全市場" in blob
        bot.screener.run_full_screening.assert_not_called()

    asyncio.run(run())


def test_ai_deploy_cap_never_fills_all_three_slots():
    from ai_trader import CORE_SLOTS, DIP_SLOTS, MAX_SLOTS, market_deploy_cap

    assert CORE_SLOTS + DIP_SLOTS < MAX_SLOTS
    with patch("taiwan_market.analyze_taiwan_market", return_value={"ok": False}):
        assert market_deploy_cap("x.db", "20260907", {"leave_zero": [{"stock_id": "2330"}]}) == 1
    with patch(
        "taiwan_market.analyze_taiwan_market",
        return_value={"ok": True, "regime": "bear", "falling_risk": 80, "vs_ma20_pct": -3},
    ):
        cap = market_deploy_cap(
            "x.db",
            "20260907",
            {"leave_zero": [{"stock_id": "2330"}], "golden_buy": [{"stock_id": "2303"}]},
        )
        assert cap == 2
        assert cap < MAX_SLOTS


def test_help_and_two_guide_pages_parallel_under_deadline(tmp_path):
    import time

    slug_a, title_a, body_a = PAGES[1]
    slug_b, title_b, body_b = PAGES[4]
    out_a = str(tmp_path / "menu.png")
    out_b = str(tmp_path / "discipline.png")
    t0 = time.perf_counter()
    with ThreadPoolExecutor(max_workers=2) as pool:
        fa = pool.submit(render_page, slug_a, title_a, body_a, out_a)
        fb = pool.submit(render_page, slug_b, title_b, body_b, out_b)
        fa.result()
        fb.result()
    wall = time.perf_counter() - t0
    from PIL import Image

    for path in (out_a, out_b):
        with Image.open(path) as im:
            assert im.size == (PAGE_WIDTH, PAGE_HEIGHT)
    assert wall < 25.0, f"兩頁並行太慢 {wall:.2f}s"
