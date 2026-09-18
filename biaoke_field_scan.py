# -*- coding: utf-8 -*-
"""他教過怎麼找還沒點名的族群：洞燭先機＋次族群第一名誰先過前高＋從底部找落後。

資金流騙不了人：單位＝CMoney 細項佔當日法人買超％、％怎麼變。流入＝佔比升，流出＝佔比降。
佔比如實主判，飆大找法只參考、不是唯一。張數會被當下熱門族蓋過，不拿來排名。對五件只落在族群：底部這層（不數浪）、形態還沒過前高、
量價落後檔量起來、關鍵K＝官方收、碎形＝第一名還沒先過。個股不數 5／9。盤中未收不當官方收。
不是買訊、不進海選。切入只認高低卡黃金買點。
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
        "layers": ("電子上游", "IP/ASIC"),
        "leaders": (("3443", "創意"), ("3661", "世芯-KY"), ("3035", "智原")),
    },
    {
        "key": "cool",
        "field": "散熱",
        "names": ("散熱", "健策", "奇鋐"),
        "needles": ("散熱",),
        "layers": ("電子中游", "散熱零組件"),
        "leaders": (("3653", "健策"), ("3017", "奇鋐")),
    },
    {
        "key": "inp",
        "field": "光通訊 InP",
        "names": ("光通訊", "InP", "聯亞", "全新", "穩懋"),
        "needles": (),
        "layers": ("電子上游", "半導體元件"),
        "leaders": (("3081", "聯亞"), ("2455", "全新"), ("3105", "穩懋")),
    },
    {
        "key": "mem",
        "field": "記憶體",
        "names": ("記憶體", "南亞科"),
        "needles": ("記憶體",),
        "layers": ("電子上游", "記憶體製造"),
        "leaders": (("2408", "南亞科"),),
    },
    {
        "key": "pcb",
        "field": "PCB",
        "names": ("PCB", "台光電", "CCL"),
        "needles": ("PCB",),
        "layers": ("電子上游", "PCB", "材料設備"),
        "leaders": (("2383", "台光電"),),
    },
    {
        "key": "abf",
        "field": "ABF",
        "names": ("ABF", "欣興", "南電"),
        "needles": ("ABF",),
        "layers": ("電子上游", "ABF"),
        "leaders": (("3037", "欣興"),),
    },
    {
        "key": "pass",
        "field": "被動元件",
        "names": ("被動元件", "被動", "國巨"),
        "needles": ("被動元件",),
        "layers": ("電子上游", "被動元件"),
        "leaders": (("2327", "國巨"),),
    },
    {
        "key": "test",
        "field": "高階測試／封測",
        "names": ("高階測試", "封測", "穎崴", "旺矽", "汎銓"),
        "needles": ("封測",),
        "layers": ("電子上游", "IC", "封測"),
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


def _chip_cap(db_path: str, cap: str = "") -> str:
    """法人還沒寫進當日柱（全日 0）不當資金日。盤中未收不當官方收。"""
    cap = _ymd(cap) or _cap(db_path)
    if not db_path or not cap:
        return cap
    conn = sqlite3.connect(db_path, timeout=8.0)
    try:
        if not _has_chip_cols(conn):
            return cap
        row = conn.execute(
            """
            SELECT MAX(REPLACE(CAST(date AS TEXT),'-','')) FROM daily_quotes
            WHERE REPLACE(CAST(date AS TEXT),'-','') <= ?
              AND IFNULL(foreign_net,0)+IFNULL(trust_net,0)+IFNULL(dealer_net,0) != 0
            """,
            (cap,),
        ).fetchone()
    except sqlite3.Error:
        return cap
    finally:
        conn.close()
    day = _ymd(row[0] if row else "")
    return day or cap


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


def pick_unnamed_field(db_path: str, *, ask: str = "", spoken: Optional[str] = None) -> Dict[str, Any]:
    """結構化找法。對不上就空 field，不准猜。spoken=None 才讀最新主文；空字＝他沒開口。"""
    del ask
    if not db_path:
        return _empty_pick(_HOW + " 官方日 K 還沒這列，不准猜。不是買訊。")
    cap = _cap(db_path)
    if not cap:
        return _empty_pick(_HOW + " 官方完整日還沒，盤中未收不當官方收。不是買訊。")
    if spoken is None:
        spoken = latest_spoken(db_path)
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


def scan_unnamed_field(db_path: str, *, ask: str = "", spoken: Optional[str] = None) -> str:
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
                pos_member INTEGER DEFAULT 0,
                market_in INTEGER DEFAULT 0,
                market_out INTEGER DEFAULT 0,
                share_pct REAL DEFAULT 0,
                share_chg REAL DEFAULT 0,
                fine_tag TEXT DEFAULT '',
                PRIMARY KEY (date, group_key)
            )
            """
        )
        cols = {str(r[1]) for r in conn.execute("PRAGMA table_info(dongzhu_flow_tape)")}
        for name, spec in (
            ("pos_member", "INTEGER DEFAULT 0"),
            ("market_in", "INTEGER DEFAULT 0"),
            ("market_out", "INTEGER DEFAULT 0"),
            ("share_pct", "REAL DEFAULT 0"),
            ("share_chg", "REAL DEFAULT 0"),
            ("fine_tag", "TEXT DEFAULT ''"),
        ):
            if name not in cols:
                conn.execute(f"ALTER TABLE dongzhu_flow_tape ADD COLUMN {name} {spec}")
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
    """把教過的次族群寫進膠帶：細項、三大法人張、佔當日買超／賣超％。來源＝日 K 的 T86，不抓分點。"""
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
        prev_share: Dict[str, float] = {}
        for day in dates:
            mkt = conn.execute(
                """
                SELECT
                  IFNULL(SUM(CASE WHEN t>0 THEN t ELSE 0 END),0),
                  IFNULL(SUM(CASE WHEN t<0 THEN -t ELSE 0 END),0)
                FROM (
                  SELECT IFNULL(foreign_net,0)+IFNULL(trust_net,0)+IFNULL(dealer_net,0) AS t
                  FROM daily_quotes
                  WHERE REPLACE(CAST(date AS TEXT),'-','')=? AND length(stock_id)=4
                )
                """,
                (day,),
            ).fetchone()
            market_in = int(mkt[0] or 0) if mkt else 0
            market_out = int(mkt[1] or 0) if mkt else 0
            for g in _GROUPS:
                sids = members.get(g["key"]) or []
                if not sids:
                    continue
                row = conn.execute(
                    f"""
                    SELECT COUNT(*),
                           IFNULL(SUM(t),0),
                           IFNULL(SUM(CASE WHEN t>0 THEN 1 ELSE 0 END),0)
                    FROM (
                      SELECT IFNULL(foreign_net,0)+IFNULL(trust_net,0)+IFNULL(dealer_net,0) AS t
                      FROM daily_quotes
                      WHERE REPLACE(CAST(date AS TEXT),'-','')=?
                        AND stock_id IN ({qmarks_by_key[g['key']]})
                    )
                    """,
                    [day, *sids],
                ).fetchone()
                n = int(row[0] or 0) if row else 0
                three = int(row[1] or 0) if row else 0
                pos_n = int(row[2] or 0) if row else 0
                if three > 0 and market_in > 0:
                    share = 100.0 * three / market_in
                elif three < 0 and market_out > 0:
                    share = -100.0 * abs(three) / market_out
                else:
                    share = 0.0
                chg = share - float(prev_share.get(g["key"]) or 0.0) if g["key"] in prev_share else 0.0
                prev_share[g["key"]] = share
                needles = tuple(g.get("needles") or ())
                fine = str(needles[-1] if needles else g["field"])
                conn.execute(
                    """
                    INSERT INTO dongzhu_flow_tape(
                        date, group_key, field, three_net, member_n, pos_member,
                        market_in, market_out, share_pct, share_chg, fine_tag
                    ) VALUES (?,?,?,?,?,?,?,?,?,?,?)
                    ON CONFLICT(date, group_key) DO UPDATE SET
                        field=excluded.field,
                        three_net=excluded.three_net,
                        member_n=excluded.member_n,
                        pos_member=excluded.pos_member,
                        market_in=excluded.market_in,
                        market_out=excluded.market_out,
                        share_pct=excluded.share_pct,
                        share_chg=excluded.share_chg,
                        fine_tag=excluded.fine_tag
                    """,
                    (day, g["key"], g["field"], three, n, pos_n, market_in, market_out, share, chg, fine),
                )
                written += 1
        conn.commit()
    except sqlite3.Error:
        return 0
    finally:
        conn.close()
    return written


