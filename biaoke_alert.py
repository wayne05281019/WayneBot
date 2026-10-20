# -*- coding: utf-8 -*-
"""飆大急推 vs 一般抓文（2026-10-01 鎖死；2026-10-10 補時效）。

一般新文／自回：只進未讀匣＋飆大鈕彙整／融合，不准另推 Telegram。
急推才推偉權＋哥哥兩支手機：
  1) 現在就要出清 → 完整原文
  2) 現在差不多到底／抄底窗口 → 完整原文
  3) 官方收盤柱碰到他已點過的位 → 國中生口語一句（碰到關了、收大概在哪邊、還要再看）；
     同根柱一次碰到多個已點位 → 仍併成一則；不准關卡串／收點串／機器規則句上話筒
只對「新抓到且未逾時效」的文急推；重掃／換 id／deploy 後不准把多天前舊文當急推重播。
如果／萬一／怕＋賣出、舊回憶賣光、發文通知、命令句、加權跌幾點＝一般，不急推。
確認低點仍要主音疊輔助；單講趨勢向上、初步止訊號、右肩有守＝還不到確認。
不是買訊。同一則／同一位不重覆推。社團不推。盤中未收不當收。
"""
from __future__ import annotations

import hashlib
import logging
import os
import re
import sqlite3
import unicodedata
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Sequence, Tuple
from zoneinfo import ZoneInfo

from tg_layout import html_escape

logger = logging.getLogger("WayneBot.BiaokeAlert")

DROP_POINTS = 700.0
# Telegram HTML 上限 4096；預留標題行，急推正文要完整。
_TG_BODY_MAX = 3800
# 急推時效：原文時戳（台北）超過這小時數＝舊文，不准當急推（重掃／換 id 也不行）。
URGENT_MAX_AGE_HOURS = 24
_TAIPEI = ZoneInfo("Asia/Taipei")

_DDL = """
CREATE TABLE IF NOT EXISTS biaoke_alerts (
    post_id TEXT PRIMARY KEY,
    score INTEGER NOT NULL DEFAULT 0,
    reasons TEXT NOT NULL DEFAULT '',
    sent_at TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS biaoke_level_alerts (
    alert_key TEXT PRIMARY KEY,
    post_id TEXT NOT NULL DEFAULT '',
    level REAL,
    bar_date TEXT NOT NULL DEFAULT '',
    reasons TEXT NOT NULL DEFAULT '',
    sent_at TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS biaoke_chat_dedupe (
    chat_id TEXT NOT NULL,
    dedupe_key TEXT NOT NULL,
    sent_at TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (chat_id, dedupe_key)
);
"""

# 族＝意圖，不是單一名詞。新詞只要落在同一族就會加分。
_EXIT = re.compile(
    r"(出清|一股不留|全部賣(?!光)|全部出|先回收|不要再碰|不要再布局|"
    r"不要再介入|不要再買|停損|減碼一半|減碼\s*1\s*/\s*2|"
    r"調節總持股|今天不要有動作|不能介入布局|"
    r"逃命(?!波))"
)
_HYPOTHETICAL_ACT = re.compile(
    r"(如果|萬一|假如|要是|若是).{0,80}"
    r"(賣出|先賣|抽出|出清|逃命|先回收|減碼|一股不留)"
)
_HISTORICAL_SELL = re.compile(
    r"(幾乎全部賣光|全部賣光|賣光只留|"
    r"那個時候.{0,40}(賣|出)|過年前.{0,40}(賣|出)|當時.{0,16}(賣|出清))"
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
    r"(一定要|全面|今天不要|不能介入|等盤後判斷|先不要|"
    r"一股不留|趕快跑|立刻(?!站))"
)
_INDEXISH = re.compile(r"(大盤|加權|台指|夜盤|細微波|波浪位階|下降軌)")
_NIGHT_CRASH = re.compile(r"夜盤.{0,10}(大跌|崩|重挫|跳空)")
_ROUTINE = re.compile(
    r"(散熱族群最為強勢|輪漲格局|謝謝|感謝飆大|Yes$|耐心等待)"
)
_SOFT_WATCH = re.compile(
    r"(微乎其微|幾乎不可能|反而覺得比較好|點到為止|當天無法判斷)"
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


def _normalize_for_fp(text: str) -> str:
    """急推／關卡去重用：全半形、空白、常見標點差異不當成新文。"""
    s = unicodedata.normalize("NFKC", str(text or ""))
    s = re.sub(r"<[^>]+>", "", s)
    s = re.sub(r"\s+", "", s)
    s = s.replace("，", ",").replace("。", ".").replace("、", ",")
    s = s.replace("：", ":").replace("；", ";")
    return s.strip()


def _body_fingerprint(text: str) -> str:
    """同一原文指紋。HTML :rN 與 API :c{id} 不同列也要擋住。"""
    s = _normalize_for_fp(text)
    if not s:
        return ""
    return hashlib.sha1(s.encode("utf-8")).hexdigest()


def _event_posted_at(event: Dict[str, Any]) -> Optional[datetime]:
    """原文台北時戳。沒日期＝不當新文（不准急推）。"""
    day = str(event.get("date") or "").strip()
    hm = str(event.get("time") or "00:00").strip() or "00:00"
    if not day:
        return None
    try:
        return datetime.strptime(f"{day} {hm[:5]}", "%Y-%m-%d %H:%M").replace(
            tzinfo=_TAIPEI
        )
    except ValueError:
        return None


def event_too_old_for_urgent(
    event: Dict[str, Any],
    *,
    now: Optional[datetime] = None,
    max_age_hours: float = URGENT_MAX_AGE_HOURS,
) -> bool:
    """True＝超過急推時效（或沒時戳）→ 不准當急推重播。"""
    posted = _event_posted_at(event)
    if posted is None:
        return True
    dt = now or datetime.now(_TAIPEI)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=_TAIPEI)
    else:
        dt = dt.astimezone(_TAIPEI)
    age = dt - posted
    if age < timedelta(0):
        # 時鐘誤差／未來戳：仍當可推（抓到當下）
        return False
    return age > timedelta(hours=max(1.0, float(max_age_hours)))


