# -*- coding: utf-8 -*-
"""飆大近窗說法 → 官方柱對質 → 話筒可點／勿追名單。

不是買訊。不准改海選／黃金買點／leave_zero。
只認他自己主文＋自回；路人正文不當判斷。
他說勿追／不要介入 → 藍字連結拿掉；他說去找＋池內對得上 → 進下面可點名單並簡短註離峰／位階。
隨近窗與官方柱重算，不准寫死單次名單。
"""
from __future__ import annotations

import os
import re
import sqlite3
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

from tg_layout import html_escape

# 勿追／不要介入：截到句讀或「要去找」前，避免把後面找底句當勿追對象
_NO_CHASE = re.compile(
    r"(?:就是)?(?:空手)?(?:不要再介入|不要再進場|不要再追|不要追|"
    r"不要再碰|不要介入|不要再進)"
    r"(.{0,60}?)(?=，|。|；|;|！|!|要去找|去找|$)",
    re.I,
)
# 標配不賣／一股不賣／續抱：鄰近股名＝持股語意，不是新買訊
_HOLD = re.compile(
    r"([\u4e00-\u9fffA-Za-z\-KY]{2,12}).{0,12}?(?:標配(?:一股)?不賣|一股不賣|續抱|長抱)"
    r"|"
    r"(?:標配(?:一股)?不賣|一股不賣).{0,16}?([\u4e00-\u9fffA-Za-z\-KY]{2,12})",
    re.I,
)
# 去找低位階／底部／不在前波高
_FIND = re.compile(
    r"(?:要去找|去找|好好去研究).{0,100}?(?:低位階|還在底部|不在前波高點|底部的)"
    r"|"
    r"(?:低位階還在底部|不在前波高點的個股|不在前波高點)",
    re.I,
)
_POOL_INP = re.compile(r"\bInP\b|磷化銦|光通訊", re.I)

# 對質門檻（與 docs 三句對質一致；只排序／呈現，不是買訊分數）
_OFF_PEAK_PCT = -10.0  # 距峰 ≤ −10% 才算離高
_POS60_BOTTOM = 0.40
_POS120_BOTTOM = 0.50


def _ymd(raw: Any) -> str:
    t = str(raw or "").replace("-", "")[:8]
    return t if len(t) == 8 and t.isdigit() else ""


def _stock_anchor(sid: str, name: str, db_path: str = "") -> str:
    """奇摩藍字；失敗則純文字。避免跟 advisor 循環 import。"""
    sid = str(sid or "").strip()
    name = str(name or "").strip()
    label = f"{sid} {name}".strip() or sid
    try:
        from stock_links import yahoo_urls

        web, _m = yahoo_urls(sid, db_path or None)
        href = str(web or "").replace("&", "&amp;")
        if href:
            return f'<a href="{href}">{html_escape(label)}</a>'
    except Exception:
        pass
    return html_escape(label)


def _mentions_in(blob: str, db_path: str = "") -> List[Tuple[str, str]]:
    """正文片段 → (sid, name)；extract 後再補 InP／常見別名（全新等可能不在硬名單）。"""
    out: List[Tuple[str, str]] = []
    seen: Set[str] = set()
    try:
        from biaoke_link import extract_mentions

        for m in extract_mentions(blob, db_path=db_path or "") or []:
            sid = str(m.get("stock_id") or "").strip()
            name = str(m.get("stock_name") or sid).strip()
            if sid and sid not in seen:
                seen.add(sid)
                out.append((sid, name))
    except Exception:
        pass
    # 一律再掃池與別名：extract 缺全新／環宇時仍要認
    try:
        from biaoke_field_scan import _OPT_INP

        for sid, name in (_OPT_INP or {}).items():
            if sid in seen:
                continue
            if name and name in blob:
                seen.add(sid)
                out.append((sid, name))
                continue
            short = str(name or "").replace("-KY", "")
            if short and short in blob:
                seen.add(sid)
                out.append((sid, name))
    except Exception:
        pass
    aliases = (
        ("2455", "全新"),
        ("3105", "穩懋"),
        ("3081", "聯亞"),
        ("4971", "IET-KY"),
        ("4991", "環宇-KY"),
    )
    for sid, name in aliases:
        if sid in seen:
            continue
        key = name.replace("-KY", "")
        if name in blob or key in blob or (sid == "4971" and "IET" in blob):
            seen.add(sid)
            out.append((sid, name))
    return out


