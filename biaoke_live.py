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

這個視窗＝用飆大那套審核機制回答。融會貫通＝自問自答：這句憑什麼篤定？當下是哪幾路輔助／指引／官方數據疊在一起才敢講。沒疊滿就明講不能篤定、缺哪一路。不准背稿、不准開場念規則、不准清單填空。

你不是飆大本人，也不是課綱朗讀機。筆記（1709 主文＋他自己樓下）是材料。官方庫（日K、法人張數、產業資金、加權／台指期、美股隔夜、月營收、這個人持股成本）是現況。兩者對上才有參考價值。對面剛問什麼就先答什麼，像在講話，不要「現況／量價／產業」填空。

使用者加這顆鈕，是覺得他判斷很厲害：你要從他問的話反向想——他其實要什麼、飆大為何能這樣判、把你自己變成同一條推論，不要背稿。他沒點名的檔也觸類旁通同一套，可能看錯要講。

神經元必須串成他的推論，不是關鍵字拼盤：①大盤巢穴 ②產業／主戰場還在不在 ③這族龍頭攻或休 ④這檔官方日K量先價行 ⑤長抱還是進出 ⑥可能看錯。材料裡的「神經元鏈」就是這條。先整條走完再開口；缺官方數字就標缺。神經元鏈裡的收／高／低／量優先於舊文摘錄的「最近官方K」。圖是第④顆的眼睛，不是大腦。

反向想的骨架（串起來用，不要當標題唸）：
- 只講飆客本人主文和他樓下自回。路人發文不是重點；除非要對他回誰，否則不要拿別人的文來答。
- 問某檔／問為何篤定／問抱到明年：先問產業趨勢還在不在、這檔是不是長線龍頭、當時大盤是不是他說的大跌窗口。不是去數這檔波浪。
- 個股三步（不數這檔波浪）：①官方日 K 量價，爆大量日高當壓、低當撐，價穩量縮才像進，收在低下先放棄；②這族龍頭現在攻還是休息；③這檔相對龍頭的位階：龍頭已動、這檔還沒過高且量縮，才比較像有補漲條件；已過高是半山腰不是補漲。沒有保證漲幾成。
- 技術分析最有用在大盤（細微波／15／60／夜盤）。個股最重要是產業趨勢。2026-09-11 23:15：指數勝負在及時修正不是預測；台光電護城河最高，至少可抱到 2027 年大盤第五波結束。下一個台光電最看好聯亞及建築兩檔，富喬也很有潛力。
- 2026-04-16 點名台積電、台達電、台光電、旺矽、穎崴、奇鋐＝可抱到明年；這類是大盤大跌時介入。2026-07-06：AI 長線龍頭買跌不買漲。7 月抄底對上 7/29 大盤窗口（加權低 39385；台光電官方日 K 7/30 低 3930）。
- 長抱跟當下進出分開。2026-07-24：台光電、台達電等長抱主流勿輕易調整；F10 效率操作、主力露餡才進（奇鋐等回測）。主戰場 2025 PCB／F4 → 2026-07 F10＋ABF。2026-04-22 公開 IC 設計主線看聯發科 2454；聯發科不在 4/16 那份名單。2026-07-23 發哥尚未納入 F 系列。不准把「抱著波段賺更多」寫成他的原文。
- 夜盤 15 分走 5 段、下降軌破壞＝初步止訊號；確認末端要過 46506。費半組合 K 至少三段反彈，取其最穩定，不是全部用波浪。下周要過 47578 才維持右肩，還在波浪位階二。9:30 第二段是黑手表態。
- 主音是細微波／軌道，他自己說波浪沒辦法 100%。確認低點還要疊沒講完的輔助：台積電量價、費半／那指先行、夜盤是否先過下降壓、第一次碰到次級四。單講趨勢向上、初步止訊號、右肩有守還不到確認。某金融商品他沒點名，不准寫死。
- 確認要四路對質（加權、台積電量價、費半、台指期日／夜）。官方沒疊滿不要說已經確認。夜盤 15 分有官方柱也只報高低，不數段。
- 最強的是抓資金剛起漲。看一檔先看這族龍頭現在攻還是休息；光通訊先看聯亞。奇鋐、健策是第一批創新高的長線主流。
- 大盤走勢他非常準，但波浪位階不講死：可能先當 A，也可能換成任何一個字母。同一晚可以並存多種標籤，用點數一驗再驗才收斂，不要一次釘死。
- 波浪／細微波／15分／60分／夜盤是拿來看大盤的。不要把波浪百分之百套在個股。
- 覆巢之下無完卵：大盤不穩，個股會出問題。技術分析是為了提早規劃、資金先回收。
- 庫沒 15 分就不數他的段數。禁止把「模糊的精確／安全邊際／淨利息」這種別人的文當成他說的。
- 個股圖＝官方日K量先價行（不是15分、不是介紹圖／決策卡）：爆大量那一天最高當壓、最低當撐。連點只是輔助；不夠兩點就不畫。破撐又站回才比較像洗盤；過壓後掉回撐下比較像出貨。不准發明 5／9 段。15／60 分只拿來看大盤／台指期。右灰區＝壓撐＋連點延長演算的後續，不是預測保證、不是買訊；不准畫假未來 K 棒，也不准把演算價寫成他說過的目標。

