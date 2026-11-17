#!/usr/bin/env python3
"""話筒自測波浪位階：出文＋三張遠／近／超近。

規則（2026-11-17）：
- 不准把 LOADING／倒數原文貼上話筒（會被誤認軟體卡住）。
- 只送敘述 HTML、三張圖、一句短結語；結語不准含 LOADING。
- 二次按鎖必須並發測；鎖句用白話摘要，不准貼進度框。
- WAYNE_SKIP_POLLING=1；不准搶正式 getUpdates。
"""
from __future__ import annotations

import asyncio
import json
import os
import shutil
import tempfile
import time
import traceback
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from zoneinfo import ZoneInfo

import requests

from bot_servers import MENU_BTN_WAVE_STATUS, WayneTelegramBot
from config import get_db_path

TZ = ZoneInfo("Asia/Taipei")
TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
CHAT = os.environ["TELEGRAM_CHAT_ID"]
FAMILY = (os.environ.get("WAYNE_FAMILY_CHAT_IDS") or "8772209416").split(",")[0].strip()
ART = os.environ.get(
    "WAVE_SELFTEST_ART", "/opt/cursor/artifacts/wave-phone-selftest"
)


def _is_loading_bubble(text: str) -> bool:
    t = str(text or "")
    return (
        "LOADING" in t
        or "進行中" in t
        or "好了這則會消失" in t
        or "約剩" in t
        or "□□" in t
    )


def tg_text(cid: str, text: str) -> bool:
    body = str(text or "")[:3900]
    if _is_loading_bubble(body):
        return False
    try:
        return bool(
            requests.post(
                f"https://api.telegram.org/bot{TOKEN}/sendMessage",
                json={
                    "chat_id": cid,
                    "text": body,
                    "disable_web_page_preview": True,
                },
                timeout=60,
            )
            .json()
            .get("ok")
        )
    except Exception as e:
        print("tg_text fail", cid, e)
        return False


def tg_photo(cid: str, path: str, cap: str = "") -> bool:
    try:
        with open(path, "rb") as f:
            return bool(
                requests.post(
                    f"https://api.telegram.org/bot{TOKEN}/sendPhoto",
                    data={"chat_id": cid, "caption": (cap or "")[:1024]},
                    files={"photo": (os.path.basename(path), f, "image/png")},
                    timeout=120,
                )
                .json()
                .get("ok")
            )
    except Exception as e:
        print("tg_photo fail", cid, e)
        return False


def make_msg(uid: int, text: str, *, forward_loading: bool = False):
    msg = MagicMock()
    msg.chat_id = uid
    msg.chat = SimpleNamespace(id=uid)
    msg.from_user = SimpleNamespace(id=uid, first_name="selftest")
    msg.text = text
    msg.message_id = int(time.time() * 1000) % 1_000_000_000
    msg.date = datetime.now(timezone.utc)
    sent = {"texts": [], "photos": [], "htmls": [], "events": []}

    async def rt(*a, **k):
        body = str(a[0] if a else k.get("text", ""))
        sent["texts"].append(body)
        sent["events"].append(("text", body[:200]))
        if forward_loading or not _is_loading_bubble(body):
            tg_text(CHAT, body[:3500])
        m = MagicMock()
        m.message_id = 1
        m.delete = AsyncMock()
        m.edit_text = AsyncMock()
        return m

    async def rh(*a, **k):
        body = str(a[0] if a else "")
        sent["htmls"].append(body)
        sent["events"].append(("html", body[:200]))
        plain = body
        for t in ("<b>", "</b>", "<i>", "</i>", "<code>", "</code>"):
            plain = plain.replace(t, "")
        if not _is_loading_bubble(plain):
            tg_text(CHAT, plain[:3500])
        m = MagicMock()
        m.message_id = 1
        m.delete = AsyncMock()
        return m

    async def rp(*a, **k):
        photo = k.get("photo") or (a[0] if a else None)
        cap = k.get("caption") or ""
        path = None
        photos_dir = os.path.join(ART, "photos")
        os.makedirs(photos_dir, exist_ok=True)
        if hasattr(photo, "read"):
            data = photo.read()
            photo.seek(0)
            path = os.path.join(
                photos_dir, f"single-{len(sent['photos'])}-{int(time.time()*1000)}.png"
            )
            open(path, "wb").write(data)
        elif isinstance(photo, str) and os.path.isfile(photo):
            path = os.path.join(
                photos_dir, f"single-{len(sent['photos'])}-{os.path.basename(photo)}"
            )
            shutil.copy(photo, path)
        ok = tg_photo(CHAT, path, cap or "波浪圖") if path else False
        sent["photos"].append(
            {
                "kind": "photo",
                "path": path,
                "cap": str(cap),
                "ok": ok,
                "bytes": os.path.getsize(path) if path else 0,
            }
        )
        sent["events"].append(("photo", path, str(cap)[:80]))
        m = MagicMock()
        m.message_id = 1
        m.delete = AsyncMock()
        return m

    msg.reply_text = AsyncMock(side_effect=rt)
    msg.reply_html = AsyncMock(side_effect=rh)
    msg.reply_photo = AsyncMock(side_effect=rp)
    msg.reply_media_group = AsyncMock(return_value=[])
    msg.reply_sticker = AsyncMock(return_value=MagicMock(delete=AsyncMock()))
    msg._sent = sent
    return msg


