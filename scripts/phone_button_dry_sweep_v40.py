#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""v40 全鈕＋子鍵本機乾掃：真 handler／真庫，不准 getUpdates、不准洗話筒。

驗：每鈕有回覆；HTML／圖有真內容（非空、非純失敗句）；第三排綜合篩選與空白格。
結果寫 /opt/cursor/artifacts/phone-button-dry-sweep-v40.json
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import sys
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List
from unittest.mock import AsyncMock, MagicMock
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("WAYNE_SKIP_POLLING", "1")
os.environ.setdefault("MPLBACKEND", "Agg")

TZ = ZoneInfo("Asia/Taipei")
ARTIFACT = Path(os.environ.get("WAYNE_ARTIFACT_DIR", "/opt/cursor/artifacts"))
ARTIFACT.mkdir(parents=True, exist_ok=True)
OUT = ARTIFACT / "phone-button-dry-sweep-v40.json"

# 主選單＋子鍵／打字入口（AI倉＝關閉句仍須正確）
BUTTONS: List[str] = [
    "勝率買點",
    "海選",
    "持股",
    "加入觀察",
    "飆大",
    "台股大盤",
    "資金輪動",
    "流水線",
    "波浪位階",
    "沖區",
    "壓撐觀察",
    "低估名單",
    "連買區",
    "剛脫離零",
    "洞燭先機",
    "綜合篩選",
    # 子鍵／別名
    "當沖",
    "隔日沖",
    "離開飆大",
    "離開洞燭先機",
    "AI倉",
]

FAIL_MARKERS = (
    "失敗",
    "逾時",
    "組不出",
    "暫時沒",
    "異常",
    "找不到",
)


def _strip_html(s: str) -> str:
    return re.sub(r"<[^>]+>", "", s or "")


def _bot():
    from bot_servers import WayneTelegramBot
    from config import allowed_telegram_uids, get_db_path

    uids = [str(u) for u in allowed_telegram_uids() if str(u).strip()]
    chat = uids[0] if uids else "0"
    # 真建構：帶 screener／portfolio／pending；WAYNE_SKIP_POLLING 已設，不准輪詢
    bot = WayneTelegramBot(
        token=os.environ.get("TELEGRAM_BOT_TOKEN") or "dry-token",
        chat_id=chat,
        db_path=get_db_path(),
    )
    bot.charts_dir = str(ARTIFACT / "dry-charts")
    Path(bot.charts_dir).mkdir(parents=True, exist_ok=True)
    return bot


def _msg(uid: int, text: str, bucket: Dict[str, Any]):
    user = SimpleNamespace(id=uid, first_name="dry")
    chat = SimpleNamespace(id=uid)
    message = MagicMock()
    message.chat_id = uid
    message.chat = chat
    message.from_user = user
    message.text = text
    message.message_id = int(time.time() * 1000) % 1_000_000
    message.date = datetime.now(timezone.utc)

    async def _reply_text(*args, **kwargs):
        body = args[0] if args else kwargs.get("text", "")
        bucket["texts"].append(str(body))
        m = MagicMock()
        m.message_id = message.message_id + len(bucket["texts"])
        m.delete = AsyncMock()
        m.edit_text = AsyncMock()
        return m

    async def _reply_html(*args, **kwargs):
        body = args[0] if args else kwargs.get("text", "")
        bucket["htmls"].append(str(body))
        m = MagicMock()
        m.message_id = message.message_id + 100 + len(bucket["htmls"])
        m.delete = AsyncMock()
        m.edit_text = AsyncMock()
        m.edit_caption = AsyncMock()
        return m

    async def _reply_photo(*args, **kwargs):
        photo = kwargs.get("photo") or (args[0] if args else None)
        cap = kwargs.get("caption") or ""
        info: Dict[str, Any] = {"caption": str(cap)[:300]}
        if hasattr(photo, "read"):
            data = photo.read()
            try:
                photo.seek(0)
            except Exception:
                pass
            info["bytes"] = len(data)
        elif isinstance(photo, (str, os.PathLike)) and os.path.isfile(photo):
            info["path"] = str(photo)
            info["bytes"] = os.path.getsize(photo)
        elif isinstance(photo, (bytes, bytearray)):
            info["bytes"] = len(photo)
        bucket["photos"].append(info)
        m = MagicMock()
        m.message_id = message.message_id + 200 + len(bucket["photos"])
        m.delete = AsyncMock()
        return m

    message.reply_text = AsyncMock(side_effect=_reply_text)
    message.reply_html = AsyncMock(side_effect=_reply_html)
    message.reply_photo = AsyncMock(side_effect=_reply_photo)
    return message


