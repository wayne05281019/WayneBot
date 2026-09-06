# -*- coding: utf-8 -*-
"""主選單「回報」：文字／截圖寫進庫，偉權與哥哥互不干擾。"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from bot_servers import MENU_BTN_REPORT, WayneTelegramBot
from issue_reports import list_recent_issue_reports, save_issue_report
from wayne_db import init_database


def _msg(uid: int, text: str = "", *, caption: str = "", photo=None, document=None):
    user = SimpleNamespace(id=uid, first_name="哥" if uid == 9002 else "權")
    chat = SimpleNamespace(id=uid)
    message = MagicMock()
    message.chat_id = uid
    message.chat = chat
    message.from_user = user
    message.text = text
    message.caption = caption
    message.photo = photo or []
    message.document = document
    message.reply_text = AsyncMock(return_value=MagicMock(delete=AsyncMock()))
    message.reply_html = AsyncMock(return_value=MagicMock(delete=AsyncMock()))
    return message


def _update(message):
    return SimpleNamespace(message=message, effective_user=message.from_user)


def _bot(db_path: str):
    init_database(db_path)
    bot = WayneTelegramBot.__new__(WayneTelegramBot)
    bot.db_path = db_path
    bot.token = ""
    bot.chat_id = "9001"
    bot.charts_dir = "data/charts"
    bot._pending = {}
    bot._pending_locks = {}
    bot._last_card = {}
    bot._lookup_ctx = {}
    bot._menu_fade_msgs = {}
    bot._lookup_fade_msgs = {}
    bot._screening_msgs = {}
    bot._line_pack_status_msgs = {}
    bot._help_msgs = {}
    bot._lookup_locks = {}
    bot._screening_running = set()
    bot._menu_fade_gen = {}
    bot._menu_pin_msgs = {}
    bot._menu_layout_ok = MagicMock(return_value=True)
    bot._touch_user = MagicMock()
    bot._notify_owner_issue = MagicMock()
    return bot


def test_save_issue_report_roundtrip(tmp_path):
    db = str(tmp_path / "r.db")
    init_database(db)
    rec = save_issue_report(db, "9002", display_name="哥", body="大盤沒圖")
    assert rec["id"] >= 1
    rows = list_recent_issue_reports(db)
    assert rows[0]["body"] == "大盤沒圖"
    assert rows[0]["user_id"] == "9002"


def test_report_button_prompts_and_saves_text(tmp_path):
    db = str(tmp_path / "r.db")
    bot = _bot(db)
    msg = _msg(9002, MENU_BTN_REPORT)

    async def run():
        await bot.on_text(_update(msg), MagicMock())
        actor = f"{9002}:{9002}"
        assert bot._pending[actor] == "report"
        follow = _msg(9002, "按海選沒動")
        await bot.on_text(_update(follow), MagicMock())
        assert actor not in bot._pending or bot._pending.get(actor) != "report"

    asyncio.run(run())
    rows = list_recent_issue_reports(db)
    assert len(rows) == 1
    assert "海選" in rows[0]["body"]
    htmls = [str(c[0][0]) for c in msg.reply_html.await_args_list if c[0]]
    assert any("回報問題" in h for h in htmls)
    bot._notify_owner_issue.assert_called_once()


def test_report_photo_while_pending(tmp_path):
    db = str(tmp_path / "r.db")
    bot = _bot(db)
    actor = "9002:9002"
    bot._pending[actor] = "report"
    photo = [SimpleNamespace(file_id="AgFILE1")]
    msg = _msg(9002, caption="這張圖缺字", photo=photo)

    async def run():
        await bot.on_photo(_update(msg), MagicMock())

    asyncio.run(run())
    rows = list_recent_issue_reports(db)
    assert rows[0]["photo_file_id"] == "AgFILE1"
    assert "缺字" in rows[0]["body"]
    assert bot._pending.get(actor) != "report"


def test_stray_photo_without_pending_is_ignored(tmp_path):
    db = str(tmp_path / "r.db")
    bot = _bot(db)
    msg = _msg(9002, photo=[SimpleNamespace(file_id="AgX")])

    async def run():
        await bot.on_photo(_update(msg), MagicMock())

    asyncio.run(run())
    assert list_recent_issue_reports(db) == []
    msg.reply_html.assert_not_awaited()


def test_brother_report_does_not_steal_wayne_pending(tmp_path):
    db = str(tmp_path / "r.db")
    bot = _bot(db)
    bot._pending["9001:9001"] = "buy:2330"

    async def run():
        await bot.on_text(_update(_msg(9002, "回報")), MagicMock())
        await bot.on_text(_update(_msg(9002, "哥哥這邊數字怪")), MagicMock())

    asyncio.run(run())
    assert bot._pending["9001:9001"] == "buy:2330"
    rows = list_recent_issue_reports(db)
    assert rows[0]["user_id"] == "9002"


def test_help_covers_report_and_no_secret():
    from bot_servers import HELP_TOPICS

    blob = "\n".join(HELP_TOPICS.values())
    assert "回報" in blob
    assert "截圖" in blob
    assert "程式密鑰" in blob
    assert "TELEGRAM_BOT_TOKEN" not in blob
    assert "getUpdates" not in blob
