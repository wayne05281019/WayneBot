# -*- coding: utf-8 -*-
"""說明書：第一次用三步、紀律白話、按錯導回、Telegram 切塊與 HTML。"""
from __future__ import annotations

import re

from bot_servers import HELP_TOPICS, WayneTelegramBot
from tg_layout import chunk_telegram_html


def test_guide_starts_with_three_steps_in_first_chunk():
    guide = HELP_TOPICS["guide"]
    chunks = chunk_telegram_html(guide)
    assert chunks, "總覽不該是空的"
    first = chunks[0]
    assert first.index("第一次用") < first.index("挑股")
    assert "直接打四碼" in first
    assert "⌨️" in first
    assert "四格" in first
    assert "圖下面" in first or "圖下方" in first
    assert "一次只出一張" in first
    assert "第 2 張" in first
    assert len(chunks) == 1, "總覽應一則看完，不要切成兩則"


def test_stock_help_has_plain_discipline_notes():
    stock = HELP_TOPICS["stock"]
    assert "粉紅" in stock or "紀律" in stock
    assert "先別追" in stock
    assert "先出一點" in stock
    assert "不是買訊" in stock
    assert "現在高點跟熱度都退了" in stock
    assert "現在價到高了" in stock
    assert "現在很熱但價沒過前高" in stock
    assert "現在高點跟熱度都沒了" in stock
    assert "月K一句" in stock
    assert "不改海選" in stock
    assert "200股" in HELP_TOPICS["buy"]
    assert "留現金" in HELP_TOPICS["guide"]
    assert "預留" not in HELP_TOPICS["guide"]
    assert "官方收盤掃" in HELP_TOPICS["guide"]
    assert "平常最多 1 份" in HELP_TOPICS["row1"]
    assert "最多 3 檔" not in HELP_TOPICS["guide"]
    assert "最多 3 檔" not in HELP_TOPICS["row1"]
    assert "最多 3 檔" not in HELP_TOPICS["ai"]


def test_screen_help_separates_two_line_doors():
    screen = HELP_TOPICS["screen"]
    assert "開 LINE・傳這檔" in screen
    assert "一鍵傳 LINE" in screen
    assert "只傳這一檔" in screen
    assert "勾選" in screen
    pos_one = screen.index("開 LINE・傳這檔")
    pos_pack = screen.index("一鍵傳 LINE")
    assert pos_one != pos_pack


def test_oops_covers_streak_report_not_found_weekend():
    oops = HELP_TOPICS["oops"]
    assert "連買" in oops
    assert "回報" in oops
    assert "找不到股票" in oops or "再打一次四碼" in oops
    assert "海選" in oops and "隔日沖" in oops
    assert "當沖" in oops
    assert "圖下面" in oops or "圖下方" in oops
    assert "oops" in HELP_TOPICS
    guide = HELP_TOPICS["guide"]
    assert "連買選到一半" in guide
    assert "改按其他按鈕即可" in guide


def test_help_html_tags_balanced_and_no_wide_pad():
    pad = re.compile(r"^(產業|同業|單位|用途)\s{3,}", re.M)
    for key, body in HELP_TOPICS.items():
        for tag in ("b", "code", "i"):
            open_n = len(re.findall(fr"<{tag}>", body))
            close_n = len(re.findall(fr"</{tag}>", body))
            assert open_n == close_n, f"{key} <{tag}> {open_n}/{close_n}"
        assert pad.search(body) is None, key
        assert "曆日" not in body
        chunks = chunk_telegram_html(body)
        assert all(len(c) <= 3500 for c in chunks), key


def test_help_nav_has_oops_and_no_reply_overlap():
    bot = WayneTelegramBot.__new__(WayneTelegramBot)
    kb = bot._help_nav_keyboard()
    labels = [btn.text for row in kb.inline_keyboard for btn in row]
    assert labels.count("按錯") == 1
    assert len(kb.inline_keyboard) == 3
    assert [b.text for b in kb.inline_keyboard[0]] == ["總覽", "查股", "圖文"]
    assert [b.text for b in kb.inline_keyboard[2]] == ["記買入", "按錯", "✕"]
    reply = {btn.text for row in bot._reply_menu().keyboard for btn in row}
    overlap = reply & set(labels)
    assert overlap == set(), overlap
    assert "圖文" in HELP_TOPICS["row2"]
    assert "圖文" in HELP_TOPICS["guide"]


def test_row2_help_page_explains_help_button():
    row2 = HELP_TOPICS["row2"]
    assert "④ 說明" in row2
    assert "/help" in row2
    assert "按錯" in row2
    assert row2.count("\n") >= 8


def test_start_cmd_leads_with_three_steps():
    import inspect

    from bot_servers import WayneTelegramBot

    src = inspect.getsource(WayneTelegramBot.start_cmd)
    assert "第一次用，先做這三步" in src
    assert "直接打四碼" in src
    assert "圖下面" in src
    assert "圖文" in src
    assert "按錯" in src


def test_pick_and_decision_are_first_time_friendly():
    assert "不要先按" in HELP_TOPICS["pick"]
    assert "直接打四碼" in HELP_TOPICS["decision"]
    assert "第一次用" in HELP_TOPICS["menu"]