def _ignite_from_nets(nets: Sequence[int], shares: Optional[Sequence[float]] = None) -> Dict[str, Any]:
    """流入／流出看佔比升降。沒有佔比才退回連日買超張。單日暴衝張不算流入。"""
    vals = [int(n) for n in nets][-5:]
    pos = sum(1 for n in vals if n > 0)
    cum = sum(vals)
    last = vals[-1] if vals else 0
    mx = max((abs(n) for n in vals), default=0)
    lots_in = bool(vals) and pos >= 3 and cum > 0 and last > 0 and (pos >= 4 or mx * 10 <= abs(cum) * 8)
    sh = [float(x) for x in (shares or [])][-5:]
    rise = sum(1 for i in range(1, len(sh)) if sh[i] > sh[i - 1] + 1e-9)
    up = (sh[-1] - sh[0]) if len(sh) >= 2 else 0.0
    share_in = len(sh) >= 3 and rise >= 2 and up > 0 and sh[-1] > 0
    share_out = len(sh) >= 2 and up < -1e-9
    if sh:
        flowing_in = bool(share_in and not share_out)
    else:
        flowing_in = bool(lots_in)
    return {
        "nets": vals,
        "pos_days": pos,
        "cum5": cum,
        "last": last,
        "shares": sh,
        "share_last": sh[-1] if sh else 0.0,
        "share_up": up,
        "share_rise_days": rise,
        "flowing_in": flowing_in,
        "slow_in": flowing_in,
    }