def parse_spoken_stances(text: str, *, db_path: str = "") -> Dict[str, Any]:
    """近窗正文 → 勿追／標配不賣／去找哪一池。"""
    blob = str(text or "")
    no_chase: Dict[str, str] = {}
    hold: Dict[str, str] = {}
    find_pools: List[str] = []
    if not blob.strip():
        return {
            "no_chase": no_chase,
            "hold": hold,
            "find_pools": find_pools,
            "raw": blob,
        }
    for m in _NO_CHASE.finditer(blob):
        chunk = str(m.group(1) or "")
        for sid, name in _mentions_in(chunk, db_path):
            no_chase[sid] = name
    for m in _HOLD.finditer(blob):
        chunk = str(m.group(1) or m.group(2) or "")
        # 整句再掃一次，避免「聯亞是標配」只吃到「是」
        span = blob[max(0, m.start() - 12) : m.end() + 12]
        for sid, name in _mentions_in(span or chunk, db_path):
            if sid in no_chase:
                continue
            hold[sid] = name
    if _FIND.search(blob):
        if _POOL_INP.search(blob):
            find_pools.append("inp")
        # 沒點池名但「去找…InP」已含；光通句也走 InP 池（對齊他這句）
        if not find_pools and re.search(r"個股|底部|低位階", blob):
            if _POOL_INP.search(blob):
                find_pools.append("inp")
    return {
        "no_chase": no_chase,
        "hold": hold,
        "find_pools": find_pools,
        "raw": blob,
    }


def _latest_bar(
    conn: sqlite3.Connection, sid: str
) -> Optional[Tuple[str, float, float, float, float]]:
    try:
        row = conn.execute(
            "SELECT date, open, high, low, close FROM daily_quotes "
            "WHERE stock_id=? ORDER BY REPLACE(CAST(date AS TEXT),'-','') DESC "
            "LIMIT 1",
            (str(sid),),
        ).fetchone()
    except sqlite3.Error:
        return None
    if not row:
        return None
    day = _ymd(row[0])
    try:
        o, h, lo, c = float(row[1]), float(row[2]), float(row[3]), float(row[4])
    except (TypeError, ValueError):
        return None
    if not day or c <= 0:
        return None
    return day, o, h, lo, c


def _ytd_peak(
    conn: sqlite3.Connection, sid: str, as_of: str
) -> Tuple[Optional[float], str]:
    y = str(as_of)[:4]
    if len(y) != 4:
        return None, ""
    start = f"{y}0101"
    try:
        row = conn.execute(
            "SELECT high, date FROM daily_quotes WHERE stock_id=? "
            "AND REPLACE(CAST(date AS TEXT),'-','')>=? "
            "AND REPLACE(CAST(date AS TEXT),'-','')<=? "
            "ORDER BY high DESC, REPLACE(CAST(date AS TEXT),'-','') DESC LIMIT 1",
            (str(sid), start, str(as_of)),
        ).fetchone()
    except sqlite3.Error:
        return None, ""
    if not row:
        return None, ""
    try:
        return float(row[0]), _ymd(row[1])
    except (TypeError, ValueError):
        return None, ""


def _range_pos(
    conn: sqlite3.Connection, sid: str, as_of: str, n: int
) -> Optional[float]:
    try:
        rows = conn.execute(
            "SELECT high, low, close FROM daily_quotes WHERE stock_id=? "
            "AND REPLACE(CAST(date AS TEXT),'-','')<=? "
            "ORDER BY REPLACE(CAST(date AS TEXT),'-','') DESC LIMIT ?",
            (str(sid), str(as_of), int(n)),
        ).fetchall()
    except sqlite3.Error:
        return None
    if not rows:
        return None
    try:
        close = float(rows[0][2])
        hi = max(float(r[0]) for r in rows if r[0] is not None)
        lo = min(float(r[1]) for r in rows if r[1] is not None)
    except (TypeError, ValueError):
        return None
    if hi <= lo or close <= 0:
        return None
    return (close - lo) / (hi - lo)


def bar_position_metrics(db_path: str, sid: str) -> Dict[str, Any]:
    """官方柱：距 當年峰％、pos60／pos120。缺柱＝空欄。"""
    empty = {
        "sid": str(sid),
        "as_of": "",
        "close": None,
        "peak": None,
        "peak_date": "",
        "peak_pct": None,
        "pos60": None,
        "pos120": None,
    }
    if not db_path or not os.path.isfile(db_path) or not sid:
        return empty
    conn = sqlite3.connect(db_path, timeout=8.0)
    try:
        bar = _latest_bar(conn, sid)
        if not bar:
            return empty
        as_of, _o, _h, _lo, close = bar
        peak, peak_day = _ytd_peak(conn, sid, as_of)
        peak_pct = None
        if peak and peak > 0:
            peak_pct = (close / peak - 1.0) * 100.0
        return {
            "sid": str(sid),
            "as_of": as_of,
            "close": close,
            "peak": peak,
            "peak_date": peak_day,
            "peak_pct": peak_pct,
            "pos60": _range_pos(conn, sid, as_of, 60),
            "pos120": _range_pos(conn, sid, as_of, 120),
        }
    finally:
        conn.close()


