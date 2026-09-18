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
# needles＝籌碼K細項鏈裡他教過的次族群字，用來把族內成員從庫裡補齊。
_GROUPS: Tuple[Dict[str, Any], ...] = (
    {
        "key": "asic",
        "field": "ASIC",
        "names": ("ASIC", "創意", "世芯", "智原"),
        "needles": ("IP/ASIC", "ASIC"),
        "leaders": (("3443", "創意"), ("3661", "世芯-KY"), ("3035", "智原")),
    },
    {
        "key": "cool",
        "field": "散熱",
        "names": ("散熱", "健策", "奇鋐"),
        "needles": ("散熱",),
        "leaders": (("3653", "健策"), ("3017", "奇鋐")),
    },
    {
        "key": "inp",
        "field": "光通訊 InP",
        "names": ("光通訊", "InP", "聯亞", "全新", "穩懋"),
        "needles": (),
        "leaders": (("3081", "聯亞"), ("2455", "全新"), ("3105", "穩懋")),
    },
    {
        "key": "mem",
        "field": "記憶體",
        "names": ("記憶體", "南亞科"),
        "needles": ("記憶體",),
        "leaders": (("2408", "南亞科"),),
    },
    {
        "key": "pcb",
        "field": "PCB",
        "names": ("PCB", "台光電", "CCL"),
        "needles": ("PCB",),
        "leaders": (("2383", "台光電"),),
    },
    {
        "key": "abf",
        "field": "ABF",
        "names": ("ABF", "欣興", "南電"),
        "needles": ("ABF",),
        "leaders": (("3037", "欣興"),),
    },
    {
        "key": "pass",
        "field": "被動元件",
        "names": ("被動元件", "被動", "國巨"),
        "needles": ("被動元件",),
        "leaders": (("2327", "國巨"),),
    },
    {
        "key": "test",
        "field": "高階測試／封測",
        "names": ("高階測試", "封測", "穎崴", "旺矽", "汎銓"),
        "needles": ("封測",),
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
_HOW = (
    "他教過怎麼找：①次族群還沒熱、很少人提；②次族群第一名誰先過前高，不比絕對漲跌；"
    "③高點整理的從底部找落後。不是猜新聞。"
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
    try:
        vs20 = float(st["vs20"])
        vs60 = float(st["vs60"])
        volr = float(st["volr"])
        broke = bool(st["broke"])
    except (KeyError, TypeError, ValueError):
        return False
    return vs20 >= -5.0 and vs60 <= -8.0 and volr >= 1.5 and not broke


def _empty_pick(line: str, *, cap: str = "", named: Optional[set] = None, missing: int = 0) -> Dict[str, Any]:
    named = named or set()
    named_txt = "、".join(g["field"] for g in _GROUPS if g["key"] in named)
    return {
        "how": _HOW,
        "cap": cap,
        "field": "",
        "key": "",
        "group": None,
        "laggard": None,
        "leader": None,
        "named": [g["field"] for g in _GROUPS if g["key"] in named],
        "named_txt": named_txt,
        "missing": missing,
        "line": line,
    }


def pick_unnamed_field(db_path: str, *, ask: str = "", spoken: str = "") -> Dict[str, Any]:
    """結構化找法。對不上就空 field，不准猜。"""
    del ask
    if not db_path:
        return _empty_pick(_HOW + " 官方日 K 還沒這列，不准猜。不是買訊。")
    cap = _cap(db_path)
    if not cap:
        return _empty_pick(_HOW + " 官方完整日還沒，盤中未收不當官方收。不是買訊。")
    spoken = spoken or latest_spoken(db_path)
    named = _named_keys(spoken)
    hits: List[Tuple[float, Dict[str, Any], Dict[str, Any], Optional[Tuple[str, str, Dict[str, Any]]]]] = []
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
    named_txt = "、".join(g["field"] for g in _GROUPS if g["key"] in named)
    extra = " 已點名的 " + named_txt + " 不當新族群。" if named_txt else ""
    if not hits:
        if missing:
            line = (
                _HOW
                + extra
                + f" 官方收 {cap} 還沒對上「還沒熱＋贴近20高＋量起來＋第一名還沒先過前高」的次族群，不准發明。不是買訊。"
            )
        else:
            line = (
                _HOW
                + extra
                + f" 官方收 {cap} 還沒對上底部蠢蠢的次族群，不准發明。不是買訊。"
            )
        return _empty_pick(line, cap=cap, named=named, missing=missing)
    hits.sort(key=lambda x: -x[0])
    _volr, g, st, lead = hits[0]
    lead_bit = ""
    if lead:
        lead_bit = (
            f"龍頭 {lead[1]} {lead[0]} 收 {_px(lead[2]['close'])}"
            f"{' 還沒先過前高' if not lead[2]['broke'] else ' 已先過前高'}。"
        )
    named_bit = ("已點名的 " + named_txt + " 不當新族群。") if named_txt else ""
    line = (
        _HOW
        + f" 官方收 {st['date']}：最像 {g['field']}，落後檔 {st['name']} {st['sid']}"
        f" 收 {_px(st['close'])} 距20高 {_pct(st['vs20'])} 距60高 {_pct(st['vs60'])}"
        f" 量比 {st['volr']:.2f}。{lead_bit}{named_bit}"
        "不是他當下點名。不是買訊。"
    )
    why = (
        f"還沒點名；落後檔 {st['name']} 贴近20高、60高仍明顯在上、量起來。"
        + (f" {lead_bit}" if lead_bit else "")
        + named_bit
        + "不是他當下點名。"
    )
    return {
        "how": _HOW,
        "cap": str(st["date"]),
        "field": g["field"],
        "key": g["key"],
        "group": g,
        "laggard": st,
        "leader": {"sid": lead[0], "name": lead[1], **lead[2]} if lead else None,
        "named": [x["field"] for x in _GROUPS if x["key"] in named],
        "named_txt": named_txt,
        "missing": missing,
        "why": why.strip(),
        "line": line,
    }


def scan_unnamed_field(db_path: str, *, ask: str = "", spoken: str = "") -> str:
    """回一句產業抽屜用的找法＋官方柱對質。對不上就寫還沒，不准猜。"""
    return str(pick_unnamed_field(db_path, ask=ask, spoken=spoken).get("line") or "")


def _stock_name(db_path: str, sid: str, fallback: str = "") -> str:
    if fallback:
        return fallback
    if not db_path or not sid:
        return sid
    conn = sqlite3.connect(db_path, timeout=8.0)
    try:
        row = conn.execute(
            "SELECT stock_name FROM daily_quotes WHERE stock_id=? "
            "AND IFNULL(stock_name,'')!='' ORDER BY REPLACE(CAST(date AS TEXT),'-','') DESC LIMIT 1",
            (sid,),
        ).fetchone()
    except sqlite3.Error:
        row = None
    finally:
        conn.close()
    return str(row[0] or sid) if row else sid


def group_members(db_path: str, group: Optional[Dict[str, Any]]) -> List[Tuple[str, str]]:
    """族內成員＝他點過的龍頭／落後檔 ＋ 籌碼K細項鏈對得上的。不准發明次族群。"""
    if not group:
        return []
    out: Dict[str, str] = {}
    for sid, name in list(group.get("leaders") or ()) + list(group.get("laggards") or ()):
        out[str(sid)] = str(name)
    needles = tuple(group.get("needles") or ())
    if db_path and needles:
        conn = sqlite3.connect(db_path, timeout=8.0)
        try:
            hit = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='stock_fine_industry'"
            ).fetchone()
            if hit:
                clauses = " OR ".join(["chain LIKE ?" for _ in needles])
                rows = conn.execute(
                    f"SELECT stock_id, chain FROM stock_fine_industry WHERE {clauses}",
                    tuple(f"%{n}%" for n in needles),
                ).fetchall()
                for sid, _chain in rows:
                    sid = str(sid or "").strip()
                    if not sid or sid in out:
                        continue
                    out[sid] = _stock_name(db_path, sid, "")
        except sqlite3.Error:
            pass
        finally:
            conn.close()
    return [(sid, out[sid]) for sid in sorted(out)]


def _has_chip_cols(conn: sqlite3.Connection) -> bool:
    cols = {str(r[1]) for r in conn.execute("PRAGMA table_info(daily_quotes)")}
    return {"foreign_net", "trust_net", "dealer_net"} <= cols


def ensure_dongzhu_flow_table(db_path: str) -> None:
    if not db_path:
        return
    conn = sqlite3.connect(db_path, timeout=8.0)
    try:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS dongzhu_flow_tape (
                date TEXT NOT NULL,
                group_key TEXT NOT NULL,
                field TEXT NOT NULL,
                three_net INTEGER DEFAULT 0,
                member_n INTEGER DEFAULT 0,
                PRIMARY KEY (date, group_key)
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_dongzhu_flow_key ON dongzhu_flow_tape(group_key, date)"
        )
        conn.commit()
    finally:
        conn.close()


def _quote_dates(conn: sqlite3.Connection, cap: str, n: int = 10) -> List[str]:
    cap = _ymd(cap)
    if not cap:
        return []
    rows = conn.execute(
        "SELECT DISTINCT REPLACE(CAST(date AS TEXT),'-','') AS d FROM daily_quotes "
        "WHERE REPLACE(CAST(date AS TEXT),'-','') <= ? ORDER BY d DESC LIMIT ?",
        (cap, int(n)),
    ).fetchall()
    return sorted(_ymd(r[0]) for r in rows if _ymd(r[0]))


def record_dongzhu_flow(db_path: str, cap: str = "", lookback: int = 10) -> int:
    """把教過的次族群近幾日三大法人張寫進膠帶。來源＝日 K 的 T86，不抓分點。"""
    if not db_path:
        return 0
    cap = _ymd(cap) or _cap(db_path)
    if not cap:
        return 0
    ensure_dongzhu_flow_table(db_path)
    conn = sqlite3.connect(db_path, timeout=8.0)
    written = 0
    try:
        if not _has_chip_cols(conn):
            return 0
        dates = _quote_dates(conn, cap, lookback)
        if not dates:
            return 0
        members = {g["key"]: [sid for sid, _n in group_members(db_path, g)] for g in _GROUPS}
        qmarks_by_key = {}
        for key, sids in members.items():
            if sids:
                qmarks_by_key[key] = ",".join("?" * len(sids))
        for day in dates:
            for g in _GROUPS:
                sids = members.get(g["key"]) or []
                if not sids:
                    continue
                row = conn.execute(
                    f"SELECT COUNT(*), IFNULL(SUM(IFNULL(foreign_net,0)+IFNULL(trust_net,0)+IFNULL(dealer_net,0)),0) "
                    f"FROM daily_quotes WHERE REPLACE(CAST(date AS TEXT),'-','')=? AND stock_id IN ({qmarks_by_key[g['key']]})",
                    [day, *sids],
                ).fetchone()
                n = int(row[0] or 0) if row else 0
                three = int(row[1] or 0) if row else 0
                conn.execute(
                    """
                    INSERT INTO dongzhu_flow_tape(date, group_key, field, three_net, member_n)
                    VALUES (?,?,?,?,?)
                    ON CONFLICT(date, group_key) DO UPDATE SET
                        field=excluded.field,
                        three_net=excluded.three_net,
                        member_n=excluded.member_n
                    """,
                    (day, g["key"], g["field"], three, n),
                )
                written += 1
        conn.commit()
    except sqlite3.Error:
        return 0
    finally:
        conn.close()
    return written


def _ignite_from_nets(nets: Sequence[int]) -> Dict[str, Any]:
    vals = [int(n) for n in nets][-5:]
    pos = sum(1 for n in vals if n > 0)
    cum = sum(vals)
    last = vals[-1] if vals else 0
    mx = max((abs(n) for n in vals), default=0)
    slow = bool(vals) and pos >= 3 and cum > 0 and last > 0 and (pos >= 4 or mx * 10 <= abs(cum) * 8)
    return {
        "nets": vals,
        "pos_days": pos,
        "cum5": cum,
        "last": last,
        "slow_in": slow,
    }


def group_ignite(db_path: str, group_key: str, cap: str) -> Dict[str, Any]:
    empty = {"nets": [], "pos_days": 0, "cum5": 0, "last": 0, "slow_in": False, "dates": []}
    if not db_path or not group_key:
        return empty
    ensure_dongzhu_flow_table(db_path)
    cap = _ymd(cap)
    conn = sqlite3.connect(db_path, timeout=8.0)
    try:
        rows = conn.execute(
            "SELECT date, three_net FROM dongzhu_flow_tape "
            "WHERE group_key=? AND date<=? ORDER BY date",
            (group_key, cap),
        ).fetchall()
    except sqlite3.Error:
        rows = []
    finally:
        conn.close()
    last = rows[-5:] if rows else []
    ign = _ignite_from_nets([int(r[1] or 0) for r in last])
    ign["dates"] = [_ymd(r[0]) for r in last]
    return ign


def member_cum5(db_path: str, sid: str, cap: str) -> int:
    if not db_path or not sid:
        return 0
    conn = sqlite3.connect(db_path, timeout=8.0)
    try:
        if not _has_chip_cols(conn):
            return 0
        rows = conn.execute(
            "SELECT IFNULL(foreign_net,0)+IFNULL(trust_net,0)+IFNULL(dealer_net,0) "
            "FROM daily_quotes WHERE stock_id=? AND REPLACE(CAST(date AS TEXT),'-','')<=? "
            "ORDER BY REPLACE(CAST(date AS TEXT),'-','') DESC LIMIT 5",
            (sid, _ymd(cap)),
        ).fetchall()
    except sqlite3.Error:
        return 0
    finally:
        conn.close()
    return int(sum(int(r[0] or 0) for r in rows))


def _lots_txt(val: int) -> str:
    n = int(val)
    body = f"{abs(n):,}"
    if n > 0:
        return f"＋{body}張"
    if n < 0:
        return f"−{body}張"
    return "0張"


def _flow_why(ign: Dict[str, Any]) -> str:
    nets = list(ign.get("nets") or [])
    if not nets:
        return "法人張還沒這列，資金輪動不准猜。"
    bits = "/".join(_lots_txt(n).replace("張", "") for n in nets)
    extra = (
        f"{ign.get('pos_days') or 0}日買超＝慢慢匯入、準備點火。"
        if ign.get("slow_in")
        else "還沒連日匯入，不算點火。"
    )
    return f"近{len(nets)}日三大法人 {bits} 累計 {_lots_txt(int(ign.get('cum5') or 0))}。{extra}"


def _bucket_by_id(db_path: str, bucket: str) -> Dict[str, Dict[str, Any]]:
    if not db_path:
        return {}
    try:
        from screen_sessions import load_bucket_rows
        from universe import is_screen_equity
    except Exception:
        return {}
    out: Dict[str, Dict[str, Any]] = {}
    try:
        rows = load_bucket_rows(db_path, bucket) or []
    except Exception:
        return {}
    for raw in rows:
        sid = str(raw.get("stock_id") or raw.get("code") or "").strip()
        name = str(raw.get("stock_name") or raw.get("name") or "")
        if not sid:
            continue
        try:
            if not is_screen_equity(sid, name):
                continue
        except Exception:
            pass
        out[sid] = dict(raw)
    return out


def _score_member(st: Optional[Dict[str, Any]], row: Optional[Dict[str, Any]]) -> Tuple:
    """越高越值得：先法人慢慢匯入，再蠢蠢欲動的量價，只在黃金買點列上排。"""
    del row
    st = st or {}
    try:
        volr = float(st.get("volr") or 0.0)
    except (TypeError, ValueError):
        volr = 0.0
    try:
        vs20 = float(st["vs20"]) if st.get("vs20") is not None else -999.0
    except (TypeError, ValueError):
        vs20 = -999.0
    stir = 1.0 if _stirring(st) else 0.0
    try:
        cum = int(st.get("cum5") or 0)
    except (TypeError, ValueError):
        cum = 0
    return (1.0 if cum > 0 else 0.0, float(cum), stir, volr, vs20)


def _decorate(db_path: str, sid: str, name: str, cap: str, row: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    st = _stats(_bars(db_path, sid, cap)) or {}
    item = {
        "sid": sid,
        "name": name or str((row or {}).get("stock_name") or sid),
        "close": st.get("close"),
        "vs20": st.get("vs20"),
        "vs60": st.get("vs60"),
        "volr": st.get("volr"),
        "date": st.get("date") or cap,
        "stirring": bool(st) and _stirring(st),
        "broke": bool(st.get("broke")),
        "chase_warning": bool((row or {}).get("chase_warning")),
        "cum5": member_cum5(db_path, sid, cap),
    }
    if row:
        item["pick_close"] = row.get("pick_close") or row.get("close")
        item["entry_price"] = row.get("entry_price")
    return item


def dongzhu_picks(db_path: str, *, spoken: str = "") -> Dict[str, Any]:
    """洞燭先機鈕：飆大找法當主因，資金輪動膠帶確認慢慢匯入，切入＝這族 ∩ 黃金買點。"""
    pick = pick_unnamed_field(db_path, spoken=spoken)
    cap = str(pick.get("cap") or _cap(db_path) or "")
    if db_path and cap:
        try:
            record_dongzhu_flow(db_path, cap)
        except Exception:
            pass
    named_keys = _named_keys(spoken or latest_spoken(db_path) if db_path else spoken)
    flow_hit = None
    named_hot_cum = 0
    named_hot_field = ""
    for g in _GROUPS:
        ign = group_ignite(db_path, g["key"], cap) if db_path and cap else {}
        if g["key"] in named_keys:
            if int(ign.get("cum5") or 0) > named_hot_cum:
                named_hot_cum = int(ign.get("cum5") or 0)
                named_hot_field = g["field"]
            continue
        if not ign.get("slow_in"):
            continue
        lead_broke = False
        for sid, _name in g["leaders"][:1]:
            st = _stats(_bars(db_path, sid, cap)) if db_path else None
            if st and st.get("broke"):
                lead_broke = True
                break
        if lead_broke:
            continue
        cand = {"group": g, "ign": ign}
        if flow_hit is None or int(ign.get("cum5") or 0) > int(flow_hit["ign"].get("cum5") or 0):
            flow_hit = cand
    k_group = pick.get("group")
    k_ign = group_ignite(db_path, pick.get("key") or "", cap) if pick.get("key") else {}
    if (not pick.get("field")) and flow_hit:
        g = flow_hit["group"]
        pick = {
            **pick,
            "field": g["field"],
            "key": g["key"],
            "group": g,
            "why": (
                f"還沒點名；資金近5日慢慢匯入 {_lots_txt(int(flow_hit['ign'].get('cum5') or 0))}，準備點火。"
                + (("已點名的 " + "、".join(pick.get("named") or []) + " 不當新族群。") if pick.get("named") else "")
                + "不是他當下點名。"
            ),
        }
        k_ign = flow_hit["ign"]
    elif k_group and k_ign:
        pass
    pick["flow"] = k_ign if pick.get("key") else (flow_hit["ign"] if flow_hit else {})
    pick["flow_named_hot"] = {"field": named_hot_field, "cum5": named_hot_cum}
    members = group_members(db_path, pick.get("group"))
    buys_map = _bucket_by_id(db_path, "leave_zero")
    watch_map = _bucket_by_id(db_path, "golden_buy")
    buys: List[Dict[str, Any]] = []
    watches: List[Dict[str, Any]] = []
    for sid, name in members:
        if sid in buys_map:
            buys.append(_decorate(db_path, sid, name, cap, buys_map[sid]))
        elif sid in watch_map:
            item = _decorate(db_path, sid, name, cap, watch_map[sid])
            if item.get("close") is None:
                continue
            watches.append(item)
    buys.sort(key=lambda x: _score_member(x, None), reverse=True)
    watches.sort(key=lambda x: _score_member(x, None), reverse=True)
    laggard = pick.get("laggard")
    return {
        **pick,
        "members": members,
        "buys": buys[:5],
        "watches": watches[:5],
        "laggards_note": laggard,
    }


def _esc(val: Any) -> str:
    return (
        str(val if val is not None else "")
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def _stock_line(item: Dict[str, Any], idx: int, tag: str) -> str:
    sid = _esc(item.get("sid"))
    name = _esc(item.get("name"))
    close = item.get("close")
    close_s = _px(float(close)) if close is not None else "—"
    vs20 = item.get("vs20")
    vs60 = item.get("vs60")
    volr = item.get("volr")
    bits = [f"{idx}. {sid} {name}　{_esc(tag)}　收 {close_s}"]
    if vs20 is not None:
        bits.append(f"距20高 {_pct(float(vs20))}")
    if vs60 is not None:
        bits.append(f"距60高 {_pct(float(vs60))}")
    if volr is not None:
        bits.append(f"量比 {float(volr):.2f}")
    if item.get("cum5"):
        bits.append(f"近5日法人 {_lots_txt(int(item.get('cum5') or 0))}")
    return "　".join(bits)


def dongzhu_page(db_path: str, *, spoken: str = "") -> str:
    """主選單洞燭先機頁。飆大找法＋資金輪動膠帶。切入只認高低卡黃金買點。"""
    data = dongzhu_picks(db_path, spoken=spoken)
    cap = _esc(data.get("cap") or "")
    lines = [
        "<b>洞燭先機</b>",
        _esc(data.get("how") or _HOW),
        "飆大找法當參考主因；資金輪動看三大法人張是否慢慢匯入、準備點火。盤中未收不當官方收。不是買訊、不進海選。切入只認高低卡黃金買點。",
    ]
    if cap:
        lines.append(f"官方收 {cap}")
    field = str(data.get("field") or "")
    if not field:
        lines.append(f"<i>{_esc(data.get('line') or '還沒對上底部蠢蠢的次族群，不准發明。不是買訊。')}</i>")
        flow = data.get("flow") or {}
        if flow.get("nets"):
            lines.append(_esc(_flow_why(flow)))
        return "\n".join(lines)
    lines.append(f"<b>此刻最像</b> {_esc(field)}")
    why = str(data.get("why") or "")
    if why:
        lines.append(f"<i>原因：{_esc(why)}</i>")
    flow = data.get("flow") or {}
    lines.append(_esc("資金輪動（記在膠帶）" + _flow_why(flow)))
    hot = data.get("flow_named_hot") or {}
    if hot.get("field") and int(hot.get("cum5") or 0) > 0:
        lines.append(
            _esc(f"已點名的 {hot['field']} 近5日仍 {_lots_txt(int(hot['cum5']))}，當下熱門不當新族群。")
        )
    buys = list(data.get("buys") or [])
    lines.append("<b>這族最值得切入</b>（跟全市場黃金買點對過；同列再看法人是否匯入）")
    if buys:
        for i, item in enumerate(buys, start=1):
            lines.append(_stock_line(item, i, "買點"))
    else:
        lines.append("<i>這族此刻沒有黃金買點，不准發明切入。</i>")
    watches = list(data.get("watches") or [])
    if watches:
        lines.append("<b>還在零</b>（只觀察，不是買）")
        for i, item in enumerate(watches, start=1):
            lines.append(_stock_line(item, i, "觀察"))
    lag = data.get("laggards_note") or data.get("laggard")
    if lag and str(lag.get("sid") or "") not in {x.get("sid") for x in buys}:
        lines.append("<b>蠢蠢欲動的落後檔</b>（不是買訊）")
        lines.append(_stock_line(lag, 1, "落後"))
    lines.append("紅箭頭不是買訊。不是他當下點名。")
    return "\n".join(lines)
