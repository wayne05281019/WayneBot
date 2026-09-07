# -*- coding: utf-8 -*-
"""說明書、圖文、兩排主選單必須講同一套按鈕與頁序。"""
from __future__ import annotations

from bot_servers import (
    HELP_TOPICS,
    MENU_BTN_AI,
    MENU_BTN_MARKET,
    MENU_BTN_REPORT,
    MENU_BTN_STREAK,
    MENU_LAYOUT_VERSION,
    WayneTelegramBot,
)
from picture_guide import PAGE_SLUGS, page_copy_blob

ROW1 = ["決策卡", "當沖", "持股", "觀察", "海選", MENU_BTN_AI]
ROW2 = ["隔日沖", MENU_BTN_MARKET, "資金", MENU_BTN_STREAK, "說明", MENU_BTN_REPORT]
GUIDE_PAGE_ORDER = (
    "cover",
    "menu",
    "charts",
    "hub",
    "discipline",
    "screen",
    "lists",
    "streak",
    "oops",
)


def test_reply_keyboard_matches_help_and_picture_copy():
    bot = WayneTelegramBot.__new__(WayneTelegramBot)
    kb = bot._reply_menu()
    row1 = [b.text for b in kb.keyboard[0]]
    row2 = [b.text for b in kb.keyboard[1]]
    assert row1 == ROW1
    assert row2 == ROW2
    assert MENU_LAYOUT_VERSION == "11"

    guide = HELP_TOPICS["guide"]
    menu = HELP_TOPICS["menu"]
    row2_help = HELP_TOPICS["row2"]
    blob = page_copy_blob()
    assert "連買區" in guide and "說明" in guide
    assert "<b>連買區</b>｜<b>說明</b>" in guide
    assert "連買區／說明" in menu
    assert row2_help.index("④ 連買區") < row2_help.index("⑤ 說明")
    assert "隔日沖　大盤　資金　連買區　說明　回報" in blob
    assert "一張圖卡" in blob
    assert "跑馬燈" in blob
    assert "圖卡" in HELP_TOPICS["industry"]
    assert "小框" in HELP_TOPICS["industry"]
    assert "講人話" not in HELP_TOPICS["industry"]


def test_picture_guide_page_order_is_first_use_then_lookup():
    """九頁順序：先叫鍵盤 → 查股三張圖 → 紀律／海選 → 三種清單 → 連買 → 按錯。"""
    assert tuple(PAGE_SLUGS) == GUIDE_PAGE_ORDER
    assert PAGE_SLUGS[0] == "cover"
    assert PAGE_SLUGS[1] == "menu"
    assert PAGE_SLUGS.index("charts") < PAGE_SLUGS.index("hub")
    assert PAGE_SLUGS.index("discipline") < PAGE_SLUGS.index("screen")
    assert PAGE_SLUGS.index("lists") < PAGE_SLUGS.index("streak")
    assert PAGE_SLUGS[-1] == "oops"
    blob = page_copy_blob()
    assert blob.index("第一次用") < blob.index("兩排主選單在哪")
    assert blob.index("查一檔") < blob.index("海選怎麼轉 LINE")
    assert blob.index("海選怎麼轉 LINE") < blob.index("三種清單不要搞混")
    assert blob.index("三種清單不要搞混") < blob.index("按錯了怎麼辦")


def test_how_to_sell_and_daily_clock_are_in_help_and_pictures():
    stock = HELP_TOPICS["stock"]
    guide = HELP_TOPICS["guide"]
    blob = page_copy_blob()
    assert "如何賣" in stock and "如何賣" in blob
    assert "最高價＝20日高" in stock and "最高價＝20日高" in blob
    assert "不自動賣" in stock
    for clock in ("06:30", "12:45", "16:30", "20:00"):
        assert clock in guide, clock
        assert clock in blob, clock


def test_ai_help_stays_simulated_not_broker_injection():
    ai = HELP_TOPICS["ai"]
    assert "不會真的下單" in ai
    assert "量化積木" in ai
    assert "不能把這支程式塞進" in ai
    assert "place_order" not in ai
    assert "Neo" not in ai
