#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""五／十人格 UX 探測：排版、雅虎連結、LINE 轉傳、按鈕密度。"""
from __future__ import annotations

import asyncio
import json
import os
import re
import sys
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

YAHOO_RE = re.compile(
    r'href="https://tw\.stock\.yahoo\.com/quote/(\d{4,6})\.(TW|TWO)(?:/[^"]*)?"',
    re.I,
)
LINE_HOP_RE = re.compile(r"/line/(?:stock|pack)/|line\.me/R/share|line://msg")
MAX_PICK_ROWS = 8
MAX_BTNS_PER_ROW = 3
MAX_TOTAL_INLINE_ROWS = 14

PERSONAS_5 = [
    ("偉權", 9001, ["決策卡", "大盤", "資金", "海選", "持股"]),
    ("哥哥", 9002, ["觀察", "大盤", "當沖", "2330"]),
    ("新手", 9003, ["連買區", "說明", "大盤", "南亞"]),
    ("不懂股", 9004, ["asdf", "持股", "股票"]),
    ("亂按", 9005, ["大盤", "資金", "海選", "大盤"]),
]

PERSONAS_10 = PERSONAS_5 + [
    ("長線族", 9006, ["持股", "觀察", "資金"]),
    ("只看盤", 9007, ["大盤", "資金"]),
    ("愛轉LINE", 9008, ["海選", "當沖", "隔日沖"]),
    ("比較股", 9009, ["台積電", "鴻海", "南亞"]),
    ("夜間", 9010, ["說明", "隔日沖", "大盤"]),
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
    message.reply_sticker = AsyncMock(return_value=MagicMock(delete=AsyncMock()))
    return message


def _update(message):
    return SimpleNamespace(message=message, effective_user=message.from_user)


def _audit_html(html: str, *, context: str) -> list[str]:
    issues = []
    if not html or not str(html).strip():
        issues.append(f"{context}:空內容")
        return issues
    links = YAHOO_RE.findall(html)
    for sid, ex in links:
        if ex.upper() not in ("TW", "TWO"):
            issues.append(f"{context}:雅虎交易所異常 {sid}.{ex}")
    if "<a href=" in html and "yahoo.com" in html and not links:
        issues.append(f"{context}:有雅虎字樣但連結格式不符")
    if html.count("<blockquote>") != html.count("</blockquote>"):
        issues.append(f"{context}:blockquote 未閉合")
    if "\n\n\n\n" in html:
        issues.append(f"{context}:過多空行影響手機閱讀")
    return issues


def _audit_keyboard(markup, *, context: str) -> list[str]:
    if markup is None:
        return []
    issues = []
    rows = getattr(markup, "inline_keyboard", None) or []
    if len(rows) > MAX_TOTAL_INLINE_ROWS:
        issues.append(f"{context}:inline 列數過多({len(rows)}>{MAX_TOTAL_INLINE_ROWS})")
    for i, row in enumerate(rows):
        if len(row) > MAX_BTNS_PER_ROW:
            issues.append(f"{context}:第{i+1}列按鈕過多({len(row)})")
        for btn in row:
            txt = str(getattr(btn, "text", "") or "")
            if len(txt.encode("utf-8")) > 60:
                issues.append(f"{context}:按鈕文字過長「{txt[:12]}…」")
            url = getattr(btn, "url", None)
            if url and "line" in str(url).lower() and not LINE_HOP_RE.search(str(url)):
                issues.append(f"{context}:LINE URL 異常 {url[:40]}")
    return issues


def _collect_outputs(msg) -> tuple[list[str], list, list[str]]:
    texts, markups, htmls = [], [], []
    for call in msg.reply_text.await_args_list:
        if call[0]:
            texts.append(str(call[0][0]))
        kw = call[1] if len(call) > 1 else {}
        if kw.get("reply_markup"):
            markups.append(kw["reply_markup"])
    for call in msg.reply_html.await_args_list:
        if call[0]:
            htmls.append(str(call[0][0]))
        kw = call[1] if len(call) > 1 else {}
        if kw.get("reply_markup"):
            markups.append(kw["reply_markup"])
    return texts + htmls, markups, htmls


async def _probe_action(bot, uid: int, label: str) -> dict:
    msg = _msg(uid, label)
    t0 = time.time()
    err = None
    try:
        bot._menu_layout_ok = MagicMock(return_value=True)
        await bot.on_text(_update(msg), MagicMock())
    except Exception as e:
        err = str(e)
    elapsed = round(time.time() - t0, 2)
    blob, markups, htmls = _collect_outputs(msg)
    content = "\n".join(blob)
    issues = _audit_html(content, context=label)
    for j, mk in enumerate(markups):
        issues.extend(_audit_keyboard(mk, context=f"{label}#kb{j+1}"))
    for h in htmls:
        if (
            "開 LINE" in h
            and "/line/" not in h
            and "line.me" not in h
            and '<a href="' in h
            and "line" in h.lower()
        ):
            issues.append(f"{label}:LINE 連結缺中轉頁")
    yahoo_links = YAHOO_RE.findall(content)
    return {
        "action": label,
        "elapsed_s": elapsed,
        "ok": err is None and bool(content.strip()),
        "error": err,
        "yahoo_links": len(yahoo_links),
        "inline_rows": sum(len(getattr(m, "inline_keyboard", []) or []) for m in markups),
        "issues": issues,
        "preview": content[:280],
    }


def _make_bot():
    from bot_servers import WayneTelegramBot
    from config import get_db_path

    db = get_db_path()
    bot = WayneTelegramBot.__new__(WayneTelegramBot)
    bot.db_path = db
    bot.charts_dir = os.environ.get("WAYNE_CHARTS_DIR", "data/charts")
    bot._pending = {}
    bot._last_card = {"9001": "3105", "9009": "2330"}
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
    return bot, db


async def run_personas(personas: list, tag: str) -> dict:
    bot, db = _make_bot()
    report = {"phase": tag, "db": db, "personas": [], "summary": {}}
    all_issues = []
    for name, uid, actions in personas:
        persona = {"name": name, "uid": uid, "results": []}
        for act in actions:
            persona["results"].append(await _probe_action(bot, uid, act))
        persona["issues"] = [i for r in persona["results"] for i in r.get("issues") or []]
        all_issues.extend(persona["issues"])
        report["personas"].append(persona)
    report["summary"] = {
        "personas": len(personas),
        "actions": sum(len(p["results"]) for p in report["personas"]),
        "fail_actions": [
            f"{p['name']}/{r['action']}"
            for p in report["personas"]
            for r in p["results"]
            if not r["ok"]
        ],
        "ui_issues": all_issues,
        "ui_issue_count": len(all_issues),
    }
    return report


async def main():
    phase = (sys.argv[1] if len(sys.argv) > 1 else "all").lower()
    reports = []
    if phase in ("5", "all"):
        reports.append(await run_personas(PERSONAS_5, "personas_5"))
    if phase in ("10", "all"):
        reports.append(await run_personas(PERSONAS_10, "personas_10"))

    out = "/opt/cursor/artifacts/persona_ux_probe_report.json"
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        json.dump(reports, f, ensure_ascii=False, indent=2)
    print(out)
    for r in reports:
        print(r["phase"], json.dumps(r["summary"], ensure_ascii=False))
    bad = any(r["summary"]["fail_actions"] for r in reports)
    ui = sum(r["summary"]["ui_issue_count"] for r in reports)
    return 1 if bad else (1 if ui else 0)


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
