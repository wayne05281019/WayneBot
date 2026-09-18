# -*- coding: utf-8 -*-
"""他教過怎麼找還沒點名的族群：洞燭先機＋次族群第一名誰先過前高＋從底部找落後。

只對官方日 K。盤中未收不當官方收。不是買訊、不進海選。
"""
from __future__ import annotations

import re
import sqlite3
from typing import Any, Dict, List, Optional, Sequence, Tuple

WANT_ASK = re.compile(
    r"(新族群|蠢蠢欲動|怎麼找|根據我的指引|找族群|還沒點名|底部蠢蠢|指引去找)"
)

# 只准他公開教過、有點過第一名的次族群。不准掃全市場發明一族。
_GROUPS: Tuple[Dict[str, Any], ...] = (
    {
        "key": "asic",
        "field": "ASIC",
        "names": ("ASIC", "創意", "世芯", "智原"),
        "leaders": (("3443", "創意"), ("3661", "世芯-KY"), ("3035", "智原")),
    },
    {
        "key": "cool",
        "field": "散熱",
        "names": ("散熱", "健策", "奇鋐"),
        "leaders": (("3653", "健策"), ("3017", "奇鋐")),
    },
    {
        "key": "inp",
        "field": "光通訊 InP",
        "names": ("光通訊", "InP", "聯亞", "全新", "穩懋"),
        "leaders": (("3081", "聯亞"), ("2455", "全新"), ("3105", "穩懋")),
    },
    {
        "key": "mem",
        "field": "記憶體",
        "names": ("記憶體", "南亞科"),
        "leaders": (("2408", "南亞科"),),
    },
    {
        "key": "pcb",
        "field": "PCB",
        "names": ("PCB", "台光電", "CCL"),
        "leaders": (("2383", "台光電"),),
    },
    {
        "key": "abf",
        "field": "ABF",
        "names": ("ABF", "欣興", "南電"),
        "leaders": (("3037", "欣興"),),
    },
    {
        "key": "pass",
        "field": "被動元件",
        "names": ("被動元件", "被動", "國巨"),
        "leaders": (("2327", "國巨"),),
    },
    {
        "key": "test",
        "field": "高階測試／封測",
        "names": ("高階測試", "封測", "穎崴", "旺矽", "汎銓"),
        "leaders": (("6515", "穎崴"), ("6223", "旺矽")),
        "laggards": (
            ("6257", "矽格"),
            ("3264", "欣銓"),
            ("2449", "京元電子"),
            ("2441", "超豐"),
            ("6830", "汎銓"),
        ),
    },
)


def want_field_scan(ask: str) -> bool:
    return bool(WANT_ASK.search(str(ask or "")))


def _cap(db_path: str) -> str:
    try:
        from import_health import latest_complete_quote_date

        return str(latest_complete_quote_date(db_path) or "").replace("-", "")[:8]
    except Exception:
        return ""


def _ymd(raw: Any) -> str:
    return str(raw or "").replace("-", "")[:8]


def _bars(db_path: str, sid: str, cap: str) -> List[Tuple[str, float, float, float, float]]:
    if not db_path or not sid:
        return []
    conn = sqlite3.connect(db_path, timeout=8.0)
    try:
        rows = conn.execute(
            "SELECT date, high, low, close, volume FROM daily_quotes "
            "WHERE stock_id=? ORDER BY REPLACE(CAST(date AS TEXT),'-','')",
            (sid,),
        ).fetchall()
    except sqlite3.Error:
        return []
    finally:
        conn.close()
    out: List[Tuple[str, float, float, float, float]] = []
    for d, h, l, c, v in rows:
        day = _ymd(d)
        if cap and day > cap:
            continue
        try:
            out.append((day, float(h), float(l), float(c), float(v or 0)))
        except (TypeError, ValueError):
            continue
    return out


def _stats(rows: Sequence[Tuple[str, float, float, float, float]]) -> Optional[Dict[str, Any]]:
    if len(rows) < 21:
        return None
    last = rows[-1]
    w20 = rows[-20:]
    w60 = rows[-60:] if len(rows) >= 60 else rows
    h20 = max(x[1] for x in w20)
    h60 = max(x[1] for x in w60)
    avg_v = sum(x[4] for x in w20) / 20.0
    prior = rows[-45:-5] if len(rows) >= 25 else rows[:-5]
    prior_h = max(x[1] for x in prior) if prior else h60
    last5_h = max(x[1] for x in rows[-5:])
    return {
        "date": last[0],
        "close": last[3],
        "vs20": (last[3] / h20 - 1.0) * 100.0 if h20 else 0.0,
        "vs60": (last[3] / h60 - 1.0) * 100.0 if h60 else 0.0,
        "volr": (last[4] / avg_v) if avg_v else 0.0,
        "broke": last5_h > prior_h,
    }


