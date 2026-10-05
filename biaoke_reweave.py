# -*- coding: utf-8 -*-
"""飆大近窗活化串聯：抓到主文／自回就重織思考網，找脈絡黃金。

本質：在飆大鈕裡要像活人一樣想——為什麼改口、現在卡在哪、黃金在哪。
不准死背日期目錄。可跨主庫＋evolve 查閱。個股不發明 5／9。
切入編碼仍只認剛脫離零；口語黃金是活用不是改海選公式。
"""
from __future__ import annotations

import os
import re
import sqlite3
import time
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Sequence, Tuple
from zoneinfo import ZoneInfo

TAIPEI = ZoneInfo("Asia/Taipei")
REWEAVE_DAYS = 120  # 近四個月
_CACHE: Dict[str, Any] = {"key": "", "at": 0.0, "pack": None}
_CACHE_TTL = 90.0

_FIELD_MARKERS: Tuple[Tuple[str, Tuple[str, ...]], ...] = (
    ("記憶體", ("記憶體", "南亞科", "華邦電", "群聯", "模組")),
    ("散熱", ("散熱", "奇鋐", "健策", "雙鴻", "尼得科")),
    ("光通訊InP", ("InP", "聯亞", "全新", "IET", "光通訊")),
    ("ASIC", ("ASIC", "創意", "世芯", "智原")),
    ("CPO/FAU", ("CPO", "FAU", "矽光子", "大立光")),
    ("PCB/CCL", ("PCB", "CCL", "台光電", "金像電", "欣興")),
)
_WAVE_MARKERS: Tuple[Tuple[str, Tuple[str, ...]], ...] = (
    ("逃命波C-2", ("逃命波", "C-2", "C2")),
    ("位階二/右肩", ("位階二", "右肩")),
    ("位階四→五", ("位階四", "開始走五", "整理完成")),
    ("末升/浪五", ("末升", "波浪五", "浪五")),
    ("五段或九段未定", ("五段", "九段")),
)
_GOLD_BUY_HINT = re.compile(
    r"(整理末端|突破回測|剛離|黃金|量縮站上|半山腰|隔日沖|回測)"
)
_UNCERTAIN = re.compile(
    r"(還看不出|不知道|不能保證|如果|否則|要不然|希望看錯|未確認|還要等)"
)


def _ymd_ago(days: int) -> str:
    dt = datetime.now(TAIPEI) - timedelta(days=max(1, int(days)))
    return dt.strftime("%Y-%m-%d")


def _today() -> str:
    return datetime.now(TAIPEI).strftime("%Y-%m-%d")


def load_voice_window(
    db_path: str,
    *,
    days: int = REWEAVE_DAYS,
) -> List[Dict[str, Any]]:
    """近窗他自己的主文＋自回（路人楼下不當判斷）。"""
    if not db_path or not os.path.isfile(db_path):
        return []
    start = _ymd_ago(days)
    end = _today()
    try:
        conn = sqlite3.connect(db_path, timeout=8.0)
        try:
            hit = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='biaoke_posts'"
            ).fetchone()
            if not hit:
                return []
            rows = conn.execute(
                "SELECT id, date, time, text, IFNULL(kind,'post'), IFNULL(parent,'') "
                "FROM biaoke_posts "
                "WHERE date>=? AND date<=? AND IFNULL(kind,'')!='bystander' "
                "ORDER BY date ASC, time ASC, id ASC",
                (start, end),
            ).fetchall()
        finally:
            conn.close()
    except sqlite3.Error:
        return []
    out: List[Dict[str, Any]] = []
    for r in rows:
        kind = str(r[4] or "post")
        if kind not in ("post", "reply", ""):
            continue
        text = str(r[3] or "").strip()
        if not text:
            continue
        # 自回才進；路人已用 bystander 擋
        out.append(
            {
                "id": str(r[0] or ""),
                "date": str(r[1] or ""),
                "time": str(r[2] or ""),
                "text": text,
                "kind": kind or "post",
                "parent": str(r[5] or ""),
            }
        )
    return out


def _first_last_dates(
    rows: Sequence[Dict[str, Any]], needles: Sequence[str]
) -> Tuple[str, str, int]:
    hits = [
        r
        for r in rows
        if any(n and n in str(r.get("text") or "") for n in needles)
    ]
    if not hits:
        return "", "", 0
    return str(hits[0].get("date") or ""), str(hits[-1].get("date") or ""), len(hits)