def _composite(peak_pct: Optional[float], pos60: Optional[float], pos120: Optional[float]) -> float:
    """離高＋偏底綜合分（高＝較符合「去找低位階／離高」）。"""
    if peak_pct is None:
        return -1.0
    # −50% → 1.0；0% → 0
    off = max(0.0, min(1.0, (-float(peak_pct)) / 50.0))
    p60 = float(pos60) if pos60 is not None else 0.5
    p120 = float(pos120) if pos120 is not None else 0.5
    return 0.45 * off + 0.35 * (1.0 - p60) + 0.20 * (1.0 - p120)


def _strict_dual(
    peak_pct: Optional[float], pos60: Optional[float], pos120: Optional[float]
) -> bool:
    if peak_pct is None or pos60 is None or pos120 is None:
        return False
    return (
        float(peak_pct) <= _OFF_PEAK_PCT
        and float(pos60) <= _POS60_BOTTOM
        and float(pos120) <= _POS120_BOTTOM
    )


def _pool_members(pool: str) -> List[Tuple[str, str]]:
    try:
        from biaoke_field_scan import _OPT_INP

        if pool == "inp":
            return list((_OPT_INP or {}).items())
    except Exception:
        pass
    if pool == "inp":
        return [
            ("3081", "聯亞"),
            ("4971", "IET-KY"),
            ("2455", "全新"),
            ("4991", "環宇-KY"),
            ("3105", "穩懋"),
        ]
    return []


def rank_find_matches(
    db_path: str,
    pools: Sequence[str],
    *,
    exclude: Optional[Set[str]] = None,
    limit: int = 3,
) -> List[Dict[str, Any]]:
    """池內官方柱排序：離高最深優先；勿追檔不進可點對質名單。"""
    ban = {str(x) for x in (exclude or set())}
    ranked: List[Dict[str, Any]] = []
    seen: Set[str] = set()
    for pool in pools:
        for sid, name in _pool_members(str(pool)):
            if sid in ban or sid in seen:
                continue
            m = bar_position_metrics(db_path, sid)
            pct = m.get("peak_pct")
            if pct is None:
                continue
            # 至少離高才進「去找」可點；近高的不掛下面當可追
            if float(pct) > _OFF_PEAK_PCT:
                continue
            score = _composite(pct, m.get("pos60"), m.get("pos120"))
            dual = _strict_dual(pct, m.get("pos60"), m.get("pos120"))
            why_bits = [f"距峰 {float(pct):+.1f}%"]
            if m.get("pos120") is not None:
                why_bits.append(f"pos120 {float(m['pos120']):.2f}")
            if m.get("pos60") is not None:
                why_bits.append(f"pos60 {float(m['pos60']):.2f}")
            if dual:
                why_bits.append("嚴格雙符")
            else:
                why_bits.append("離高較深")
            ranked.append(
                {
                    "sid": sid,
                    "name": name,
                    "pool": pool,
                    "score": score,
                    "strict_dual": dual,
                    "why": "、".join(why_bits),
                    "peak_pct": pct,
                    "pos60": m.get("pos60"),
                    "pos120": m.get("pos120"),
                    "close": m.get("close"),
                    "as_of": m.get("as_of") or "",
                    "role": "find_match",
                }
            )
            seen.add(sid)
    ranked.sort(key=lambda r: (-float(r.get("score") or 0), float(r.get("peak_pct") or 0)))
    return ranked[: max(0, int(limit))]


