# -*- coding: utf-8 -*-
"""兩排主選單對齊；圖文說明模組已清，只鎖鍵盤與取消狀態。"""
from __future__ import annotations

import importlib.util

from bot_servers import (
    HELP_TOPICS,
    MENU_BTN_AI,
    MENU_BTN_BIAOKE_FACE,
    MENU_BTN_FLOW,
    MENU_BTN_LEAVE_ZERO,
    MENU_BTN_MARKET,
    MENU_BTN_DONGZHU,
    MENU_BTN_PRESSURE,
    MENU_BTN_STREAK,
    MENU_LAYOUT_VERSION,
    WayneTelegramBot,
    MENU_BTN_WATCH,
)

ROW1 = ["勝率買點", "海選", "持股", MENU_BTN_WATCH, MENU_BTN_BIAOKE_FACE, MENU_BTN_MARKET, MENU_BTN_FLOW]
ROW2_LABELS = ["當沖", "隔日沖", MENU_BTN_PRESSURE, MENU_BTN_AI, MENU_BTN_STREAK, MENU_BTN_LEAVE_ZERO, MENU_BTN_DONGZHU]


def test_reply_keyboard_matches_menu_layout():
    assert HELP_TOPICS == {}
    assert importlib.util.find_spec("picture_guide") is None
    bot = WayneTelegramBot.__new__(WayneTelegramBot)
    kb = bot._reply_menu()
    row1 = [b.text for b in kb.keyboard[0]]
    row2 = [b.text for b in kb.keyboard[1]]
    assert row1 == ROW1
    assert row2 == ROW2_LABELS
    assert row2[2] == MENU_BTN_PRESSURE
    assert row2[-1] == MENU_BTN_DONGZHU
    assert MENU_LAYOUT_VERSION == "33"


def test_picture_guide_cancelled_stubs_remain():
    bot = WayneTelegramBot.__new__(WayneTelegramBot)
    assert not bot._picture_guide_keyboard(0, 9).inline_keyboard
    src = open("bot_servers.py", encoding="utf-8").read()
    assert "_send_picture_guide" in src
    assert "_show_picture_guide_page" in src
    assert 'startswith("pg:")' in src