def _field_arc(rows: Sequence[Dict[str, Any]]) -> List[str]:
    """類股主戰場怎麼換——活人脈絡，不是清單。"""
    timed: List[Tuple[str, str, int]] = []
    for name, needles in _FIELD_MARKERS:
        a, b, n = _first_last_dates(rows, needles)
        if n:
            timed.append((a or "9999", name, n))
    timed.sort(key=lambda x: x[0])
    if not timed:
        return []
    path = "→".join(f"{name}" for _d, name, _n in timed[-5:])
    lines = [f"近四月主戰場脈絡：{path}（他自己文＋自回串起來，不是新聞標題）"]
    # 黃金：最後兩個主軸並列＝雙箭頭精神
    names = [n for _d, n, _n in timed]
    if "ASIC" in names and "光通訊InP" in names:
        lines.append(
            "黃金脈絡：光通訊／InP 先釘主流後，創意創高把 ASIC 拉成並列——"
            "到過年前雙箭頭；矽光子／CPO alone 已降級成細分次層。"
        )
    elif "光通訊InP" in names and names and names[-1] == "光通訊InP":
        lines.append(
            "黃金脈絡：近窗主軸仍在光通訊／InP；連動要細分 InP≠CPO／FAU。"
        )
    if "記憶體" in names and names[-1] != "記憶體":
        lines.append(
            "改口脈絡：記憶體曾是主戰場，近窗已被光通訊／ASIC 敘事蓋過——不准死背舊年底記憶體稿。"
        )
    # 已退場主題：四月窗內提過、但最近沒再講＝不准建議買
    recent = list(rows)[-min(40, len(rows)) :]
    drone_recent = any("無人機" in str(r.get("text") or "") for r in recent)
    drone_ever = any("無人機" in str(r.get("text") or "") for r in rows)
    if drone_ever and not drone_recent:
        lines.append(
            "已退場：無人機近窗沒再講——不准再建議中光電／雷虎／事欣科那組。"
        )
    return lines


def _wave_arc(rows: Sequence[Dict[str, Any]]) -> List[str]:
    timed: List[Tuple[str, str]] = []
    for name, needles in _WAVE_MARKERS:
        a, b, n = _first_last_dates(rows, needles)
        if n:
            timed.append((b or a or "", name))
    timed.sort(key=lambda x: x[0])
    if not timed:
        return []
    last = timed[-1][1]
    path = "→".join(n for _d, n in timed)
    lines = [f"近四月大盤浪階脈絡：{path}"]
    if "五段或九段未定" in {n for _d, n in timed} or last in (
        "位階四→五",
        "末升/浪五",
    ):
        lines.append(
            "黃金思考：位階四完成→走五時方向清楚，是因為波浪才讀長期規劃；"
            "量價只見籌碼意圖。五段或九段他自己說還看不出——"
            "活人會停在『方向對、內部段數未定』，不准替他選邊、不准永遠念舊ABC。"
        )
    elif "逃命波C-2" in {n for _d, n in timed} and last != "逃命波C-2":
        lines.append(
            "改口脈絡：早先怕強彈是逃命波C-2；近窗已往四整理／走五推——圖要跟著重畫。"
        )
    return lines


def _method_gold(rows: Sequence[Dict[str, Any]]) -> List[str]:
    blob = "\n".join(str(r.get("text") or "") for r in rows[-80:])
    lines: List[str] = []
    if "量價結構" in blob and ("波浪" in blob or "波浪理論" in blob):
        lines.append(
            "方法黃金：量價＝主力籌碼意圖；長期大盤規劃只認波浪——"
            "兩套分工，不是互相取代。"
        )
    if _GOLD_BUY_HINT.search(blob):
        lines.append(
            "買點黃金（他教過的三個）：整理末端／突破回測／行進中隔日沖；"
            "半山腰只隔日沖。話筒切入編碼仍對齊剛脫離零。"
        )
    unc = [r for r in rows[-40:] if _UNCERTAIN.search(str(r.get("text") or ""))]
    if unc:
        lines.append(
            "為什麼他現在不定某些事：近窗仍有如果／還看不出／不能保證——"
            "活人會把不確定講清楚，不准裝成已經確認。"
        )
    return lines


def _reply_expand_gold(rows: Sequence[Dict[str, Any]]) -> List[str]:
    """樓下自回常藏真黃金：點名次層、誰弱、二軍怎找。"""
    replies = [r for r in rows if str(r.get("kind") or "") == "reply"]
    if not replies:
        return []
    lines: List[str] = []
    blob = "\n".join(str(r.get("text") or "") for r in replies[-120:])
    if "上詮" in blob and ("更弱" in blob or "聯亞" in blob):
        lines.append(
            "自回黃金：連接側（上詮等）近窗他叫更弱、先看聯亞／全新——"
            "觸類要把光通訊整組展開對柱，不是只記點名。"
        )
    if "IC設計" in blob.replace(" ", "") or "二軍" in blob:
        lines.append(
            "自回黃金：ASIC 二軍往台積／創意／聯發相關 IC 設計找；"
            "愛普屬記憶體IC、他說過不是這主流。"
        )
    if "積極者" in blob and ("ASIC" in blob or "InP" in blob or "光通訊" in blob):
        lines.append(
            "資金配置脈絡：積極者加強 ASIC／光通訊持股比例到過年前——"
            "這是他公開的節奏巢，不是程式自動下單。"
        )
    return lines