def _alert_keys(post_id: str, text: str) -> List[str]:
    keys: List[str] = []
    pid = str(post_id or "").strip()
    if pid:
        keys.append(pid)
    fp = _body_fingerprint(text)
    if fp:
        keys.append(f"fp:{fp}")
    out: List[str] = []
    seen = set()
    for k in keys:
        if k not in seen:
            seen.add(k)
            out.append(k)
    return out


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


def _clear_now(blob: str) -> bool:
    """現在就要出清。如果／萬一／舊回憶賣光不算。"""
    if not _EXIT.search(blob):
        return False
    if _HYPOTHETICAL_ACT.search(blob) or _HISTORICAL_SELL.search(blob):
        return False
    return True


def _bottom_now(blob: str) -> bool:
    """現在差不多到底／抄底窗口。如果＋賣出那類不算。"""
    if _HYPOTHETICAL_ACT.search(blob):
        return False
    return bool(_ENTER.search(blob) or _MAIN_A_LOW.search(blob))


def judge_emergency(
    text: str,
    *,
    move: Optional[Dict[str, Any]] = None,
    prev_text: str = "",
    kind: str = "post",
) -> Dict[str, Any]:
    """自己研判新文／自回。回 push / score / reasons。

    急推只認出清／到底（含確認末端）。一般新文 push=False → 只進未讀匣。
    「官方碰到已點位」另走 maybe_push_marked_level_hits，不在這條。
    """
    blob = str(text or "").strip()
    if not blob:
        return {"push": False, "score": 0, "reasons": []}
    if _SOFT_WATCH.search(blob) and not (_EXIT.search(blob) or _ENTER.search(blob)):
        return {
            "push": False,
            "score": 0,
            "reasons": ["觀盤／更差情境他認為機率很低，不推"],
        }
    mkt = move if move is not None else twii_move()
    s1, w1 = market_shock(mkt, blob)
    s2, w2 = content_intents(blob)
    s3, w3 = stance_flip(blob, prev_text)
    stack = confirm_stack(blob)
    s4 = int(stack.get("score") or 0)
    w4 = list(stack.get("reasons") or [])
    if stack.get("veto") and not stack.get("confirmed"):
        s4 = 0
        w4 = [x for x in w4 if "疊成確認" not in x]
    score = s1 + s2 + s3 + s4
    reasons = w1 + w2 + w3 + w4
    if _HYPOTHETICAL_ACT.search(blob):
        reasons.append("如果／萬一情境，先進未讀匣")
    if _HISTORICAL_SELL.search(blob):
        reasons.append("舊回憶賣光，不算出清")
    clear_now = _clear_now(blob)
    bottom_now = _bottom_now(blob)
    confirmed = bool(stack.get("confirmed"))
    push = bool(confirmed or clear_now or bottom_now)
    if stack.get("veto") and not (confirmed or clear_now or bottom_now):
        push = False
        if not reasons:
            reasons = ["還不到確認末端，主音不夠"]
    if s1 >= 4 and s2 == 0 and s3 == 0 and s4 == 0:
        push = False
        reasons = reasons + ["急跌但這則沒有特別判斷"]
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


def _already(db_path: str, post_id: str, text: str = "") -> bool:
    """同 post_id 或同正文指紋已 claim／已送 → 不准再推。"""
    if not db_path:
        return False
    keys = _alert_keys(post_id, text)
    if not keys:
        return False
    _ensure(db_path)
    conn = sqlite3.connect(db_path, timeout=30.0)
    try:
        for key in keys:
            row = conn.execute(
                "SELECT 1 FROM biaoke_alerts WHERE post_id=?", (key,)
            ).fetchone()
            if row:
                return True
        return False
    except sqlite3.Error:
        return False
    finally:
        conn.close()


def _mark(db_path: str, post_id: str, score: int, reasons: Sequence[str], text: str = "") -> None:
    """寫入 post_id＋正文指紋（相容舊呼叫）。優先改走 _claim_push。"""
    if not db_path:
        return
    keys = _alert_keys(post_id, text)
    if not keys:
        return
    _ensure(db_path)
    conn = sqlite3.connect(db_path, timeout=30.0)
    try:
        for key in keys:
            conn.execute(
                "INSERT OR REPLACE INTO biaoke_alerts(post_id, score, reasons, sent_at) "
                "VALUES(?,?,?,datetime('now'))",
                (key, int(score), "／".join(reasons)[:400]),
            )
        conn.commit()
    except sqlite3.Error:
        logger.debug("緊急推播已送記號寫不進", exc_info=True)
    finally:
        conn.close()


def _claim_push(
    db_path: str,
    post_id: str,
    text: str,
    score: int,
    reasons: Sequence[str],
) -> bool:
    """先占位再送。True＝本輪可送；False＝同 id／同指紋已占 → 不准重送。

    BEGIN IMMEDIATE 擋住多 worker 競速。送失敗也不撤銷（重試不重送）。
    """
    if not db_path:
        return True
    keys = _alert_keys(post_id, text)
    if not keys:
        return False
    _ensure(db_path)
    conn = sqlite3.connect(db_path, timeout=30.0)
    try:
        conn.execute("BEGIN IMMEDIATE")
        for key in keys:
            hit = conn.execute(
                "SELECT 1 FROM biaoke_alerts WHERE post_id=?", (key,)
            ).fetchone()
            if hit:
                conn.rollback()
                return False
        why = "／".join(reasons)[:400]
        for key in keys:
            conn.execute(
                "INSERT INTO biaoke_alerts(post_id, score, reasons, sent_at) "
                "VALUES(?,?,?,datetime('now'))",
                (key, int(score), why),
            )
        conn.commit()
        return True
    except sqlite3.Error:
        try:
            conn.rollback()
        except sqlite3.Error:
            pass
        logger.debug("緊急推播 claim 失敗", exc_info=True)
        # 占位失敗＝寧可略過，不准洗版
        return False
    finally:
        conn.close()


