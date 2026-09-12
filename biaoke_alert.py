# -*- coding: utf-8 -*-
"""盤中／夜盤緊急：自己研判要不要跳過飆大鈕，直接推進偉權＋哥哥對話框。

促發不是一組固定名詞。大盤急跌七百點＋「台積電最值得抄底」只是一種例子。
下次他換句話說、換一種位階改口、或夜盤先崩，也要能判出來。
看四件事疊在一起：指數力度、這則在做什麼（出清／抄底／改口／通知／命令）、
跟上則比有沒有翻面、主音（波浪）有沒有疊到他沒講完的輔助。
波浪他自己說沒辦法 100%；確認低點還要台積電量價、費半先行、夜盤是否過壓。
單講趨勢向上、初步止訊號、右肩有守＝還不到確認，不推。
沒把握才問對話線一句 yes/no。不是買訊。同一則不重覆推。社團不推。
"""
from __future__ import annotations

import logging
import os
import re
import sqlite3
from typing import Any, Dict, List, Optional, Sequence, Tuple

from tg_layout import html_escape

logger = logging.getLogger("WayneBot.BiaokeAlert")

DROP_POINTS = 700.0
PUSH_SCORE = 5
GRAY_SCORE = 3

_DDL = """
CREATE TABLE IF NOT EXISTS biaoke_alerts (
    post_id TEXT PRIMARY KEY,
    score INTEGER NOT NULL DEFAULT 0,
    reasons TEXT NOT NULL DEFAULT '',
    sent_at TEXT NOT NULL DEFAULT ''
);
"""

# 族＝意圖，不是單一名詞。新詞只要落在同一族就會加分。
_EXIT = re.compile(
    r"(出清|一股不留|全部賣|全部出|先回收|不要再碰|不要再布局|"
    r"不要再介入|不要再買|停損|逃命|減碼一半|減碼\s*1\s*/\s*2|"
    r"調節總持股|今天不要有動作|不能介入布局)"
)
_ENTER = re.compile(
    r"(抄底|開始介入|分批布局|分三次|第一次抄|買跌不買漲|"
    r"買點到|現在就是|值得抄|可以開始|這就是.{0,12}(位置|時間|買點)|"
    r"大跌時介入|技術分析抄底|這次B波|第一次.*抄)"
)
_RETRACT = re.compile(
    r"(已經沒了|失敗的第五|改\s*A-c|改口|更正|今天最低|"
    r"最樂觀.{0,12}沒了|不破\s*40000|講錯|看錯了)"
)
_NOTIFY = re.compile(
    r"(發文通知|C-2\s*轉\s*C-3|出現才發文|一定會發文|觀盤重點就是今晚|"
    r"穿越.{0,6}才確認)"
)
_LEADER = re.compile(
    r"(台積電.{0,30}(買點|抄|介入|區間|布局)|"
    r"(買點|抄|介入).{0,16}台積電|"
    r"長線龍頭.{0,24}(介入|出清|勿輕易|續抱)|"
    r"護城河最高|倒了就是)"
)
_COMMAND = re.compile(
    r"(一定要|立刻|全面|今天不要|不能介入|等盤後判斷|先不要|"
    r"一股不留|趕快跑)"
)
_INDEXISH = re.compile(r"(大盤|加權|台指|夜盤|細微波|波浪位階|下降軌)")
_NIGHT_CRASH = re.compile(r"夜盤.{0,10}(大跌|崩|重挫|跳空)")
_ROUTINE = re.compile(
    r"(散熱族群最為強勢|輪漲格局|謝謝|感謝飆大|Yes$|耐心等待)"
)