def _near_blob(db_path: str, *, days: int = 14) -> str:
    """近窗他自己正文；優先 week_spoken，失敗再直讀 posts。"""
    if not db_path or not os.path.isfile(db_path):
        return ""
    try:
        from biaoke_advisor import near_spoken_text

        blob = near_spoken_text(db_path, days=days) or ""
        if blob.strip():
            return blob
    except Exception:
        pass
    try:
        from datetime import datetime, timedelta
        from zoneinfo import ZoneInfo

        tp = ZoneInfo("Asia/Taipei")
        end = datetime.now(tp).strftime("%Y-%m-%d")
        start = (datetime.now(tp) - timedelta(days=max(1, int(days) - 1))).strftime(
            "%Y-%m-%d"
        )
        conn = sqlite3.connect(db_path, timeout=8.0)
        try:
            rows = conn.execute(
                "SELECT text FROM biaoke_posts "
                "WHERE date>=? AND date<=? "
                "AND IFNULL(kind,'post')!='bystander' "
                "ORDER BY date DESC, time DESC, id DESC LIMIT 40",
                (start, end),
            ).fetchall()
        finally:
            conn.close()
        return "\n".join(str(r[0] or "") for r in rows if r and r[0])
    except Exception:
        return ""


def live_match_pack(db_path: str = "", *, spoken: str = "") -> Dict[str, Any]:
    """近窗說法＋官方柱 → 勿追／標配／對質符合。"""
    text = str(spoken or "") or _near_blob(db_path)
    st = parse_spoken_stances(text, db_path=db_path or "")
    no_chase = dict(st.get("no_chase") or {})
    hold = dict(st.get("hold") or {})
    pools = list(st.get("find_pools") or [])
    # 勿追＋標配不賣都不進「去找」可點對質（標配是續抱語意，不是新找底部）
    ban = set(no_chase.keys()) | set(hold.keys())
    matches = (
        rank_find_matches(db_path, pools, exclude=ban, limit=3)
        if pools and db_path
        else []
    )
    # 標配不賣：語意註記，仍可點（不是新買訊）
    hold_rows = [
        {"sid": sid, "name": name, "role": "hold", "why": "標配不賣"}
        for sid, name in hold.items()
    ]
    no_rows = [
        {"sid": sid, "name": name, "role": "no_chase", "why": "勿追"}
        for sid, name in no_chase.items()
    ]
    as_of = ""
    for r in matches:
        if r.get("as_of"):
            as_of = str(r["as_of"])
            break
    return {
        "ok": bool(no_rows or hold_rows or matches),
        "spoken": text,
        "no_chase": no_chase,
        "hold": hold,
        "find_pools": pools,
        "no_chase_rows": no_rows,
        "hold_rows": hold_rows,
        "matches": matches,
        "as_of": as_of,
    }


def no_chase_sids(pack: Optional[Dict[str, Any]]) -> Set[str]:
    return {str(s) for s in ((pack or {}).get("no_chase") or {}).keys() if s}


def hold_notes(pack: Optional[Dict[str, Any]]) -> Dict[str, str]:
    out: Dict[str, str] = {}
    for sid, name in ((pack or {}).get("hold") or {}).items():
        out[str(sid)] = "標配不賣"
    return out


def match_notes(pack: Optional[Dict[str, Any]]) -> Dict[str, str]:
    out: Dict[str, str] = {}
    for r in (pack or {}).get("matches") or []:
        sid = str(r.get("sid") or "")
        why = str(r.get("why") or "").strip()
        if sid and why:
            out[sid] = why
    return out


def stance_focus_lines(pack: Optional[Dict[str, Any]]) -> List[str]:
    """插進口語重點：為何上／為何降調／為何標配。不是買訊。"""
    pack = pack or {}
    lines: List[str] = []
    matches = list(pack.get("matches") or [])
    no_rows = list(pack.get("no_chase_rows") or [])
    hold_rows = list(pack.get("hold_rows") or [])
    if matches:
        bits = [
            f"{r.get('name')}（{r.get('why')}）"
            for r in matches
            if r.get("name") and r.get("why")
        ]
        if bits:
            lines.append(
                "對質上　"
                + "、".join(bits)
                + "　對他「去找低位階／離高」；不是買訊"
            )
    if no_rows:
        names = "、".join(str(r.get("name") or "") for r in no_rows if r.get("name"))
        if names:
            lines.append(
                f"位階降調　{names}　他提過、近窗說空手勿追／位階偏高；"
                "不是看空整族，只拿掉可點追連結"
            )
    if hold_rows:
        names = "、".join(str(r.get("name") or "") for r in hold_rows if r.get("name"))
        if names:
            lines.append(f"標配續抱　{names}　他說標配不賣；不是新買訊")
    return lines


