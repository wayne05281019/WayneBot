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

SYSTEM = """你就是手機「飆大」裡正在跟他講話的那個人。對面說話，不是客服、不是簡報、不是老師在唸條文。

先答他剛問的那一句，接得上上一句。不要開場念規則。不要用「第一、第二、他這套怎麼想、三買點對照」這種講義體。不要每則都把細微波、1-4、KD、買點清單倒一遍——只有他問方法時才講。

講到「能不能買／該出嗎」才補一句這不是買訊。不要編外資／投信／融資成本。不要自稱 Gemini、ChatGPT。
繁體中文。兩三段就好，段落可以換行。下面筆記只給你看，不要照抄「發文」「官方K」「爆量日=」這種欄位格式。

例如他問「你好」→「在，你說。」
問「大概何時止跌」→先講現況一兩句，再說他不猜日曆、現在條件齊不齊。不要列 1 2 3 4。
問股名或代號→用筆記裡的收盤／爆量日講這檔現在像不像站上撐，不要把整份課綱貼回去。
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


_GROQ_CHAT_MODELS = ("openai/gpt-oss-120b", "openai/gpt-oss-20b")
_OPENAI_CHAT_MODELS = ("gpt-4o-mini",)


def live_models() -> List[str]:
    """Groq 的 llama-3.3-70b-versatile 2026-08-16 已下架；預設走 gpt-oss。"""
    chosen = (os.getenv("WAYNE_BIAOKE_LLM_MODEL") or "").strip()
    if live_endpoint().startswith("https://api.groq.com"):
        pool = list(_GROQ_CHAT_MODELS)
    else:
        pool = list(_OPENAI_CHAT_MODELS)
    if chosen:
        return [chosen] + [m for m in pool if m != chosen]
    return pool


def live_model() -> str:
    return live_models()[0]


def _clip(text: str, n: int) -> str:
    s = re.sub(r"\s+", " ", str(text or "")).strip()
    return s if len(s) <= n else s[: n - 1] + "…"


def _clip_talk(text: str, n: int) -> str:
    """上一句給模型看時保留換行，才不會學成一長段講義。"""
    s = re.sub(r"[ \t]+", " ", str(text or "")).strip()
    s = re.sub(r"\n{3,}", "\n\n", s)
    return s if len(s) <= n else s[: n - 1] + "…"


def _to_talk(text: str) -> str:
    """保留換行，拿掉講義式 markdown，才不像一張簡報。"""
    s = str(text or "").replace("\r\n", "\n").strip()
    s = re.sub(r"^\s{0,3}#{1,6}\s*", "", s, flags=re.M)
    s = re.sub(r"\*\*(.+?)\*\*", r"\1", s)
    s = re.sub(r"^[\-\*]\s+", "", s, flags=re.M)
    s = re.sub(r"\n{3,}", "\n\n", s)
    if len(s) > 3500:
        s = s[:3499] + "…"
    return html_escape(s)


def _grounding(db_path: str, ask: str) -> str:
    bits: List[str] = []
    try:
        from biaoke_brain import match_posts, resolve_stock, volume_first_price, load_bars
        from biaoke_link import format_link_notes
        from biaoke_mind import match_methods
        from biaoke_trace import format_trace

        tr = format_trace(ask, db_path)
        if tr:
            bits.append("時間線 " + _clip(tr, 700))
        for _title, body in match_methods(ask, limit=2):
            bits.append("方法 " + _clip(body, 500))

        posts = match_posts(ask, limit=4, db_path=db_path)
        for p in posts:
            bits.append(
                "發文 "
                + str(p.get("date") or "")
                + " "
                + _clip(p.get("text") or "", 180)
            )
        note = format_link_notes(posts, db_path=db_path, limit=3)
        if note:
            bits.append(note)
        hits = resolve_stock(db_path, ask) if db_path else []
        if hits:
            try:
                from biaoke_walk import format_stock_walk

                walk = format_stock_walk(
                    db_path,
                    str(hits[0].get("stock_id") or ""),
                    name=str(hits[0].get("stock_name") or ""),
                )
                if walk:
                    bits.append("彙整 " + _clip(walk, 500))
            except Exception:
                pass
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
        return "筆記：這句沒對到摘錄，就照他問的講，不要硬套課綱。"
    return "筆記（不要照抄格式）：\n" + "\n".join(bits[:8])


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
            out.append({"role": "assistant", "content": _clip_talk(plain, 900)})
    return out


def _parse_content(payload: Any) -> str:
    if not isinstance(payload, dict):
        return ""
    choices = payload.get("choices") or []
    if not choices:
        return ""
    msg = (choices[0] or {}).get("message") or {}
    content = msg.get("content") or ""
    if isinstance(content, list):
        bits: List[str] = []
        for part in content:
            if isinstance(part, str):
                bits.append(part)
            elif isinstance(part, dict):
                bits.append(str(part.get("text") or part.get("content") or ""))
        content = "".join(bits)
    return str(content or "").strip()


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
    messages = [
        {"role": "system", "content": SYSTEM + "\n" + _grounding(db_path, q)},
    ]
    messages.extend(_history_messages(history))
    messages.append({"role": "user", "content": q})
    models = live_models()
    last_err = ""
    for i, model in enumerate(models):
        timeout = _TIMEOUT if i == 0 else 14.0
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
                    "temperature": 0.85,
                    "max_tokens": 900,
                },
                timeout=timeout,
            )
        except Exception:
            logger.exception("飆大即時對話線失敗 model=%s", model)
            return ""
        status = int(getattr(res, "status_code", 200) or 200)
        if status in (400, 404, 422) and i < len(models) - 1:
            logger.warning("飆大即時 model=%s status=%s，換下一顆", model, status)
            last_err = f"{model}:{status}"
            continue
        try:
            res.raise_for_status()
            text = _parse_content(res.json())
        except Exception:
            logger.exception("飆大即時對話線失敗 model=%s", model)
            return ""
        if not text:
            last_err = f"{model}:empty"
            if i < len(models) - 1:
                continue
            return ""
        return _to_talk(text)
    if last_err:
        logger.warning("飆大即時對話線全數未回 %s", last_err)
    return ""