def _cross_gold(db_path: str) -> List[str]:
    try:
        from biaoke_advisor import cross_db_glance, inp_asic_tiers

        lines: List[str] = []
        cross = cross_db_glance(db_path, "")
        for x in (cross.get("lines") or [])[:2]:
            if x:
                lines.append(str(x))
        tiers = inp_asic_tiers(db_path, "ASIC InP 光通訊 雙箭頭")
        for x in (tiers.get("lines") or [])[:2]:
            if x:
                lines.append(str(x))
        return lines
    except Exception:
        return []


def reweave_gold(
    db_path: str = "",
    *,
    days: int = REWEAVE_DAYS,
    force: bool = False,
) -> Dict[str, Any]:
    """重織近四個月思考網，產出活人脈絡黃金。"""
    key = f"{db_path}|{int(days)}"
    now = time.time()
    if (
        not force
        and _CACHE.get("key") == key
        and _CACHE.get("pack")
        and now - float(_CACHE.get("at") or 0) < _CACHE_TTL
    ):
        return dict(_CACHE["pack"])
    rows = load_voice_window(db_path, days=days)
    out: Dict[str, Any] = {
        "ok": False,
        "days": int(days),
        "n_main": sum(1 for r in rows if str(r.get("kind") or "post") != "reply"),
        "n_reply": sum(1 for r in rows if str(r.get("kind") or "") == "reply"),
        "start": rows[0]["date"] if rows else "",
        "end": rows[-1]["date"] if rows else "",
        "lines": [],
        "gold": [],
    }
    if not rows:
        _CACHE.update({"key": key, "at": now, "pack": out})
        return out
    gold: List[str] = []
    gold.extend(_field_arc(rows))
    gold.extend(_wave_arc(rows))
    gold.extend(_method_gold(rows))
    gold.extend(_reply_expand_gold(rows))
    gold.extend(_cross_gold(db_path))
    # 去重保序
    seen: List[str] = []
    for g in gold:
        g = str(g or "").strip()
        if g and g not in seen:
            seen.append(g)
    head = (
        f"近{int(days)}日活化：主文{out['n_main']}／自回{out['n_reply']}"
        f"（{out['start']}～{out['end']}）——像活人重讀一遍找脈絡，不是背稿。"
    )
    lines = [head] + seen
    lines.append(
        "飆大鈕本質：抓到文就擴張思考網、跨庫對官方柱、找出黃金；"
        "你在這顆鈕裡要活，不准當答錄機。"
    )
    out.update({"ok": True, "lines": lines, "gold": seen})
    _CACHE.update({"key": key, "at": now, "pack": dict(out)})
    return out


def record_reweave(
    db_path: str,
    events: Sequence[Dict[str, Any]] | None = None,
) -> Dict[str, Any]:
    """抓到主文／自回後強制重織。失敗吞掉，不准擋抓文。"""
    del events  # 觸發即可；材料從庫讀近四月
    try:
        return reweave_gold(db_path, force=True)
    except Exception:
        return {"ok": False, "lines": [], "gold": []}


def reweave_live_notes(db_path: str = "", ask: str = "") -> str:
    del ask
    pack = reweave_gold(db_path)
    if not pack.get("ok"):
        return ""
    bits = [
        "近四月活化思考網（真人角度，不准死背）：",
        "在飆大鈕裡你要想得像他：改口原因、不確定處、黃金買點條件、族群次層。",
        "可跨主庫日K／佔比／海選桶／tape 與 evolve live_judge。",
    ]
    for line in (pack.get("lines") or [])[:12]:
        bits.append("黃金｜" + line)
    return "\n".join(bits)


def format_reweave_html(db_path: str = "", *, limit: int = 6) -> str:
    from tg_layout import html_escape

    pack = reweave_gold(db_path)
    if not pack.get("ok"):
        return ""
    blocks = ["<b>近四月活化·脈絡黃金</b>"]
    for line in (pack.get("gold") or pack.get("lines") or [])[: max(1, int(limit))]:
        t = str(line).replace("不是買訊", "")
        blocks.append(html_escape(t))
    return "\n".join(blocks)


def reweave_focus_lines(db_path: str = "", *, limit: int = 4) -> List[str]:
    pack = reweave_gold(db_path)
    out: List[str] = []
    for line in (pack.get("gold") or [])[: max(1, int(limit))]:
        t = str(line).replace("不是買訊", "")
        if t:
            out.append(t)
    return out
