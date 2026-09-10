# -*- coding: utf-8 -*-
"""飆大按鈕＝即時對話窗口。問句走雲端對話線，接上一句暢談。

金鑰沿用話筒聽寫那組（GROQ_API_KEY／OPENAI_API_KEY／WAYNE_STT_KEY），
也可用 WAYNE_BIAOKE_LLM_KEY／URL／MODEL 指定。pytest 預設不打外網。
"""
from __future__ import annotations

import logging
import os
import re
from typing import Any, List, Optional, Sequence

import requests

from tg_layout import html_escape

logger = logging.getLogger("WayneBot.BiaokeLive")

_GROQ_CHAT = "https://api.groq.com/openai/v1/chat/completions"
_OPENAI_CHAT = "https://api.openai.com/v1/chat/completions"
_TIMEOUT = 28.0

SYSTEM = """你是 WayneBot 手機話筒「飆大」按鈕後面那顆即時對話腦。
偉權與哥哥兩支手機同一條路。現在就是對話窗口：直接答、接上一句，不要倒選單、不要倒課綱、不要叫人去按其他鈕才能聊。

你可以暢談：台股、美股、大盤、個股、這顆 Bot 怎麼用（鍵盤、圈圈、海選、持股、觀察、更新到手機）。
講進出場時加一句「這不是買訊」。不改海選／黃金買點。
個股用飆大公開文那套想：量先價行、夜盤先於日盤、1-4 重疊、三個買點、半山腰只隔日沖、止跌講結構不猜日曆。語料沒點名的檔也用同一套套官方 K，並說可能看錯。
下面「參考」是庫內語料與官方 K，有就用，沒有就明講庫沒這筆，不要編造外資／投信／融資成本。
回答用繁體中文，像對面說話，短句。不要自稱 Gemini 或 ChatGPT。
"""


def live_key() -> str:
    return (
        os.getenv("WAYNE_BIAOKE_LLM_KEY")
        or os.getenv("GROQ_API_KEY")
        or os.getenv("OPENAI_API_KEY")
        or os.getenv("WAYNE_STT_KEY")
        or ""
    ).strip()


def live_enabled() -> bool:
    flag = (os.getenv("WAYNE_BIAOKE_LIVE") or "1").strip().lower()
    if flag in ("0", "off", "false", "no"):
        return False
    if os.environ.get("PYTEST_CURRENT_TEST") and os.getenv("WAYNE_BIAOKE_LIVE_TEST") != "1":
        return False
    return bool(live_key())


def live_endpoint() -> str:
    url = (os.getenv("WAYNE_BIAOKE_LLM_URL") or "").strip()
    if url:
        return url
    key = live_key()
    if key.startswith("gsk_"):
        return _GROQ_CHAT
    groq = (os.getenv("GROQ_API_KEY") or "").strip()
    if groq and key == groq:
        return _GROQ_CHAT
    return _OPENAI_CHAT


def live_model() -> str:
    raw = (os.getenv("WAYNE_BIAOKE_LLM_MODEL") or "").strip()
    if raw:
        return raw
    if live_endpoint().startswith("https://api.groq.com"):
        return "llama-3.3-70b-versatile"
    return "gpt-4o-mini"


def _clip(text: str, n: int) -> str:
    s = re.sub(r"\s+", " ", str(text or "")).strip()
    return s if len(s) <= n else s[: n - 1] + "…"


def _grounding(db_path: str, ask: str) -> str:
    bits: List[str] = []
    try:
        from biaoke_brain import match_posts, resolve_stock, volume_first_price, load_bars

        posts = match_posts(ask, limit=4, db_path=db_path)
        for p in posts:
            bits.append(
                "語料 "
                + str(p.get("date") or "")
                + " "
                + _clip(p.get("text") or "", 180)
            )
        hits = resolve_stock(db_path, ask) if db_path else []
        if hits:
            hit = hits[0]
            sid = str(hit.get("stock_id") or "")
            bars = load_bars(db_path, sid) if sid else []
            st = volume_first_price(bars) if bars else {}
            bits.append(
                "官方K "
                + sid
                + " "
                + str(hit.get("stock_name") or "")
                + " 爆量日="
                + str(st.get("spike_date") or "")
                + " 高="
                + str(st.get("spike_high") or "")
                + " 低="
                + str(st.get("spike_low") or "")
                + " 量縮="
                + str(st.get("shrinking"))
            )
    except Exception:
        logger.debug("飆大即時參考略過", exc_info=True)
    if not bits:
        return "參考：這句庫內沒對到語料摘錄。"
    return "參考：\n" + "\n".join(bits[:8])


def _history_messages(history: Optional[Sequence[Any]]) -> List[dict]:
    out: List[dict] = []
    for item in list(history or [])[-12:]:
        if isinstance(item, dict):
            ask = str(item.get("ask") or "").strip()
            ans = str(item.get("answer") or "").strip()
        elif isinstance(item, (list, tuple)) and len(item) >= 2:
            ask, ans = str(item[0] or "").strip(), str(item[1] or "").strip()
        else:
            continue
        if ask:
            out.append({"role": "user", "content": _clip(ask, 400)})
        if ans:
            plain = re.sub(r"<[^>]+>", "", ans)
            out.append({"role": "assistant", "content": _clip(plain, 700)})
    return out


def _parse_content(payload: Any) -> str:
    if not isinstance(payload, dict):
        return ""
    choices = payload.get("choices") or []
    if not choices:
        return ""
    msg = (choices[0] or {}).get("message") or {}
    return str(msg.get("content") or "").strip()


def live_reply(
    db_path: str,
    ask: str,
    history: Optional[Sequence[Any]] = None,
) -> str:
    """即時一句回覆。沒金鑰或外網失敗回空字串，由呼叫端走彙整。"""
    q = (ask or "").strip()
    if not q or not live_enabled():
        return ""
    key = live_key()
    url = live_endpoint()
    model = live_model()
    messages = [
        {"role": "system", "content": SYSTEM + "\n" + _grounding(db_path, q)},
    ]
    messages.extend(_history_messages(history))
    messages.append({"role": "user", "content": q})
    try:
        res = requests.post(
            url,
            headers={
                "Authorization": f"Bearer {key}",
                "Content-Type": "application/json",
            },
            json={
                "model": model,
                "messages": messages,
                "temperature": 0.5,
                "max_tokens": 700,
            },
            timeout=_TIMEOUT,
        )
        res.raise_for_status()
        text = _parse_content(res.json())
    except Exception:
        logger.exception("飆大即時對話線失敗 model=%s", model)
        return ""
    if not text:
        return ""
    return html_escape(_clip(text, 3500))
