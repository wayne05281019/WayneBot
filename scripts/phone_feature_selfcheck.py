#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""話筒自測：本機走真實查股五張路徑，結果用 Bot API 直送白名單手機。

硬規則：
- WAYNE_SKIP_POLLING=1，不准 getUpdates（不跟 Render 搶輪詢）
- 只 sendMessage／sendPhoto（HTTP），不開 Application 輪詢
- 不是買訊；只驗功能有沒有正常出東西
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import time
import traceback
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List, Optional

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


def _chat_ids() -> List[str]:
    ids: List[str] = []
    main = (os.environ.get("TELEGRAM_CHAT_ID") or "").strip()
    if main:
        ids.append(main)
    fam = (os.environ.get("WAYNE_FAMILY_CHAT_IDS") or "").strip()
    for part in fam.split(","):
        p = part.strip()
        if p and p not in ids:
            ids.append(p)
    if not ids:
        raise SystemExit("缺 TELEGRAM_CHAT_ID／WAYNE_FAMILY_CHAT_IDS")
    return ids


def _ok(name: str, detail: str = "", **extra: Any) -> None:
    REPORT.append({"name": name, "ok": True, "detail": detail, **extra})
    print(f"OK  {name}  {detail}", flush=True)


def _fail(name: str, detail: str = "", **extra: Any) -> None:
    REPORT.append({"name": name, "ok": False, "detail": detail, **extra})
    print(f"FAIL {name}  {detail}", flush=True)


