# -*- coding: utf-8 -*-
"""兩排主選單與本機圖文 9 頁仍對齊；話筒說明頁已取消。"""
from __future__ import annotations

from bot_servers import (
    HELP_TOPICS,
    MENU_BTN_AI,
    MENU_BTN_BIAOKE_FACE,
    MENU_BTN_LEAVE_ZERO,
    MENU_BTN_MARKET,
    MENU_BTN_DONGZHU,
    MENU_BTN_STREAK,
    MENU_LAYOUT_VERSION,
    WayneTelegramBot,
)
from picture_guide import PAGE_SLUGS, page_copy_blob

ROW1 = ["海選", "持股", "觀察", MENU_BTN_BIAOKE_FACE, MENU_BTN_MARKET, "資金"]
ROW2_LABELS = ["當沖", "隔日沖", MENU_BTN_AI, MENU_BTN_STREAK, MENU_BTN_LEAVE_ZERO, MENU_BTN_DONGZHU]
GUIDE_PAGE_ORDER = (
    "cover",
    "menu",
    "lookup",
    "lists",
    "screen",
    "sell",
    "lowbuy",
    "more",
    "oops",
)


def test_reply_keyboard_matches_picture_copy():
    assert HELP_TOPICS == {}
    bot = WayneTelegramBot.__new__(WayneTelegramBot)
    kb = bot._reply_menu()
    row1 = [b.text for b in kb.keyboard[0]]
    row2 = [b.text for b in kb.keyboard[1]]
    assert row1 == ROW1
    assert row2 == ROW2_LABELS
    assert row2[5] == MENU_BTN_DONGZHU
    assert MENU_LAYOUT_VERSION == "28"
    blob = page_copy_blob()
    assert "海選　持股　觀察　飆大　台股大盤　資金" in blob
    assert "當沖　隔日沖　AI倉　連買區　剛脫離零　洞燭先機" in blob
    assert "一張圖卡" in blob
    assert "講人話" not in blob


def test_picture_guide_page_order_is_first_use_then_lookup():
    """九頁順序：先叫鍵盤 → 查股兩張圖 → 三種清單 → 海選怎麼用 → 如何賣 → 如何低買 → 其餘鈕 → 按錯。"""
    assert tuple(PAGE_SLUGS) == GUIDE_PAGE_ORDER
    assert PAGE_SLUGS[0] == "cover"
    assert PAGE_SLUGS[1] == "menu"
    assert PAGE_SLUGS.index("lookup") < PAGE_SLUGS.index("lists")
    assert PAGE_SLUGS.index("lists") < PAGE_SLUGS.index("screen")
    assert PAGE_SLUGS.index("screen") < PAGE_SLUGS.index("sell")
    assert PAGE_SLUGS.index("sell") < PAGE_SLUGS.index("lowbuy")
    assert PAGE_SLUGS.index("lowbuy") < PAGE_SLUGS.index("more")
    assert PAGE_SLUGS[-1] == "oops"
    blob = page_copy_blob()
    assert blob.index("第一次用") < blob.index("兩排主選單在哪")
    assert blob.index("查一檔") < blob.index("三種清單不要搞混")
    assert blob.index("三種清單不要搞混") < blob.index("海選怎麼用")
    assert blob.index("海選怎麼用") < blob.index("如何賣")
    assert blob.index("如何賣") < blob.index("如何低買")
    assert blob.index("如何低買") < blob.index("大盤頁")
    assert blob.index("大盤頁") < blob.index("按錯了怎麼辦")
    assert "用平常話問原因" not in blob
    assert "一共 9 張" in blob or "共 9 張" in blob
    assert "現在共 9 張" in blob


def test_how_to_sell_and_daily_clock_are_in_pictures():
    blob = page_copy_blob()
    assert "如何賣" in blob
    assert "如何低買" in blob
    assert "最高價＝20日高" in blob
    for clock in ("06:30", "12:45", "16:30", "20:00"):
        assert clock in blob, clock
    assert "16:45" not in blob
    assert "台股休市當日" in blob
    assert "美股當天沒開" in blob
    assert "北市全日" in blob
