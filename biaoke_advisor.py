# -*- coding: utf-8 -*-
"""飆大智囊團：活用近窗說法＋跨庫官方資料，不准當答錄機只倒原文。

精神：為什麼他這樣說、為什麼現在還不能確定、雙箭頭改口後誰對誰還要等。
飆大鈕內所有能力可隨意取用主庫（行情／語料／佔比／海選桶／期貨／tape）
與 evolve（live_judge）查閱，不准自我設限只念一篇舊文。
切入編碼仍只認黃金買點（leave_zero）；這層是口語活用，不是改海選公式。
個股不准發明 5／9；大盤五段／九段只轉述他自己說「還看不出」。
"""
from __future__ import annotations

import os
import re
import sqlite3
from typing import Any, Dict, List, Optional, Sequence, Tuple

from tg_layout import html_escape

# 問句觸發：整顆飆大鈕都要能活，不只點名 InP
_ADVISOR_ASK = re.compile(
    r"(InP|光通訊|矽光子|CPO|FAU|ASIC|創意|聯亞|全新|IET|"
    r"雙箭頭|主流|可買|能不能買|該買|買點|回測|"
    r"波浪|位階|末升|主升|五段|九段|量價|"
    r"過年|農曆|為什麼|為何|怎麼看|智囊|活用|"
    r"大盤|台股|族群|二軍|IC設計)",
    re.I,
)

_DUAL_ARROW = re.compile(
    r"ASIC.{0,40}光通訊|光通訊.{0,40}ASIC|雙箭頭|"
    r"兩大最強|稍微改變|改為ASIC",
    re.I,
)
_WAVE_FIVE = re.compile(
    r"位階四.{0,24}(完成|走五)|開始走五|波浪位階五|"
    r"五段.{0,12}九段|九段.{0,12}五段|末升",
)
_METHOD = re.compile(r"量價結構|波浪理論|主力籌碼|長期的大盤規劃")

# 建議只用近窗還在講的族群。已退場主題近窗沒再講＝不准推那些檔。
NEAR_ADVICE_DAYS = 14
_RETIRED_THEME_SIDS: Dict[str, Tuple[str, ...]] = {
    # 無人機：2025-09-05 不要再碰；近窗（14日）沒再講就不准建議
    "無人機": ("5371", "8033", "4916", "2645", "2634"),  # 中光電／雷虎／事欣科／長榮航太／亞航
}
_RETIRED_NEEDLES: Dict[str, Tuple[str, ...]] = {
    "無人機": ("無人機",),
}


def near_spoken_text(db_path: str, *, days: int = NEAR_ADVICE_DAYS) -> str:
    """近 N 日他自己主文＋自回正文。建議只認這窗，不准翻舊題材。"""
    if not db_path or not os.path.isfile(db_path):
        return ""
    try:
        from datetime import datetime, timedelta
        from zoneinfo import ZoneInfo

        tp = ZoneInfo("Asia/Taipei")
        end = datetime.now(tp).strftime("%Y-%m-%d")
        start = (datetime.now(tp) - timedelta(days=max(1, int(days) - 1))).strftime(
            "%Y-%m-%d"
        )
        from biaoke_field_scan import week_spoken

        return week_spoken(db_path, start, end) or ""
    except Exception:
        return ""


def theme_is_live(db_path: str, theme: str, *, days: int = NEAR_ADVICE_DAYS) -> bool:
    """主題近窗還有沒有他自己再講。沒講＝已退場，不准建議那組。"""
    needles = _RETIRED_NEEDLES.get(theme) or (theme,)
    blob = near_spoken_text(db_path, days=days)
    return any(n and n in blob for n in needles)


def advice_sid_blocked(db_path: str, sid: str, *, days: int = NEAR_ADVICE_DAYS) -> bool:
    """已退場主題的檔，近窗沒再講該主題＝封鎖建議。"""
    sid = str(sid or "").strip()
    if not sid:
        return True
    for theme, sids in _RETIRED_THEME_SIDS.items():
        if sid in sids and not theme_is_live(db_path, theme, days=days):
            return True
    return False