def group_ignite(db_path: str, group_key: str, cap: str) -> Dict[str, Any]:
    empty = {
        "nets": [],
        "pos_days": 0,
        "cum5": 0,
        "last": 0,
        "slow_in": False,
        "dates": [],
        "shares": [],
        "share_last": 0.0,
        "share_up": 0.0,
        "share_rise_days": 0,
        "flowing_in": False,
        "fine_tag": "",
        "pos_member": 0,
        "member_n": 0,
        "share_chg": 0.0,
    }
    if not db_path or not group_key:
        return empty
    ensure_dongzhu_flow_table(db_path)
    cap = _ymd(cap)
    conn = sqlite3.connect(db_path, timeout=8.0)
    try:
        rows = conn.execute(
            "SELECT date, three_net, IFNULL(share_pct,0), IFNULL(fine_tag,''), "
            "IFNULL(pos_member,0), IFNULL(member_n,0), IFNULL(share_chg,0) "
            "FROM dongzhu_flow_tape WHERE group_key=? AND date<=? ORDER BY date",
            (group_key, cap),
        ).fetchall()
    except sqlite3.Error:
        rows = []
    finally:
        conn.close()
    last = rows[-5:] if rows else []
    ign = _ignite_from_nets(
        [int(r[1] or 0) for r in last],
        [float(r[2] or 0) for r in last],
    )
    ign["dates"] = [_ymd(r[0]) for r in last]
    if last:
        ign["fine_tag"] = str(last[-1][3] or "")
        ign["pos_member"] = int(last[-1][4] or 0)
        ign["member_n"] = int(last[-1][5] or 0)
        ign["share_chg"] = float(last[-1][6] or 0)
    else:
        ign["fine_tag"] = ""
        ign["pos_member"] = 0
        ign["member_n"] = 0
        ign["share_chg"] = 0.0
    return ign


def _member_nets(db_path: str, sid: str, cap: str, n: int = 5) -> List[int]:
    if not db_path or not sid:
        return []
    conn = sqlite3.connect(db_path, timeout=8.0)
    try:
        if not _has_chip_cols(conn):
            return []
        rows = conn.execute(
            "SELECT IFNULL(foreign_net,0)+IFNULL(trust_net,0)+IFNULL(dealer_net,0) "
            "FROM daily_quotes WHERE stock_id=? AND REPLACE(CAST(date AS TEXT),'-','')<=? "
            "ORDER BY REPLACE(CAST(date AS TEXT),'-','') DESC LIMIT ?",
            (sid, _ymd(cap), int(n)),
        ).fetchall()
    except sqlite3.Error:
        return []
    finally:
        conn.close()
    vals = [int(r[0] or 0) for r in rows]
    vals.reverse()
    return vals


def member_cum5(db_path: str, sid: str, cap: str) -> int:
    return int(sum(_member_nets(db_path, sid, cap, 5)))


def member_last_net(db_path: str, sid: str, cap: str) -> int:
    nets = _member_nets(db_path, sid, cap, 1)
    return int(nets[-1]) if nets else 0


def _fine_chain(db_path: str, sid: str) -> str:
    parts = _chain_parts(db_path, sid)
    return parts[-1] if parts else ""