def _claim_chat_dedupe(chat_id: str, dedupe_key: str, *, db_path: str = "") -> bool:
    """同一 chat＋同一 dedupe_key 只准送一次。True＝可送。

    沒庫時退回 True（靠上層 post／level claim）；有庫占位失敗則不准送。
    """
    cid = str(chat_id or "").strip()
    key = str(dedupe_key or "").strip()
    if not cid or not key:
        return False
    path = str(db_path or "").strip()
    if not path:
        try:
            path = _push_db()
        except Exception:
            path = ""
    if not path:
        return True
    _ensure(path)
    conn = sqlite3.connect(path, timeout=30.0)
    try:
        conn.execute("BEGIN IMMEDIATE")
        hit = conn.execute(
            "SELECT 1 FROM biaoke_chat_dedupe WHERE chat_id=? AND dedupe_key=?",
            (cid, key),
        ).fetchone()
        if hit:
            conn.rollback()
            return False
        conn.execute(
            "INSERT INTO biaoke_chat_dedupe(chat_id, dedupe_key, sent_at) "
            "VALUES(?,?,datetime('now'))",
            (cid, key),
        )
        conn.commit()
        return True
    except sqlite3.Error:
        try:
            conn.rollback()
        except sqlite3.Error:
            pass
        logger.debug("chat dedupe claim 失敗", exc_info=True)
        return False
    finally:
        conn.close()


def format_alert(event: Dict[str, Any], judged: Dict[str, Any], move: Dict[str, Any]) -> str:
    """急推：完整他原文到兩支手機。加權現價、程式標籤不進對話框。"""
    kind = "樓下" if (event.get("kind") or "") == "reply" else "主文"
    body = str(event.get("text") or "").strip()
    if len(body) > _TG_BODY_MAX:
        body = body[: _TG_BODY_MAX - 1] + "…"
    bits = [
        "<b>飆大急推</b>",
        (
            f"他原文 {html_escape(str(event.get('date') or ''))} "
            f"{html_escape(str(event.get('time') or ''))} {kind}："
        ),
        html_escape(body),
        "對原文用。",
    ]
    return "\n".join(bits)


def _level_face(level: float) -> str:
    try:
        lv = float(level)
    except (TypeError, ValueError):
        return str(level or "")
    if abs(lv - round(lv)) < 1e-6:
        return f"{lv:.0f}"
    return f"{lv:g}"


def _essence_around_level(text: str, level: float) -> str:
    """含該點位的一句立場；去蕪存菁，不准整篇貼文。"""
    blob = re.sub(r"\s+", " ", str(text or "")).strip()
    if not blob:
        return ""
    face = _level_face(level)
    # 先切句，找含點位且帶判斷詞的
    parts = [p.strip() for p in re.split(r"(?<=[。！？；\n])", blob) if p and p.strip()]
    if not parts:
        parts = [blob]
    ranked: List[Tuple[int, str]] = []
    for p in parts:
        if face not in p and (not face.isdigit() or face not in p.replace(",", "")):
            # 容許 46,747 寫法
            if face not in p.replace(",", ""):
                continue
        score = 0
        for w in (
            "穿刺",
            "突破",
            "回測",
            "支撐",
            "壓力",
            "否則",
            "出清",
            "守",
            "破",
            "過",
            "整理",
            "反彈",
            "下殺",
            "抄底",
        ):
            if w in p:
                score += 2
        score += 1
        ranked.append((score, p))
    if not ranked:
        # 退回 extract 的短 ctx
        return blob[:72] + ("…" if len(blob) > 72 else "")
    ranked.sort(key=lambda x: -x[0])
    best = ranked[0][1]
    if len(best) > 96:
        # 以點位為中心裁
        idx = best.find(face)
        if idx < 0:
            idx = 0
        a = max(0, idx - 36)
        b = min(len(best), idx + len(face) + 48)
        best = ("…" if a else "") + best[a:b] + ("…" if b < len(best) else "")
    return best.strip(" ，、；")


def format_level_hit_alert(
    *,
    post_id: str,
    date: str,
    time_s: str,
    kind: str,
    text: str,
    level: float,
    bar_date: str,
    note: str,
) -> str:
    """單則相容入口 → 去蕪存菁判斷（不再整篇貼文）。"""
    return format_level_hit_synthesis(
        level=level,
        bar_date=bar_date,
        bar_high=None,
        bar_low=None,
        bar_close=None,
        note=note,
        sources=[
            {
                "date": date,
                "time": time_s,
                "kind": kind,
                "text": text,
                "post_id": post_id,
                "role": note,
            }
        ],
    )


def _close_vs_level(bar_close: Optional[float], level: float) -> str:
    """收相對該位（內部／測試用）；話筒改走口語一句，不再逐位「之上／之下」。"""
    try:
        if bar_close is None:
            return ""
        c = float(bar_close)
        lv_f = float(level)
        if c > lv_f:
            return f"收 {_level_face(c)} 在這位之上"
        if c < lv_f:
            return f"收 {_level_face(c)} 在這位之下"
        return f"收在 {_level_face(c)}"
    except (TypeError, ValueError):
        return ""


def _close_side_groups(
    bar_close: Optional[float], levels: Sequence[float]
) -> Tuple[List[str], List[str], List[str]]:
    """依收盤把已點位分成站上／還沒過／剛好收在（臉數字，由低到高）。"""
    above: List[str] = []
    below: List[str] = []
    at: List[str] = []
    if bar_close is None:
        return above, below, at
    try:
        c = float(bar_close)
    except (TypeError, ValueError):
        return above, below, at
    for lv in sorted(float(x) for x in levels):
        face = _level_face(lv)
        if c > lv:
            above.append(face)
        elif c < lv:
            below.append(face)
        else:
            at.append(face)
    return above, below, at


