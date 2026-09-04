#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""連買區完整精靈：3 種類 × 2 市場 × 天數 × 點第一檔；十輪；雙人交錯。"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

WAYNE = 9001
BRO = 9002
COMBOS = (
    ("外資", "上市"),
    ("投信", "上市"),
    ("外資+投信", "上市"),
    ("外資", "上櫃"),
    ("投信", "上櫃"),
    ("外資+投信", "上櫃"),
)


def _msg(uid: int, text: str = ""):
    user = SimpleNamespace(id=uid, first_name="u")
    chat = SimpleNamespace(id=uid)
    m = MagicMock()
    m.chat_id = uid
    m.chat = chat
    m.from_user = user
    m.text = text
    m.reply_text = AsyncMock(return_value=MagicMock(delete=AsyncMock()))
    m.reply_html = AsyncMock(return_value=MagicMock(delete=AsyncMock()))
    m.reply_photo = AsyncMock()
    m.reply_media_group = AsyncMock(return_value=MagicMock())
    m.reply_sticker = AsyncMock(return_value=MagicMock())
    return m


def _bot():
    from bot_servers import WayneTelegramBot
    from config import get_db_path
    from wayne_db import init_database

    bot = WayneTelegramBot.__new__(WayneTelegramBot)
    bot.db_path = get_db_path()
    init_database(bot.db_path)
    bot.charts_dir = os.environ.get("WAYNE_CHARTS_DIR", "data/charts")
    bot._pending = {}
    bot._last_card = {}
    bot._lookup_ctx = {}
    bot._menu_fade_msgs = {}
    bot._lookup_fade_msgs = {}
    bot._screening_msgs = {}
    bot._line_pack_status_msgs = {}
    bot._help_msgs = {}
    bot._lookup_locks = {}
    bot._pending_locks = {}
    bot._screening_running = set()
    bot._screening_gate = asyncio.Lock()
    bot._screening_global_owner = ""
    bot._menu_fade_gen = {}
    bot._touch_user = MagicMock()
    bot._dismiss_menu_transients = AsyncMock()
    bot._transient_status = AsyncMock(return_value=MagicMock())
    bot._delete_message = AsyncMock()
    bot._send_card_to = AsyncMock()
    bot.screener = MagicMock()
    return bot


def _htmls(msg) -> list[str]:
    out = []
    for call in msg.reply_html.await_args_list:
        if call[0]:
            out.append(str(call[0][0]))
    return out


async def walk_wizard(bot, uid: int, kind: str, market: str) -> dict:
    from buy_streak import KIND_ALIASES, MARKET_ALIASES, load_snapshot

    actor = f"{uid}:{uid}"
    t0 = time.perf_counter()
    await bot._start_buy_streak(_msg(uid, "連買區"), str(uid))
    assert bot._pending.get(actor) == "fbuy:kind"

    m1 = _msg(uid, kind)
    await bot._handle_buy_streak(m1, str(uid), "fbuy:kind", kind, actor=actor)
    kcode = KIND_ALIASES[kind]
    assert bot._pending.get(actor) == f"fbuy:mkt:{kcode}"

    m2 = _msg(uid, market)
    await bot._handle_buy_streak(m2, str(uid), bot._pending[actor], market, actor=actor)
    mcode = MARKET_ALIASES[market]
    pending_now = bot._pending.get(actor, "")
    assert pending_now in (
        f"fbuy:days:{kcode}:{mcode}",
        f"fbuy:mkt:{kcode}",
    ), pending_now

    snap = await asyncio.to_thread(load_snapshot, bot.db_path, kcode, mcode, use_cache=True)
    days = snap.max_days
    first = None
    if days >= 2:
        m3 = _msg(uid, str(days))
        await bot._handle_buy_streak(m3, str(uid), bot._pending[actor], str(days), actor=actor)
        rows = snap.stocks(days)
        first = rows[0].stock_id if rows else None
        if first:
            bot._send_card_to.reset_mock()
            m4 = _msg(uid, first)
            await bot._handle_buy_streak(m4, str(uid), bot._pending[actor], first, actor=actor)
            bot._send_card_to.assert_awaited()

    ms = int((time.perf_counter() - t0) * 1000)
    return {
        "uid": uid,
        "kind": kind,
        "market": market,
        "as_of": snap.as_of,
        "max_days": days,
        "first": first,
        "pending": bot._pending.get(actor, ""),
        "ms": ms,
        "ok": snap.as_of == "20260903" and bot._pending.get(actor, "").startswith("fbuy:"),
    }


async def main():
    bot = _bot()
    combo_results = []
    for kind, market in COMBOS:
        combo_results.append(await walk_wizard(bot, WAYNE, kind, market))

    interleave = []
    for i in range(10):
        bot._pending[f"{WAYNE}:{WAYNE}"] = "fbuy:days:foreign:TW"
        w = await walk_wizard(bot, WAYNE, COMBOS[i % 6][0], COMBOS[i % 6][1])
        b = await walk_wizard(bot, BRO, COMBOS[(i + 1) % 6][0], COMBOS[(i + 1) % 6][1])
        isolated = (
            bot._pending.get(f"{WAYNE}:{WAYNE}", "").startswith("fbuy:")
            and bot._pending.get(f"{BRO}:{BRO}", "").startswith("fbuy:")
            and f"{WAYNE}:{WAYNE}" in bot._pending
            and f"{BRO}:{BRO}" in bot._pending
        )
        interleave.append(
            {
                "round": i + 1,
                "ok": bool(w["ok"] and b["ok"] and isolated),
                "wayne_ms": w["ms"],
                "bro_ms": b["ms"],
                "wayne_pending": w["pending"],
                "bro_pending": b["pending"],
            }
        )

    report = {
        "combos": combo_results,
        "interleave": interleave,
        "combo_ok": all(r["ok"] for r in combo_results),
        "interleave_ok": all(r["ok"] for r in interleave),
    }
    out = os.path.join(os.environ.get("WAYNE_ARTIFACT_DIR", "/opt/cursor/artifacts"), "live_streak_wizard_report.json")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    lines = ["【連買區完整精靈 ×6 組合 + 雙人交錯×10】"]
    for r in combo_results:
        lines.append(
            f"{r['kind']} {r['market']} as_of={r['as_of']} max={r['max_days']} "
            f"first={r['first'] or '—'} {r['ms']}ms ok={r['ok']}"
        )
    lines.append(f"交錯 ok={sum(1 for x in interleave if x['ok'])}/10")

    token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat = os.getenv("TELEGRAM_CHAT_ID") or os.getenv("TG_CHAT_ID")
    if token and chat:
        import requests

        requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat, "text": "\n".join(lines)[:3900]},
            timeout=20,
        )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["combo_ok"] and report["interleave_ok"] else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