def _chain_parts(db_path: str, sid: str) -> List[str]:
    if not db_path or not sid:
        return []
    conn = sqlite3.connect(db_path, timeout=8.0)
    try:
        hit = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='stock_fine_industry'"
        ).fetchone()
        if not hit:
            return []
        row = conn.execute(
            "SELECT chain FROM stock_fine_industry WHERE stock_id=? LIMIT 1", (sid,)
        ).fetchone()
    except sqlite3.Error:
        return []
    finally:
        conn.close()
    chain = str(row[0] or "").strip() if row else ""
    if not chain:
        return []
    return [p.strip() for p in chain.replace("／", "-").split("-") if p.strip()]


def _group_layers(db_path: str, group: Optional[Dict[str, Any]]) -> List[str]:
    if not group:
        return []
    declared = [str(x) for x in (group.get("layers") or ()) if str(x)]
    sid = ""
    leads = list(group.get("leaders") or ())
    if leads:
        sid = str(leads[0][0] or "")
    parts = _chain_parts(db_path, sid) if sid else []
    return parts or declared


def _layer_line(layers: Sequence[str]) -> str:
    labs = ("主產業", "次產業", "細項")
    bits = []
    for i, part in enumerate(list(layers)[:3]):
        lab = labs[i] if i < len(labs) else "層"
        bits.append(f"{lab} {part}")
    return " → ".join(bits)


def _layer_short(layers: Sequence[str]) -> str:
    return "／".join(str(x) for x in layers if x)


def _stock_role(group: Optional[Dict[str, Any]], sid: str) -> str:
    sid = str(sid or "")
    if not group or not sid:
        return ""
    leads = [str(x[0]) for x in (group.get("leaders") or ()) if x]
    if sid in leads:
        return "龍頭"
    return "次級"


def _sibling_txt(
    group: Optional[Dict[str, Any]],
    all_igns: Sequence[Dict[str, Any]],
    db_path: str = "",
) -> str:
    if not group or not all_igns:
        return ""
    layers = _group_layers(db_path, group)
    if not layers:
        return ""
    main = layers[0]
    by_key = {str(g["key"]): g for g in _GROUPS}
    bits: List[str] = []
    for ign in all_igns:
        g = by_key.get(str(ign.get("_key") or ""))
        if not g:
            continue
        gl = _group_layers(db_path, g)
        if not gl or gl[0] != main:
            continue
        last = float(ign.get("share_last") or 0)
        up = float(ign.get("share_up") or 0)
        if last == 0 and abs(up) < 1e-9:
            continue
        sub = "／".join(gl[1:]) if len(gl) > 1 else gl[0]
        mark = "升" if up > 0 else ("退" if up < 0 else "平")
        bits.append(f"{sub} {_share_txt(last)}（{mark}）")
    if len(bits) < 2:
        return ""
    return "同主產業 " + "｜".join(bits)


def _parity_txt(
    group: Optional[Dict[str, Any]],
    buys: Sequence[Dict[str, Any]],
    leader: Optional[Dict[str, Any]],
) -> str:
    if not group:
        return ""
    lead_sids = {str(x[0]) for x in (group.get("leaders") or ()) if x}
    buy_sids = {str(x.get("sid") or "") for x in buys}
    lead_bought = bool(lead_sids & buy_sids)
    sec_bought = any(str(x.get("role") or "") == "次級" for x in buys)
    broke = bool((leader or {}).get("broke"))
    if broke and sec_bought:
        return "龍頭已先過前高＝來不及買；比價下次級有黃金買點才切入。"
    if not lead_bought and sec_bought:
        return "龍頭這刻沒有黃金買點；比價下次級有買點才切入。"
    if lead_bought and sec_bought:
        return "龍頭有買點；次級只當比價，不是替代買訊。"
    if lead_bought:
        return "先看龍頭。次級還沒買點，不准發明比價切入。"
    return ""


def _lots_txt(val: int) -> str:
    n = int(val)
    body = f"{abs(n):,}"
    if n > 0:
        return f"＋{body}張"
    if n < 0:
        return f"−{body}張"
    return "0張"


def _share_txt(val: float) -> str:
    n = float(val)
    body = f"{abs(n):.1f}%"
    if n < 0:
        return "−" + body
    return body


def _pt_txt(val: float) -> str:
    n = float(val)
    body = f"{abs(n):.1f}pt"
    if n > 0:
        return "＋" + body
    if n < 0:
        return "−" + body
    return "0.0pt"