def _key_level_mentioned(text: str, levels: Sequence[float]) -> str:
    """近窗說法裡已出現的關鍵已點位（若有）；沒有就空。不准發明新價。"""
    s = str(text or "")
    if not s:
        return ""
    # 由高到低：較常是「還卡／僵在」的那關
    for lv in sorted((float(x) for x in levels), reverse=True):
        face = _level_face(lv)
        if face and face in s:
            return face
    return ""


def _close_band_plain(
    bar_close: Optional[float], levels: Sequence[float]
) -> str:
    """國中生口語：收在偏高／偏低／中間…；不准塞收點數字或關卡串。"""
    above, below, at = _close_side_groups(bar_close, levels)
    n = len(above) + len(below) + len(at)
    if n == 0:
        return ""
    if n == 1:
        if above:
            return "現在已經站上這關"
        if below:
            return "現在還沒過這關"
        return "現在剛好收在這關附近"
    if above and not below and not at:
        return "現在收在偏高、這些關大致站上了"
    if below and not above and not at:
        return "現在收在偏低、這些關都還沒過"
    if at and not above and not below:
        return "現在剛好收在關卡附近"
    # 兩邊都有：用相對位置講中間偏低／偏高，不准列關卡數字
    try:
        c = float(bar_close)  # type: ignore[arg-type]
        lo = min(float(x) for x in levels)
        hi = max(float(x) for x in levels)
    except (TypeError, ValueError):
        return "現在收在中間、還沒過他較高的關"
    if hi <= lo:
        return "現在收在關卡附近、還沒過他較高的關"
    pos = (c - lo) / (hi - lo)
    if pos < 0.4:
        band = "中間偏低"
    elif pos > 0.6:
        band = "中間偏高"
    else:
        band = "中間"
    return f"現在收在{band}、還沒過他較高的關"


def _plain_wait_clause(
    read_now: str,
    levels: Sequence[float],
    bar_close: Optional[float],
) -> str:
    """還要再看／還卡在哪：最多一個關鍵位（且收仍在其下），其餘白話。"""
    key = _key_level_mentioned(read_now, levels)
    if key and bar_close is not None:
        try:
            c = float(bar_close)
            for lv in levels:
                if _level_face(float(lv)) == key and c < float(lv):
                    return f"還卡在 {key} 附近，還要再看大盤怎麼走"
        except (TypeError, ValueError):
            pass
    return "還要再看大盤怎麼走"


def _sources_essence(level: float, sources: Sequence[Dict[str, Any]]) -> str:
    """同一點位多則來源：最近文優先抽出立場。"""
    rows = [dict(s) for s in (sources or []) if s]
    rows.sort(
        key=lambda r: (
            str(r.get("date") or ""),
            str(r.get("time") or ""),
        ),
        reverse=True,
    )
    for r in rows:
        essence = _essence_around_level(str(r.get("text") or ""), level)
        if essence:
            return essence
        ctx = str(r.get("ctx") or "").strip()
        if ctx:
            return ctx
    return ""


def _pick_level_thesis(rows: Sequence[Dict[str, Any]]) -> str:
    """多關時取最近來源的既有中心思想；話筒優先近窗原句，不准發明新價。"""
    thesis_candidates: List[Tuple[str, str, str]] = []
    for r in rows:
        try:
            lv = float(r["level"])
        except (KeyError, TypeError, ValueError):
            continue
        srcs = [dict(s) for s in (r.get("sources") or []) if s]
        srcs.sort(
            key=lambda s: (str(s.get("date") or ""), str(s.get("time") or "")),
            reverse=True,
        )
        if not srcs:
            continue
        top = srcs[0]
        essence = _sources_essence(lv, srcs)
        oral = _oral_level_thesis(essence, _level_face(lv)) if essence else ""
        # 近窗原句較像人話；模板句當備援
        body = (essence or oral or "").strip()
        if not body:
            continue
        thesis_candidates.append(
            (
                str(top.get("date") or ""),
                str(top.get("time") or ""),
                body,
            )
        )
    thesis_candidates.sort(key=lambda t: (t[0], t[1]), reverse=True)
    if thesis_candidates:
        return thesis_candidates[0][2]
    return ""


LEVEL_HIT_TITLE = "飆大提醒·大盤碰到關卡"


def _plain_level_hit_body(
    *,
    faces: Sequence[str],
    bar_date: str,
    bar_high: Optional[float],
    bar_low: Optional[float],
    bar_close: Optional[float],
    levels_for_side: Sequence[float],
    read_now: str,
) -> str:
    """話筒正文：國中生也看得懂的一句＋下一行「不是買訊」。

    不准收點數字串、不准完整關卡清單、不准機器規則句。
    詳細關卡／收點只打 log；主句最多一個「還卡在Ｘ附近」。
    """
    del faces, bar_date, bar_high, bar_low  # 細節留 log，不上主句
    band = _close_band_plain(bar_close, levels_for_side)
    wait = _plain_wait_clause(read_now, levels_for_side, bar_close)
    main = "今天加權碰到飆大以前講過的關了"
    if band:
        main += "；" + band + "，" + wait
    else:
        main += "，" + wait
    if not main.endswith("。"):
        main += "。"
    return "\n".join(
        [
            f"<b>{LEVEL_HIT_TITLE}</b>",
            html_escape(main),
            "不是買訊",
        ]
    )


def format_level_hit_synthesis(
    *,
    level: float,
    bar_date: str,
    bar_high: Optional[float],
    bar_low: Optional[float],
    bar_close: Optional[float],
    note: str = "",
    sources: Sequence[Dict[str, Any]],
) -> str:
    """官方柱碰到已點位：真正一句人話給話筒；詳細關卡不上主句。"""
    del note  # 加權／台指備註只給內部，不上話筒
    lv = _level_face(level)
    rows = [dict(s) for s in (sources or []) if s]
    essence = _sources_essence(level, rows)
    oral = _oral_level_thesis(essence, lv) if essence else ""
    # 話筒優先近窗原句（較像人話）；沒有再走模板
    read_now = essence or oral or ""
    logger.info(
        "level_hit_plain level=%s bar=%s close=%s hi=%s lo=%s",
        lv,
        bar_date,
        bar_close,
        bar_high,
        bar_low,
    )
    return _plain_level_hit_body(
        faces=[lv],
        bar_date=bar_date,
        bar_high=bar_high,
        bar_low=bar_low,
        bar_close=bar_close,
        levels_for_side=[float(level)],
        read_now=read_now,
    )