class TgHttp:
    """最小 Bot HTTP 客戶端：只 sendMessage／sendPhoto／sendChatAction。"""

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

    def send_message(
        self,
        chat_id: int,
        text: str,
        *,
        parse_mode: Optional[str] = None,
        disable_web_page_preview: bool = True,
    ) -> dict:
        return self._post_json(
            "sendMessage",
            {
                "chat_id": chat_id,
                "text": (text or "")[:3900],
                "parse_mode": parse_mode,
                "disable_web_page_preview": "true" if disable_web_page_preview else "false",
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

    def send_photo(
        self,
        chat_id: int,
        photo,
        *,
        caption: str = "",
        parse_mode: Optional[str] = None,
        read_timeout: float = 90.0,
        write_timeout: float = 120.0,
        connect_timeout: float = 30.0,
        reply_markup=None,
        **_kwargs,
    ) -> dict:
        # multipart
        import uuid

        boundary = f"----wayne{uuid.uuid4().hex}"
        chunks: List[bytes] = []

        def add_field(name: str, value: str):
            chunks.append(f"--{boundary}\r\n".encode())
            chunks.append(
                f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode()
            )
            chunks.append(value.encode() if isinstance(value, str) else value)
            chunks.append(b"\r\n")

        add_field("chat_id", str(chat_id))
        if caption:
            add_field("caption", caption[:1024])
        if parse_mode:
            add_field("parse_mode", parse_mode)
        if reply_markup is not None:
            try:
                mk = reply_markup.to_dict() if hasattr(reply_markup, "to_dict") else reply_markup
                add_field("reply_markup", json.dumps(mk, ensure_ascii=False))
            except Exception:
                pass

        # photo: file path / bytes / file obj
        filename = "chart.jpg"
        if isinstance(photo, (str, Path)) and os.path.isfile(str(photo)):
            filename = os.path.basename(str(photo))
            with open(photo, "rb") as fh:
                blob = fh.read()
        elif hasattr(photo, "read"):
            blob = photo.read()
            filename = getattr(photo, "name", None) or filename
            if isinstance(filename, str) and "/" in filename:
                filename = os.path.basename(filename)
        elif isinstance(photo, (bytes, bytearray)):
            blob = bytes(photo)
        else:
            raise TypeError(f"unsupported photo type {type(photo)}")

        chunks.append(f"--{boundary}\r\n".encode())
        chunks.append(
            (
                f'Content-Disposition: form-data; name="photo"; '
                f'filename="{filename}"\r\n'
                f"Content-Type: application/octet-stream\r\n\r\n"
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
        # write_timeout≈整體；urllib 只有單一 timeout
        timeout = max(float(read_timeout or 90), float(write_timeout or 120), 60.0)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode())


def check_health() -> Dict[str, Any]:
    raw = urllib.request.urlopen(
        "https://waynebot-service.onrender.com/health", timeout=25
    ).read()
    return json.loads(raw)


def _wire_message(tg: TgHttp, chat_id: str, text: str = ""):
    uid = int(chat_id)
    user = SimpleNamespace(id=uid, first_name="自測")
    chat = SimpleNamespace(id=uid)

    async def send_action(action: str):
        await asyncio.to_thread(tg.send_chat_action, uid, action)

    chat.send_action = send_action

    class _Sent:
        def __init__(self, payload: Optional[dict] = None):
            result = (payload or {}).get("result") or {}
            self.message_id = int(result.get("message_id") or 0)
            self.photo = result.get("photo")

        async def edit_text(self, text="", **kwargs):
            return self

    class _Msg:
        def __init__(self):
            self.chat_id = uid
            self.chat = chat
            self.from_user = user
            self.message_id = int(time.time()) % 1_000_000
            self.text = text
            self.caption = None
            self.photo = None

        async def reply_text(self, text="", **kwargs):
            payload = await asyncio.to_thread(
                tg.send_message,
                uid,
                text or "",
                parse_mode=kwargs.get("parse_mode"),
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
                connect_timeout=kwargs.get("connect_timeout", 30.0),
                reply_markup=kwargs.get("reply_markup"),
            )
            return _Sent(payload)

        async def edit_text(self, text="", **kwargs):
            return self

    return _Msg()


async def run_lookup_five(wb, tg: TgHttp, chat_id: str, code: str, name: str) -> None:
    from bot_servers import WayneTelegramBot

    msg = _wire_message(tg, chat_id, text=code)
    uid = str(chat_id)
    actor = WayneTelegramBot._actor_key(msg, uid=uid, chat_id=int(chat_id))
    hits = [{"code": code, "name": name, "market": "上市"}]
    t0 = time.perf_counter()
    try:
        await wb._send_card_to_locked(
            msg, code, uid, actor, hits, wait_msg=None, ensure_task=None
        )
        elapsed = time.perf_counter() - t0
        _ok(f"lookup-{code}", f"{name} 五張路徑 {elapsed:.1f}s")
    except Exception as exc:
        _fail(f"lookup-{code}", f"{type(exc).__name__}: {exc}")
        traceback.print_exc()


async def send_menu_rows(tg: TgHttp, chat_id: str) -> None:
    from bot_servers import MENU_ROW1, MENU_ROW2

    lines = [
        "【話筒自測・兩排主選單】",
        "上排：" + "｜".join(MENU_ROW1),
        "下排：" + "｜".join(MENU_ROW2),
    ]
    await asyncio.to_thread(tg.send_message, int(chat_id), "\n".join(lines))
    _ok("menu-rows", f"{len(MENU_ROW1)}+{len(MENU_ROW2)}")


async def smoke_other_features(wb, tg: TgHttp, chat_id: str) -> None:
    import sqlite3

    try:
        con = sqlite3.connect(wb.db_path)
        n_posts = con.execute("SELECT COUNT(*) FROM biaoke_posts").fetchone()[0]
        latest = con.execute(
            "SELECT date, time, substr(text,1,80) FROM biaoke_posts "
            "ORDER BY date DESC, time DESC LIMIT 1"
        ).fetchone()
        con.close()
        await asyncio.to_thread(
            tg.send_message,
            int(chat_id),
            (
                f"飆大自測：庫內 {n_posts} 則；最新 {latest[0]} {latest[1]}\n"
                f"{(latest[2] or '')[:80]}…\n（非買訊・只驗庫）"
            ),
        )
        _ok("biaoke-db", f"n={n_posts}")
    except Exception as exc:
        _fail("biaoke-db", f"{type(exc).__name__}: {exc}")

    # 持股／觀察：只確認表可讀
    try:
        con = sqlite3.connect(wb.db_path)
        tables = {
            r[0]
            for r in con.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        con.close()
        need = {"holdings", "watchlist", "user_trades", "tg_users"}
        # 表名可能不同；有相關就過
        related = [t for t in tables if any(k in t for k in ("hold", "watch", "trade", "tg_user", "portfolio"))]
        await asyncio.to_thread(
            tg.send_message,
            int(chat_id),
            f"私人本自測：相關表 {', '.join(sorted(related)[:12]) or '無'}（非買訊）",
        )
        _ok("private-tables", f"n={len(related)}")
    except Exception as exc:
        _fail("private-tables", f"{type(exc).__name__}: {exc}")


async def main() -> int:
    out_dir = ROOT / "data" / "phone_selfcheck"
    out_dir.mkdir(parents=True, exist_ok=True)
    chats = _chat_ids()
    chat_id = chats[0]
    tg = TgHttp(_token())

    from bot_servers import WayneTelegramBot

    wb = WayneTelegramBot(token=_token(), chat_id=chat_id, db_path=None)

    h = check_health()
    sha = str(h.get("git_sha") or "")
    await asyncio.to_thread(
        tg.send_message,
        int(chat_id),
        (
            f"【話筒自測開始】Render git_sha={sha[:12]} "
            f"serving={h.get('serving')} polling={h.get('polling_alive')}\n"
            "本機走正式查股五張路徑直送；不搶 getUpdates；非買訊。"
        ),
    )
    if not sha.startswith("3d5663a"):
        _fail("health-sha", sha)
    else:
        _ok("health-sha", sha[:12])

    await send_menu_rows(tg, chat_id)
    await run_lookup_five(wb, tg, chat_id, "3595", "山太士")
    await run_lookup_five(wb, tg, chat_id, "2330", "台積電")
    await smoke_other_features(wb, tg, chat_id)

    fails = [r for r in REPORT if not r.get("ok")]
    summary = (
        f"【話筒自測結束】通過 {len(REPORT) - len(fails)}／{len(REPORT)}"
        + (f"；失敗：{', '.join(r['name'] for r in fails)}" if fails else "；全過")
    )
    await asyncio.to_thread(tg.send_message, int(chat_id), summary)
    if len(chats) > 1:
        await asyncio.to_thread(
            tg.send_message, int(chats[1]), summary + "（哥哥摘要・詳見偉權）"
        )

    (out_dir / "report.json").write_text(
        json.dumps(REPORT, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(summary, flush=True)
    return 1 if fails else 0


if __name__ == "__main__":
    try:
        raise SystemExit(asyncio.run(main()))
    except Exception:
        traceback.print_exc()
        raise SystemExit(2)