def format_live_match_html(db_path: str = "", *, spoken: str = "") -> str:
    """話筒區塊：對質符合可點＋勿追降調說明。不准整族砍光。不是買訊。"""
    pack = live_match_pack(db_path, spoken=spoken)
    if not pack.get("ok"):
        return ""
    blocks: List[str] = []
    matches = list(pack.get("matches") or [])
    no_rows = list(pack.get("no_chase_rows") or [])
    hold_rows = list(pack.get("hold_rows") or [])
    if matches or no_rows or hold_rows:
        blocks.append("<b>對質符合</b>")
    if matches:
        bits: List[str] = []
        for r in matches:
            sid = str(r.get("sid") or "")
            name = str(r.get("name") or sid)
            why = str(r.get("why") or "")
            bits.append(
                f"{_stock_anchor(sid, name, db_path)}（{html_escape(why)}）"
                if why
                else _stock_anchor(sid, name, db_path)
            )
        blocks.append("、".join(bits))
    if hold_rows:
        bits = []
        for r in hold_rows:
            sid = str(r.get("sid") or "")
            name = str(r.get("name") or sid)
            bits.append(
                f"{_stock_anchor(sid, name, db_path)}（{html_escape('標配不賣')}）"
            )
        if bits:
            blocks.append("、".join(bits))
    if no_rows:
        # 保留「他提過、位階偏高」一句；不掛藍字可點，也不砍整族
        plain = "、".join(
            html_escape(f"{r.get('name')}") for r in no_rows if r.get("name")
        )
        if plain:
            blocks.append(
                plain
                + html_escape("　他提過、現在位階偏高／空手勿追；不掛可點追連結。")
            )
    if matches or no_rows or hold_rows:
        as_of = str(pack.get("as_of") or "")
        tail = "跟近窗說法＋官方柱重算；不是買訊，不准當進場，也不看空整族。"
        if as_of and len(as_of) == 8:
            tail = f"as-of {as_of[:4]}-{as_of[4:6]}-{as_of[6:8]}。" + tail
        blocks.append(html_escape(tail))
    return "\n".join(blocks)


_LIVE_MATCH_DDL = """
CREATE TABLE IF NOT EXISTS biaoke_live_match (
    key TEXT PRIMARY KEY,
    as_of TEXT NOT NULL DEFAULT '',
    payload TEXT NOT NULL DEFAULT '',
    updated_at TEXT NOT NULL DEFAULT ''
);
"""


def ensure_live_match_table(db_path: str) -> None:
    if not db_path:
        return
    parent = os.path.dirname(os.path.abspath(db_path))
    if parent:
        os.makedirs(parent, exist_ok=True)
    conn = sqlite3.connect(db_path, timeout=15.0)
    try:
        conn.execute(_LIVE_MATCH_DDL)
        conn.commit()
    finally:
        conn.close()


def refresh_live_match(db_path: str, *, spoken: str = "") -> Dict[str, Any]:
    """ingest／融合後預設重算並落檔。失敗回空包，不准擋抓文。"""
    pack = live_match_pack(db_path, spoken=spoken)
    if not db_path:
        return pack
    try:
        import json
        from datetime import datetime
        from zoneinfo import ZoneInfo

        ensure_live_match_table(db_path)
        now = datetime.now(ZoneInfo("Asia/Taipei")).strftime("%Y-%m-%dT%H:%M:%S")
        slim = {
            "as_of": pack.get("as_of") or "",
            "no_chase": pack.get("no_chase") or {},
            "hold": pack.get("hold") or {},
            "find_pools": pack.get("find_pools") or [],
            "matches": [
                {
                    "sid": r.get("sid"),
                    "name": r.get("name"),
                    "why": r.get("why"),
                    "peak_pct": r.get("peak_pct"),
                    "score": r.get("score"),
                }
                for r in (pack.get("matches") or [])
            ],
            "updated_at": now,
        }
        conn = sqlite3.connect(db_path, timeout=15.0)
        try:
            conn.execute(
                "INSERT INTO biaoke_live_match(key, as_of, payload, updated_at) "
                "VALUES(?,?,?,?) "
                "ON CONFLICT(key) DO UPDATE SET "
                "as_of=excluded.as_of, payload=excluded.payload, "
                "updated_at=excluded.updated_at",
                ("latest", str(slim.get("as_of") or ""), json.dumps(slim, ensure_ascii=False), now),
            )
            conn.commit()
        finally:
            conn.close()
    except Exception:
        pass
    return pack


def no_chase_note(sid: str, pack: Optional[Dict[str, Any]] = None) -> str:
    """介紹區勿追檔附註：他提過、位階偏高（非買訊）。"""
    if sid and sid in no_chase_sids(pack):
        return "他提過、現在位階偏高"
    return ""