def _share_path(ign: Dict[str, Any]) -> str:
    shares = list(ign.get("shares") or [])
    if len(shares) >= 2:
        return f"{shares[0]:.1f}%→{shares[-1]:.1f}%（{_pt_txt(shares[-1] - shares[0])}）"
    if shares:
        return _share_txt(shares[-1])
    return ""


def _flow_why(ign: Dict[str, Any]) -> str:
    nets = list(ign.get("nets") or [])
    shares = list(ign.get("shares") or [])
    if not nets and not shares:
        return "法人佔比還沒這列，資金進出不准猜。"
    bits = "/".join(_lots_txt(n).replace("張", "") for n in nets) if nets else ""
    share_bits = "→".join(f"{x:.1f}%" for x in shares) if shares else ""
    if ign.get("flowing_in") or ign.get("slow_in"):
        extra = "佔比在升＝資金流入這細項。"
    elif float(ign.get("share_up") or 0) < 0 or int(ign.get("last") or 0) < 0:
        extra = "佔比在退＝資金流出，不當新點火。"
    else:
        extra = "佔比還沒升，不算流入。"
    fine = str(ign.get("fine_tag") or "").strip()
    fine_bit = f"細項 {fine}。" if fine else ""
    last_sh = float(ign.get("share_last") or 0)
    chg = float(ign.get("share_chg") or 0)
    pos_n = int(ign.get("pos_member") or 0)
    mem_n = int(ign.get("member_n") or 0)
    breadth = f"買超 {pos_n}/{mem_n} 檔。" if mem_n else ""
    share_now = (
        f"佔當日法人買超 {_share_txt(last_sh)}（{_pt_txt(chg)}）。" if shares else ""
    )
    path = f"近{len(shares)}日佔比 {share_bits}。" if share_bits else ""
    lots = (
        f"近{len(nets)}日三大法人 {bits} 累計 {_lots_txt(int(ign.get('cum5') or 0))}。"
        if bits
        else ""
    )
    return fine_bit + share_now + path + lots + breadth + extra


def _flow_rank(ign: Dict[str, Any]) -> Tuple[float, float, int]:
    """先機＝佔比升最多；同分取還比較小的佔比。不拿張數壓過。"""
    return (
        float(ign.get("share_up") or 0.0),
        -float(ign.get("share_last") or 0.0),
        int(ign.get("cum5") or 0),
    )


def _is_money_hot(ign: Dict[str, Any], all_igns: Sequence[Dict[str, Any]]) -> bool:
    """當下資金主戰場＝佔比最高的那族。用數字，不靠他有沒有點名。"""
    last = float(ign.get("share_last") or 0)
    if last <= 0:
        return False
    mx = max((float(x.get("share_last") or 0) for x in all_igns), default=0.0)
    return last + 1e-9 >= mx


def _hot_ref_line(hot: Dict[str, Any], spoken_named: Sequence[str]) -> str:
    if not hot.get("field"):
        named = "、".join(spoken_named)
        return f"飆大點名 {named} 只參考。" if named else ""
    bits = [
        f"佔比最高的 {hot['field']} 佔當日買超 {_share_txt(float(hot.get('share_last') or 0))}"
        f"（近5日 {_pt_txt(float(hot.get('share_up') or 0))}），當下資金主戰場。"
    ]
    named = [n for n in spoken_named if n and n != hot.get("field")]
    if hot.get("field") in spoken_named or named:
        bits.append("飆大點名 " + "、".join([hot["field"]] + named) + " 只參考，不是唯一。")
    else:
        bits.append("飆大只參考，不是唯一。")
    return "".join(bits)


