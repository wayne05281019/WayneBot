# -*- coding: utf-8 -*-
"""說明書、圖文、兩排主選單必須講同一套按鈕與頁序。"""
from __future__ import annotations

from bot_servers import (
    HELP_TOPICS,
    MENU_BTN_AI,
    MENU_BTN_CARD,
    MENU_BTN_MARKET,
    MENU_BTN_REPORT,
    MENU_BTN_STREAK,
    MENU_LAYOUT_VERSION,
    WayneTelegramBot,
)
from picture_guide import PAGE_SLUGS, page_copy_blob

ROW1 = ["說明", "海選", "持股", "觀察", MENU_BTN_CARD, MENU_BTN_REPORT]
ROW2 = [MENU_BTN_MARKET, "資金", "當沖", "隔日沖", MENU_BTN_AI, MENU_BTN_STREAK]
GUIDE_PAGE_ORDER = (
    "cover",
    "menu",
    "lookup",
    "lists",
    "screen",
    "sell",
    "more",
    "oops",
)


def test_reply_keyboard_matches_help_and_picture_copy():
    bot = WayneTelegramBot.__new__(WayneTelegramBot)
    kb = bot._reply_menu()
    row1 = [b.text for b in kb.keyboard[0]]
    row2 = [b.text for b in kb.keyboard[1]]
    assert row1 == ROW1
    assert row2 == ROW2
    assert MENU_LAYOUT_VERSION == "14"

    guide = HELP_TOPICS["guide"]
    menu = HELP_TOPICS["menu"]
    row1_help = HELP_TOPICS["row1"]
    row2_help = HELP_TOPICS["row2"]
    blob = page_copy_blob()
    assert "連買區" in guide and "說明" in guide
    assert "說明／海選" in menu or "說明／海選／持股" in menu
    assert row1_help.index("① 說明") < row1_help.index("② 海選")
    assert row2_help.index("① 大盤") < row2_help.index("⑥ 連買區")
    assert "說明　海選　持股　觀察　刷新　回報" in blob
    assert "大盤　資金　當沖　隔日沖　AI倉　連買區" in blob
    assert "一張圖卡" in blob
    assert "圖卡" in HELP_TOPICS["industry"]
    assert "小框" in HELP_TOPICS["industry"]
    assert "講人話" not in HELP_TOPICS["industry"]


def test_picture_guide_page_order_is_first_use_then_lookup():
    """八頁順序：先叫鍵盤 → 查股三張圖 → 三種清單 → 海選轉 LINE → 如何賣 → 其餘鈕／原因 → 按錯。"""
    assert tuple(PAGE_SLUGS) == GUIDE_PAGE_ORDER
    assert PAGE_SLUGS[0] == "cover"
    assert PAGE_SLUGS[1] == "menu"
    assert PAGE_SLUGS.index("lookup") < PAGE_SLUGS.index("lists")
    assert PAGE_SLUGS.index("lists") < PAGE_SLUGS.index("screen")
    assert PAGE_SLUGS.index("screen") < PAGE_SLUGS.index("sell")
    assert PAGE_SLUGS.index("sell") < PAGE_SLUGS.index("more")
    assert PAGE_SLUGS[-1] == "oops"
    blob = page_copy_blob()
    assert blob.index("第一次用") < blob.index("兩排主選單在哪")
    assert blob.index("查一檔") < blob.index("三種清單不要搞混")
    assert blob.index("三種清單不要搞混") < blob.index("海選怎麼轉 LINE")
    assert blob.index("海選怎麼轉 LINE") < blob.index("如何賣")
    assert blob.index("如何賣") < blob.index("大盤頁")
    assert blob.index("大盤頁") < blob.index("按錯了怎麼辦")
    assert blob.index("大盤頁") < blob.index("用平常話問原因")
    assert "一共 8 張" in HELP_TOPICS["guide"] or "共 8 張" in blob
    assert "現在共 8 張" in blob


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
    assert "16:45" not in guide
    assert "16:45" not in blob
    assert "台股休市當日" in guide
    assert "台股休市當日" in blob
    assert "美股當天沒開" in blob
    assert "北市全日" in blob


def test_ai_help_stays_simulated_not_broker_injection():
    ai = HELP_TOPICS["ai"]
    assert "不會真的下單" in ai
    assert "量化積木" in ai
    assert "不能把這支程式塞進" in ai
    assert "place_order" not in ai
    assert "Neo" not in ai


def test_family_invite_is_in_help():
    guide = HELP_TOPICS["guide"]
    assert "t.me/WC_ai_trade_bot" in guide
    assert "按<b>開始</b>" in guide or "按開始" in guide
    assert "不要拉進同一個群組" in guide
    assert "各看各的" in guide
    assert "06:30" in guide and "各寄一份" in guide
