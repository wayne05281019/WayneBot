# -*- coding: utf-8 -*-
"""問一檔時先走飆大那套：龍頭、資金剛起漲、量價。波浪只對大盤。

材料給對話線用，不要變成填空表。不是買訊、不進海選。
"""
from __future__ import annotations

import os
import sqlite3
from datetime import datetime, timedelta
from typing import Any, Dict, List, Tuple

from tg_layout import html_escape

_SKIP = frozenset({"TWII", "TX", "TXN", "^TWII"})
_FOLLOW = {
    "6442": ("3081", "聯亞"),
    "3363": ("3081", "聯亞"),
    "4979": ("3081", "聯亞"),
    "4977": ("3081", "聯亞"),
    "3450": ("3081", "聯亞"),
    "4971": ("3081", "聯亞"),
    "3653": ("3017", "奇鋐"),
    "3324": ("3017", "奇鋐"),
    "2421": ("3017", "奇鋐"),
    "8299": ("2408", "南亞科"),
    "2344": ("2408", "南亞科"),
    "3260": ("2408", "南亞科"),
    "2368": ("2383", "台光電"),
    "6274": ("2383", "台光電"),
    "6213": ("2383", "台光電"),
    "6223": ("6515", "穎崴"),
    "6830": ("6515", "穎崴"),
}
_CHAIN = (
    (("光通", "光通訊", "矽光子", "矽光"), "3081", "聯亞"),
    (("散熱",), "3017", "奇鋐"),
    (("記憶體", "DRAM"), "2408", "南亞科"),
    (("高階測試", "探針"), "6515", "穎崴"),
    (("IC設計", "IC 設計"), "2454", "聯發科"),
    (("伺服器", "AI伺服"), "2382", "廣達"),
    (("PCB", "CCL", "銅箔基板"), "2383", "台光電"),
)

# 2026-04-16：可抱到明年的長線主流龍頭；大盤大跌時介入，不是天天短打。
_LONG_HOLD = {
    "2330": "台積電",
    "2308": "台達電",
    "2383": "台光電",
    "6230": "旺矽",
    "6515": "穎崴",
    "3017": "奇鋐",
}


def _ymd(raw: Any) -> str:
    t = str(raw or "").replace("-", "")[:8]
    if len(t) == 8 and t.isdigit():
        return f"{t[:4]}-{t[4:6]}-{t[6:8]}"
    return str(raw or "").strip()


def _px(val: Any) -> str:
    try:
        n = float(val)
    except (TypeError, ValueError):
        return ""
    if abs(n - round(n)) < 1e-9:
        return str(int(round(n)))
    return f"{n:.2f}".rstrip("0").rstrip(".")


def _pct(val: Any) -> str:
    try:
        n = float(val)
    except (TypeError, ValueError):
        return ""
    sign = "＋" if n > 0 else ""
    return f"{sign}{n:.2f}%".replace("＋-", "−").replace("-", "−")


def _industry(db_path: str, sid: str) -> str:
    if not db_path or not os.path.isfile(db_path) or not sid:
        return ""
    conn = sqlite3.connect(db_path, timeout=10.0)
    try:
        row = conn.execute(
            "SELECT industry FROM stock_universe WHERE stock_id=?", (sid,)
        ).fetchone()
    except sqlite3.Error:
        row = None
    finally:
        conn.close()
    return str((row or [""])[0] or "").strip()


def leader_of(db_path: str, sid: str, name: str = "") -> Tuple[str, str, str]:
    """(leader_id, leader_name, why)。沒對上就空，不編。"""
    sid = str(sid or "").strip()
    if not sid or sid in _SKIP:
        return "", "", ""
    hit = _FOLLOW.get(sid)
    if hit:
        if hit[0] == sid:
            return sid, str(name or hit[1]), "自己就是這族龍頭"
        return hit[0], hit[1], "同族跟漲先看龍頭"
    for _src, (lid, lname) in _FOLLOW.items():
        if lid == sid:
            return sid, str(name or lname), "自己就是這族龍頭"
    if sid in _LONG_HOLD:
        return sid, str(name or _LONG_HOLD[sid]), "自己就是長線龍頭"
    blob = (name or "") + " " + _industry(db_path, sid)
    for keys, lid, lname in _CHAIN:
        if any(k in blob for k in keys):
            if lid == sid:
                return sid, str(name or lname), "自己就是這族龍頭"
            return lid, lname, "同族跟漲先看龍頭"
    return "", "", ""


