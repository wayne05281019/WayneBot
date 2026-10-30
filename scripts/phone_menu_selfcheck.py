#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""話筒主選單逐鈕自測：走 _on_text_bound 真路徑，結果直送手機。不准 getUpdates。"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import time
import traceback
import urllib.parse
import urllib.request
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("WAYNE_SKIP_POLLING", "1")
os.environ.setdefault("MPLBACKEND", "Agg")

REPORT: List[Dict[str, Any]] = []


def _token() -> str:
    t = (os.environ.get("TELEGRAM_BOT_TOKEN") or "").strip()
    if not t:
        raise SystemExit("缺 TELEGRAM_BOT_TOKEN")
    return t


def _chat_id() -> str:
    c = (os.environ.get("TELEGRAM_CHAT_ID") or "").strip()
    if not c:
        raise SystemExit("缺 TELEGRAM_CHAT_ID")
    return c


def _ok(name: str, detail: str = "") -> None:
    REPORT.append({"name": name, "ok": True, "detail": detail})
    print(f"OK  {name}  {detail}", flush=True)


def _fail(name: str, detail: str = "") -> None:
    REPORT.append({"name": name, "ok": False, "detail": detail})
    print(f"FAIL {name}  {detail}", flush=True)


class TgHttp:
    def __init__(self, token: str):
        self.base = f"https://api.telegram.org/bot{token}"

    def _post_json(self, method: str, payload: dict, timeout: float = 60.0) -> dict:
        data = urllib.parse.urlencode(
            {k: v for k, v in payload.items() if v is not None}
        ).encode()
        req = urllib.request.Request(
            f"{self.base}/{method}",
            data=data,
            method="POST",
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode())

    def send_message(self, chat_id: int, text: str, *, parse_mode: Optional[str] = None) -> dict:
        return self._post_json(
            "sendMessage",
            {
                "chat_id": chat_id,
                "text": (text or "")[:3900],
                "parse_mode": parse_mode,
                "disable_web_page_preview": "true",
            },
        )

    def send_chat_action(self, chat_id: int, action: str = "typing") -> dict:
        try:
            return self._post_json(
                "sendChatAction",
                {"chat_id": chat_id, "action": action},
                timeout=15.0,
            )
        except Exception:
            return {}

    def send_photo(self, chat_id: int, photo, *, caption: str = "", parse_mode=None, **kwargs):
        import uuid

        boundary = f"----wayne{uuid.uuid4().hex}"
        chunks: List[bytes] = []

        def add_field(name: str, value: str):
            chunks.append(f"--{boundary}\r\n".encode())
            chunks.append(
                f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode()
            )
            chunks.append(value.encode())
            chunks.append(b"\r\n")

        add_field("chat_id", str(chat_id))
        if caption:
            add_field("caption", caption[:1024])
        if parse_mode:
            add_field("parse_mode", str(parse_mode))
        mk = kwargs.get("reply_markup")
        if mk is not None:
            try:
                add_field(
                    "reply_markup",
                    json.dumps(mk.to_dict() if hasattr(mk, "to_dict") else mk, ensure_ascii=False),
                )
            except Exception:
                pass
        filename = "chart.jpg"
        if hasattr(photo, "read"):
            blob = photo.read()
            filename = os.path.basename(getattr(photo, "name", None) or filename)
        elif isinstance(photo, (str, Path)) and os.path.isfile(str(photo)):
            filename = os.path.basename(str(photo))
            with open(photo, "rb") as fh:
                blob = fh.read()
        else:
            blob = bytes(photo)
        chunks.append(f"--{boundary}\r\n".encode())
        chunks.append(
            (
                f'Content-Disposition: form-data; name="photo"; filename="{filename}"\r\n'
                "Content-Type: application/octet-stream\r\n\r\n"
            ).encode()
        )
        chunks.append(blob)
        chunks.append(b"\r\n")
        chunks.append(f"--{boundary}--\r\n".encode())
        body = b"".join(chunks)
        req = urllib.request.Request(
            f"{self.base}/sendPhoto",
            data=body,
            method="POST",
            headers={
                "Content-Type": f"multipart/form-data; boundary={boundary}",
                "Content-Length": str(len(body)),
            },
        )
        timeout = max(float(kwargs.get("read_timeout") or 90), float(kwargs.get("write_timeout") or 120), 60.0)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode())


