#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""十人格 × 十子人格（100 人）同時查股／連買：除錯報告送 Telegram。"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from persona_grid import PERSONAS_10, iter_grid, sub_uid


def _make_bot():
    from unittest.mock import AsyncMock, MagicMock

    from bot_servers import WayneTelegramBot
    from config import get_db_path
    from wayne_db import init_database

    bot = WayneTelegramBot.__new__(WayneTelegramBot)
    bot.db_path = get_db_path()
    init_database(bot.db_path)
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
    from bot_servers import WayneTelegramBot

    grid = iter_grid()
    bot = _make_bot()
    rounds = []

    for round_i in range(10):
        results: dict[int, str] = {}
        paths: list[str] = []

        def fake_lookup(code, *a, **k):
            c = str(code).strip()
            return [{"stock_id": c, "stock_name": f"N{c}", "close": 100.0, "market": "TW"}]

        async def fake_locked(message, code, uid, actor, hits):
            results[int(uid)] = str(code).strip()

        t0 = time.perf_counter()
        bot._send_card_to = WayneTelegramBot._send_card_to.__get__(bot, WayneTelegramBot)
        bot._send_card_to_locked = fake_locked

        from unittest.mock import patch

        with patch("bot_servers.lookup_stocks", side_effect=fake_lookup):
            await asyncio.gather(
                *[
                    bot._send_card_to(_msg(uid), code, str(uid))
                    for _, _, _, uid, code in grid
                ]
            )

        for _, _, _, uid, code in grid:
            paths.append(bot._scratch_chart_path(bot.charts_dir, code, "chips", str(uid)))

        mism = [uid for _, _, _, uid, code in grid if results.get(uid) != code]
        ok = len(mism) == 0 and len(set(paths)) == len(grid)
        ms = int((time.perf_counter() - t0) * 1000)
        rounds.append({"round": round_i + 1, "ok": ok, "ms": ms, "mismatch": len(mism), "paths_unique": len(set(paths))})

    # 十人格各一子人格連買
    streak_ok = 0
    for round_i in range(10):
        for name, parent_uid, codes in PERSONAS_10:
            uid = sub_uid(parent_uid, (round_i % 10) + 1)
            actor = f"{uid}:{uid}"
            bot._pending[actor] = "fbuy:kind"
            kind = ["外資", "投信", "外資+投信"][round_i % 3]
            await bot._handle_buy_streak(_msg(uid, kind), str(uid), "fbuy:kind", kind, actor=actor)
            if bot._pending.get(actor, "").startswith("fbuy:mkt:"):
                streak_ok += 1

    lines = [
        "【十人格×十子人格 100 人同時查股 ×10 輪】",
        f"人格數 {len(PERSONAS_10)} × 子人格 {10} = {len(grid)}",
        "",
    ]
    for r in rounds:
        lines.append(f"#{r['round']} ok={r['ok']} {r['ms']}ms mismatch={r['mismatch']} paths={r['paths_unique']}")
    lines.append(f"連買步驟 ok={streak_ok}/{len(PERSONAS_10)*10}")

    report = {"rounds": rounds, "streak_ok": streak_ok, "grid_size": len(grid)}
    out = os.path.join(os.environ.get("WAYNE_ARTIFACT_DIR", "/opt/cursor/artifacts"), "persona_grid_concurrent_report.json")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

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
    return 0 if all(r["ok"] for r in rounds) else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