def format_multi_level_hit_synthesis(
    *,
    levels: Sequence[Dict[str, Any]],
    bar_date: str,
    bar_high: Optional[float],
    bar_low: Optional[float],
    bar_close: Optional[float],
) -> str:
    """同根官方柱碰到多個已點位 → 真正一句人話；不准列完整關卡進話筒。

    levels 每項：{"level": float, "sources": [...], "note": str?}
    單一位仍走 format_level_hit_synthesis。詳細關卡打 log。
    """
    rows = [dict(x) for x in (levels or []) if x and x.get("level") is not None]
    if not rows:
        return ""
    if len(rows) == 1:
        one = rows[0]
        return format_level_hit_synthesis(
            level=float(one["level"]),
            bar_date=bar_date,
            bar_high=bar_high,
            bar_low=bar_low,
            bar_close=bar_close,
            note=str(one.get("note") or ""),
            sources=one.get("sources") or [],
        )
    rows.sort(key=lambda r: float(r["level"]))
    faces = [_level_face(float(r["level"])) for r in rows]
    lv_nums = [float(r["level"]) for r in rows]
    read_now = _pick_level_thesis(rows)
    # 多關：話筒不要塞完整清單；完整關卡只留 log
    logger.info(
        "multi_level_hit_plain bar=%s close=%s hi=%s lo=%s levels=%s",
        bar_date,
        bar_close,
        bar_high,
        bar_low,
        "／".join(faces),
    )
    return _plain_level_hit_body(
        faces=faces,
        bar_date=bar_date,
        bar_high=bar_high,
        bar_low=bar_low,
        bar_close=bar_close,
        levels_for_side=lv_nums,
        read_now=read_now,
    )


def _oral_level_thesis(essence: str, level_face: str) -> str:
    """把含點位的句子收成口語中心思想，不是複誦日期目錄。"""
    s = str(essence or "").strip()
    if not s:
        return ""
    lv = str(level_face or "")
    if any(k in s for k in ("穿刺", "突破", "有效過", "過前")) and any(
        k in s for k in ("否則", "再測", "要不然")
    ):
        return f"他要 {lv} 這位有效過才算脫離震盪；過不了還得再測更低——柱碰到只是提醒對原文，不是自動突破。"
    if "最後整理" in s or "整理完" in s or "整理完成" in s:
        return f"他近窗把 {lv} 當最後整理關；過了才談主升，不是一碰到就改劇本。"
    if "回測" in s:
        return f"他點 {lv} 是回測／關前觀察位；柱碰到＝對質提醒，不是叫你追。"
    if "支撐" in s or "守" in s:
        return f"他點 {lv} 當守住才像多頭結構未壞；碰到要看收有沒有守住。"
    if "壓力" in s or "關" in s:
        return f"他點 {lv} 當關卡／壓力；碰到是觀察能不能過，不是已過。"
    # 去蕪：去掉多餘標點，壓成一句口語
    t = re.sub(r"^[…\s]+", "", s)
    if len(t) > 80:
        t = t[:79] + "…"
    return t


def _send_family(html: str, *, dedupe_key: str = "", db_path: str = "") -> int:
    """推白名單兩人；同一 dedupe_key 每 chat 只送一次（先占位再送）。"""
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
    key = str(dedupe_key or "").strip() or f"html:{_body_fingerprint(html)}"
    import requests

    n = 0
    for cid in uids:
        if not _claim_chat_dedupe(cid, key, db_path=db_path):
            logger.info("飆大推播 chat dedupe 略過 chat=%s key=%s", cid, key[:96])
            continue
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
                try:
                    mid = int(((resp.json() or {}).get("result") or {}).get("message_id") or 0)
                except Exception:
                    mid = 0
                if mid:
                    _record_push_msg(cid, mid, html)
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
    now: Optional[datetime] = None,
    max_age_hours: float = URGENT_MAX_AGE_HOURS,
) -> Dict[str, Any]:
    """ingest 抓到新文後：只有出清／到底急推；一般新文／自回不推。

    同一 post_id／同一正文指紋只推一次；先 claim 再送，TimedOut 重試不重送。
    HTML :rN 與 API :c{id} 不同列但同正文 → 併擋。
    超過時效的舊文（重掃／換 id／deploy 回補）不准當急推；claim 指紋後略過。
    純 updated（正文微改／欄位補齊）不准當急推；只認第一次 added。
    """
    stats = {
        "checked": 0,
        "pushed": 0,
        "skipped": 0,
        "routine": 0,
        "stale": 0,
        "updated_skip": 0,
    }
    rows = [dict(e) for e in (events or []) if e.get("text")]
    if not rows:
        return stats
    mkt = move if move is not None else twii_move()
    seen_fp: set[str] = set()
    for ev in rows:
        if ev.get("club") or ev.get("kind") == "bystander":
            continue
        pid = str(ev.get("id") or ev.get("post_id") or "").strip()
        if not pid:
            continue
        body = str(ev.get("text") or "")
        stats["checked"] += 1
        fp = _body_fingerprint(body)
        if fp and fp in seen_fp:
            stats["skipped"] += 1
            continue
        if db_path and _already(db_path, pid, body):
            stats["skipped"] += 1
            if fp:
                seen_fp.add(fp)
            continue
        # 純 updated＝欄位／附圖補齊，不是新文；不准當急推
        hit = str(ev.get("_ingest") or "").strip().lower()
        if hit == "updated":
            stats["updated_skip"] += 1
            if fp:
                seen_fp.add(fp)
            continue
        # 超過時效＝舊文重掃；claim 指紋以免換 id 再撞
        if event_too_old_for_urgent(
            ev, now=now, max_age_hours=max_age_hours
        ):
            stats["stale"] += 1
            if db_path:
                _claim_push(
                    db_path,
                    pid,
                    body,
                    0,
                    ["超過急推時效，不重播舊文"],
                )
            if fp:
                seen_fp.add(fp)
            continue
        judged = judge_emergency(
            body,
            move=mkt,
            prev_text=prev_text,
            kind=str(ev.get("kind") or "post"),
        )
        if not judged.get("push"):
            stats["routine"] += 1
            continue
        score = int(judged.get("score") or 0)
        reasons = judged.get("reasons") or []
        # 先占位再送：送失敗／TimedOut 也不撤，重試不重送
        if db_path and not _claim_push(db_path, pid, body, score, reasons):
            stats["skipped"] += 1
            if fp:
                seen_fp.add(fp)
            continue
        if fp:
            seen_fp.add(fp)
        html = format_alert(ev, judged, mkt if isinstance(mkt, dict) else {})
        # 同原文指紋再擋一層（deploy／重掃當 added 也不准同一 chat 重送）
        dedupe = f"urgent:fp:{fp}" if fp else f"urgent:id:{pid}"
        sent = _send_family(html, dedupe_key=dedupe, db_path=db_path)
        stats["pushed"] += 1
        logger.info(
            "飆大緊急推播 post=%s score=%s reasons=%s sent=%s",
            pid,
            judged.get("score"),
            judged.get("reasons"),
            sent,
        )
    return stats