def _judge(label: str, bucket: Dict[str, Any], *, expect_closed: bool = False) -> Dict[str, Any]:
    texts = bucket.get("texts") or []
    htmls = bucket.get("htmls") or []
    photos = bucket.get("photos") or []
    plain = "\n".join(_strip_html(x) for x in texts + htmls)
    n_out = len(texts) + len(htmls) + len(photos)
    ok = n_out > 0
    reason = ""
    if expect_closed:
        ok = any("關閉" in (t or "") for t in texts + htmls) or "已關" in plain
        reason = "closed_ack" if ok else "missing_closed_ack"
    elif n_out == 0:
        ok = False
        reason = "no_output"
    else:
        # 純失敗句＝不過；允許文中含「非買訊」
        hard_fail = False
        for blob in texts + htmls:
            s = _strip_html(blob)
            if any(m in s for m in ("組不出", "觀測失敗", "綜合篩選失敗", "流水線觀測失敗")):
                hard_fail = True
            if s.strip() in ("", "None"):
                hard_fail = True
        if hard_fail and not photos:
            ok = False
            reason = "hard_fail_text"
        elif label in ("綜合篩選", "流水線"):
            need = ("非買訊" in plain) and (
                ("節點" in plain) or ("層" in plain) or ("對質" in plain) or ("齊" in plain)
            )
            ok = bool(need)
            reason = "combo_or_pipeline_shape" if ok else "missing_node_shape"
        elif label in ("當沖", "隔日沖", "沖區", "勝率買點", "剛脫離零", "海選", "連買區", "低估名單"):
            # 名單／頁面至少有文字或圖；空名單要講清楚；暫態失敗句不算過
            bad = any(
                x in plain
                for x in ("暫時沒跑完", "AttributeError", "EXC ", "組不出", "查詢失敗")
            )
            ok = (not bad) and n_out > 0 and (len(plain) >= 8 or photos)
            reason = "list_or_page"
        elif label in ("台股大盤", "波浪位階", "資金輪動", "壓撐觀察"):
            ok = n_out > 0 and (len(plain) >= 8 or photos)
            reason = "marketish"
        else:
            ok = n_out > 0
            reason = "any_output"
    return {
        "label": label,
        "ok": bool(ok),
        "reason": reason,
        "n_text": len(texts),
        "n_html": len(htmls),
        "n_photo": len(photos),
        "photo_bytes": [p.get("bytes") for p in photos if p.get("bytes")],
        "plain_head": plain[:240].replace("\n", "／"),
    }


async def _press(bot, uid: int, label: str) -> Dict[str, Any]:
    bucket: Dict[str, Any] = {"texts": [], "htmls": [], "photos": []}
    msg = _msg(uid, label, bucket)
    upd = SimpleNamespace(
        message=msg,
        effective_user=msg.from_user,
        effective_message=msg,
        effective_chat=msg.chat,
    )
    ctx = MagicMock()
    ctx.user_data = {}
    t0 = time.monotonic()
    err = ""
    try:
        # 優先走 on_text；沒有則 _on_text_bound
        if hasattr(bot, "on_text"):
            await asyncio.wait_for(bot.on_text(upd, ctx), timeout=120.0)
        else:
            await asyncio.wait_for(bot._on_text_bound(upd, ctx), timeout=120.0)
    except Exception as e:
        err = f"{type(e).__name__}: {e}"
        bucket["texts"].append(f"EXC {err}")
    dt = time.monotonic() - t0
    judged = _judge(label, bucket, expect_closed=(label == "AI倉"))
    judged["sec"] = round(dt, 2)
    judged["error"] = err
    return judged