def _cal60(bars: List[Dict[str, Any]]) -> Dict[str, Any]:
    if not bars:
        return {}
    last = bars[-1]
    ymd = str(last.get("date") or "").replace("-", "")[:8]
    if len(ymd) != 8:
        return {}
    try:
        day = datetime.strptime(ymd, "%Y%m%d").date()
    except ValueError:
        return {}
    cut = (day - timedelta(days=60)).strftime("%Y%m%d")
    win = [b for b in bars if str(b.get("date") or "").replace("-", "")[:8] >= cut]
    if not win:
        return {}
    closes = [float(b.get("close") or 0) for b in win if b.get("close") is not None]
    if not closes:
        return {}
    lo = min(closes)
    close = float(last.get("close") or 0)
    pct = ((close / lo) - 1.0) * 100.0 if lo else 0.0
    return {"low": lo, "close": close, "pct": pct}


def _rotation(db_path: str, ymd: str, industry: str) -> str:
    if not db_path or not industry or not ymd:
        return ""
    try:
        from money_flow import sector_flow_maps
    except Exception:
        return ""
    key = ymd.replace("-", "")[:8]
    try:
        maps = sector_flow_maps(db_path, key)
    except Exception:
        return ""
    just = maps.get("just_rotated") or {}
    inflow = maps.get("inflow") or {}
    outflow = maps.get("outflow") or {}
    if industry in just:
        return f"三大法人這天剛輪進{industry}"
    if industry in inflow:
        return f"{industry}在流入前段"
    if industry in outflow:
        return f"{industry}在流出前段，還不像剛起漲"
    return ""


def _pace(
    struct: Dict[str, Any],
    rot: str,
    leader: Dict[str, Any],
    *,
    long_hold: bool = False,
) -> str:
    if not struct:
        return ""
    if not struct.get("above_support"):
        bit = "這腳量價還在爆大量日低點之下，他這套是先放棄，不是擺著等。"
    elif struct.get("broke_resistance"):
        if long_hold:
            bit = "量價已過爆大量日高，但這檔他當長線龍頭，不是半山腰隔日沖那一類。"
        else:
            bit = "已經過爆大量日高，比較像半山腰；他只做隔日沖。"
    elif struct.get("shrinking"):
        bit = "量縮又站上爆大量日低點，比較像整理末端那一類。"
    else:
        bit = "站上撐了但量還沒縮，還不到他說的進。"
    if rot:
        bit += rot + "。"
    ls = leader.get("struct") or {}
    if ls and leader.get("sid") and leader.get("sid") != struct.get("sid"):
        if ls.get("broke_resistance"):
            bit += f"龍頭{leader.get('name')}已經過高，跟漲檔要想想是接棒還是龍頭先休息。"
        elif not ls.get("above_support"):
            bit += f"龍頭{leader.get('name')}還沒站上自己的量價撐，這族比較不像剛起漲。"
        elif ls.get("shrinking"):
            bit += f"龍頭{leader.get('name')}量縮站上，比較像資金要動。"
    return bit


def _hold_note(sid: str, in_corpus: bool) -> str:
    if sid not in _LONG_HOLD:
        return ""
    name = _LONG_HOLD[sid]
    bit = (
        f"{name}在他 4/16 長線龍頭名單：產業趨勢還在就不是天天管；"
        "買點是大盤大跌窗口，不是把波浪套在這檔日 K。"
    )
    if sid == "2383":
        bit += "錨是 7/6 買跌不買漲，官方日 K 7/29 低 3985、7/30 低 3930。"
    if not in_corpus:
        bit += "公開文沒點名這檔時只套量價，可能看錯。"
    return bit


def judge_stock(db_path: str, sid: str, name: str = "") -> Dict[str, Any]:
    from biaoke_brain import load_bars, volume_first_price

    sid = str(sid or "").strip()
    out: Dict[str, Any] = {"sid": sid, "name": name or sid}
    if not sid or sid in _SKIP:
        return out
    bars = load_bars(db_path, sid, n=80) if db_path else []
    struct = volume_first_price(bars) if bars else {}
    if struct:
        out["struct"] = struct
        out["name"] = str(struct.get("name") or name or sid)
    out["cal60"] = _cal60(bars)
    ind = _industry(db_path, sid)
    out["industry"] = ind
    ymd = str((struct or {}).get("date") or "")
    out["rotation"] = _rotation(db_path, ymd, ind)
    lid, lname, why = leader_of(db_path, sid, out.get("name") or name)
    leader: Dict[str, Any] = {}
    if lid:
        leader = {"sid": lid, "name": lname, "why": why}
        if lid != sid:
            lb = load_bars(db_path, lid, n=80) if db_path else []
            leader["struct"] = volume_first_price(lb) if lb else {}
        else:
            leader["struct"] = struct
    out["leader"] = leader
    posts = []
    try:
        from biaoke_brain import match_posts

        posts = match_posts(out.get("name") or sid, limit=3, db_path=db_path)
    except Exception:
        posts = []
    out["in_corpus"] = bool(posts)
    claims = ""
    try:
        from biaoke_claims import format_stock_claims

        claims = format_stock_claims(db_path, sid, name=out.get("name") or name)
    except Exception:
        claims = ""
    out["claims"] = claims
    out["long_hold"] = sid in _LONG_HOLD
    out["hold"] = _hold_note(sid, bool(out.get("in_corpus")))
    out["pace"] = _pace(
        struct,
        out.get("rotation") or "",
        leader,
        long_hold=bool(out.get("long_hold")),
    )
    return out