def want_advisor(ask: str = "", *, spoken: str = "") -> bool:
    """空白進飆大、近窗有改口、或問句碰到活用主題 → 智囊團要開口。"""
    blob = f"{ask or ''}\n{spoken or ''}"
    if not blob.strip():
        return True  # 空白按進去也要活
    if _ADVISOR_ASK.search(blob):
        return True
    if _DUAL_ARROW.search(blob) or _WAVE_FIVE.search(blob) or _METHOD.search(blob):
        return True
    return False


def _evolve_path(market_db: str) -> str:
    path = os.path.abspath(str(market_db or "data/wayne_market.db"))
    root = os.path.dirname(path) or "."
    name = os.path.basename(path)
    if name == "wayne_evolve.db":
        return path
    return os.path.join(root, "wayne_evolve.db")


def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    try:
        hit = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
            (name,),
        ).fetchone()
        return bool(hit)
    except sqlite3.Error:
        return False


def cross_db_glance(
    db_path: str,
    ask: str = "",
    *,
    sids: Optional[Sequence[str]] = None,
) -> Dict[str, Any]:
    """飆大鈕跨庫查閱一覽：主庫＋evolve，給智囊活用，不是原文目錄。"""
    out: Dict[str, Any] = {
        "ok": False,
        "twii": None,
        "share_top": [],
        "leave_zero": [],
        "golden_buy": [],
        "tape": [],
        "field_expand": [],
        "lines": [],
    }
    if not db_path or not os.path.isfile(db_path):
        return out
    want_sids = [str(s) for s in (sids or ()) if s][:12]
    lines: List[str] = []
    try:
        conn = sqlite3.connect(db_path, timeout=8.0)
        try:
            if _table_exists(conn, "index_daily"):
                row = conn.execute(
                    "SELECT date, close, high, low FROM index_daily "
                    "WHERE symbol='TWII' OR IFNULL(symbol,'')='' "
                    "ORDER BY REPLACE(CAST(date AS TEXT),'-','') DESC LIMIT 1"
                ).fetchone()
                if row:
                    out["twii"] = {
                        "date": str(row[0] or ""),
                        "close": row[1],
                        "high": row[2],
                        "low": row[3],
                    }
                    lines.append(
                        f"跨庫加權 {row[0]} 收 {row[1]}（主庫 index_daily）"
                    )
            if _table_exists(conn, "dongzhu_flow_tape"):
                rows = conn.execute(
                    "SELECT date, field, share_pct, share_chg, fine_tag "
                    "FROM dongzhu_flow_tape ORDER BY date DESC, share_pct DESC LIMIT 4"
                ).fetchall()
                out["share_top"] = [
                    {
                        "date": str(r[0] or ""),
                        "field": str(r[1] or ""),
                        "share_pct": r[2],
                        "share_chg": r[3],
                        "fine_tag": str(r[4] or ""),
                    }
                    for r in rows
                ]
                if rows:
                    top = rows[0]
                    lines.append(
                        f"跨庫佔比近窗首位 {top[1]} "
                        f"{float(top[2] or 0):.1f}%（升降 {float(top[3] or 0):+.1f}；主判仍佔比）"
                    )
            if _table_exists(conn, "screen_picks"):
                for bucket, key in (
                    ("leave_zero", "leave_zero"),
                    ("golden_buy", "golden_buy"),
                ):
                    rows = conn.execute(
                        "SELECT stock_id, stock_name, pick_close, as_of FROM screen_picks "
                        "WHERE bucket=? ORDER BY as_of DESC LIMIT 6",
                        (bucket,),
                    ).fetchall()
                    items = [
                        {
                            "sid": str(r[0] or ""),
                            "name": str(r[1] or ""),
                            "px": r[2],
                            "as_of": str(r[3] or ""),
                        }
                        for r in rows
                    ]
                    out[key] = items
                if out["leave_zero"]:
                    lines.append(
                        "跨庫海選剛脫離零 "
                        + "、".join(
                            f"{x['name']or x['sid']}" for x in out["leave_zero"][:4]
                        )
                        + "（切入只認這條）"
                    )
                if out["golden_buy"]:
                    lines.append(
                        "跨庫還在零觀察 "
                        + "、".join(
                            f"{x['name']or x['sid']}" for x in out["golden_buy"][:3]
                        )
                        + "（只觀察不是買）"
                    )
            if _table_exists(conn, "biaoke_tape") and want_sids:
                q = ",".join("?" * len(want_sids))
                rows = conn.execute(
                    f"SELECT stock_id, stock_name, bar_date, close, high, low, volume "
                    f"FROM biaoke_tape WHERE stock_id IN ({q}) "
                    f"ORDER BY bar_date DESC LIMIT 8",
                    tuple(want_sids),
                ).fetchall()
                out["tape"] = [
                    {
                        "sid": str(r[0] or ""),
                        "name": str(r[1] or ""),
                        "date": str(r[2] or ""),
                        "close": r[3],
                    }
                    for r in rows
                ]
                if rows:
                    lines.append(
                        "跨庫飆大tape "
                        + "、".join(
                            f"{r[1]or r[0]} {r[2]}收{r[3]}" for r in rows[:3]
                        )
                    )
            elif _table_exists(conn, "biaoke_tape"):
                rows = conn.execute(
                    "SELECT stock_id, stock_name, bar_date, close FROM biaoke_tape "
                    "ORDER BY bar_date DESC LIMIT 4"
                ).fetchall()
                if rows:
                    out["tape"] = [
                        {
                            "sid": str(r[0] or ""),
                            "name": str(r[1] or ""),
                            "date": str(r[2] or ""),
                            "close": r[3],
                        }
                        for r in rows
                    ]
                    lines.append(
                        "跨庫近窗tape "
                        + "、".join(f"{r[1]or r[0]}" for r in rows[:4])
                    )
        finally:
            conn.close()
    except sqlite3.Error:
        pass
    # evolve：live_judge 類股展開／對質材料
    evo = _evolve_path(db_path)
    if os.path.isfile(evo):
        try:
            conn = sqlite3.connect(evo, timeout=8.0)
            try:
                if _table_exists(conn, "live_judge"):
                    rows = conn.execute(
                        "SELECT as_of, kind, pick, sid, name, px, extra FROM live_judge "
                        "WHERE kind LIKE 'biaoke%' OR kind LIKE '%field%' "
                        "ORDER BY as_of DESC, ran_at DESC LIMIT 8"
                    ).fetchall()
                    out["field_expand"] = [
                        {
                            "as_of": str(r[0] or ""),
                            "kind": str(r[1] or ""),
                            "pick": str(r[2] or ""),
                            "sid": str(r[3] or ""),
                            "name": str(r[4] or ""),
                            "px": r[5],
                        }
                        for r in rows
                    ]
                    if rows:
                        lines.append(
                            "跨庫evolve聯想 "
                            + "、".join(
                                f"{r[4]or r[3]}" for r in rows[:4] if r[3]
                            )
                            + "（live_judge）"
                        )
            finally:
                conn.close()
        except sqlite3.Error:
            pass
    # 問句若點名，補官方日K一句
    core = (ask or "").strip()
    if db_path and core:
        try:
            from biaoke_brain import load_bars, resolve_stock

            hits = resolve_stock(db_path, core) or []
            if hits:
                sid = str(hits[0].get("stock_id") or "")
                name = str(hits[0].get("stock_name") or sid)
                bars = load_bars(db_path, sid, n=3) if sid else []
                if bars:
                    b = bars[-1]
                    lines.append(
                        f"跨庫個股 {name} {b.get('date')} "
                        f"收 {b.get('close')} 高 {b.get('high')} 低 {b.get('low')} 量 {b.get('volume')}"
                    )
        except Exception:
            pass
    out["lines"] = lines[:8]
    out["ok"] = bool(lines)
    return out


