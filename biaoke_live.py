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

SYSTEM = """你是偉權與哥哥手機「飆大」視窗裡那顆 AI。不是飆大本人。不准背稿、不准開場念規則、不准清單填空。繁體中文。兩三段說完。不要自稱別家模型。

硬規則：
- 神經元必須串成一條判斷。六顆（大盤巢穴／產業／主戰場／這族龍頭／這檔量價／長抱還是進出／可能看錯）只當抽屜歸檔，要重讀材料再對官方。開火只出：上一句他自己點過的位 → 官方柱碰到沒 → 改口或還在等。
- 開口第一句用材料「判斷｜」那句，不是六顆交叉稿。個股不准硬套大盤等待、不准貼舊文、不准寫「他自己最新」。
- 想只更新他點過的條件。沒說過的價不准當下一步。不准發明 5／9。個股不數浪。盤中未收不當官方。五件只有疊在同一個他點過的位才叫交叉。圖是第④顆的眼睛；公開附圖索引對官方日K，社團附圖只對價。演算不是保證、不是買訊。截圖會改口。
- 筆記（1709 主文＋一／二層自回）是材料庫，當下去對，不准把日記背進這份規則。路人樓下收進討論串，正文不當他的判斷。IET＝IET-KY 4971。
- 點位只准用材料裡出現過的數字或官方收／高／低。他自己點過、准用的大盤位（不是新價）：43500／45398／45839／46506／46626／46747／46767／47548／47578／48218。沒有就說沒有。禁止 17000、16500。禁止客服腔。禁止套教科書上升三浪。禁止把「模糊的精確／安全邊際／淨利息」當成他說的。不准把官方收盤改寫成他沒說過的目標。
- 最新主文＋全部自回優先於舊文。樓下改口會改位階。每次開口前用材料對，不准只用舊位階。講到能不能買才補不是買訊。
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


def live_notes(db_path: str, ask: str, uid: str = "") -> str:
    """每句對話都帶：神經元鏈（推論）＋最新主文／樓下／官方點位。沒對到關鍵字也不准空手。"""
    bits: List[str] = [
        "硬規則：點位只准用下面出現過的數字。沒有就說沒有。禁止 17000／16500。最新優先於舊文。"
        "判斷鏈／貫通是沿時間軸互證後的推論，不准改念原文。"
        "先出一條判斷，六顆只歸檔；不准只抽一個關鍵字答完。"
        "收／高／低／量優先於舊文摘錄。"
    ]
    chained = False
    try:
        from biaoke_chain import format_chain_notes

        chain = format_chain_notes(db_path, ask, uid=uid)
        if chain:
            bits.append(chain)
            chained = True
    except Exception:
        logger.debug("飆大神經元鏈略過", exc_info=True)
    try:
        from biaoke_why import format_why_notes, is_why_query

        why = format_why_notes(ask)
        if why:
            bits.append(why)
        elif is_why_query(ask):
            bits.append("判斷鏈：這句對不到已建檔的點位／改口鏈，不准編。")
    except Exception:
        pass
    try:
        from biaoke_desk import load_corpus
        from biaoke_brain import load_index_bars, match_posts, resolve_stock, volume_first_price, load_bars
        from biaoke_walk import extract_index_levels, post_chart_urls

        blob = load_corpus(db_path if db_path else None)
        posts = list((blob or {}).get("posts") or [])
        mains = [p for p in posts if (p.get("kind") or "post") not in ("reply", "bystander")]
        replies = [p for p in posts if p.get("kind") == "reply"]
        bits.append(
            f"庫 {blob.get('from') or ''}～{blob.get('to') or ''} "
            f"主文{blob.get('n') or 0}＋樓下{blob.get('replies') or 0}"
        )
        keep_m, keep_r = (2, 16) if chained else (3, 16)
        latest_mains = list(mains[-keep_m:])
        for i, p in enumerate(latest_mains):
            charts = post_chart_urls(str(p.get("text") or ""))
            extra = f" 附圖{len(charts)}" if charts else ""
            clip_n = 980 if i == len(latest_mains) - 1 else 420
            bits.append(
                "最新發文 "
                + str(p.get("date") or "")
                + " "
                + str(p.get("time") or "")
                + extra
                + " "
                + _clip(p.get("text") or "", clip_n)
            )
        for p in replies[-keep_r:]:
            bits.append(
                "最新樓下 "
                + str(p.get("date") or "")
                + " "
                + str(p.get("time") or "")
                + " "
                + _clip(p.get("text") or "", 280)
            )
        for p in list(mains[-keep_m:]) + list(replies[-keep_r:]):
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
        skip_method = (
            {
                "個股先看產業趨勢",
                "長抱主流／F4→F10／聯發科",
                "南亞 1303 長抱或進出",
                "洞燭先機",
                "9/10 主戰場",
                "量先價行",
                "右肩／45839",
                "半山腰只隔日沖",
            }
            if chained
            else set()
        )
        added = 0
        leftover: List[tuple] = []
        for title, body in match_methods(ask, limit=6):
            if title in skip_method:
                leftover.append((title, body))
                continue
            bits.append("方法 " + _clip(body, 520))
            added += 1
            if added >= 2:
                break
        if added == 0:
            for _title, body in leftover[:1]:
                bits.append("方法 " + _clip(body, 520))
        keyed = match_posts(ask, limit=(2 if chained else 3), db_path=db_path)
        if not chained:
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
            bits.append(
                "個股回覆：消化下面材料，不要貼舊文或「他自己最新」。"
                "只講這檔現在官方日K與接下來最可能怎走。"
            )
            if not chained:
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
            from biaoke_facts import format_market_facts

            pack = format_market_facts(db_path, ask, uid=uid)
            if pack:
                bits.append(pack)
        except Exception:
            pass
    except Exception:
        logger.debug("飆大即時參考略過", exc_info=True)
    return "筆記（不要照抄格式）：\n" + "\n".join(bits[:64])


def _grounding(db_path: str, ask: str, uid: str = "") -> str:
    return live_notes(db_path, ask, uid=uid)


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
    uid: str = "",
) -> str:
    """即時一句回覆。沒金鑰回空。外網失敗換下一顆模型，不中途放棄。"""
    q = (ask or "").strip()
    if not q or not live_enabled():
        return ""
    key = live_key()
    url = live_endpoint()
    messages = [
        {"role": "system", "content": SYSTEM + "\n" + _grounding(db_path, q, uid=uid)},
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
        try:
            from biaoke_chain import attach_five_lead

            return attach_five_lead(_to_talk(text), db_path, q, uid)
        except Exception:
            return _to_talk(text)
    if last_err:
        logger.warning("飆大即時對話線全數未回 %s", last_err)
    return ""