def _level_already(db_path: str, alert_key: str) -> bool:
    if not db_path or not alert_key:
        return False
    _ensure(db_path)
    conn = sqlite3.connect(db_path, timeout=30.0)
    try:
        row = conn.execute(
            "SELECT 1 FROM biaoke_level_alerts WHERE alert_key=?", (alert_key,)
        ).fetchone()
        return bool(row)
    except sqlite3.Error:
        return False
    finally:
        conn.close()


def _mark_level(
    db_path: str,
    alert_key: str,
    *,
    post_id: str,
    level: float,
    bar_date: str,
    reasons: Sequence[str],
) -> None:
    if not db_path or not alert_key:
        return
    _ensure(db_path)
    conn = sqlite3.connect(db_path, timeout=30.0)
    try:
        conn.execute(
            "INSERT OR REPLACE INTO biaoke_level_alerts"
            "(alert_key, post_id, level, bar_date, reasons, sent_at) "
            "VALUES(?,?,?,?,?,datetime('now'))",
            (
                alert_key,
                str(post_id or ""),
                float(level),
                str(bar_date or ""),
                "／".join(reasons)[:400],
            ),
        )
        conn.commit()
    except sqlite3.Error:
        logger.debug("位階急推記號寫不進", exc_info=True)
    finally:
        conn.close()


def _claim_level_batch(
    db_path: str,
    rows: Sequence[Tuple[str, str, float, str, Sequence[str]]],
) -> bool:
    """先占位再送關卡推播。任一 key 已占 → False（整批不送）。

    rows: (alert_key, post_id, level, bar_date, reasons)
    BEGIN IMMEDIATE 擋住 ingest／tape 雙路徑競速。
    """
    if not db_path:
        return False
    items = [r for r in (rows or []) if r and str(r[0] or "").strip()]
    if not items:
        return False
    _ensure(db_path)
    conn = sqlite3.connect(db_path, timeout=30.0)
    try:
        conn.execute("BEGIN IMMEDIATE")
        for alert_key, _pid, _lv, _day, _why in items:
            hit = conn.execute(
                "SELECT 1 FROM biaoke_level_alerts WHERE alert_key=?",
                (str(alert_key),),
            ).fetchone()
            if hit:
                conn.rollback()
                return False
        for alert_key, post_id, level, bar_date, reasons in items:
            conn.execute(
                "INSERT INTO biaoke_level_alerts"
                "(alert_key, post_id, level, bar_date, reasons, sent_at) "
                "VALUES(?,?,?,?,?,datetime('now'))",
                (
                    str(alert_key),
                    str(post_id or ""),
                    float(level or 0),
                    str(bar_date or ""),
                    "／".join(reasons)[:400],
                ),
            )
        conn.commit()
        return True
    except sqlite3.Error:
        try:
            conn.rollback()
        except sqlite3.Error:
            pass
        logger.debug("位階急推 claim 失敗", exc_info=True)
        return False
    finally:
        conn.close()


def _last_official_twii(db_path: str) -> Optional[Dict[str, Any]]:
    if not db_path:
        return None
    try:
        from trading_calendar import is_official_daily_bar
    except Exception:
        return None
    conn = sqlite3.connect(db_path, timeout=15.0)
    try:
        rows = conn.execute(
            """
            SELECT date, open, high, low, close FROM index_daily
            WHERE symbol IN ('TWII','^TWII')
              AND high IS NOT NULL AND low IS NOT NULL
            ORDER BY date DESC LIMIT 8
            """
        ).fetchall()
    except sqlite3.Error:
        return None
    finally:
        conn.close()
    for raw_d, o, h, lo, c in rows:
        day = str(raw_d or "").replace("-", "")[:8]
        if not day or not is_official_daily_bar(day):
            continue
        try:
            return {
                "date": day,
                "open": float(o) if o is not None else None,
                "high": float(h),
                "low": float(lo),
                "close": float(c) if c is not None else None,
            }
        except (TypeError, ValueError):
            continue
    return None


