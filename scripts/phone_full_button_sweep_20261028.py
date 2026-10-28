#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""話筒全鈕掃（2026-10-28）：正式 handler 出圖／回覆 → 偉權白名單 sendMessage／sendPhoto。

不准 getUpdates。撞 03–04／06:30／16:30 或 busy_gate=true 立刻停。
"""
from __future__ import annotations

import asyncio
import io
import json
import os
import sys
import tempfile
import time
import traceback
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from zoneinfo import ZoneInfo

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("WAYNE_SKIP_POLLING", "1")
os.environ.setdefault("MPLBACKEND", "Agg")

import requests

TZ = ZoneInfo("Asia/Taipei")
HEALTH = "https://waynebot-service.onrender.com/health"
ARTIFACT = Path(os.environ.get("WAYNE_ARTIFACT_DIR", "/opt/cursor/artifacts")) / "phone-full-button-sweep-20261028"
ARTIFACT.mkdir(parents=True, exist_ok=True)

MENU_BUTTONS = [
    "勝率買點",
    "海選",
    "持股",
    "加入觀察",
    "飆大",
    "台股大盤",
    "資金輪動",
    "當沖",
    "隔日沖",
    "壓撐觀察",
    "AI倉",
    "連買區",
    "剛脫離零",
    "洞燭先機",
]

LOOKUP_HUB = [
    ("產業", "n"),
    ("籌碼", "h"),
    ("營收", "f"),
    ("高低導航圖", "g"),
    ("情境預估", "sf"),
    ("加入觀察", "w"),
    # 記買入會進 pending 問價，只觸發確認進入即可
    ("記買入", "b"),
]


def now_tp() -> datetime:
    return datetime.now(TZ)


def heavy_window(dt: datetime | None = None) -> bool:
    dt = dt or now_tp()
    hhmm = dt.hour * 100 + dt.minute
    return (300 <= hhmm < 400) or (630 <= hhmm < 700) or (1630 <= hhmm < 1735)


def health() -> dict:
    r = requests.get(HEALTH, timeout=30)
    r.raise_for_status()
    return r.json()


def gate_or_stop(results: list) -> bool:
    """回 True＝可繼續；False＝該停。"""
    if heavy_window():
        results.append(
            {
                "item": "GATE",
                "ok": False,
                "status": "stop_heavy_window",
                "at": now_tp().isoformat(),
            }
        )
        return False
    try:
        h = health()
    except Exception as e:
        results.append({"item": "GATE", "ok": False, "status": "health_fail", "error": str(e)})
        return False
    if h.get("busy_gate") is True:
        results.append(
            {
                "item": "GATE",
                "ok": False,
                "status": "stop_busy_gate",
                "at": now_tp().isoformat(),
                "health": {k: h.get(k) for k in ("busy_gate", "uptime_s", "polling_age_s")},
            }
        )
        return False
    if not h.get("data_ok") or not h.get("db_ok"):
        results.append({"item": "GATE", "ok": False, "status": "data_not_ok", "health": h})
        return False
    return True


def tg_api(method: str, *, data=None, files=None, timeout=90):
    token = os.environ["TELEGRAM_BOT_TOKEN"]
    url = f"https://api.telegram.org/bot{token}/{method}"
    if files:
        r = requests.post(url, data=data or {}, files=files, timeout=timeout)
    else:
        r = requests.post(url, json=data or {}, timeout=timeout)
    try:
        body = r.json()
    except Exception:
        body = {"ok": False, "raw": r.text[:300]}
    return r.status_code, body


def send_text(chat: str, text: str) -> dict:
    st, body = tg_api(
        "sendMessage",
        data={"chat_id": chat, "text": text[:3900], "disable_web_page_preview": True},
    )
    return {"http": st, "ok": bool(body.get("ok")), "msg_id": (body.get("result") or {}).get("message_id")}


def send_photo(chat: str, path: str, caption: str = "") -> dict:
    if not path or not os.path.isfile(path):
        return {"ok": False, "error": "missing_path", "path": path}
    size = os.path.getsize(path)
    with open(path, "rb") as f:
        st, body = tg_api(
            "sendPhoto",
            data={"chat_id": chat, "caption": (caption or "")[:1024]},
            files={"photo": (os.path.basename(path), f, "image/png")},
            timeout=120,
        )
    return {
        "http": st,
        "ok": bool(body.get("ok")),
        "msg_id": (body.get("result") or {}).get("message_id"),
        "bytes": size,
    }


def _forwarding_message(chat_id: int, uid: int, text: str = ""):
    """reply_* 同時轉送到真話筒。"""
    user = SimpleNamespace(id=uid, first_name="sweep")
    chat = SimpleNamespace(id=chat_id)
    message = MagicMock()
    message.chat_id = chat_id
    message.chat = chat
    message.from_user = user
    message.text = text
    message.message_id = 1
    sent = {"texts": [], "photos": [], "htmls": []}

    async def _reply_text(*args, **kwargs):
        body = args[0] if args else kwargs.get("text", "")
        sent["texts"].append(str(body)[:800])
        # 轉送
        send_text(str(chat_id), f"[掃] {str(body)[:3500]}")
        m = MagicMock()
        m.message_id = 1
        m.delete = AsyncMock()
        m.edit_text = AsyncMock()
        return m

    async def _reply_html(*args, **kwargs):
        body = args[0] if args else kwargs.get("text", "")
        sent["htmls"].append(str(body)[:800])
        # HTML → 純文字摘要轉送，避免話筒炸 tag
        plain = (
            str(body)
            .replace("<b>", "")
            .replace("</b>", "")
            .replace("<i>", "")
            .replace("</i>", "")
            .replace("<code>", "")
            .replace("</code>", "")
        )
        for tag in ("<a ", "</a>", "<blockquote>", "</blockquote>"):
            if tag in plain:
                # crude strip links keep text
                import re

                plain = re.sub(r"<[^>]+>", "", plain)
                break
        send_text(str(chat_id), f"[掃HTML]\n{plain[:3500]}")
        m = MagicMock()
        m.message_id = 1
        m.delete = AsyncMock()
        m.edit_text = AsyncMock()
        m.edit_caption = AsyncMock()
        return m

    async def _reply_photo(*args, **kwargs):
        photo = kwargs.get("photo") or (args[0] if args else None)
        cap = kwargs.get("caption") or ""
        path = None
        if hasattr(photo, "read"):
            # file-like from open()
            data = photo.read()
            photo.seek(0)
            td = ARTIFACT / "photos"
            td.mkdir(exist_ok=True)
            path = str(td / f"fwd-{int(time.time()*1000)}.png")
            with open(path, "wb") as f:
                f.write(data)
        elif isinstance(photo, (str, os.PathLike)) and os.path.isfile(photo):
            path = str(photo)
        elif isinstance(photo, (bytes, bytearray)):
            td = ARTIFACT / "photos"
            td.mkdir(exist_ok=True)
            path = str(td / f"fwd-{int(time.time()*1000)}.bin")
            with open(path, "wb") as f:
                f.write(photo)
        info = {"caption": str(cap)[:200], "path": path}
        if path:
            info["send"] = send_photo(str(chat_id), path, caption=str(cap)[:900] or "[掃圖]")
        else:
            info["send"] = {"ok": False, "error": "no_path"}
            send_text(str(chat_id), f"[掃圖缺檔] {cap[:200]}")
        sent["photos"].append(info)
        m = MagicMock()
        m.message_id = 1
        m.delete = AsyncMock()
        return m

    message.reply_text = AsyncMock(side_effect=_reply_text)
    message.reply_html = AsyncMock(side_effect=_reply_html)
    message.reply_photo = AsyncMock(side_effect=_reply_photo)
    message.reply_media_group = AsyncMock(return_value=[MagicMock(), MagicMock()])
    message.reply_sticker = AsyncMock(return_value=MagicMock(delete=AsyncMock()))
    message.edit_text = AsyncMock()
    message.delete = AsyncMock()
    message._sweep_sent = sent
    return message


def _make_bot(db: str, charts: str, uid: str):
    from bot_servers import WayneTelegramBot

    bot = WayneTelegramBot(token=os.environ["TELEGRAM_BOT_TOKEN"], chat_id=str(uid), db_path=db)
    bot.charts_dir = charts
    os.makedirs(charts, exist_ok=True)
    return bot


def _audit_blob(blob: str) -> list[str]:
    issues = []
    bad = ("查詢失敗", "出圖逾時", "Traceback", "Internal Server Error", "PHONE_BUSY", "資料處理中")
    for b in bad:
        if b in blob:
            issues.append(f"marker:{b}")
    if "�" in blob:
        issues.append("replacement_char")
    return issues


async def run_menu(bot, chat_id: int, uid: int, results: list) -> None:
    from bot_servers import MENU_BTN_LEAVE_BIAOKE, MENU_BTN_LEAVE_DONGZHU, MENU_BTN_BACK_MAIN

    for label in MENU_BUTTONS:
        if not gate_or_stop(results):
            return
        msg = _forwarding_message(chat_id, uid, label)
        t0 = time.perf_counter()
        err = None
        try:
            upd = SimpleNamespace(message=msg, effective_user=msg.from_user, callback_query=None)
            await bot.on_text(upd, MagicMock())
        except Exception as e:
            err = f"{type(e).__name__}: {e}"
            traceback.print_exc()
        dt = round(time.perf_counter() - t0, 2)
        sent = msg._sweep_sent
        blob = "\n".join(sent["texts"] + sent["htmls"])
        issues = _audit_blob(blob)
        # 離開特殊模式，避免擋下一鈕
        for leave in (MENU_BTN_LEAVE_BIAOKE, MENU_BTN_LEAVE_DONGZHU, MENU_BTN_BACK_MAIN, "回主選單"):
            try:
                m2 = _forwarding_message(chat_id, uid, leave)
                await bot.on_text(
                    SimpleNamespace(message=m2, effective_user=m2.from_user, callback_query=None),
                    MagicMock(),
                )
            except Exception:
                pass
        results.append(
            {
                "item": f"menu:{label}",
                "ok": err is None and (bool(sent["texts"]) or bool(sent["htmls"]) or bool(sent["photos"])),
                "elapsed_s": dt,
                "n_text": len(sent["texts"]),
                "n_html": len(sent["htmls"]),
                "n_photo": len(sent["photos"]),
                "issues": issues,
                "error": err,
                "preview": blob[:240],
            }
        )
        await asyncio.sleep(0.8)


async def run_lookup(bot, chat_id: int, uid: int, code: str, results: list, *, hub: bool) -> None:
    if not gate_or_stop(results):
        return
    msg = _forwarding_message(chat_id, uid, code)
    t0 = time.perf_counter()
    err = None
    try:
        # 走鎖定查股正式路徑
        await bot._send_card_to(msg, code, str(uid))
    except Exception as e:
        err = f"{type(e).__name__}: {e}"
        traceback.print_exc()
    dt = round(time.perf_counter() - t0, 2)
    sent = msg._sweep_sent
    photos_ok = sum(1 for p in sent["photos"] if (p.get("send") or {}).get("ok"))
    results.append(
        {
            "item": f"lookup:{code}",
            "ok": err is None and photos_ok >= 1,
            "elapsed_s": dt,
            "photos_sent_ok": photos_ok,
            "photos_total": len(sent["photos"]),
            "n_text": len(sent["texts"]) + len(sent["htmls"]),
            "error": err,
            "photo_caps": [p.get("caption") for p in sent["photos"][:6]],
        }
    )
    if not hub or not gate_or_stop(results):
        return
    # 子鈕 callback
    for label, prefix in LOOKUP_HUB:
        if not gate_or_stop(results):
            return
        cb_data = f"{prefix}:{code}"
        cq_msg = _forwarding_message(chat_id, uid, "")
        cq = SimpleNamespace(
            id="sweep1",
            data=cb_data,
            from_user=SimpleNamespace(id=uid, first_name="sweep"),
            message=cq_msg,
            answer=AsyncMock(),
        )
        upd = SimpleNamespace(
            callback_query=cq,
            effective_user=cq.from_user,
            message=None,
        )
        t0 = time.perf_counter()
        err = None
        try:
            if hasattr(bot, "on_callback"):
                await bot.on_callback(upd, MagicMock())
            elif hasattr(bot, "on_callback_query"):
                await bot.on_callback_query(upd, MagicMock())
            else:
                # fallback: common name
                handler = getattr(bot, "button_callback", None) or getattr(bot, "_on_callback", None)
                if handler is None:
                    raise RuntimeError("no callback handler")
                await handler(upd, MagicMock())
        except Exception as e:
            err = f"{type(e).__name__}: {e}"
            traceback.print_exc()
        dt = round(time.perf_counter() - t0, 2)
        sent = cq_msg._sweep_sent
        blob = "\n".join(sent["texts"] + sent["htmls"])
        results.append(
            {
                "item": f"hub:{code}:{label}",
                "ok": err is None
                and (bool(sent["texts"]) or bool(sent["htmls"]) or bool(sent["photos"])),
                "elapsed_s": dt,
                "n_text": len(sent["texts"]) + len(sent["htmls"]),
                "n_photo": len(sent["photos"]),
                "issues": _audit_blob(blob),
                "error": err,
                "preview": blob[:200],
            }
        )
        # 記買入離開
        if prefix == "b":
            try:
                m2 = _forwarding_message(chat_id, uid, "回主選單")
                await bot.on_text(
                    SimpleNamespace(message=m2, effective_user=m2.from_user, callback_query=None),
                    MagicMock(),
                )
            except Exception:
                pass
        await asyncio.sleep(0.5)


async def main() -> int:
    chat = os.environ.get("TELEGRAM_CHAT_ID") or ""
    token = os.environ.get("TELEGRAM_BOT_TOKEN") or ""
    if not chat or not token:
        print("missing TELEGRAM_CHAT_ID/TOKEN", file=sys.stderr)
        return 2
    uid = int(chat)
    results: list = []
    meta = {
        "started": now_tp().isoformat(),
        "heavy_at_start": heavy_window(),
        "methods": ["getMe?", "sendMessage", "sendPhoto"],
        "no_getUpdates": True,
    }
    if not gate_or_stop(results):
        meta["stopped_before_start"] = True
        _dump(meta, results)
        return 1

    h0 = health()
    meta["health0"] = {
        k: h0.get(k)
        for k in (
            "git_sha",
            "booting",
            "uptime_s",
            "polling_age_s",
            "data_ok",
            "busy_gate",
            "latest_complete",
            "cap",
        )
    }
    send_text(
        chat,
        f"【全鈕掃開始】{now_tp().strftime('%H:%M:%S')} 台北\n"
        f"sha={(h0.get('git_sha') or '')[:12]} busy={h0.get('busy_gate')} "
        f"polling_age={round(float(h0.get('polling_age_s') or 0),1)}s\n"
        f"未搶 getUpdates；busy／重活窗會停。可忽略本串。",
    )

    from config import get_db_path

    db = get_db_path()
    charts = tempfile.mkdtemp(prefix="sweep-charts-")
    bot = _make_bot(db, charts, str(uid))

    # 1) 主選單
    await run_menu(bot, uid, uid, results)
    # 2) 查股 1303＋子鈕
    await run_lookup(bot, uid, uid, "1303", results, hub=True)
    # 3) 通道件 6274（四張即可，子鈕略以免 OOM）
    await run_lookup(bot, uid, uid, "6274", results, hub=False)
    # 4) 興櫃 3595
    await run_lookup(bot, uid, uid, "3595", results, hub=False)
    # 5) 台光電 2383（對 23:23 失敗）
    await run_lookup(bot, uid, uid, "2383", results, hub=False)

    # 興櫃海選入口（連買底）
    if gate_or_stop(results):
        for text in ("興櫃海選", "/start"):
            if not gate_or_stop(results):
                break
            msg = _forwarding_message(uid, uid, text)
            err = None
            t0 = time.perf_counter()
            try:
                await bot.on_text(
                    SimpleNamespace(message=msg, effective_user=msg.from_user, callback_query=None),
                    MagicMock(),
                )
            except Exception as e:
                err = f"{type(e).__name__}: {e}"
            sent = msg._sweep_sent
            results.append(
                {
                    "item": f"text:{text}",
                    "ok": err is None
                    and (bool(sent["texts"]) or bool(sent["htmls"]) or bool(sent["photos"])),
                    "elapsed_s": round(time.perf_counter() - t0, 2),
                    "error": err,
                    "preview": "\n".join(sent["texts"] + sent["htmls"])[:240],
                }
            )

    meta["finished"] = now_tp().isoformat()
    try:
        meta["health1"] = {
            k: health().get(k)
            for k in ("uptime_s", "polling_age_s", "busy_gate", "data_ok", "booting")
        }
    except Exception as e:
        meta["health1_error"] = str(e)

    fails = [r for r in results if not r.get("ok")]
    summary_lines = [
        f"【全鈕掃結束】{now_tp().strftime('%H:%M:%S')}",
        f"項次 {len(results)} 失敗 {len(fails)}",
    ]
    for r in fails[:12]:
        summary_lines.append(f"× {r.get('item')} {r.get('status') or r.get('error') or r.get('issues')}")
    if not fails:
        summary_lines.append("主掃項皆有回覆／圖。細節見報告。")
    send_text(chat, "\n".join(summary_lines))
    path = _dump(meta, results)
    print(path)
    print("FAILS", len(fails))
    return 0 if not fails else 1


def _dump(meta: dict, results: list) -> str:
    out = {
        "meta": meta,
        "results": results,
        "fail_items": [r.get("item") for r in results if not r.get("ok")],
    }
    path = str(ARTIFACT / "report.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    return path


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