def format_judge_notes(brief: Dict[str, Any]) -> str:
    """給即時對話線當材料，禁止模型照抄當填空表。"""
    if not brief or not brief.get("sid"):
        return ""
    st = brief.get("struct") or {}
    bits = [
        "問檔材料（這是材料，不要照抄標題）：",
        f"{brief.get('sid')} {brief.get('name') or ''} "
        f"{st.get('date') or ''}收{st.get('close') or ''} "
        f"爆量日{st.get('spike_date') or ''}高{st.get('spike_high') or ''}低{st.get('spike_low') or ''}"
        f" 量縮={st.get('shrinking')} 站上撐={st.get('above_support')}",
    ]
    if not brief.get("in_corpus"):
        bits.append("公開文沒點名這檔，只用官方K套他的量價，可能看錯。")
    cal = brief.get("cal60") or {}
    if cal.get("low"):
        bits.append(f"近60曆日收盤低{_px(cal.get('low'))} 距低{_pct(cal.get('pct'))}")
    if brief.get("industry"):
        bits.append("產業 " + str(brief.get("industry")))
    if brief.get("rotation"):
        bits.append(str(brief.get("rotation")))
    leader = brief.get("leader") or {}
    if leader.get("sid"):
        ls = leader.get("struct") or {}
        bits.append(
            f"這族先看龍頭 {leader.get('sid')} {leader.get('name')}（{leader.get('why')}）"
            f" 收{ls.get('close') or ''} 量縮={ls.get('shrinking')} 站上撐={ls.get('above_support')}"
        )
    if brief.get("pace"):
        bits.append(str(brief.get("pace")))
    if brief.get("hold"):
        bits.append(str(brief.get("hold")))
    claims = str(brief.get("claims") or "").strip()
    if claims:
        bits.append("他寫過的價：" + claims.replace("\n", "；")[:420])
    else:
        bits.append("這檔他沒寫目標價，不准編會漲到哪。")
    bits.append("波浪不要套這檔；個股先看產業趨勢，大盤才用細微波／15分／60分／夜盤。")
    return "\n".join(bits)


def format_judge_html(brief: Dict[str, Any]) -> str:
    """沒走即時線時的短答。講人話，不要欄位表。"""
    if not brief or not brief.get("sid"):
        return ""
    st = brief.get("struct") or {}
    sid = html_escape(str(brief.get("sid") or ""))
    name = html_escape(str(brief.get("name") or sid))
    lines: List[str] = []
    if not brief.get("in_corpus"):
        lines.append(
            f"{sid} {name} 資料庫從頭到尾沒點名這檔，我就拿官方日 K 用他那套量價看，可能看錯。"
        )
    else:
        lines.append(f"{sid} {name}。")
    if st:
        body = (
            f"{html_escape(st.get('date'))} 收 {_px(st.get('close')) or '—'}"
            f"（{_pct(st.get('pct')) or '—'}）。"
            f"近窗爆大量日 {html_escape(st.get('spike_date'))}，"
            f"高 {_px(st.get('spike_high')) or '—'}、低 {_px(st.get('spike_low')) or '—'}。"
            f"{html_escape(st.get('stance') or '')}"
        )
        lines.append(body)
    leader = brief.get("leader") or {}
    if leader.get("sid") and leader.get("sid") != brief.get("sid"):
        lines.append(
            f"這族要先看 {html_escape(leader.get('sid'))} {html_escape(leader.get('name'))}，"
            f"{html_escape(leader.get('why') or '同族跟漲先看龍頭')}。"
        )
    if brief.get("pace"):
        lines.append(html_escape(str(brief.get("pace"))))
    if brief.get("hold"):
        lines.append(html_escape(str(brief.get("hold"))))
    claims = str(brief.get("claims") or "").strip()
    if claims:
        for ln in claims.split("\n"):
            if ln and ln != "不是買訊。" and ln not in lines:
                lines.append(html_escape(ln) if "<" not in ln else ln)
    else:
        lines.append("這檔他沒寫目標價，這裡不編漲到哪。")
    return "\n".join(x for x in lines if x)