def _load_marked_index_posts(
    db_path: str, *, lookback_days: int = 90
) -> List[Dict[str, Any]]:
    """他點過的大盤位＋原文。路人／社團不算。"""
    if not db_path:
        return []
    try:
        from biaoke_walk import extract_index_levels
    except Exception:
        return []
    from datetime import datetime, timedelta
    from zoneinfo import ZoneInfo

    floor = (datetime.now(ZoneInfo("Asia/Taipei")) - timedelta(days=lookback_days)).strftime(
        "%Y-%m-%d"
    )
    conn = sqlite3.connect(db_path, timeout=15.0)
    try:
        rows = conn.execute(
            """
            SELECT id, date, time, kind, text FROM biaoke_posts
            WHERE IFNULL(kind,'post') != 'bystander'
              AND date >= ?
              AND IFNULL(text,'') != ''
            ORDER BY date DESC, time DESC
            """,
            (floor,),
        ).fetchall()
    except sqlite3.Error:
        return []
    finally:
        conn.close()
    out: List[Dict[str, Any]] = []
    for pid, day, hm, kind, text in rows:
        levels = extract_index_levels(str(text or ""))
        if not levels:
            continue
        out.append(
            {
                "post_id": str(pid or ""),
                "date": str(day or ""),
                "time": str(hm or ""),
                "kind": str(kind or "post"),
                "text": str(text or ""),
                "levels": levels,
            }
        )
    return out


def maybe_push_marked_level_hits(
    db_path: str,
    *,
    now: Optional[Any] = None,
) -> Dict[str, Any]:
    """官方已收柱碰到他已點過的大盤位 → 同根柱／同日併成一則白話推播。

    未收盤不當收。一般新文不走這條。不准逐則堆幾月幾號舊文。
    同根柱一次碰到多個已點位 → 國中生一句（標題「飆大提醒·大盤碰到關卡」）；
    不准關卡串／收點串／之上之下表／機器規則句上話筒（2026-10-13 教訓）。
    先 claim 再送：同日同位／同關卡正文不重推；真新關卡仍兩支話筒各一則。
    """
    del now  # 官方柱是否已收走 is_official_daily_bar；保留參數相容呼叫端
    stats = {"checked": 0, "pushed": 0, "skipped": 0, "levels": 0}
    if not db_path:
        return stats
    bar = _last_official_twii(db_path)
    if not bar:
        return {**stats, "skipped": "no_official"}
    bar_ymd = str(bar["date"])
    hi = float(bar["high"])
    lo = float(bar["low"])
    posts = _load_marked_index_posts(db_path)
    # 同一點位併源，最近文優先進判斷
    by_lv: Dict[float, List[Dict[str, Any]]] = {}
    for post in posts:
        post_day = str(post.get("date") or "").replace("-", "")[:8]
        # 他點位那天或之後才對質；當日柱若未收不算，已收才進 bar。
        if post_day and post_day > bar_ymd:
            continue
        for hit in post.get("levels") or []:
            try:
                level = float(hit.get("level"))
            except (TypeError, ValueError):
                continue
            if not (lo <= level <= hi):
                continue
            stats["checked"] += 1
            by_lv.setdefault(level, []).append(
                {
                    "post_id": str(post.get("post_id") or ""),
                    "date": str(post.get("date") or ""),
                    "time": str(post.get("time") or ""),
                    "kind": str(post.get("kind") or "post"),
                    "text": str(post.get("text") or ""),
                    "role": str(hit.get("role") or "點位"),
                    "ctx": str(hit.get("ctx") or ""),
                }
            )
    pending: List[Dict[str, Any]] = []
    for level, sources in sorted(by_lv.items(), key=lambda kv: kv[0]):
        key = f"idx:lv:{level:g}:{bar_ymd}"
        if _level_already(db_path, key):
            stats["skipped"] += 1
            continue
        # 舊鍵（逐則）若已推過其中任一則，仍略過免洗版
        if any(
            _level_already(
                db_path, f"idx:{s.get('post_id')}:{level:g}:{bar_ymd}"
            )
            for s in sources
            if s.get("post_id")
        ):
            _mark_level(
                db_path,
                key,
                post_id=str(sources[0].get("post_id") or ""),
                level=level,
                bar_date=bar_ymd,
                reasons=[f"官方{bar_ymd}碰到{level:g}", "舊鍵已推"],
            )
            stats["skipped"] += 1
            continue
        roles = sorted(
            {
                str(s.get("role") or "點位")
                for s in sources
                if str(s.get("role") or "").strip()
            }
        )
        note = "加權" + ("／".join(roles) if roles else "點位")
        pending.append(
            {
                "level": level,
                "sources": sources,
                "note": note,
                "key": key,
            }
        )
    if not pending:
        return stats
    html = format_multi_level_hit_synthesis(
        levels=pending,
        bar_date=bar_ymd,
        bar_high=hi,
        bar_low=lo,
        bar_close=bar.get("close"),
    )
    if not html:
        return stats
    body_fp = _body_fingerprint(html)
    body_key = f"idx:body:{bar_ymd}:{body_fp}"
    # 同日同關卡正文已推過（即使 level 鍵集合微變）→ 不重送
    if body_fp and _level_already(db_path, body_key):
        stats["skipped"] += len(pending)
        return stats
    claim_rows: List[Tuple[str, str, float, str, Sequence[str]]] = []
    for item in pending:
        sources = item["sources"]
        level = float(item["level"])
        claim_rows.append(
            (
                str(item["key"]),
                str(sources[0].get("post_id") or ""),
                level,
                bar_ymd,
                [
                    f"官方{bar_ymd}碰到{level:g}",
                    str(item.get("note") or ""),
                    f"n={len(sources)}",
                    f"coalesce={len(pending)}",
                ],
            )
        )
    if body_fp:
        claim_rows.append(
            (
                body_key,
                "",
                0.0,
                bar_ymd,
                [f"同日同關卡正文 n={len(pending)}"],
            )
        )
    # 先占位再送：ingest＋tape 雙呼叫／多 worker 也不洗版
    if not _claim_level_batch(db_path, claim_rows):
        stats["skipped"] += len(pending)
        return stats
    dedupe = body_key if body_fp else f"idx:coalesce:{bar_ymd}:{len(pending)}"
    sent = _send_family(html, dedupe_key=dedupe, db_path=db_path)
    stats["pushed"] = 1
    stats["levels"] = len(pending)
    logger.info(
        "飆大位階急推 coalesce levels=%s bar=%s sent=%s",
        [float(x["level"]) for x in pending],
        bar_ymd,
        sent,
    )
    return stats


