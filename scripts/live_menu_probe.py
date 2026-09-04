#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""真實 handler + 生產 DB：模擬五角色按主選單，記錄回應與耗時。"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

PERSONAS = [
    ("偉權", 9001, ["決策卡", "大盤", "資金", "海選"]),
    ("哥哥", 9002, ["觀察", "大盤", "持股"]),
    ("新手", 9003, ["連買區", "說明", "大盤", "資金"]),
    ("不懂股", 9004, ["股票", "asdf", "持股"]),
    ("亂按", 9005, ["大盤", "資金", "大盤"]),
]


def _msg(uid: int, text: str):
    user = SimpleNamespace(id=uid, first_name="probe")
    chat = SimpleNamespace(id=99)
    message = MagicMock()
    message.chat_id = 99
    message.chat = chat
    message.from_user = user
    message.text = text
    message.reply_text = AsyncMock(return_value=MagicMock(delete=AsyncMock()))
    message.reply_html = AsyncMock(return_value=MagicMock(delete=AsyncMock()))
    message.reply_photo = AsyncMock()
    # bot_servers._send_lookup_album 會 await reply_media_group
    message.reply_media_group = AsyncMock(return_value=MagicMock())
    return message


def _update(message):
    return SimpleNamespace(message=message, effective_user=message.from_user)


async def _probe_button(bot, uid: int, label: str) -> dict:
    from bot_servers import WayneTelegramBot

    msg = _msg(uid, label)
    msg.reply_text.reset_mock()
    msg.reply_html.reset_mock()
    t0 = time.time()
    err = None
    try:
        bot._menu_layout_ok = MagicMock(return_value=True)
        await bot.on_text(_update(msg), MagicMock())
    except Exception as e:
        err = str(e)
    elapsed = round(time.time() - t0, 2)
    texts = []
    for call in msg.reply_text.await_args_list:
        if call[0]:
            texts.append(str(call[0][0])[:200])
    htmls = []
    for call in msg.reply_html.await_args_list:
        if call[0]:
            htmls.append(str(call[0][0])[:300])
    ack_3s = elapsed <= 3.0 and (bool(texts) or bool(htmls))
    return {
        "button": label,
        "elapsed_s": elapsed,
        "ack_within_3s": ack_3s,
        "reply_text": texts,
        "reply_html_preview": htmls,
        "error": err,
        "ok": err is None and (bool(texts) or bool(htmls)),
    }


async def main():
    from bot_servers import WayneTelegramBot
    from config import get_db_path

    db = get_db_path()
    if not db or not os.path.isfile(db):
        print(json.dumps({"error": "no production db", "path": db}, ensure_ascii=False))
        return 1

    bot = WayneTelegramBot.__new__(WayneTelegramBot)
    bot.db_path = db
    bot.charts_dir = os.environ.get("WAYNE_CHARTS_DIR", "data/charts")
    bot._pending = {}
    bot._last_card = {"9001": "3105"}
    bot._lookup_ctx = {}
    bot._menu_fade_msgs = {}
    bot._lookup_fade_msgs = {}
    bot._screening_msgs = {}
    bot._line_pack_status_msgs = {}
    bot._help_msgs = {}
    bot._lookup_locks = {}
    bot._pending_locks = {}
    bot._screening_running = set()
    # 全域掃描鎖：避免多人/重度測試互相拖慢
    bot._screening_gate = asyncio.Lock()
    bot._screening_global_owner = ""
    bot._menu_fade_gen = {}
    bot._touch_user = MagicMock()
    bot.screener = MagicMock()
    bot.screener.screen_daytrade = MagicMock(return_value={"items": []})
    bot.screener.screen_overnight = MagicMock(return_value={"items": []})
    bot.screener.screen_morning = MagicMock(return_value={"items": []})
    bot.portfolio_engine = __import__("portfolio_engine").PortfolioEngine(db)

    report = {"db": db, "personas": []}
    for name, uid, buttons in PERSONAS:
        persona = {"name": name, "uid": uid, "results": []}
        for label in buttons:
            persona["results"].append(await _probe_button(bot, uid, label))
        report["personas"].append(persona)

    out = os.path.join(os.environ.get("WAYNE_ARTIFACT_DIR", "/opt/cursor/artifacts"), "live_menu_probe_report.json")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(out)
    fails = [
        f"{p['name']}/{r['button']}"
        for p in report["personas"]
        for r in p["results"]
        if not r["ok"]
    ]
    slow = [
        f"{p['name']}/{r['button']}:{r['elapsed_s']}s"
        for p in report["personas"]
        for r in p["results"]
        if r["elapsed_s"] > 25
    ]
    print("FAIL:", fails or "none")
    print("SLOW:", slow or "none")
    return 0 if not fails else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