def _wire_update(tg: TgHttp, chat_id: str, text: str):
    uid = int(chat_id)
    user = SimpleNamespace(id=uid, first_name="自測", username="selfcheck")
    chat = SimpleNamespace(id=uid, type="private")

    async def send_action(action: str):
        await asyncio.to_thread(tg.send_chat_action, uid, action)

    chat.send_action = send_action

    class _Sent:
        def __init__(self, payload=None):
            result = (payload or {}).get("result") or {}
            self.message_id = int(result.get("message_id") or int(time.time()) % 1_000_000)
            self.chat = chat
            self.photo = result.get("photo")

        async def edit_text(self, *a, **k):
            return self

        async def delete(self):
            return True

    class _Msg:
        def __init__(self):
            self.chat_id = uid
            self.chat = chat
            self.from_user = user
            self.message_id = int(time.time()) % 1_000_000
            self.text = text
            self.caption = None
            self.photo = None
            self.date = int(time.time())

        async def reply_text(self, text="", **kwargs):
            payload = await asyncio.to_thread(
                tg.send_message, uid, text or "", parse_mode=kwargs.get("parse_mode")
            )
            return _Sent(payload)

        async def reply_html(self, text="", **kwargs):
            return await self.reply_text(text, parse_mode="HTML", **kwargs)

        async def reply_photo(self, photo=None, caption="", **kwargs):
            payload = await asyncio.to_thread(
                tg.send_photo,
                uid,
                photo,
                caption=caption or "",
                parse_mode=kwargs.get("parse_mode"),
                read_timeout=kwargs.get("read_timeout", 90.0),
                write_timeout=kwargs.get("write_timeout", 120.0),
                reply_markup=kwargs.get("reply_markup"),
            )
            return _Sent(payload)

        async def reply_document(self, document=None, caption="", **kwargs):
            # 少數路徑用 document；改文字告知
            await self.reply_text(f"[document] {caption or '檔案'}")
            return _Sent()

        async def edit_text(self, *a, **k):
            return self

    msg = _Msg()
    update = SimpleNamespace(message=msg, effective_user=user, effective_chat=chat, callback_query=None)
    context = MagicMock()
    context.bot = MagicMock()
    context.user_data = {}
    context.chat_data = {}
    return update, context, msg


async def press(wb, tg: TgHttp, chat_id: str, label: str, text: str, timeout_s: float) -> None:
    update, context, msg = _wire_update(tg, chat_id, text)
    raw = text
    t0 = time.perf_counter()
    try:
        await asyncio.wait_for(
            wb._on_text_bound(update, context, raw=raw, text=text, uid=str(chat_id)),
            timeout=timeout_s,
        )
        _ok(label, f"{time.perf_counter()-t0:.1f}s")
    except asyncio.TimeoutError:
        _fail(label, f"timeout>{timeout_s}s")
        await asyncio.to_thread(
            tg.send_message, int(chat_id), f"【自測逾時】{label} >{timeout_s}s"
        )
    except Exception as exc:
        _fail(label, f"{type(exc).__name__}: {exc}")
        traceback.print_exc()
        await asyncio.to_thread(
            tg.send_message, int(chat_id), f"【自測失敗】{label}：{type(exc).__name__}"
        )


async def main() -> int:
    from bot_servers import (
        MENU_BTN_WINRATE,
        MENU_BTN_SCREEN,
        MENU_BTN_WATCH,
        MENU_BTN_BIAOKE,
        MENU_BTN_MARKET,
        MENU_BTN_FLOW,
        MENU_BTN_PRESSURE,
        MENU_BTN_AI,
        MENU_BTN_STREAK,
        MENU_BTN_LEAVE_ZERO,
        MENU_BTN_DONGZHU,
        WayneTelegramBot,
    )

    chat_id = _chat_id()
    tg = TgHttp(_token())
    wb = WayneTelegramBot(token=_token(), chat_id=chat_id)

    await asyncio.to_thread(
        tg.send_message,
        int(chat_id),
        "【話筒主選單自測開始】逐鈕走正式 handler 直送；不搶 getUpdates；非買訊。",
    )

    # 重鈕設較長逾時；海選最重
    from bot_servers import MENU_BTN_LEAVE_BIAOKE, MENU_BTN_LEAVE_DONGZHU

    buttons = [
        ("勝率買點", MENU_BTN_WINRATE, 180),
        ("海選", MENU_BTN_SCREEN, 300),
        ("持股", "持股", 90),
        ("加入觀察", MENU_BTN_WATCH, 90),
        ("飆大", MENU_BTN_BIAOKE, 120),
        ("離開飆大", MENU_BTN_LEAVE_BIAOKE, 60),
        ("台股大盤", MENU_BTN_MARKET, 180),
        ("資金輪動", MENU_BTN_FLOW, 180),
        ("當沖", "當沖", 180),
        ("隔日沖", "隔日沖", 180),
        ("壓撐觀察", MENU_BTN_PRESSURE, 180),
        ("AI倉", MENU_BTN_AI, 120),
        ("連買區", MENU_BTN_STREAK, 120),
        ("剛脫離零", MENU_BTN_LEAVE_ZERO, 180),
        ("洞燭先機", MENU_BTN_DONGZHU, 180),
        ("離開洞燭先機", MENU_BTN_LEAVE_DONGZHU, 60),
    ]
    for label, text, to in buttons:
        await press(wb, tg, chat_id, label, text, float(to))
        await asyncio.sleep(0.8)

    fails = [r for r in REPORT if not r["ok"]]
    summary = (
        f"【話筒主選單自測結束】通過 {len(REPORT)-len(fails)}／{len(REPORT)}"
        + (f"；失敗：{', '.join(r['name'] for r in fails)}" if fails else "；全過")
    )
    await asyncio.to_thread(tg.send_message, int(chat_id), summary)
    out = ROOT / "data" / "phone_selfcheck" / "menu_report.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(REPORT, ensure_ascii=False, indent=2), encoding="utf-8")
    print(summary, flush=True)
    return 1 if fails else 0


if __name__ == "__main__":
    try:
        raise SystemExit(asyncio.run(main()))
    except Exception:
        traceback.print_exc()
        raise SystemExit(2)