def _px(val: float) -> str:
    if abs(val - round(val)) < 1e-9:
        return str(int(round(val)))
    return f"{val:.2f}".rstrip("0").rstrip(".")


def _pct(val: float) -> str:
    if val > 0:
        return f"＋{val:.1f}%"
    if val < 0:
        return f"{val:.1f}%".replace("-", "−")
    return "0.0%"


def latest_spoken(db_path: str) -> str:
    if not db_path:
        return ""
    conn = sqlite3.connect(db_path, timeout=8.0)
    try:
        hit = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='biaoke_posts'"
        ).fetchone()
        if not hit:
            return ""
        row = conn.execute(
            "SELECT text FROM biaoke_posts "
            "WHERE IFNULL(kind,'post')!='reply' "
            "ORDER BY date DESC, time DESC, id DESC LIMIT 1"
        ).fetchone()
    except sqlite3.Error:
        return ""
    finally:
        conn.close()
    return str(row[0] or "") if row else ""


def _named_keys(spoken: str) -> set:
    blob = spoken or ""
    out = set()
    for g in _GROUPS:
        if any(n and n in blob for n in g["names"]):
            out.add(g["key"])
    if any(k in blob for k in ("轉弱", "減碼", "整理三個月")) and "pcb" in out:
        pass
    return out


def _stirring(st: Dict[str, Any]) -> bool:
    """底部蠢蠢：贴近 20 高、60 高仍明顯在上、量起來。不是已先過前高的主戰場。"""
    return (
        st["vs20"] >= -5.0
        and st["vs60"] <= -8.0
        and st["volr"] >= 1.5
        and not st["broke"]
    )


def scan_unnamed_field(db_path: str, *, ask: str = "", spoken: str = "") -> str:
    """回一句產業抽屜用的找法＋官方柱對質。對不上就寫還沒，不准猜。"""
    how = (
        "他教過怎麼找：①次族群還沒熱、很少人提；②次族群第一名誰先過前高，不比絕對漲跌；"
        "③高點整理的從底部找落後。不是猜新聞。"
    )
    if not db_path:
        return how + " 官方日 K 還沒這列，不准猜。不是買訊。"
    cap = _cap(db_path)
    if not cap:
        return how + " 官方完整日還沒，盤中未收不當官方收。不是買訊。"
    spoken = spoken or latest_spoken(db_path)
    named = _named_keys(spoken)
    hits: List[Tuple[float, Dict[str, Any], Dict[str, Any], Dict[str, Any]]] = []
    missing = 0
    for g in _GROUPS:
        if g["key"] in named:
            continue
        leaders = []
        for sid, name in g["leaders"]:
            st = _stats(_bars(db_path, sid, cap))
            if st:
                leaders.append((sid, name, st))
            else:
                missing += 1
        watch = list(g.get("laggards") or g["leaders"])
        for sid, name in watch:
            st = _stats(_bars(db_path, sid, cap))
            if not st:
                missing += 1
                continue
            if not _stirring(st):
                continue
            lead = leaders[0] if leaders else None
            if lead and lead[2].get("broke"):
                continue
            hits.append((float(st["volr"]), g, {"sid": sid, "name": name, **st}, lead))
    named_txt = "、".join(
        g["field"] for g in _GROUPS if g["key"] in named
    )
    if not hits:
        extra = " 已點名的 " + named_txt + " 不當新族群。" if named_txt else ""
        if missing:
            return (
                how
                + extra
                + f" 官方收 {cap} 還沒對上「還沒熱＋贴近20高＋量起來＋第一名還沒先過前高」的次族群，不准發明。不是買訊。"
            )
        return (
            how
            + extra
            + f" 官方收 {cap} 還沒對上底部蠢蠢的次族群，不准發明。不是買訊。"
        )
    hits.sort(key=lambda x: -x[0])
    _volr, g, st, lead = hits[0]
    lead_bit = ""
    if lead:
        lead_bit = (
            f"龍頭 {lead[1]} {lead[0]} 收 {_px(lead[2]['close'])}"
            f"{' 還沒先過前高' if not lead[2]['broke'] else ' 已先過前高'}。"
        )
    named_bit = ("已點名的 " + named_txt + " 不當新族群。") if named_txt else ""
    return (
        how
        + f" 官方收 {st['date']}：最像 {g['field']}，落後檔 {st['name']} {st['sid']}"
        f" 收 {_px(st['close'])} 距20高 {_pct(st['vs20'])} 距60高 {_pct(st['vs60'])}"
        f" 量比 {st['volr']:.2f}。{lead_bit}{named_bit}"
        "不是他當下點名。不是買訊。"
    )