def _spoken_pack(db_path: str) -> Dict[str, Any]:
    """只取近窗正文；不准回呼 biaoke_week_link（會循環）。"""
    out: Dict[str, Any] = {
        "spoken": "",
        "start": "",
        "end": "",
    }
    if not db_path:
        return out
    try:
        from biaoke_field_scan import recent_spoken_range, week_spoken

        a, b = recent_spoken_range(db_path)
        spoken = week_spoken(db_path, a, b) or ""
        out.update({"spoken": spoken, "start": a, "end": b})
    except Exception:
        pass
    if not out["spoken"]:
        try:
            from biaoke_field_scan import latest_spoken

            out["spoken"] = latest_spoken(db_path) or ""
        except Exception:
            pass
    return out


def _wave_why(spoken: str, db_path: str = "") -> List[str]:
    """為什麼位階四→五已經看得清楚，卻還不能確定五段或九段。"""
    text = str(spoken or "")
    lines: List[str] = []
    last_tag = ""
    try:
        from biaoke_wave import last_two

        last, _prev = last_two(db_path) if db_path else (None, None)
        last_tag = str((last or {}).get("tag") or "")
    except Exception:
        last_tag = ""
    hit_wave = bool(_WAVE_FIVE.search(text)) or last_tag in {
        "位階四",
        "主升段",
        "末升段",
    }
    if not hit_wave:
        return lines
    lines.append(
        "為什麼這樣說：量價結構只能讀主力籌碼意圖；"
        "長期大盤規劃他認波浪才能辨識——"
        "位階四整理完成、開始走五時，大一級方向特別清楚。"
    )
    lines.append(
        "為什麼現在還不能確定：波浪五的內部要走五段還是九段，"
        "他自己講還看不出；缺細微波／官方柱走完前，智囊不准替他選邊、不准發明段數。"
    )
    if last_tag == "末升段":
        lines.append(
            "近窗標籤已往末升／浪五推——圖跟精神要跟著改口重畫，不准永遠念舊ABC下殺。"
        )
    elif last_tag == "位階四":
        lines.append(
            "近窗還在位階四完成→要走五：重點是整理完往上推，不是鎖死逃命波劇本。"
        )
    return lines