# 主音＝波浪／軌道。他自己 7/31 寫「波浪理論沒辦法 100% 確認」。
_MAIN_DONE = re.compile(
    r"(走完\s*[59]\s*段|[59]\s*段.{0,10}(走完|結束|完成)|下跌走\s*5|"
    r"完整結構|末跌段.{0,8}(結束|走完|沒了))"
)
_MAIN_BREAK = re.compile(
    r"(下降軌.{0,10}破壞|軌道.{0,8}破壞|躍過.{0,12}下降|"
    r"穿刺.{0,16}下降|越過.{0,16}(下降|壓力))"
)
_MAIN_CROSS = re.compile(
    r"(已穿越|已經穿越|有效穿刺|"
    r"(已經|完全|100%\s*)確認.{0,18}(低點|A\s*波低|到底|不會再))"
)
_MAIN_14 = re.compile(r"(1[\s\-－—]*4\s*重疊|１[\s\-－]*４\s*重疊|14重疊|１４重疊)")
_MAIN_A_LOW = re.compile(
    r"(A\s*波低|大\s*A.{0,8}低|第一次抄底那天就是|"
    r"今年的低點|這就是.{0,8}低點|差不多到底)"
)
_MAIN_B_UP = re.compile(
    r"(大\s*B\s*波啟動|B\s*波啟動|趨勢向上.{0,10}時間|"
    r"漲漲跌跌但趨勢向上)"
)

# 沒講完的輔助：他偶爾寫「輔助判別」，更多次直接並用、不聲明。
_AUX_TSMC = re.compile(
    r"(台積電.{0,48}(量價|爆大量|最大量|假跌破|收.?[=＝].?低|量縮上漲|支撐|止跌)|"
    r"(量價結構|量價).{0,28}(台積電|確認)|"
    r"不公開.{0,12}量價|"
    r"某金融商品.{0,20}量價|"
    r"輔助判別.{0,16}台積電)"
)
_AUX_SOX = re.compile(
    r"(費半|費城半導體|那指|那斯達[克科]).{0,36}"
    r"(1[\s\-－]*4|１[\s\-－]*４|14重疊|重疊|先行|過前|突破盤整|不再破|早就)"
)
_AUX_SOX_SEE = re.compile(r"(費半|費城半導體|那指|那斯達[克科])")
_AUX_NIGHT_OK = re.compile(
    r"夜盤.{0,28}(過|穿刺|突破|破壞|越過).{0,18}(下降|壓力|軌道|水平)"
)
_AUX_NIGHT_NOT = re.compile(
    r"夜盤.{0,18}(沒過|沒有突破|沒突破|沒穿刺).{0,18}(下降|壓力)|"
    r"(還可能擴延|可能擴延|夜盤沒突破下降)"
)
_AUX_TURN = re.compile(
    r"(籌碼換手|月最大量|爆近期.{0,10}最大量|量先價行|價穩量縮|"
    r"量縮上漲過.{0,8}壓力)"
)
_AUX_VANE = re.compile(
    r"(風向球|長線龍頭.{0,18}(修正完成|率先)|"
    r"散熱.{0,14}(先確認低點|先反彈)|"
    r"台積電.{0,16}(比大盤強|先行)|誰先過前高)"
)
_AUX_W4 = re.compile(
    r"(第一次.{0,14}(回測|碰到).{0,14}(四|4)|次級四|"
    r"波浪四點價區|回測.{0,8}四浪)"
)

# 還不到確認：這些是觀盤／濾網，不能當「趨勢往上」推播。
_NOT_YET = re.compile(
    r"(初步止訊號|初步止跌|無法判斷.{0,12}[59]\s*段|"
    r"還無法確認|還沒確認|有沒有守住|"
    r"才確認|至少要穿越|新聞變多|半山腰)"
)
_SHOULDER_ONLY = re.compile(
    r"(高檔震盪.{0,8}趨勢向上|有守住.{0,20}右肩|"
    r"高有過前高.{0,12}低不破前低|維持右肩|做右肩)"
)
_PCT100 = re.compile(r"(100%\s*確認|完全確認|已經\s*100%)")


