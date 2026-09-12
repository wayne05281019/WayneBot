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

SYSTEM = """你是使用者認可、正在跟他講話的那顆 AI。手機按「飆大」進來，打字或語音都是對你說。

你不是飆大本人，也不是課綱朗讀機。筆記是材料，不是逐條照念的表格。對面剛問什麼就先答什麼，像在講話，不要清單、不要「現況／量價／產業」填空、不要開場念規則。

他怎麼想（串起來用，不要當標題唸）：
- 最強的是抓資金剛起漲。看一檔先看這族龍頭現在攻還是休息，再看這檔；例如光通訊先看聯亞。
- 大盤走勢他非常準，但波浪位階不講死：可能先當 A，也可能換成任何一個字母。同一晚可以並存多種標籤，用點數一驗再驗才收斂，不要一次釘死。
- 波浪／細微波／15分／60分／夜盤是拿來看大盤的。2024-06-02 說用波浪操作股票比解大盤難很多；2024-06-12 說很少用波浪分析個股。不要把波浪百分之百套在個股。
- 覆巢之下無完卵：大盤不穩，個股會出問題。不是神，但技術分析是為了提早規劃、資金先回收，不是等大跌才跑。
- 個股看產業趨勢、龍頭量價、誰先過前高、量先價行。庫沒 15 分就不數他的段數。

硬規則：
- 點位只准用筆記裡出現過的數字。沒有就說這句筆記沒這點位，不准自己編。
- 他預估哪一檔會到哪個價：只用彙整列的當日收與後來實價。沒這列不准編目標。
- 加權／台指期現在是四萬點這一級。禁止寫 17000、16500、17200。2025 年的 22000 不是現在。
- 禁止套教科書「上升三浪」。
- 問「可以用嗎／讀得到嗎」：用最新一則的日期＋他原話裡一個點位證明你讀到了。禁止客服腔。
- 樓下＝他自己回覆，不是路人。最新發文優先於舊文。

講到「能不能買／該出嗎」才補一句這不是買訊。不要自稱 Gemini、ChatGPT、Claude。
繁體中文。兩三段說完。
"""


def live_key() -> str:
    return (
        os.getenv("WAYNE_BIAOKE_LLM_KEY")
        or os.getenv("GROQ_API_KEY")
        or os.getenv("OPENAI_API_KEY")
        or os.getenv("WAYNE_STT_KEY")
        or ""
    ).strip()


def live_configured() -> bool:
    """雲端有沒有對話金鑰。健檢用；不看 pytest 開關。"""
    return bool(live_key())


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