def _dual_arrow_why(spoken: str) -> List[str]:
    text = str(spoken or "")
    if not (_DUAL_ARROW.search(text) or ("InP" in text and "ASIC" in text)):
        # 近窗有光通訊／InP 仍給改口精神，避免只剩舊「InP 第一」死記
        if "InP" not in text and "光通訊" not in text and "ASIC" not in text:
            return []
    lines: List[str] = []
    if _DUAL_ARROW.search(text) or ("創意" in text and "歷史高" in text):
        lines.append(
            "為什麼改口：他剛回來先釘光通訊／InP 第一；"
            "創意創先過歷史高點後，改成 ASIC＋光通訊（尤其 InP）"
            "到農曆年前兩大最強雙箭頭——不是刪掉 InP，是把 ASIC 拉成並列主軸。"
        )
    elif "InP" in text:
        lines.append(
            "近窗主流精神：光通訊要細分 InP／CPO／FAU；"
            "他說過主流是 InP 不是 CPO——矽光子舊標籤 alone 已跟不上。"
        )
    if "過年" in text or "農曆" in text:
        lines.append(
            "時間巢：這波行情他點過年前差不多走完；過年後大修是更後面的巢，不是現在劇本。"
        )
    return lines


def _tier_row(
    sid: str,
    name: str,
    *,
    leave_zero: bool,
    in_buy_bucket: bool,
    in_watch_bucket: bool,
    vs20: Optional[float],
    broke: Optional[bool],
    chg5: Optional[float],
) -> Dict[str, Any]:
    """可買／還不能買／偏晚——活用官方柱＋黃金買點，不是猜新聞。"""
    action = "族群對、等回測或整理末端"
    why = "方向對得上雙箭頭／InP，但還沒到剛脫離零買點；歷史上強勢主流常回測才好接。"
    if leave_zero or in_buy_bucket:
        action = "可買（黃金買點）"
        why = "官方柱對上剛脫離零＝切入只認這一條。"
    elif in_watch_bucket:
        action = "可買但現在還不能買"
        why = "還在零／嚴重低估觀察桶＝只觀察不是買；等獲利剛離零。"
    elif broke and vs20 is not None and float(vs20) >= -3.0:
        action = "偏晚、先不追"
        why = "近窗已攻／贴近20高，追價勝率差；等回測或量縮站上再說。"
    elif vs20 is not None and float(vs20) <= -12.0:
        action = "可看、位階仍低"
        why = "相對20高還有空間，但沒剛離零就不叫買點；盯整理末端／突破回測。"
    elif vs20 is not None and float(vs20) >= -5.0:
        action = "偏熱、等回測"
        why = "已靠近前高區；他教過半山腰只隔日沖，中線要等回測。"
    return {
        "sid": sid,
        "name": name,
        "action": action,
        "why": why,
        "vs20": vs20,
        "chg5": chg5,
        "broke": broke,
        "leave_zero": bool(leave_zero or in_buy_bucket),
    }


