#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""連買區十輪：官方基準日、天數、張數、％核對 + 全主選單路由探測。"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from bot_servers import MENU_BTN_MARKET, MENU_BTN_STREAK, WayneTelegramBot
from buy_streak import (
    KIND_BOTH,
    KIND_FOREIGN,
    KIND_TRUST,
    MARKET_TW,
    MARKET_TWO,
    clear_cache,
    load_snapshot,
)
from trading_calendar import format_trading_date_zh, fuse_end_trading_date, resolve_screen_as_of


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
    return message


def _update(message):
    return SimpleNamespace(message=message, effective_user=message.from_user)


def _bot():
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
    bot._menu_fade_gen = {}
    bot._menu_layout_ok = MagicMock(return_value=True)
    bot._touch_user = MagicMock()
    bot._enter_main_menu = AsyncMock(side_effect=lambda m, u, **kw: f"{m.chat_id}:{u}")
    bot._transient_status = AsyncMock(return_value=MagicMock())
    bot._delete_message = AsyncMock()
    bot._dismiss_menu_transients = AsyncMock()
    bot._send_card_to = AsyncMock()
    bot.screener = MagicMock()
    bot.portfolio_engine = MagicMock()
    return bot


def verify_streak_data(db_path: str, rounds: int = 10) -> list[dict]:
    clear_cache()
    official = resolve_screen_as_of(db_path)
    cap = fuse_end_trading_date()
    assert official == cap, f"as_of mismatch official={official} cap={cap}"
    out = []
    kinds = (KIND_FOREIGN, KIND_TRUST, KIND_BOTH)
    markets = (MARKET_TW, MARKET_TWO)
    for i in range(rounds):
        kind = kinds[i % 3]
        market = markets[(i // 3) % 2]
        t0 = time.perf_counter()
        snap = load_snapshot(db_path, kind, market, use_cache=False)
        elapsed = time.perf_counter() - t0
        sample = None
        if snap.max_days >= 2:
            d = snap.max_days
            rows = snap.stocks(d)
            if rows:
                r = rows[0]
                sample = {
                    "code": r.stock_id,
                    "days": r.days,
                    "foreign": r.foreign_lots,
                    "trust": r.trust_lots,
                    "vol": r.volume_lots,
                    "f_pct": r.foreign_pct,
                    "t_pct": r.trust_pct,
                }
        out.append(
            {
                "round": i + 1,
                "kind": kind,
                "market": market,
                "as_of": snap.as_of,
                "as_of_label": format_trading_date_zh(snap.as_of),
                "max_days": snap.max_days,
                "sample": sample,
                "elapsed_ms": int(elapsed * 1000),
                "ok": snap.as_of == official,
            }
        )
    return out


async def probe_wizard_flow(bot: WayneTelegramBot, uid: int = 9101) -> dict:
    user = SimpleNamespace(id=uid, first_name="probe")
    chat = SimpleNamespace(id=99)
    m = MagicMock()
    m.chat_id = 99
    m.chat = chat
    m.from_user = user
    m.reply_text = AsyncMock(return_value=MagicMock())
    m.reply_html = AsyncMock(return_value=MagicMock())
    uid_s = str(uid)
    actor = f"99:{uid_s}"
    await bot.streak_cmd(SimpleNamespace(message=m, effective_user=user), MagicMock())
    for text in ("外資", "上市"):
        await bot._handle_buy_streak(m, uid_s, bot._pending[actor], text, actor=actor)
    snap = load_snapshot(bot.db_path, KIND_FOREIGN, MARKET_TW, use_cache=False)
    if snap.max_days < 2:
        return {"ok": False, "reason": "no streak rows"}
    await bot._handle_buy_streak(m, uid_s, bot._pending[actor], str(snap.max_days), actor=actor)
    htmls = []
    for call in m.reply_html.await_args_list:
        htmls.append(call.args[0] if call.args else call.kwargs.get("text", ""))
    return {
        "ok": any("外資連買" in str(x) and "2026/09/03" in str(x) for x in htmls),
        "days": snap.max_days,
        "as_of": snap.as_of,
    }


def send_telegram_summary(lines: list[str]) -> bool:
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat = os.getenv("TELEGRAM_CHAT_ID") or os.getenv("TG_CHAT_ID")
    if not token or not chat:
        return False
    import requests

    text = "\n".join(lines)[:3900]
    r = requests.post(
        f"https://api.telegram.org/bot{token}/sendMessage",
        json={"chat_id": chat, "text": text, "disable_web_page_preview": True},
        timeout=20,
    )
    return r.ok


async def main():
    from config import get_db_path

    db_path = get_db_path()
    rounds = verify_streak_data(db_path, 10)
    bot = _bot()
    wizard = await probe_wizard_flow(bot)
    lines = [
        "【連買區十輪核對】",
        f"官方基準日 {format_trading_date_zh(rounds[0]['as_of'])}",
        f"wizard ok={wizard.get('ok')} max_days={wizard.get('days')}",
        "",
    ]
    for r in rounds:
        s = r.get("sample") or {}
        lines.append(
            f"#{r['round']} {r['kind']}/{r['market']} as_of={r['as_of_label']} "
            f"max={r['max_days']}ms={r['elapsed_ms']} "
            + (f"例 {s.get('code')} {s.get('days')}日 {s.get('foreign')}張" if s else "—")
        )
    print(json.dumps({"rounds": rounds, "wizard": wizard}, ensure_ascii=False, indent=2))
    if send_telegram_summary(lines):
        print("sent telegram summary")
    return 0 if all(r["ok"] for r in rounds) and wizard.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