def _five_line(pick: Dict[str, Any], ign: Dict[str, Any], named_hot: Dict[str, Any]) -> str:
    """官方柱＋佔比為主；飆大五件當參考骨架，不准數 5／9。"""
    lead = pick.get("leader") or {}
    lag = pick.get("laggard") or {}
    fine = str(ign.get("fine_tag") or pick.get("field") or "").strip()
    bits = ["對五件（參考）：波浪不數在個股，這族還在底部這層。"]
    if lead:
        bits.append(
            "形態／碎形：龍頭 "
            + str(lead.get("name") or lead.get("sid") or "")
            + (" 還沒先過前高。" if not lead.get("broke") else " 已先過前高。")
        )
    else:
        bits.append("形態／碎形：次族群第一名還沒先過前高，才從底部找落後。")
    if lag and lag.get("volr") is not None:
        try:
            bits.append(
                f"量價：落後檔量比 {float(lag.get('volr') or 0):.2f}、贴近20高。"
            )
        except (TypeError, ValueError):
            bits.append("量價：落後檔量起來才算蠢蠢欲動。")
    path = _share_path(ign)
    if path:
        bits.append(f"主判是佔比：細項{fine}佔法人買超 {path}。")
    hot = named_hot or {}
    if hot.get("field"):
        bits.append(
            f"佔比最高 {hot['field']} {_share_txt(float(hot.get('share_last') or 0))} 當下資金主戰場，只參考點名。"
        )
    bits.append("關鍵K只用官方收。")
    return "".join(bits)


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
    """越高越值得：先這檔佔族流入，再蠢蠢欲動的量價，只在黃金買點列上排。"""
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
        gshare = float(st.get("group_share") or 0.0)
    except (TypeError, ValueError):
        gshare = 0.0
    try:
        cum = int(st.get("cum5") or 0)
    except (TypeError, ValueError):
        cum = 0
    return (1.0 if gshare > 0 or cum > 0 else 0.0, gshare, float(cum), stir, volr, vs20)


def _decorate(
    db_path: str,
    sid: str,
    name: str,
    cap: str,
    row: Optional[Dict[str, Any]],
    *,
    group_last: int = 0,
) -> Dict[str, Any]:
    st = _stats(_bars(db_path, sid, cap)) or {}
    last_net = member_last_net(db_path, sid, cap)
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
        "last_net": last_net,
        "group_share": (100.0 * last_net / group_last) if group_last > 0 else 0.0,
        "fine": _fine_chain(db_path, sid),
    }
    if row:
        item["pick_close"] = row.get("pick_close") or row.get("close")
        item["entry_price"] = row.get("entry_price")
    return item