def _classify_roster(
    db_path: str,
    members: Sequence[Tuple[str, str]],
) -> List[Dict[str, Any]]:
    if not db_path or not members:
        return []
    try:
        from biaoke_field_scan import (
            _bars,
            _bucket_by_id,
            _cap,
            _pct_chg_n,
            _sid_leave_zero_official,
            _stats,
        )
    except Exception:
        return []
    cap = _cap(db_path)
    buys = _bucket_by_id(db_path, "leave_zero")
    watch = _bucket_by_id(db_path, "golden_buy")
    rows: List[Dict[str, Any]] = []
    for sid, name in members:
        st = _stats(_bars(db_path, sid, cap)) if cap else None
        vs20 = None if not st else round(float(st["vs20"]), 1)
        broke = None if not st else bool(st.get("broke"))
        chg5 = _pct_chg_n(db_path, sid, 5)
        lz = bool(_sid_leave_zero_official(db_path, sid, cap)) if cap else False
        rows.append(
            _tier_row(
                sid,
                name,
                leave_zero=lz,
                in_buy_bucket=sid in buys,
                in_watch_bucket=sid in watch,
                vs20=vs20,
                broke=broke,
                chg5=chg5,
            )
        )
    # 可買優先，其次可看／等回測，偏晚最後
    rank = {
        "可買（黃金買點）": 0,
        "可買但現在還不能買": 1,
        "可看、位階仍低": 2,
        "族群對、等回測或整理末端": 3,
        "偏熱、等回測": 4,
        "偏晚、先不追": 5,
    }
    rows.sort(key=lambda r: (rank.get(str(r.get("action")), 9), str(r.get("sid"))))
    return rows


def _inp_asic_tiers(db_path: str, spoken: str) -> Dict[str, Any]:
    from biaoke_field_scan import _OPT_INP, _ASIC_IC_ANCHORS

    # 建議只認近窗正文；沒近窗才退回傳入 spoken（測試用）
    near = near_spoken_text(db_path) if db_path else ""
    text = near or str(spoken or "")
    want_opt = any(k in text for k in ("InP", "光通訊", "矽光子", "CPO", "聯亞", "全新"))
    want_asic = any(
        k in text for k in ("ASIC", "創意", "聯發", "IC設計", "雙箭頭", "兩大最強")
    )
    out: Dict[str, Any] = {"inp": [], "asic": [], "lines": []}
    # 近窗沒點到就不硬塞名冊；已退場主題檔一律剔除
    if want_opt:
        out["inp"] = [
            r
            for r in _classify_roster(db_path, list(_OPT_INP.items()))
            if not advice_sid_blocked(db_path, str(r.get("sid") or ""))
        ]
    if want_asic:
        out["asic"] = [
            r
            for r in _classify_roster(db_path, list(_ASIC_IC_ANCHORS))
            if not advice_sid_blocked(db_path, str(r.get("sid") or ""))
        ]
    for label, rows in (("InP", out["inp"]), ("ASIC錨", out["asic"])):
        if not rows:
            continue
        can = [r for r in rows if r.get("leave_zero")]
        wait = [r for r in rows if "還不能買" in str(r.get("action") or "")]
        low = [r for r in rows if "位階仍低" in str(r.get("action") or "")]
        hot = [
            r
            for r in rows
            if any(k in str(r.get("action") or "") for k in ("偏晚", "偏熱"))
        ]
        bits = [f"{label}活用"]
        if can:
            bits.append(
                "可買 "
                + "、".join(f"{r['name']}" for r in can[:3])
                + "（剛脫離零）"
            )
        if wait:
            bits.append(
                "可買但現在還不能買 "
                + "、".join(f"{r['name']}" for r in wait[:3])
                + "（還在零只觀察）"
            )
        if low:
            bits.append(
                "方向對、位階仍低 "
                + "、".join(f"{r['name']}" for r in low[:3])
                + "（等回測／整理末端）"
            )
        if hot:
            bits.append(
                "偏熱先不追 "
                + "、".join(f"{r['name']}" for r in hot[:3])
            )
        if len(bits) == 1:
            bits.append("近窗柱還沒排出黃金買點；族群對也不准硬追")
        out["lines"].append("；".join(bits))
    return out