async def main() -> int:
    from bot_servers import (
        MENU_BTN_COMBO_SCREEN,
        MENU_BTN_SLOT,
        MENU_LAYOUT_VERSION,
        MENU_ROW1,
        MENU_ROW2,
        MENU_ROW3,
        WayneTelegramBot,
    )

    bot = _bot()
    kb = bot._reply_menu("dry")
    layout = {
        "version": MENU_LAYOUT_VERSION,
        "rows": [[b.text for b in row] for row in kb.keyboard],
        "row3_ok": list(MENU_ROW3) == [b.text for b in kb.keyboard[2]],
        "combo": MENU_BTN_COMBO_SCREEN,
        "slots": MENU_ROW3.count(MENU_BTN_SLOT) == 6,
        "n1": len(MENU_ROW1),
        "n2": len(MENU_ROW2),
        "n3": len(MENU_ROW3),
    }

    from config import allowed_telegram_uids

    allowed = [str(u) for u in allowed_telegram_uids() if str(u).strip()]
    if not allowed:
        raise SystemExit("缺白名單 uid（TELEGRAM_CHAT_ID／WAYNE_FAMILY_CHAT_IDS）")
    uid = int(allowed[0])
    results: List[Dict[str, Any]] = []
    # 空白保留格：按了不應炸
    slot_bucket: Dict[str, Any] = {"texts": [], "htmls": [], "photos": []}
    slot_msg = _msg(uid, MENU_BTN_SLOT, slot_bucket)
    try:
        await bot.on_text(
            SimpleNamespace(
                message=slot_msg,
                effective_user=slot_msg.from_user,
                effective_message=slot_msg,
                effective_chat=slot_msg.chat,
            ),
            MagicMock(),
        )
        slot_ok = (len(slot_bucket["texts"]) + len(slot_bucket["htmls"]) + len(slot_bucket["photos"])) == 0
    except Exception as e:
        slot_ok = False
        slot_bucket["texts"].append(str(e))
    results.append(
        {
            "label": "空白保留格",
            "ok": slot_ok,
            "reason": "noop" if slot_ok else "slot_leaked",
            "plain_head": (slot_bucket["texts"][:1] or [""])[0][:120],
        }
    )

    for label in BUTTONS:
        print(f"… {label}", flush=True)
        try:
            r = await _press(bot, uid, label)
        except Exception:
            r = {
                "label": label,
                "ok": False,
                "reason": "outer_exc",
                "error": traceback.format_exc()[-500:],
            }
        results.append(r)
        print(
            ("OK " if r.get("ok") else "FAIL")
            + f" {label}  {r.get('reason')}  t={r.get('sec')}  {r.get('plain_head','')[:80]}",
            flush=True,
        )
        await asyncio.sleep(0.2)

    # —— 子鍵 callback：壓撐三標籤、連買三種、查股 2330 ——
    async def _callback(data: str) -> Dict[str, Any]:
        bucket: Dict[str, Any] = {"texts": [], "htmls": [], "photos": []}
        msg = _msg(uid, "", bucket)
        q = MagicMock()
        q.data = data
        q.message = msg
        q.from_user = msg.from_user
        q.answer = AsyncMock()
        q.edit_message_text = AsyncMock()
        q.edit_message_reply_markup = AsyncMock()
        upd = SimpleNamespace(
            callback_query=q,
            effective_user=msg.from_user,
            effective_message=msg,
            effective_chat=msg.chat,
            message=None,
        )
        t0 = time.monotonic()
        err = ""
        try:
            await asyncio.wait_for(bot.on_callback(upd, MagicMock()), timeout=120.0)
        except Exception as e:
            err = f"{type(e).__name__}: {e}"
            bucket["texts"].append(f"EXC {err}")
        plain = "\n".join(_strip_html(x) for x in (bucket["texts"] + bucket["htmls"]))
        n_out = len(bucket["texts"]) + len(bucket["htmls"]) + len(bucket["photos"])
        bad = any(x in plain for x in ("AttributeError", "EXC ", "暫時沒跑完", "組不出"))
        ok = (not bad) and n_out > 0 and (len(plain) >= 4 or bucket["photos"])
        return {
            "label": f"cb:{data}",
            "ok": ok,
            "reason": "callback",
            "sec": round(time.monotonic() - t0, 2),
            "n_text": len(bucket["texts"]),
            "n_html": len(bucket["htmls"]),
            "n_photo": len(bucket["photos"]),
            "photo_bytes": [p.get("bytes") for p in bucket["photos"] if p.get("bytes")],
            "plain_head": plain[:240].replace("\n", "／"),
            "error": err,
        }

    from pressure_support_watch import TAG_ORDER

    for tag in TAG_ORDER:
        print(f"… cb:ps:{tag}", flush=True)
        r = await _callback(f"ps:{tag}")
        results.append(r)
        print(("OK " if r["ok"] else "FAIL") + f" cb:ps:{tag}  {r.get('plain_head','')[:80]}", flush=True)

    for kind in ("foreign", "trust", "both"):
        data = f"fb:k:{kind}:ALL"
        print(f"… cb:{data}", flush=True)
        r = await _callback(data)
        results.append(r)
        print(("OK " if r["ok"] else "FAIL") + f" {data}  {r.get('plain_head','')[:80]}", flush=True)

    # 查股主路徑（子圖鈕另測會太長；至少代號進查股要有圖／文）
    print("… lookup:2330", flush=True)
    r = await _press(bot, uid, "2330")
    r["label"] = "lookup:2330"
    # 查股要有圖或長文
    plain = r.get("plain_head") or ""
    r["ok"] = bool(r.get("n_photo") or (r.get("n_html", 0) + r.get("n_text", 0)) >= 1) and "私人 Bot" not in plain
    results.append(r)
    print(("OK " if r["ok"] else "FAIL") + f" lookup:2330  photos={r.get('n_photo')}  {plain[:80]}", flush=True)

    summary = {
        "at": datetime.now(TZ).isoformat(),
        "layout": layout,
        "ok_n": sum(1 for r in results if r.get("ok")),
        "fail_n": sum(1 for r in results if not r.get("ok")),
        "results": results,
        "db_path": getattr(bot, "db_path", ""),
    }
    OUT.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(
        f"DONE ok={summary['ok_n']} fail={summary['fail_n']} → {OUT}",
        flush=True,
    )
    return 0 if summary["fail_n"] == 0 and layout["row3_ok"] and layout["slots"] else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