def _plain(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()


def _clip(text: str, n: int) -> str:
    s = _plain(text)
    return s if len(s) <= n else s[: n - 1] + "…"


def twii_move() -> Dict[str, Any]:
    """盤中 MIS 加權：相對昨收跌多少點、跌幾％。沒即時列就空，不准用舊收盤假裝今天在跌。"""
    out: Dict[str, Any] = {"drop": 0.0, "pct": 0.0, "px": 0.0, "y": 0.0, "ok": False}
    try:
        from live_quote import fetch_mis_index_quote

        q = fetch_mis_index_quote(fresh=True, require_session=True) or {}
    except Exception:
        return out
    try:
        y = float(q.get("yesterday_close") or 0)
        px = float(q.get("close") or 0)
    except (TypeError, ValueError):
        return out
    if y <= 0 or px <= 0:
        return out
    out.update(
        {
            "ok": True,
            "y": y,
            "px": px,
            "drop": round(y - px, 2),
            "pct": round((px - y) / y * 100.0, 2),
        }
    )
    return out


def market_shock(move: Optional[Dict[str, Any]] = None, text: str = "") -> Tuple[int, List[str]]:
    """指數力度。七百點是其中一條線，不是唯一。急跌％、夜盤崩也算。"""
    m = move or {}
    score = 0
    why: List[str] = []
    drop = float(m.get("drop") or 0)
    pct = float(m.get("pct") or 0)
    if m.get("ok"):
        if drop >= DROP_POINTS or pct <= -1.5:
            score += 4
            why.append(f"加權急跌{drop:.0f}點（{pct:.2f}%）")
        elif drop >= 400 or pct <= -0.9:
            score += 2
            why.append(f"加權明顯下跌{drop:.0f}點")
        elif drop >= 250:
            score += 1
            why.append(f"加權下跌{drop:.0f}點")
    if _NIGHT_CRASH.search(text or ""):
        score += 3
        why.append("正文自己在講夜盤急跌")
    return score, why


def confirm_stack(text: str) -> Dict[str, Any]:
    """主音（波浪）不夠。確認末端／差不多到底要疊他沒講完的輔助。

    7/31 原文：波浪沒辦法 100% 確認 A 波低，台積電＋某金融商品量價才 100%。
    「某金融商品」他沒點名，這裡只認他寫了量價結構，不准寫死是哪檔。
    單講趨勢向上、初步止訊號、右肩有守＝還不到確認。
    """
    blob = text or ""
    main: List[str] = []
    aux: List[str] = []
    if _MAIN_DONE.search(blob):
        main.append("細微波走完")
    if _MAIN_BREAK.search(blob):
        main.append("下降軌破壞")
    if _MAIN_CROSS.search(blob):
        main.append("穿越／確認末端")
    if _MAIN_14.search(blob):
        main.append("1-4 重疊")
    if _MAIN_A_LOW.search(blob):
        main.append("A 波低／差不多到底")
    if _MAIN_B_UP.search(blob):
        main.append("大 B 波趨勢向上")
    if _AUX_TSMC.search(blob):
        aux.append("台積電量價")
    if _AUX_SOX.search(blob):
        aux.append("費半／那指先行")
    elif _AUX_SOX_SEE.search(blob) and (
        _AUX_TSMC.search(blob) or _AUX_NIGHT_OK.search(blob)
    ):
        aux.append("費半／那指對照")
    if _AUX_NIGHT_OK.search(blob) and not _AUX_NIGHT_NOT.search(blob):
        aux.append("夜盤已過下降壓")
    if _AUX_TURN.search(blob):
        aux.append("籌碼／量價換手")
    if _AUX_VANE.search(blob):
        aux.append("風向球／龍頭領先")
    if _AUX_W4.search(blob):
        aux.append("第一次回測次級四")

    not_yet = bool(_NOT_YET.search(blob) or _AUX_NIGHT_NOT.search(blob))
    shoulder = bool(_SHOULDER_ONLY.search(blob)) and not _MAIN_A_LOW.search(blob)
    hard = bool(_PCT100.search(blob) and _AUX_TSMC.search(blob))
    stacked = False
    if hard:
        stacked = True
    elif _MAIN_A_LOW.search(blob) and _AUX_TSMC.search(blob):
        stacked = True
    elif _MAIN_CROSS.search(blob) and _MAIN_BREAK.search(blob) and aux and not not_yet:
        stacked = True
    elif _MAIN_14.search(blob) and _AUX_SOX.search(blob) and (
        _MAIN_BREAK.search(blob) or _PCT100.search(blob)
    ):
        stacked = True
    elif len(aux) >= 3 and not not_yet:
        stacked = True
    elif _AUX_W4.search(blob) and _MAIN_DONE.search(blob) and aux:
        stacked = True

    veto = False
    if stacked:
        pass
    elif not_yet or shoulder:
        veto = True
    elif (main or _SHOULDER_ONLY.search(blob)) and not aux:
        # 只剩主音／右肩口號，沒輔助
        veto = True

    score = 0
    why: List[str] = []
    if stacked:
        score = 5
        why.append("主音＋輔助疊成確認（" + "、".join((main + aux)[:4]) + "）")
    elif not veto and main and aux:
        score = 3
        why.append("主音有了、輔助還灰（" + "、".join((main + aux)[:3]) + "）")
    elif veto and (not_yet or shoulder):
        why.append("還不到確認末端（初步／右肩觀盤／夜盤沒過）")
    return {
        "confirmed": bool(stacked),
        "veto": bool(veto),
        "score": int(score),
        "reasons": why,
        "main": main,
        "aux": aux,
    }


def content_intents(text: str) -> Tuple[int, List[str]]:
    """這則在做什麼，不是掃有沒有出現某幾個字。"""
    blob = text or ""
    score = 0
    why: List[str] = []
    if _ROUTINE.search(blob) and not (_EXIT.search(blob) or _ENTER.search(blob) or _RETRACT.search(blob)):
        return 0, []
    hits = [
        (_EXIT, 4, "出清／逃命／先回收"),
        (_ENTER, 4, "抄底／介入窗口"),
        (_RETRACT, 3, "位階改口"),
        (_NOTIFY, 3, "他說出現會發文那類"),
        (_LEADER, 3, "長線龍頭時機"),
        (_COMMAND, 2, "命令句／禁止動作"),
    ]
    for pat, pts, label in hits:
        if pat.search(blob):
            score += pts
            why.append(label)
    if _INDEXISH.search(blob) and re.search(r"(1[\.、．]|2[\.、．])", blob):
        score += 1
        why.append("大盤編號主文")
    # 短句＋命令語氣：即使換了用詞也像緊急
    plain = _plain(blob)
    if 8 <= len(plain) <= 80 and _COMMAND.search(blob) and _INDEXISH.search(blob):
        score += 2
        why.append("短句大盤命令")
    return score, why


def stance_flip(text: str, prev_text: str = "") -> Tuple[int, List[str]]:
    if not prev_text or not text:
        return 0, []
    try:
        from biaoke_fuse import stance_of
    except Exception:
        return 0, []
    a, b = stance_of(prev_text), stance_of(text)
    if a and b and a != b and "並陳" not in (a + b):
        return 3, [f"跟上則比翻面（{a}→{b}）"]
    return 0, []


def _llm_yes(text: str, move: Dict[str, Any]) -> Optional[bool]:
    """灰區才問。pytest／沒金鑰不打。只准 yes/no。"""
    if os.environ.get("PYTEST_CURRENT_TEST"):
        return None
    try:
        from biaoke_live import live_enabled, live_endpoint, live_key, live_models
    except Exception:
        return None
    if not live_enabled():
        return None
    key = live_key()
    if not key:
        return None
    drop = move.get("drop") or 0
    pct = move.get("pct") or 0
    prompt = (
        "只判斷這則飆客新文要不要立刻推到兩個手機（使用者可能沒按飆大會錯過）。"
        "緊急＝大盤急轉、出清、抄底、位階改口、現在就做；"
        "或他用主音（波浪）再疊台積電量價／費半先行／夜盤過壓，確認低點或大 B 波啟動。"
        "單講趨勢向上、初步止訊號、右肩有守、日常觀盤、族群輪動不要。"
        "用詞不一定是抄底／七百點／台積電。只回 yes 或 no。\n"
        f"加權相對昨收跌{drop}點（{pct}%）\n正文：{_clip(text, 420)}"
    )
    import requests

    url = live_endpoint()
    for model in live_models()[:1]:
        try:
            res = requests.post(
                url,
                headers={
                    "Authorization": f"Bearer {key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": model,
                    "messages": [
                        {"role": "system", "content": "只回 yes 或 no。"},
                        {"role": "user", "content": prompt},
                    ],
                    "temperature": 0.0,
                    "max_tokens": 8,
                },
                timeout=8.0,
            )
            body = (res.json() or {}).get("choices") or []
            msg = ((body[0] or {}).get("message") or {}).get("content") or ""
            ans = str(msg).strip().lower()
            if ans.startswith("yes"):
                return True
            if ans.startswith("no"):
                return False
        except Exception:
            logger.debug("緊急研判對話線略過", exc_info=True)
            return None
    return None


def judge_emergency(
    text: str,
    *,
    move: Optional[Dict[str, Any]] = None,
    prev_text: str = "",
    kind: str = "post",
) -> Dict[str, Any]:
    """自己研判。回 push / score / reasons。"""
    blob = str(text or "").strip()
    if not blob:
        return {"push": False, "score": 0, "reasons": []}
    mkt = move if move is not None else twii_move()
    s1, w1 = market_shock(mkt, blob)
    s2, w2 = content_intents(blob)
    s3, w3 = stance_flip(blob, prev_text)
    stack = confirm_stack(blob)
    s4 = int(stack.get("score") or 0)
    w4 = list(stack.get("reasons") or [])
    hard_move = bool(
        _EXIT.search(blob) or _ENTER.search(blob) or _RETRACT.search(blob) or _COMMAND.search(blob)
    )
    # 還沒確認末端：這路不加分。沒有出清／抄底／改口就不要靠觀盤句推。
    if stack.get("veto") and not stack.get("confirmed"):
        s4 = 0
        if not hard_move and s1 < 4:
            reasons = w1 + w2 + w3 + w4
            return {
                "push": False,
                "score": s1 + s2 + s3,
                "reasons": reasons or ["還不到確認末端，主音不夠"],
            }
        w4 = [x for x in w4 if "疊成確認" not in x]
    score = s1 + s2 + s3 + s4
    reasons = w1 + w2 + w3 + w4
    # 急跌但只是日常觀盤 → 不吵
    if s1 >= 4 and s2 == 0 and s3 == 0 and s4 == 0:
        return {"push": False, "score": score, "reasons": reasons + ["急跌但這則沒有特別判斷"]}
    push = score >= PUSH_SCORE or bool(stack.get("confirmed"))
    if not push and score >= GRAY_SCORE and (s1 >= 2 or s2 >= 3 or s4 >= 3):
        llm = _llm_yes(blob, mkt if isinstance(mkt, dict) else {})
        if llm is True:
            push = True
            reasons.append("對話線判定這則不能錯過")
        elif llm is False:
            reasons.append("對話線判定還不到推播")
    return {"push": bool(push), "score": int(score), "reasons": reasons}


def _ensure(db_path: str) -> None:
    if not db_path:
        return
    conn = sqlite3.connect(db_path, timeout=30.0)
    try:
        conn.executescript(_DDL)
        conn.commit()
    finally:
        conn.close()


def _already(db_path: str, post_id: str) -> bool:
    if not db_path or not post_id:
        return False
    _ensure(db_path)
    conn = sqlite3.connect(db_path, timeout=30.0)
    try:
        row = conn.execute(
            "SELECT 1 FROM biaoke_alerts WHERE post_id=?", (post_id,)
        ).fetchone()
        return bool(row)
    except sqlite3.Error:
        return False
    finally:
        conn.close()


def _mark(db_path: str, post_id: str, score: int, reasons: Sequence[str]) -> None:
    if not db_path or not post_id:
        return
    _ensure(db_path)
    conn = sqlite3.connect(db_path, timeout=30.0)
    try:
        conn.execute(
            "INSERT OR REPLACE INTO biaoke_alerts(post_id, score, reasons, sent_at) "
            "VALUES(?,?,?,datetime('now'))",
            (post_id, int(score), "／".join(reasons)[:400]),
        )
        conn.commit()
    except sqlite3.Error:
        logger.debug("緊急推播已送記號寫不進", exc_info=True)
    finally:
        conn.close()


def format_alert(event: Dict[str, Any], judged: Dict[str, Any], move: Dict[str, Any]) -> str:
    kind = "樓下" if (event.get("kind") or "") == "reply" else "主文"
    drop = float(move.get("drop") or 0)
    pct = float(move.get("pct") or 0)
    px = move.get("px") or ""
    bits = ["<b>飆大盤中重點（沒過按鈕）</b>"]
    if move.get("ok"):
        bits.append(
            f"加權相對昨收 {html_escape(str(int(round(drop))))} 點"
            f"（{html_escape(str(pct))}%／現 {html_escape(str(px))}）"
        )
    if judged.get("reasons"):
        bits.append("研判：" + html_escape("、".join(judged["reasons"][:4])))
    bits.append(
        f"{html_escape(str(event.get('date') or ''))} "
        f"{html_escape(str(event.get('time') or ''))} {kind}："
    )
    bits.append(html_escape(_clip(str(event.get("text") or ""), 420)))
    bits.append("怕錯過才直接推。不是買訊。")
    return "\n".join(bits)


def _send_family(html: str) -> int:
    if os.environ.get("PYTEST_CURRENT_TEST"):
        return 0
    try:
        from config import allowed_telegram_uids, get_telegram_token
    except Exception:
        return 0
    token = get_telegram_token()
    uids = [str(u).strip() for u in allowed_telegram_uids() if str(u).strip()]
    if not token or not uids:
        logger.warning("飆大緊急推播沒有 token 或白名單，略過")
        return 0
    import requests

    n = 0
    for cid in uids:
        try:
            resp = requests.post(
                f"https://api.telegram.org/bot{token}/sendMessage",
                json={
                    "chat_id": cid,
                    "text": html,
                    "parse_mode": "HTML",
                    "disable_web_page_preview": True,
                },
                timeout=15,
            )
            if int(getattr(resp, "status_code", 0) or 0) == 200:
                n += 1
            else:
                logger.error("緊急推播 Telegram %s", getattr(resp, "status_code", "?"))
        except Exception:
            logger.exception("緊急推播失敗 uid 略")
    return n


def maybe_push_drop_alert(
    db_path: str,
    events: Sequence[Dict[str, Any]],
    *,
    move: Optional[Dict[str, Any]] = None,
    prev_text: str = "",
) -> Dict[str, Any]:
    """ingest 抓到新文後呼叫。該推才推兩人對話框。"""
    stats = {"checked": 0, "pushed": 0, "skipped": 0}
    rows = [dict(e) for e in (events or []) if e.get("text")]
    if not rows:
        return stats
    mkt = move if move is not None else twii_move()
    for ev in rows:
        if ev.get("club"):
            continue
        pid = str(ev.get("id") or ev.get("post_id") or "").strip()
        if not pid:
            continue
        stats["checked"] += 1
        if db_path and _already(db_path, pid):
            stats["skipped"] += 1
            continue
        judged = judge_emergency(
            str(ev.get("text") or ""),
            move=mkt,
            prev_text=prev_text,
            kind=str(ev.get("kind") or "post"),
        )
        if not judged.get("push"):
            continue
        html = format_alert(ev, judged, mkt if isinstance(mkt, dict) else {})
        sent = _send_family(html)
        if sent or os.environ.get("PYTEST_CURRENT_TEST"):
            if db_path:
                _mark(db_path, pid, int(judged.get("score") or 0), judged.get("reasons") or [])
            stats["pushed"] += 1
            logger.info(
                "飆大緊急推播 post=%s score=%s reasons=%s sent=%s",
                pid,
                judged.get("score"),
                judged.get("reasons"),
                sent,
            )
    return stats