_PUSH_MSG_DDL = """
CREATE TABLE IF NOT EXISTS biaoke_push_msgs (
    chat_id TEXT NOT NULL,
    message_id INTEGER NOT NULL,
    sent_at TEXT NOT NULL DEFAULT '',
    head TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (chat_id, message_id)
);
CREATE TABLE IF NOT EXISTS biaoke_push_wipe (
    day TEXT PRIMARY KEY,
    done_at TEXT NOT NULL DEFAULT ''
);
"""
OLD_PUSH_MARKS = (
    "沒過按鈕",
    "怕錯過才直接推",
    "研判：",
    "官方加權盤中現價",
    "程式標籤（不是他原文）",
)
WIPE_RECIPE = "labels-v1"


def _push_db() -> str:
    try:
        from config import get_db_path

        return get_db_path()
    except Exception:
        return ""


def _record_push_msg(chat_id: str, message_id: int, html: str) -> None:
    db = _push_db()
    if not db or os.environ.get("PYTEST_CURRENT_TEST"):
        return
    try:
        conn = sqlite3.connect(db, timeout=30.0)
        conn.executescript(_PUSH_MSG_DDL)
        conn.execute(
            "INSERT OR REPLACE INTO biaoke_push_msgs(chat_id, message_id, sent_at, head) "
            "VALUES(?,?,datetime('now'),?)",
            (str(chat_id), int(message_id), _clip(html, 80)),
        )
        conn.commit()
        conn.close()
    except sqlite3.Error:
        logger.debug("推播 message_id 寫不進", exc_info=True)


def _tg_api(token: str, method: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    import requests

    try:
        resp = requests.post(
            f"https://api.telegram.org/bot{token}/{method}",
            json=payload,
            timeout=20,
        )
        return resp.json() if resp is not None else {}
    except Exception:
        return {}


def wipe_biaoke_phone_pushes(
    *,
    lookback: int = 180,
    marks: Sequence[str] = OLD_PUSH_MARKS,
) -> Dict[str, Any]:
    """掃最近訊息，只刪舊的嚇人盤中推文。查股圖／一般對話不刪。"""
    stats = {"chats": 0, "deleted": 0, "scanned": 0}
    if os.environ.get("PYTEST_CURRENT_TEST"):
        return stats
    try:
        from config import allowed_telegram_uids, get_telegram_token
    except Exception:
        return stats
    token = get_telegram_token()
    uids = [str(u).strip() for u in allowed_telegram_uids() if str(u).strip()]
    if not token or not uids:
        return stats
    needles = tuple(m for m in (marks or OLD_PUSH_MARKS) if m)
    for cid in uids:
        stats["chats"] += 1
        probe = _tg_api(
            token,
            "sendMessage",
            {
                "chat_id": cid,
                "text": "（清舊的飆大推文，這則隨即刪）",
                "disable_notification": True,
                "disable_web_page_preview": True,
            },
        )
        hi = int(((probe.get("result") or {}).get("message_id") or 0) or 0)
        if hi:
            _tg_api(token, "deleteMessage", {"chat_id": cid, "message_id": hi})
        if hi <= 0:
            continue
        lo = max(1, hi - max(20, int(lookback)))
        for mid in range(hi - 1, lo - 1, -1):
            fwd = _tg_api(
                token,
                "forwardMessage",
                {
                    "chat_id": cid,
                    "from_chat_id": cid,
                    "message_id": mid,
                    "disable_notification": True,
                },
            )
            if not fwd.get("ok"):
                continue
            stats["scanned"] += 1
            res = fwd.get("result") or {}
            fid = int(res.get("message_id") or 0)
            blob = str(res.get("text") or res.get("caption") or "")
            media = bool(
                res.get("photo")
                or res.get("document")
                or res.get("animation")
                or res.get("video")
                or res.get("sticker")
            )
            if fid:
                _tg_api(token, "deleteMessage", {"chat_id": cid, "message_id": fid})
            if media:
                continue
            if any(m in blob for m in needles):
                gone = _tg_api(
                    token, "deleteMessage", {"chat_id": cid, "message_id": mid}
                )
                if gone.get("ok"):
                    stats["deleted"] += 1
    logger.info(
        "飆大舊推文清除 chats=%s scanned=%s deleted=%s",
        stats["chats"],
        stats["scanned"],
        stats["deleted"],
    )
    return stats


def wipe_biaoke_phone_pushes_once() -> Dict[str, Any]:
    """開機按配方一天一次。清舊嚇人格式與帶官方現價／程式標籤的堆疊；不清查股圖、不清新的原文補充。"""
    empty = {"chats": 0, "deleted": 0, "scanned": 0, "skipped": "once"}
    if os.environ.get("PYTEST_CURRENT_TEST"):
        return empty
    db = _push_db()
    from datetime import datetime
    from zoneinfo import ZoneInfo

    day = datetime.now(ZoneInfo("Asia/Taipei")).strftime("%Y-%m-%d") + ":" + WIPE_RECIPE
    if db:
        try:
            conn = sqlite3.connect(db, timeout=30.0)
            conn.executescript(_PUSH_MSG_DDL)
            hit = conn.execute(
                "SELECT 1 FROM biaoke_push_wipe WHERE day=?", (day,)
            ).fetchone()
            if hit:
                conn.close()
                return empty
            conn.execute(
                "INSERT OR REPLACE INTO biaoke_push_wipe(day, done_at) VALUES(?, datetime('now'))",
                (day,),
            )
            conn.commit()
            conn.close()
        except sqlite3.Error:
            logger.debug("推播清除記號寫不進", exc_info=True)
    return wipe_biaoke_phone_pushes()