def live_notes(db_path: str, ask: str) -> str:
    """每句對話都帶：最新主文、最新樓下自回、官方點位。沒對到關鍵字也不准空手。"""
    bits: List[str] = [
        "硬規則：點位只准用下面出現過的數字。沒有就說沒有。禁止 17000／16500。最新優先於舊文。"
    ]
    try:
        from biaoke_desk import load_corpus
        from biaoke_brain import load_index_bars, match_posts, resolve_stock, volume_first_price, load_bars
        from biaoke_walk import extract_index_levels, post_chart_urls

        blob = load_corpus(db_path if db_path else None)
        posts = list((blob or {}).get("posts") or [])
        mains = [p for p in posts if (p.get("kind") or "post") != "reply"]
        replies = [p for p in posts if p.get("kind") == "reply"]
        bits.append(
            f"庫 {blob.get('from') or ''}～{blob.get('to') or ''} "
            f"主文{blob.get('n') or 0}＋樓下{blob.get('replies') or 0}"
        )
        for p in mains[-3:]:
            charts = post_chart_urls(str(p.get("text") or ""))
            extra = f" 附圖{len(charts)}" if charts else ""
            bits.append(
                "最新發文 "
                + str(p.get("date") or "")
                + " "
                + str(p.get("time") or "")
                + extra
                + " "
                + _clip(p.get("text") or "", 420)
            )
        for p in replies[-8:]:
            bits.append(
                "最新樓下 "
                + str(p.get("date") or "")
                + " "
                + str(p.get("time") or "")
                + " "
                + _clip(p.get("text") or "", 280)
            )
        for p in list(mains[-3:]) + list(replies[-8:]):
            for hit in extract_index_levels(str(p.get("text") or "")):
                bits.append(
                    "他原文點位 "
                    + str(p.get("date") or "")
                    + " "
                    + str(hit.get("role") or "")
                    + " "
                    + str(hit.get("level") or "")
                    + " "
                    + _clip(hit.get("ctx") or "", 80)
                )
        bars = load_index_bars(db_path, n=2) if db_path else []
        if bars:
            last = bars[-1]
            bits.append(
                "官方加權 "
                + str(last.get("date") or "")
                + " 收 "
                + str(last.get("close") or "")
                + " 高 "
                + str(last.get("high") or "")
                + " 低 "
                + str(last.get("low") or "")
            )
        else:
            bits.append("官方加權：這顆庫還沒這列，不准自己寫點位。")
        try:
            from taiwan_market import load_futures_daily, load_futures_night

            tx = load_futures_daily(db_path) if db_path else None
            if tx:
                bits.append(
                    "官方台指期日盤 "
                    + str(tx.get("date") or "")
                    + " 收 "
                    + str(tx.get("close") or "")
                    + " 高 "
                    + str(tx.get("high") or "")
                    + " 低 "
                    + str(tx.get("low") or "")
                )
            night = load_futures_night(db_path) if db_path else None
            if night:
                bits.append(
                    "官方台指期夜盤 "
                    + str(night.get("date") or "")
                    + " 收 "
                    + str(night.get("close") or "")
                    + " 高 "
                    + str(night.get("high") or "")
                    + " 低 "
                    + str(night.get("low") or "")
                )
        except Exception:
            pass
        from biaoke_link import format_link_notes
        from biaoke_mind import match_methods
        from biaoke_trace import format_trace

        tr = format_trace(ask, db_path)
        if tr:
            bits.append("時間線 " + _clip(tr, 900))
        try:
            from biaoke_verify import format_origin_backtest, format_watch, is_watch_ask

            if is_watch_ask(ask):
                bits.append("核對 " + _clip(format_watch(db_path), 900))
            if re.search(r"(第一篇|從第一|回測|一步一腳印)", ask):
                bits.append("從第一篇 " + _clip(format_origin_backtest(db_path), 500))
        except Exception:
            pass
        try:
            from biaoke_audit import format_audit, is_audit_ask

            if is_audit_ask(ask):
                bits.append("三遍交叉 " + _clip(format_audit(db_path), 900))
        except Exception:
            pass
        for _title, body in match_methods(ask, limit=2):
            bits.append("方法 " + _clip(body, 400))
        keyed = match_posts(ask, limit=3, db_path=db_path)
        for p in keyed:
            bits.append(
                "關鍵字命中（舊文可能過時） "
                + str(p.get("date") or "")
                + " "
                + _clip(p.get("text") or "", 160)
            )
        note = format_link_notes(keyed, db_path=db_path, limit=3)
        if note:
            bits.append(note)
        hits = resolve_stock(db_path, ask) if db_path else []
        if hits:
            hit = hits[0]
            sid = str(hit.get("stock_id") or "")
            try:
                from biaoke_judge import format_judge_notes, judge_stock

                judged = format_judge_notes(
                    judge_stock(db_path, sid, name=str(hit.get("stock_name") or ""))
                )
                if judged:
                    bits.append(judged)
            except Exception:
                bars_s = load_bars(db_path, sid) if sid else []
                st = volume_first_price(bars_s) if bars_s else {}
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
            try:
                from biaoke_walk import format_stock_walk

                walk = format_stock_walk(
                    db_path,
                    sid,
                    name=str(hit.get("stock_name") or ""),
                )
                if walk:
                    bits.append("彙整 " + _clip(walk, 720))
            except Exception:
                pass
    except Exception:
        logger.debug("飆大即時參考略過", exc_info=True)
    return "筆記（不要照抄格式）：\n" + "\n".join(bits[:36])


def _grounding(db_path: str, ask: str) -> str:
    return live_notes(db_path, ask)


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
    """即時一句回覆。沒金鑰回空。外網失敗換下一顆模型，不中途放棄。"""
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
                    "temperature": 0.2,
                    "max_tokens": 900,
                },
                timeout=timeout,
            )
        except Exception:
            logger.exception("飆大即時對話線失敗 model=%s", model)
            last_err = f"{model}:exc"
            continue
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
            last_err = f"{model}:http"
            continue
        if not text:
            last_err = f"{model}:empty"
            continue
        return _to_talk(text)
    if last_err:
        logger.warning("飆大即時對話線全數未回 %s", last_err)
    return ""