async def press(bot: WayneTelegramBot, uid: int, label: str):
    msg = make_msg(uid, label)
    upd = SimpleNamespace(
        message=msg,
        effective_message=msg,
        effective_user=msg.from_user,
        callback_query=None,
    )
    err = None
    t0 = time.perf_counter()
    try:
        await bot.on_text(upd, MagicMock())
    except Exception as e:
        err = f"{type(e).__name__}: {e}"
        traceback.print_exc()
    return msg._sent, err, round(time.perf_counter() - t0, 2)


async def main() -> int:
    os.makedirs(ART, exist_ok=True)
    os.makedirs(os.path.join(ART, "photos"), exist_ok=True)
    h = requests.get(
        "https://waynebot-service.onrender.com/health", timeout=30
    ).json()
    # 開場一句，不准貼進度框
    tg_text(
        CHAT,
        f"【波浪自測開始】{datetime.now(TZ).strftime('%H:%M:%S')} 台北 "
        f"Render={str(h.get('git_sha', ''))[:12]}（代理人自測，LOADING 不貼話筒）",
    )
    uid = int(CHAT)
    bot = WayneTelegramBot(token=TOKEN, chat_id=str(uid), db_path=get_db_path())
    bot.charts_dir = tempfile.mkdtemp(prefix="wave-selftest-")

    # 主按＋並發二次按：真鎖路徑（二次須在主按仍持鎖時撞上）
    lock_preview = ""
    lock_err = None

    async def _second():
        nonlocal lock_preview, lock_err
        await asyncio.sleep(1.5)
        s2, e2, _ = await press(bot, uid, MENU_BTN_WAVE_STATUS)
        lock_err = e2
        blob = (s2["texts"][:1] or s2["htmls"][:1] or [""])[0]
        if "上一組" in blob or "還在出圖" in blob:
            lock_preview = "鎖住：上一組還在出圖"
        elif _is_loading_bubble(blob):
            lock_preview = "收到進度框（未貼話筒）"
        else:
            lock_preview = (blob or "無回覆")[:40]

    t_second = asyncio.create_task(_second())
    sent, err, dt = await press(bot, uid, MENU_BTN_WAVE_STATUS)
    try:
        await asyncio.wait_for(t_second, timeout=120)
    except Exception as e:
        lock_preview = lock_preview or f"鎖測未完:{type(e).__name__}"

    paths = [p for p in sent["photos"] if p.get("path")]
    issues = []
    if err:
        issues.append(f"err:{err}")
    if len(paths) < 3:
        issues.append(f"photos_lt_3:{len(paths)}")
    for p in paths:
        if not p.get("ok"):
            issues.append("send_fail")
        if (p.get("bytes") or 0) < 80000:
            issues.append("tiny")
    ok = not issues and len(paths) >= 3
    for i, p in enumerate(paths[:3], 1):
        dest = os.path.join(ART, f"wave-panel-{i}.png")
        shutil.copy(p["path"], dest)
    report = {
        "started": datetime.now(TZ).isoformat(),
        "ok": ok,
        "issues": issues,
        "elapsed_s": dt,
        "n_photo": len(paths),
        "lock": lock_preview,
        "lock_err": lock_err,
        "health": {k: h.get(k) for k in ("git_sha", "booting", "busy_gate")},
    }
    open(os.path.join(ART, "report.json"), "w", encoding="utf-8").write(
        json.dumps(report, ensure_ascii=False, indent=2)
    )
    # 結語：禁止 LOADING 原文
    summary = (
        f"【波浪自測結束】ok={ok} {dt}s 圖={len(paths)} "
        f"issues={issues or '無'}；{lock_preview or '鎖測略'}。"
        "（進度框未貼話筒）"
    )
    assert not _is_loading_bubble(summary)
    tg_text(CHAT, summary)
    if FAMILY and FAMILY != str(CHAT):
        tg_text(FAMILY, f"【波浪自測】ok={ok} issues={issues or '無'}（可忽略）")
    print(json.dumps(report, ensure_ascii=False))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
