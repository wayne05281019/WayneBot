#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""偉權 + 哥哥重度同時使用：十輪交錯連買／大盤／查股，結果送 Telegram。"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

WAYNE = 9001
BRO = 9002


def _make_bot():
    from unittest.mock import AsyncMock, MagicMock
    from types import SimpleNamespace

    from bot_servers import WayneTelegramBot
    from config import get_db_path

    bot = WayneTelegramBot.__new__(WayneTelegramBot)
    bot.db_path = get_db_path()
    bot.charts_dir = "data/charts"
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
    bot._enter_main_menu = AsyncMock(side_effect=lambda m, u, **kw: f"{m.chat_id}:{u}")
    bot.screener = MagicMock()
    return bot


def _msg(uid, text=""):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock, MagicMock

    user = SimpleNamespace(id=uid, first_name="u")
    chat = SimpleNamespace(id=uid)
    m = MagicMock()
    m.chat_id = uid
    m.chat = chat
    m.from_user = user
    m.text = text
    m.reply_text = AsyncMock(return_value=MagicMock())
    m.reply_html = AsyncMock(return_value=MagicMock())
    return m


async def main():
    from bot_servers import MENU_BTN_MARKET
    from buy_streak import KIND_FOREIGN, KIND_TRUST, MARKET_TW, MARKET_TWO, load_snapshot

    bot = _make_bot()
    rounds = []

    async def wayne_streak(i: int):
        actor = f"{WAYNE}:{WAYNE}"
        bot._pending[actor] = "fbuy:kind"
        t0 = time.perf_counter()
        await bot._handle_buy_streak(_msg(WAYNE, "外資"), str(WAYNE), "fbuy:kind", "外資", actor=actor)
        await bot._handle_buy_streak(_msg(WAYNE, "上市"), str(WAYNE), bot._pending[actor], "上市", actor=actor)
        ms = int((time.perf_counter() - t0) * 1000)
        return {"who": "wayne", "round": i, "pending": bot._pending.get(actor, ""), "ms": ms}

    async def bro_streak(i: int):
        actor = f"{BRO}:{BRO}"
        bot._pending[actor] = "fbuy:kind"
        t0 = time.perf_counter()
        await bot._handle_buy_streak(_msg(BRO, "投信"), str(BRO), "fbuy:kind", "投信", actor=actor)
        await bot._handle_buy_streak(_msg(BRO, "上櫃"), str(BRO), bot._pending[actor], "上櫃", actor=actor)
        ms = int((time.perf_counter() - t0) * 1000)
        return {"who": "bro", "round": i, "pending": bot._pending.get(actor, ""), "ms": ms}

    async def bro_market():
        from types import SimpleNamespace
        from unittest.mock import AsyncMock, MagicMock

        bot.market_cmd = AsyncMock()
        upd = SimpleNamespace(message=_msg(BRO, MENU_BTN_MARKET), effective_user=_msg(BRO).from_user)
        await bot.on_text(upd, MagicMock())

    for i in range(10):
        w_actor = f"{WAYNE}:{WAYNE}"
        b_actor = f"{BRO}:{BRO}"
        bot._pending[w_actor] = "fbuy:days:foreign:TW"
        t0 = time.perf_counter()
        w_res, b_res = await asyncio.gather(wayne_streak(i), bro_streak(i))
        await bro_market()
        isolated = bot._pending.get(w_actor) == "fbuy:days:foreign:TW" or w_res["pending"].startswith("fbuy:days:")
        ok = (
            w_res["pending"].startswith("fbuy:days:foreign:TW")
            and b_res["pending"].startswith("fbuy:days:trust:TWO")
        )
        rounds.append(
            {
                "round": i + 1,
                "ok": ok,
                "wayne_ms": w_res["ms"],
                "bro_ms": b_res["ms"],
                "total_ms": int((time.perf_counter() - t0) * 1000),
                "wayne_pending": w_res["pending"],
                "bro_pending": b_res["pending"],
                "wayne_days_pending_kept": bot._pending.get(w_actor, "").startswith("fbuy:"),
            }
        )

    snap_w = load_snapshot(bot.db_path, KIND_FOREIGN, MARKET_TW, use_cache=True)
    snap_b = load_snapshot(bot.db_path, KIND_TRUST, MARKET_TWO, use_cache=True)
    p1 = bot._scratch_chart_path(bot.charts_dir, "2330", "chips", str(WAYNE))
    p2 = bot._scratch_chart_path(bot.charts_dir, "2330", "chips", str(BRO))

    lines = [
        "【雙人重度同時使用 ×10】",
        f"偉權 {WAYNE}　哥哥 {BRO}",
        f"連買基準 {snap_w.as_of}（外資上市 max={snap_w.max_days}，投信上櫃 max={snap_b.max_days}）",
        f"出圖檔名隔離：{p1 != p2}",
        "",
    ]
    for r in rounds:
        lines.append(
            f"#{r['round']} ok={r['ok']} w={r['wayne_ms']}ms b={r['bro_ms']}ms tot={r['total_ms']}ms"
        )

    token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat = os.getenv("TELEGRAM_CHAT_ID") or os.getenv("TG_CHAT_ID")
    if token and chat:
        import requests

        requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat, "text": "\n".join(lines)[:3900]},
            timeout=20,
        )
    print(json.dumps({"rounds": rounds, "chart_isolated": p1 != p2}, ensure_ascii=False, indent=2))
    return 0 if all(r["ok"] for r in rounds) else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