def advisor_pack(db_path: str = "", ask: str = "") -> Dict[str, Any]:
    """一次收成智囊團判斷包：為什麼／不確定／雙箭頭／可買分層／跨庫查閱。"""
    pack = _spoken_pack(db_path)
    spoken = str(pack.get("spoken") or "")
    wave = _wave_why(spoken, db_path)
    dual = _dual_arrow_why(spoken)
    tiers = _inp_asic_tiers(db_path, spoken or ask)
    tier_sids = [
        str(r.get("sid") or "")
        for r in list(tiers.get("inp") or []) + list(tiers.get("asic") or [])
        if r.get("sid")
    ]
    cross = cross_db_glance(db_path, ask, sids=tier_sids)
    reweave_lines: List[str] = []
    try:
        from biaoke_reweave import reweave_gold

        rw = reweave_gold(db_path)
        reweave_lines = [str(x) for x in (rw.get("gold") or [])[:4] if x]
    except Exception:
        reweave_lines = []
    lines: List[str] = []
    lines.extend(dual)
    lines.extend(wave)
    lines.extend(tiers.get("lines") or [])
    for cl in reweave_lines:
        if cl and cl not in lines:
            lines.append(cl)
    # 跨庫材料壓成活用句（不准變日期目錄）
    for cl in (cross.get("lines") or [])[:3]:
        if cl and cl not in lines:
            lines.append(cl)
    if lines:
        lines.append(
            "活人思考：可隨意取用主庫＋evolve 查閱；"
            "串為什麼這樣說、為什麼還不定、黃金在哪——不准答錄機倒日期。"
        )
    return {
        "ok": bool(lines),
        "spoken": spoken,
        "start": pack.get("start") or "",
        "end": pack.get("end") or "",
        "wave": wave,
        "dual": dual,
        "tiers": tiers,
        "cross": cross,
        "lines": lines,
        "inp_rows": tiers.get("inp") or [],
        "asic_rows": tiers.get("asic") or [],
    }


def format_advisor_html(db_path: str = "", ask: str = "", *, limit: int = 8) -> str:
    """話筒用：智囊團區塊。"""
    if not want_advisor(ask) and ask.strip():
        # 個股問句也給一層活用（若近窗有雙箭頭／浪）
        pack = advisor_pack(db_path, ask="")
        if not pack.get("ok"):
            return ""
    else:
        pack = advisor_pack(db_path, ask)
    if not pack.get("ok"):
        return ""
    blocks = ["<b>智囊團活用</b>"]
    for line in (pack.get("lines") or [])[: max(1, int(limit))]:
        t = str(line).replace("不是買訊", "").replace("非買訊", "").strip(" ；")
        if t:
            blocks.append(html_escape(t))
    # 明細：InP 分層最多四檔，一眼可讀
    detail: List[str] = []
    for r in (pack.get("inp_rows") or [])[:4]:
        vs = r.get("vs20")
        vs_bit = f" vs20 {float(vs):+.1f}%" if vs is not None else ""
        detail.append(
            f"{r.get('name')}：{r.get('action')}{vs_bit}"
        )
    if detail:
        blocks.append(html_escape("InP分層　" + "；".join(detail)))
    return "\n".join(blocks)


def advisor_live_notes(db_path: str = "", ask: str = "") -> str:
    """餵給雲端 live：材料要是判斷，不是原文目錄；可跨主庫＋evolve。"""
    pack = advisor_pack(db_path, ask)
    if not pack.get("ok"):
        return ""
    bits = [
        "智囊團材料（活用，不准當答錄機照念）：",
        "飆大鈕內所有能力可隨意取用主庫（日K／佔比／海選桶／期貨／tape／公開主文）"
        "與 evolve（live_judge）查閱，不准自我設限只念一篇舊文。",
        "你要講清楚：他為什麼這樣說、為什麼現在還不能確定、哪些方向對但還不能買。",
        "圖／位階精神隨近窗改口重畫，不准永遠ABC。",
    ]
    for line in (pack.get("lines") or [])[:10]:
        bits.append("判斷｜" + line)
    for r in (pack.get("inp_rows") or [])[:5]:
        bits.append(
            f"InP檔｜{r.get('name')} {r.get('sid')} → {r.get('action')}；"
            f"{r.get('why')}"
        )
    for r in (pack.get("asic_rows") or [])[:3]:
        bits.append(
            f"ASIC錨｜{r.get('name')} {r.get('sid')} → {r.get('action')}；"
            f"{r.get('why')}"
        )
    return "\n".join(bits)


