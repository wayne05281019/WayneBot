# -*- coding: utf-8 -*-
"""飆客獨立區：語料可查、不進海選。"""
from bot_servers import (
    MENU_BTN_BIAOKE,
    MENU_BTN_BIAOKE_FACE,
    MENU_BTN_SLOT,
    MENU_ROW1,
    MENU_ROW2,
    _normalize_menu_text,
    WayneTelegramBot,
)
from intent_router import parse_intent
from biaoke_desk import format_biaoke_desk_html, search_biaoke


def test_biaoke_button_is_circled_biaoda_top_right():
    assert MENU_BTN_BIAOKE == "飆大"
    assert MENU_BTN_BIAOKE_FACE == "飆\u20dd大\u20dd"
    assert _normalize_menu_text(MENU_BTN_BIAOKE_FACE) == "飆大"
    assert MENU_ROW1[-1] == MENU_BTN_BIAOKE_FACE
    assert MENU_ROW2[-1] == MENU_BTN_SLOT
    assert MENU_BTN_SLOT.strip() == ""
    bot = WayneTelegramBot.__new__(WayneTelegramBot)
    kb = bot._reply_menu()
    assert len(kb.keyboard) == 2
    face = [b.text for b in kb.keyboard[0]][-1]
    assert face == MENU_BTN_BIAOKE_FACE
    assert "\u20dd" in face
    assert _normalize_menu_text(face) == "飆大"
    assert [b.text for b in kb.keyboard[1]][-1].strip() == ""


def test_year_end_2025_was_memory_not_pcb():
    html = search_biaoke("去年年底")
    assert "記憶體" in html
    assert "南亞科" in html or "群聯" in html
    assert "專心做記憶體" in html or "記憶體" in html
    assert "2025-12-17" in html or "2025-12-18" in html


def test_progress_page_is_independent():
    html = format_biaoke_desk_html()
    assert "海選" in html and "無關" in html
    assert "細微波" in html
    assert "費半" in html
    assert "不是買訊" in html


def test_desk_has_three_options_not_a_tree():
    html = format_biaoke_desk_html()
    assert "怎麼觀察" in html
    assert "去年年底" in html
    assert "問一檔" in html
    assert "麥克風" in html
    assert "精簡六顆" in html


def test_intent_biaoke_keeps_query():
    hit = parse_intent("飆客 勤誠")
    assert hit.kind == "biaoke"
    assert "勤誠" in hit.query
    hit2 = parse_intent("飆大 去年年底")
    assert hit2.kind == "biaoke"
    assert "去年年底" in hit2.query
    hit3 = parse_intent(MENU_BTN_BIAOKE_FACE)
    assert hit3.kind == "biaoke"


def test_qincheng_hits_corpus_not_invented():
    html = search_biaoke("勤誠")
    assert "勤誠" in html
    assert "海選" not in html or "無關" in html or "語料" in html


def test_circled_face_routes_like_biaoda():
    import asyncio
    from types import SimpleNamespace
    from unittest.mock import AsyncMock, MagicMock

    bot = WayneTelegramBot.__new__(WayneTelegramBot)
    bot._reject_stranger = AsyncMock(return_value=False)
    bot._touch_user = MagicMock()
    bot._pending = {}
    bot._actor_key = MagicMock(return_value="1:1")
    bot._send_biaoke_page = AsyncMock()
    user = SimpleNamespace(id=1, first_name="u")
    msg = MagicMock()
    msg.from_user = user
    msg.text = MENU_BTN_BIAOKE_FACE
    msg.reply_text = AsyncMock()
    msg.reply_html = AsyncMock()
    upd = SimpleNamespace(message=msg, effective_user=user)
    asyncio.run(bot.on_text(upd, MagicMock()))
    bot._send_biaoke_page.assert_awaited()


def test_blank_slot_is_silent_no_lookup():
    import asyncio
    from types import SimpleNamespace
    from unittest.mock import AsyncMock, MagicMock

    bot = WayneTelegramBot.__new__(WayneTelegramBot)
    bot._reject_stranger = AsyncMock(return_value=False)
    bot._touch_user = MagicMock()
    user = SimpleNamespace(id=1, first_name="u")
    msg = MagicMock()
    msg.from_user = user
    msg.text = MENU_BTN_SLOT
    msg.reply_text = AsyncMock()
    msg.reply_html = AsyncMock()
    upd = SimpleNamespace(message=msg, effective_user=user)
    asyncio.run(bot.on_text(upd, MagicMock()))
    msg.reply_text.assert_not_awaited()
    msg.reply_html.assert_not_awaited()
