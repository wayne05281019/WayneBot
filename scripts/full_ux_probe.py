#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""全主選單 UX 探測：十顆按鈕 × 耗時／即時回饋／內容完整性。"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

ALL_MENU_BUTTONS = [
    "決策卡",
    "當沖",
    "持股",
    "觀察",
    "海選",
    "隔日沖",
    "資金",
    "說明",
    "連買區",
    "大盤",
]

SLOW_WARN_S = 8.0
SLOW_FAIL_S = 25.0
ACK_TARGET_S = 3.0

INCOMPLETE_MARKERS = (
    "失敗",
    "逾時",
    "查詢失敗",
    "尚未就緒",
    "無法複核",
    "請稍後",
    "error",
)


def _msg(uid: int, text: str):
    user = SimpleNamespace(id=uid, first_name="ux")
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
    message.reply_sticker = AsyncMock(return_value=MagicMock())
    return message


def _update(message):
    return SimpleNamespace(message=message, effective_user=message.from_user)


def _content_blob(texts: list, htmls: list) -> str:
    return "\n".join(texts + htmls)


async def _probe(bot, label: str) -> dict:
    msg = _msg(9100, label)
    t0 = time.time()
    first_at: float | None = None
    err = None
    try:
        bot._menu_layout_ok = MagicMock(return_value=True)
        await bot.on_text(_update(msg), MagicMock())
    except Exception as e:
        err = str(e)
    elapsed = round(time.time() - t0, 2)

    texts, htmls = [], []
    for call in msg.reply_text.await_args_list:
        if call[0]:
            texts.append(str(call[0][0]))
            if first_at is None:
                first_at = round(time.time() - t0, 2)
    for call in msg.reply_html.await_args_list:
        if call[0]:
            htmls.append(str(call[0][0]))
            if first_at is None:
                first_at = round(time.time() - t0, 2)

    blob = _content_blob(texts, htmls)
    incomplete = any(m in blob for m in INCOMPLETE_MARKERS)
    empty = not blob.strip()
    ack_s = first_at if first_at is not None else elapsed
    return {
        "button": label,
        "elapsed_s": elapsed,
        "first_response_s": ack_s,
        "ack_within_3s": ack_s <= ACK_TARGET_S,
        "slow_warn": elapsed > SLOW_WARN_S,
        "slow_fail": elapsed > SLOW_FAIL_S,
        "incomplete": incomplete and not err,
        "empty": empty,
        "error": err,
        "ok": err is None and not empty,
        "preview": blob[:400],
    }


async def main():
    from bot_servers import WayneTelegramBot
    from config import get_db_path

    db = get_db_path()
    if not db or not os.path.isfile(db):
        print(json.dumps({"error": "no db", "path": db}, ensure_ascii=False))
        return 1

    bot = WayneTelegramBot.__new__(WayneTelegramBot)
    bot.db_path = db
    bot.charts_dir = os.environ.get("WAYNE_CHARTS_DIR", "data/charts")
    bot._pending = {}
    bot._last_card = {"9100": "3105"}
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
    bot.screener.screen_daytrade = MagicMock(return_value=[])
    bot.screener.screen_overnight = MagicMock(return_value=[])
    bot.screener.screen_morning = MagicMock(return_value=[])
    bot.screener.get_latest_trading_date = MagicMock(return_value="20260902")
    bot.screener.run_full_screening = MagicMock(return_value={"results": {}})
    bot.portfolio_engine = __import__("portfolio_engine").PortfolioEngine(db)

    results = []
    for label in ALL_MENU_BUTTONS:
        results.append(await _probe(bot, label))

    report = {
        "db": db,
        "thresholds": {"ack_s": ACK_TARGET_S, "slow_warn_s": SLOW_WARN_S, "slow_fail_s": SLOW_FAIL_S},
        "results": results,
        "summary": {
            "ok": sum(1 for r in results if r["ok"]),
            "slow_warn": [r["button"] for r in results if r["slow_warn"]],
            "slow_fail": [r["button"] for r in results if r["slow_fail"]],
            "no_ack_3s": [r["button"] for r in results if not r["ack_within_3s"]],
            "incomplete": [r["button"] for r in results if r["incomplete"]],
            "errors": [r["button"] for r in results if r["error"]],
        },
    }

    out = os.path.join(os.environ.get("WAYNE_ARTIFACT_DIR", "/opt/cursor/artifacts"), "full_ux_probe_report.json")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(out)
    print("SUMMARY:", json.dumps(report["summary"], ensure_ascii=False))
    bad = report["summary"]["errors"] or report["summary"]["slow_fail"]
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