def dongzhu_picks(db_path: str, *, spoken: Optional[str] = None) -> Dict[str, Any]:
    """洞燭先機鈕：佔比如實主判，飆大找法只參考、不是唯一。切入＝這族 ∩ 黃金買點。"""
    if spoken is None:
        spoken = latest_spoken(db_path) if db_path else ""
    spoken = str(spoken or "")
    pick = pick_unnamed_field(db_path, spoken=spoken)
    cap = str(pick.get("cap") or _cap(db_path) or "")
    chip_cap = _chip_cap(db_path, cap) if db_path else cap
    if db_path and cap:
        try:
            record_dongzhu_flow(db_path, cap)
        except Exception:
            pass
    named_keys = _named_keys(spoken)
    spoken_named = [g["field"] for g in _GROUPS if g["key"] in named_keys]
    flow_hit = None
    all_igns: List[Dict[str, Any]] = []
    named_hot: Dict[str, Any] = {
        "field": "",
        "cum5": 0,
        "share_last": 0.0,
        "share_up": 0.0,
        "share_chg": 0.0,
        "fine_tag": "",
    }
    cands: List[Dict[str, Any]] = []
    flow_cap = chip_cap or cap
    for g in _GROUPS:
        ign = group_ignite(db_path, g["key"], flow_cap) if db_path and flow_cap else {}
        ign = dict(ign or {})
        ign["_field"] = g["field"]
        ign["_key"] = g["key"]
        all_igns.append(ign)
        if float(ign.get("share_last") or 0) > float(named_hot.get("share_last") or 0):
            named_hot = {
                "field": g["field"],
                "cum5": int(ign.get("cum5") or 0),
                "share_last": float(ign.get("share_last") or 0),
                "share_up": float(ign.get("share_up") or 0),
                "share_chg": float(ign.get("share_chg") or 0),
                "fine_tag": str(ign.get("fine_tag") or ""),
            }
        has_share = (
            ign.get("flowing_in")
            or ign.get("slow_in")
            or float(ign.get("share_last") or 0) > 0
            or float(ign.get("share_up") or 0) > 0
        )
        if not has_share:
            continue
        lead_st = None
        for sid, name in g["leaders"][:1]:
            st = _stats(_bars(db_path, sid, cap)) if db_path else None
            if st:
                lead_st = {"sid": sid, "name": name, **st}
                break
        cands.append(
            {
                "group": g,
                "ign": ign,
                "leader": lead_st,
                "named": g["key"] in named_keys,
            }
        )
    unnamed_pos = [
        c
        for c in cands
        if not c["named"] and float(c["ign"].get("share_last") or 0) > 0
    ]
    if unnamed_pos:
        flow_hit = max(
            unnamed_pos,
            key=lambda c: (
                float(c["ign"].get("share_last") or 0.0),
                float(c["ign"].get("share_up") or 0.0),
            ),
        )
    else:
        fresh = [c for c in cands if not _is_money_hot(c["ign"], all_igns)]
        pool = fresh if fresh else cands
        for cand in pool:
            if flow_hit is None or _flow_rank(cand["ign"]) > _flow_rank(flow_hit["ign"]):
                flow_hit = cand
    k_ign = group_ignite(db_path, pick.get("key") or "", flow_cap) if pick.get("key") else {}
    if flow_hit:
        g = flow_hit["group"]
        ign = flow_hit["ign"]
        path = _share_path(ign)
        rot = ""
        if float(named_hot.get("share_up") or 0) < 0 and float(ign.get("share_up") or 0) > 0:
            rot = f"佔比最高的 {named_hot['field']} 在退、這族在升＝輪動。"
        miss = "他沒點名這族。" if g["key"] not in named_keys else ""
        spoken_named = spoken_named or list(pick.get("named") or [])
        pick = {
            **pick,
            "field": g["field"],
            "key": g["key"],
            "group": g,
            "leader": flow_hit.get("leader") or pick.get("leader"),
            "why": (
                f"主判佔比；細項 {ign.get('fine_tag') or g['field']}"
                + (f" 佔當日法人買超 {path}，資金流入。" if path else " 資金流入。")
                + rot
                + miss
                + "不靠他有沒有說蠢蠢欲動。飆大點名只參考，不是唯一。"
            ),
            "named": spoken_named,
        }
        k_ign = ign
    pick["named"] = spoken_named or list(pick.get("named") or [])
    pick["flow"] = k_ign if pick.get("key") else (flow_hit["ign"] if flow_hit else {})
    pick["flow_named_hot"] = named_hot
    pick["hot_ref"] = _hot_ref_line(named_hot, pick.get("named") or [])
    pick["five"] = _five_line(pick, pick.get("flow") or {}, named_hot)
    members = group_members(db_path, pick.get("group"))
    buys_map = _bucket_by_id(db_path, "leave_zero")
    watch_map = _bucket_by_id(db_path, "golden_buy")
    group_last = int((pick.get("flow") or {}).get("last") or 0)
    group = pick.get("group")
    layers = _group_layers(db_path, group)
    buys: List[Dict[str, Any]] = []
    watches: List[Dict[str, Any]] = []
    for sid, name in members:
        if sid in buys_map:
            item = _decorate(db_path, sid, name, cap, buys_map[sid], group_last=group_last)
        elif sid in watch_map:
            item = _decorate(
                db_path, sid, name, cap, watch_map[sid], group_last=group_last
            )
            if item.get("close") is None:
                continue
        else:
            continue
        item["role"] = _stock_role(group, sid)
        item["layers"] = _chain_parts(db_path, sid) or layers
        if sid in buys_map:
            buys.append(item)
        else:
            watches.append(item)
    buys.sort(key=lambda x: _score_member(x, None), reverse=True)
    watches.sort(key=lambda x: _score_member(x, None), reverse=True)
    pick["layers"] = layers
    pick["layer_txt"] = _layer_line(layers)
    pick["sibling_txt"] = _sibling_txt(group, all_igns, db_path)
    pick["parity"] = _parity_txt(group, buys, pick.get("leader") if isinstance(pick.get("leader"), dict) else None)
    laggard = pick.get("laggard")
    if isinstance(laggard, dict) and laggard.get("sid"):
        lag_item = _decorate(
            db_path,
            str(laggard.get("sid")),
            str(laggard.get("name") or ""),
            cap,
            None,
            group_last=group_last,
        )
        lag_item.update({k: laggard[k] for k in ("vs20", "vs60", "volr", "close", "broke") if k in laggard})
        lag_item["role"] = _stock_role(group, str(laggard.get("sid") or ""))
        lag_item["layers"] = _chain_parts(db_path, str(laggard.get("sid") or "")) or layers
        pick["laggards_note"] = lag_item
    taught: List[Dict[str, Any]] = []
    if group:
        for sid, name in list(group.get("laggards") or ()):
            item = _decorate(db_path, sid, name, cap, None, group_last=group_last)
            if item.get("close") is None:
                continue
            item["role"] = _stock_role(group, sid)
            item["layers"] = _chain_parts(db_path, sid) or layers
            taught.append(item)
        taught.sort(key=lambda x: _score_member(x, None), reverse=True)
    pick["laggards"] = taught[:5]
    return {
        **pick,
        "members": members,
        "buys": buys[:5],
        "watches": watches[:5],
        "laggards": pick.get("laggards") or [],
        "laggards_note": pick.get("laggards_note") or laggard,
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
    role = str(item.get("role") or "").strip()
    tag_s = tag if not role else f"{tag}·{role}"
    bits = [f"{idx}. {sid} {name}　{_esc(tag_s)}　收 {close_s}"]
    if vs20 is not None:
        bits.append(f"距20高 {_pct(float(vs20))}")
    if vs60 is not None:
        bits.append(f"距60高 {_pct(float(vs60))}")
    if volr is not None:
        bits.append(f"量比 {float(volr):.2f}")
    layers = item.get("layers") or []
    if layers:
        bits.append(_esc(_layer_short(layers)))
    else:
        fine = str(item.get("fine") or "").strip()
        if fine:
            bits.append(f"細項 {_esc(fine)}")
    if item.get("group_share"):
        bits.append(f"佔這族 {_share_txt(float(item.get('group_share') or 0))}")
    if item.get("cum5"):
        bits.append(f"近5日法人 {_lots_txt(int(item.get('cum5') or 0))}")
    return "　".join(bits)


def dongzhu_page(db_path: str, *, spoken: Optional[str] = None) -> str:
    """主選單洞燭先機頁。飆大找法＋五件＋細項佔比。切入只認高低卡黃金買點。"""
    data = dongzhu_picks(db_path, spoken=spoken)
    cap = _esc(data.get("cap") or "")
    lines = [
        "<b>洞燭先機</b>",
        _esc(data.get("how") or _HOW),
        "佔比如實主判，飆大找法只參考、不是唯一。資金輪動要比到主產業／次產業／細項，再分龍頭與次級：龍頭來不及買，比價下次級有黃金買點才切入。盤中未收不當官方收。不是買訊、不進海選。切入只認高低卡黃金買點。",
    ]
    if cap:
        lines.append(f"官方收 {cap}")
    field = str(data.get("field") or "")
    if not field:
        lines.append(f"<i>{_esc(data.get('line') or '還沒對上底部蠢蠢的次族群，不准發明。不是買訊。')}</i>")
        flow = data.get("flow") or {}
        if flow.get("nets") or flow.get("shares"):
            lines.append(_esc(_flow_why(flow)))
        return "\n".join(lines)
    lines.append(f"<b>此刻最像</b> {_esc(field)}")
    layer_txt = str(data.get("layer_txt") or "")
    if layer_txt:
        lines.append(_esc(layer_txt))
    sib = str(data.get("sibling_txt") or "")
    if sib:
        lines.append(_esc(sib))
    why = str(data.get("why") or "")
    if why:
        lines.append(f"<i>原因：{_esc(why)}</i>")
    five = str(data.get("five") or "")
    if five:
        lines.append(_esc(five))
    flow = data.get("flow") or {}
    lines.append(_esc("資金進出（記在膠帶）" + _flow_why(flow)))
    hot = data.get("flow_named_hot") or {}
    ref = str(data.get("hot_ref") or "")
    if ref:
        lines.append(_esc(ref))
    elif hot.get("field") and (hot.get("share_last") or hot.get("cum5")):
        lines.append(_esc(_hot_ref_line(hot, data.get("named") or [])))
    buys = list(data.get("buys") or [])
    parity = str(data.get("parity") or "")
    lines.append("<b>這族最值得切入</b>（龍頭先看；來不及買才比價次級。都要有黃金買點）")
    if parity:
        lines.append(f"<i>{_esc(parity)}</i>")
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
    shown = {str(x.get("sid") or "") for x in buys + watches}
    lags = [
        x
        for x in list(data.get("laggards") or [])
        if str(x.get("sid") or "") and str(x.get("sid") or "") not in shown
    ]
    if not lags:
        lag = data.get("laggards_note") or data.get("laggard")
        if isinstance(lag, dict) and str(lag.get("sid") or "") not in shown:
            lags = [lag]
    if lags:
        lines.append("<b>落後檔</b>（從底部找；沒黃金買點只觀察，不是買訊）")
        for i, item in enumerate(lags, start=1):
            lines.append(_stock_line(item, i, "落後"))
    lines.append("紅箭頭不是買訊。飆大只參考，不是唯一。")
    return "\n".join(lines)