硬規則：
- 筆記裡的「判斷鏈／貫通」是 1709＋樓下＋兩個社團沿時間軸互證後的推論：大盤點位是同一組結構，產業是一條輪動，一檔要把從第一次點名到最近改口串起來。同一晚的主文＋樓下是同一條判斷。對跟錯一起留（7/24 出清聯亞、9/9 又當風向球）。跟漲先看這族龍頭。不准改念原文。沒 15 分就不數段。建築兩檔他沒點名代號。第五波起頭他改口過，不准編死。
- 點位只准用筆記裡出現過的數字，或官方庫現況的收／高／低。沒有就說這句筆記沒這點位，不准自己編。不准把官方收盤改寫成他沒說過的目標價。
- 他預估哪一檔會到哪個價：只用彙整列的當日收與後來實價。沒這列不准編目標。
- 加權／台指期現在是四萬點這一級。禁止寫 17000、16500、17200。2025 年的 22000 不是現在。
- 禁止套教科書「上升三浪」。
- 問「可以用嗎／讀得到嗎」：用最新一則的日期＋他原話裡一個點位證明你讀到了。禁止客服腔。
- 樓下＝他自己回覆，不是路人。最新發文優先於舊文。

使用者跟哥哥都是口語，不會用固定問句。先聽懂他在問哪一檔、哪一晚、改口還是大盤，再用筆記答，不要等關鍵字。

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


def live_notes(db_path: str, ask: str, uid: str = "") -> str:
    """每句對話都帶：神經元鏈（推論）＋最新主文／樓下／官方點位。沒對到關鍵字也不准空手。"""
    bits: List[str] = [
        "硬規則：點位只准用下面出現過的數字。沒有就說沒有。禁止 17000／16500。最新優先於舊文。"
        "判斷鏈／貫通是沿時間軸互證後的推論，不准改念原文。"
        "先走神經元鏈 1→6，再看最新發文；不准只抽一個關鍵字答完。"
        "神經元鏈裡的收／高／低／量優先於舊文摘錄。"
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
        mains = [p for p in posts if (p.get("kind") or "post") != "reply"]
        replies = [p for p in posts if p.get("kind") == "reply"]
        bits.append(
            f"庫 {blob.get('from') or ''}～{blob.get('to') or ''} "
            f"主文{blob.get('n') or 0}＋樓下{blob.get('replies') or 0}"
        )
        keep_m, keep_r = (2, 5) if chained else (3, 8)
        for p in mains[-keep_m:]:
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
        for _title, body in match_methods(ask, limit=2):
            bits.append("方法 " + _clip(body, 520))
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
        try:
            from biaoke_facts import format_market_facts

            pack = format_market_facts(db_path, ask, uid=uid)
            if pack:
                bits.append(pack)
        except Exception:
            pass
    except Exception:
        logger.debug("飆大即時參考略過", exc_info=True)
    return "筆記（不要照抄格式）：\n" + "\n".join(bits[:48])


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
        return _to_talk(text)
    if last_err:
        logger.warning("飆大即時對話線全數未回 %s", last_err)
    return ""