def advisor_focus_lines(db_path: str = "") -> List[str]:
    """空白按飆大：插在口語重點後面的活用句。"""
    pack = advisor_pack(db_path, ask="")
    return [str(x) for x in (pack.get("lines") or [])[:5] if str(x).strip()]


def _evidence_bit(row: Dict[str, Any]) -> str:
    """官方柱憑據一句：近5日／vs20／剛離零。"""
    bits: List[str] = []
    chg5 = row.get("chg5")
    vs20 = row.get("vs20")
    if chg5 is not None:
        try:
            bits.append(f"近5日{float(chg5):+.1f}%")
        except (TypeError, ValueError):
            pass
    if vs20 is not None:
        try:
            bits.append(f"距20高{float(vs20):+.1f}%")
        except (TypeError, ValueError):
            pass
    if row.get("leave_zero"):
        bits.append("剛脫離零")
    elif "還不能買" in str(row.get("action") or ""):
        bits.append("還在零")
    elif row.get("broke"):
        bits.append("近窗已攻")
    return "、".join(bits) if bits else "官方柱不足"


_FIELD_ADVICE_ASK = re.compile(
    r"(InP|光通訊|矽光子|CPO|FAU|ASIC|雙箭頭|"
    r"可買|該買|怎麼做|建議|哪些可以|哪些能)",
    re.I,
)


def is_field_advice_ask(ask: str) -> bool:
    """問類股／雙箭頭／怎麼做 → 走多檔建議圖；單檔名仍一張結構圖。"""
    q = (ask or "").strip()
    if not q:
        return True  # 空白進場＝主動建議
    # 純單一代號／單一股名優先走單檔結構圖
    if re.fullmatch(r"\d{3,6}[A-Za-z]?", q):
        return False
    if re.fullmatch(r"[\u4e00-\u9fffA-Za-z\-]+", q) and not _FIELD_ADVICE_ASK.search(q):
        # 「聯亞」「創意」這種單檔名
        return False
    return bool(_FIELD_ADVICE_ASK.search(q))


