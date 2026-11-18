# -*- coding: utf-8 -*-
"""飆大鍵附遠窗大盤圖：夠新就直接送、兩人同按只畫一次、出不來要明講。"""
from __future__ import annotations

import asyncio
import os
import sqlite3
import tempfile
import threading
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch
from zoneinfo import ZoneInfo

from PIL import Image

from bot_servers import WayneTelegramBot


def _bot(td: str) -> WayneTelegramBot:
    bot = WayneTelegramBot.__new__(WayneTelegramBot)
    bot.db_path = os.path.join(td, "m.db")
    con = sqlite3.connect(bot.db_path)
    con.execute("CREATE TABLE biaoke_posts (id TEXT, date TEXT, time TEXT, kind TEXT)")
    con.execute("INSERT INTO biaoke_posts VALUES ('1','2026-11-18','16:48','post')")
    con.commit()
    con.close()
    return bot


def _far_png(td: str) -> str:
    p = os.path.join(td, "far.png")
    Image.frombytes("RGB", (900, 600), os.urandom(900 * 600 * 3)).save(p, "PNG")
    return p


def _msg():
    m = MagicMock()
    m.reply_photo = AsyncMock()
    m.reply_text = AsyncMock()
    m.chat = MagicMock()
    m.chat.send_action = AsyncMock()
    return m


def _common(bot):
    return [
        patch.object(bot, "_start_plain_wait", AsyncMock(return_value=(None, None, None))),
        patch.object(bot, "_stop_plain_wait", AsyncMock()),
        patch.object(bot, "_biaoke_reply_menu", return_value=None),
        patch("biaoke_level_learn._build_live_pack", return_value={}),
        patch("biaoke_level_learn._wave_now_ladder", return_value={}),
    ]


def _run(bot, msg, extra):
    async def go():
        await bot._send_biaoke_teach_charts(msg, "111")

    ps = _common(bot) + extra
    for p in ps:
        p.start()
    try:
        asyncio.run(go())
    finally:
        for p in reversed(ps):
            p.stop()


def test_fresh_stored_far_sent_without_repaint():
    td = tempfile.mkdtemp()
    bot = _bot(td)
    far = _far_png(td)
    now = datetime.now(ZoneInfo("Asia/Taipei")).strftime("%Y-%m-%dT%H:%M:%S")
    kit = {"far_path": far, "as_of": "20261118", "created_at": now, "thesis": "t"}
    paint = MagicMock()
    msg = _msg()
    _run(
        bot,
        msg,
        [
            patch("biaoke_level_learn.latest_teach_kit", return_value=kit),
            patch("biaoke_level_learn._twii_chart_as_of", return_value="20261118"),
            patch("biaoke_level_learn.paint_open_day_hypothesis", paint),
        ],
    )
    paint.assert_not_called()
    assert msg.reply_photo.await_count == 1


def test_stale_kit_older_than_latest_post_repaints():
    td = tempfile.mkdtemp()
    bot = _bot(td)
    far = _far_png(td)
    kit = {"far_path": far, "as_of": "20261118", "created_at": "2026-11-18T16:00:00"}
    with patch("biaoke_level_learn.latest_teach_kit", return_value=kit), patch(
        "biaoke_level_learn._twii_chart_as_of", return_value="20261118"
    ):
        assert bot._fresh_biaoke_far_kit() == {}


def test_paint_fail_and_no_stored_says_why():
    td = tempfile.mkdtemp()
    bot = _bot(td)
    msg = _msg()
    _run(
        bot,
        msg,
        [
            patch("biaoke_level_learn.latest_teach_kit", return_value={}),
            patch("biaoke_level_learn._twii_chart_as_of", return_value="20261118"),
            patch(
                "biaoke_level_learn.paint_open_day_hypothesis",
                return_value={"ok": False, "error": "stamp_preflight"},
            ),
        ],
    )
    msg.reply_photo.assert_not_awaited()
    txt = msg.reply_text.await_args.args[0]
    assert "大盤遠窗圖這次沒出" in txt and "官方柱戳日沒對上" in txt


def test_two_presses_share_one_paint():
    td = tempfile.mkdtemp()
    bot = _bot(td)
    calls = []
    gate = threading.Event()

    def slow_paint(*_a, **_k):
        calls.append(1)
        gate.wait(5)
        return {"ok": True, "far_path": "x"}

    async def go():
        with patch("biaoke_level_learn.paint_open_day_hypothesis", slow_paint):
            t1 = asyncio.create_task(bot._biaoke_far_paint_shared())
            await asyncio.sleep(0.05)
            t2 = asyncio.create_task(bot._biaoke_far_paint_shared())
            await asyncio.sleep(0.05)
            gate.set()
            return await t1, await t2

    a, b = asyncio.run(go())
    assert len(calls) == 1 and a == b