def action_advice_pack(db_path: str = "", ask: str = "") -> Dict[str, Any]:
    """建議怎麼做＋憑據。只認近窗還在講的族群；已退場（如無人機）不准推。"""
    q = (ask or "").strip()
    pack = advisor_pack(db_path, ask=q or "")
    near = near_spoken_text(db_path) if db_path else ""
    spoken = near or str(pack.get("spoken") or "")
    why_field = ""
    if "雙箭頭" in spoken or ("ASIC" in spoken and "InP" in spoken):
        why_field = "他近窗改口 ASIC＋光通訊(InP) 雙箭頭到過年前"
    elif "InP" in spoken or "光通訊" in spoken:
        why_field = "他近窗釘光通訊／InP 主流"
    else:
        why_field = "近窗還在講的主軸（活化）"
    # 問句可以收窄，但最終仍要近窗正文有講才展開
    ask_inp = (not q) or bool(
        re.search(r"(InP|光通訊|矽光子|CPO|FAU|聯亞|全新|IET|雙箭頭|怎麼做|建議)", q, re.I)
    )
    ask_asic = (not q) or bool(
        re.search(r"(ASIC|創意|聯發|雙箭頭|IC設計|怎麼做|建議)", q, re.I)
    )
    live_inp = any(k in spoken for k in ("InP", "光通訊", "矽光子", "CPO", "聯亞", "全新"))
    live_asic = any(k in spoken for k in ("ASIC", "創意", "聯發", "雙箭頭", "兩大最強"))
    want_inp = ask_inp and live_inp
    want_asic = ask_asic and live_asic
    rows: List[Dict[str, Any]] = []
    if want_inp:
        rows.extend(pack.get("inp_rows") or [])
    if want_asic:
        rows.extend(pack.get("asic_rows") or [])
    # 去重＋封鎖已退場檔（無人機中光電／雷虎等）
    seen: Dict[str, Dict[str, Any]] = {}
    for r in rows:
        sid = str(r.get("sid") or "")
        if not sid or sid in seen:
            continue
        if advice_sid_blocked(db_path, sid):
            continue
        seen[sid] = r
    ordered = list(seen.values())
    do_now: List[Dict[str, Any]] = []
    wait: List[Dict[str, Any]] = []
    skip: List[Dict[str, Any]] = []
    for r in ordered:
        act = str(r.get("action") or "")
        item = {
            **r,
            "evidence": _evidence_bit(r),
            "basis": why_field,
        }
        if r.get("leave_zero") or act.startswith("可買（"):
            item["do"] = "可接"
            item["how"] = "剛脫離零可接；昨收附近接，半山腰不追。"
            do_now.append(item)
        elif "還不能買" in act or "位階仍低" in act or "等回測" in act:
            item["do"] = "等回測再接"
            item["how"] = "方向對、切入未到；等回測／整理末端或剛離零再接。"
            wait.append(item)
        elif "偏晚" in act or "偏熱" in act:
            item["do"] = "偏熱先不追"
            item["how"] = "已攻／贴近前高，追價差；量縮回測再說。"
            skip.append(item)
        else:
            item["do"] = "等回測再接"
            item["how"] = "族群對得上，等官方柱把切入條件走清楚。"
            wait.append(item)
    lines: List[str] = []
    if do_now:
        bits = [
            f"{r.get('name')}可接（憑：{r['basis']}；官方{r['evidence']}）"
            for r in do_now
        ]
        lines.append("建議怎麼做｜" + "；".join(bits))
    if wait:
        bits = [
            f"{r.get('name')}等回測再接（憑：{r['basis']}；官方{r['evidence']}）"
            for r in wait
        ]
        lines.append("建議怎麼做｜" + "；".join(bits))
    if skip:
        bits = [
            f"{r.get('name')}偏熱先不追（憑：官方{r['evidence']}）"
            for r in skip
        ]
        lines.append("建議怎麼做｜" + "；".join(bits))
    if not lines and pack.get("ok"):
        lines.append(
            "建議怎麼做｜近窗雙箭頭方向在，但官方柱還沒排出可接檔；"
            "先跟節奏巢，等剛脫離零／回測再動。"
        )
    return {
        "ok": bool(lines),
        "lines": lines,
        "do_now": do_now,
        "wait": wait,
        "skip": skip,
        "basis": why_field,
    }


def format_action_advice_html(
    db_path: str = "", ask: str = "", *, limit: int = 4
) -> str:
    """建議怎麼做＋憑據（空白或問類股）。"""
    pack = action_advice_pack(db_path, ask=ask)
    if not pack.get("ok"):
        return ""
    blocks = ["<b>建議怎麼做</b>"]
    for line in (pack.get("lines") or [])[: max(1, int(limit))]:
        t = str(line).replace("不是買訊", "").replace("非買訊", "").strip()
        if t:
            blocks.append(html_escape(t))
    return "\n".join(blocks)


def advice_chart_targets(
    db_path: str = "",
    ask: str = "",
    *,
    n_do: int = 0,
    n_wait: int = 0,
    n_skip: int = 0,
) -> List[Dict[str, Any]]:
    """類股／空白進場附結構圖：名冊該給的都給（可接／等回測／偏熱），每檔帶怎麼做。

    n_*=0 表示不截斷；若呼叫端硬設上限才截。
    """
    pack = action_advice_pack(db_path, ask=ask)
    out: List[Dict[str, Any]] = []
    buckets = (
        (pack.get("do_now") or [], int(n_do)),
        (pack.get("wait") or [], int(n_wait)),
        (pack.get("skip") or [], int(n_skip)),
    )
    seen: set = set()
    for rows, lim in buckets:
        take = rows if lim <= 0 else rows[:lim]
        for r in take:
            sid = str(r.get("sid") or "")
            if not sid or sid in seen:
                continue
            seen.add(sid)
            out.append(
                {
                    "sid": sid,
                    "name": str(r.get("name") or sid),
                    "do": str(r.get("do") or ""),
                    "how": str(r.get("how") or ""),
                    "evidence": str(r.get("evidence") or ""),
                    "basis": str(r.get("basis") or ""),
                }
            )
    return out


# 公開別名：給 week_link／洞燭餵句用（避免他模組 import 底線私函）
dual_arrow_why = _dual_arrow_why
wave_why = _wave_why
inp_asic_tiers = _inp_asic_tiers
