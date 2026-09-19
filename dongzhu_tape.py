# -*- coding: utf-8 -*-
"""洞燭／黃金買點／海選落檔與 1／5／10 日官方收對質。

寫在與行情庫同碟的另一檔，公開 zip 帶不走。軟體更新不准 DROP。
不准話筒講、不准當買訊、不准改黃金買點。
"""
from __future__ import annotations

import json
import os
import sqlite3
from typing import Any, Dict, List, Optional, Sequence, Tuple

SCORE_HORIZONS: Tuple[int, ...] = (1, 5, 10)
AS_OF_KEEP = 30
KIND_DONGZHU = "dongzhu"
KIND_SCREEN = "screen"
SCREEN_TAGS = (
    "leave_zero",
    "golden_buy",
    "revenue_cross",
    "select_01",
    "half_year_high",
    "select_02",
    "select_03",
)


def tape_store_path(market_db: str) -> str:
    path = os.path.abspath(str(market_db or "data/wayne_market.db"))
    root = os.path.dirname(path) or "."
    name = os.path.basename(path)
    if name == "wayne_evolve.db":
        return path
    return os.path.join(root, "wayne_evolve.db")


def _ymd(raw: Any) -> str:
    t = str(raw or "").replace("-", "")[:8]
    return t if len(t) == 8 and t.isdigit() else ""


def _f(val: Any) -> Optional[float]:
    try:
        n = float(val)
    except (TypeError, ValueError):
        return None
    if n != n:
        return None
    return n


def ensure_dongzhu_tape_tables(db_path: str) -> None:
    store = tape_store_path(db_path) if db_path else ""
    if not store:
        return
    parent = os.path.dirname(store)
    if parent:
        os.makedirs(parent, exist_ok=True)
    conn = sqlite3.connect(store, timeout=8.0)
    try:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS dongzhu_pick_run (
                kind TEXT NOT NULL DEFAULT 'dongzhu',
                as_of TEXT NOT NULL,
                field TEXT DEFAULT '',
                pre_sign TEXT DEFAULT '',
                share_last REAL DEFAULT 0,
                buy_n INTEGER DEFAULT 0,
                watch_n INTEGER DEFAULT 0,
                capture_n INTEGER DEFAULT 0,
                ran_at TEXT DEFAULT '',
                sha TEXT DEFAULT '',
                encoding TEXT DEFAULT '',
                PRIMARY KEY (kind, as_of)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS dongzhu_pick_tape (
                kind TEXT NOT NULL DEFAULT 'dongzhu',
                as_of TEXT NOT NULL,
                sid TEXT NOT NULL,
                tag TEXT NOT NULL,
                name TEXT DEFAULT '',
                field TEXT DEFAULT '',
                role TEXT DEFAULT '',
                close REAL,
                vs20 REAL,
                vs60 REAL,
                volr REAL,
                why TEXT DEFAULT '',
                enc_id TEXT DEFAULT '',
                encoding TEXT DEFAULT '',
                PRIMARY KEY (kind, as_of, sid, tag)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS dongzhu_pick_rule (
                kind TEXT NOT NULL,
                as_of TEXT NOT NULL,
                tag TEXT NOT NULL,
                enc_id TEXT NOT NULL,
                spec TEXT DEFAULT '',
                sha TEXT DEFAULT '',
                PRIMARY KEY (kind, as_of, tag)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS dongzhu_pick_score (
                kind TEXT NOT NULL DEFAULT 'dongzhu',
                as_of TEXT NOT NULL,
                check_as_of TEXT NOT NULL,
                sid TEXT NOT NULL,
                tag TEXT NOT NULL,
                horizon INTEGER NOT NULL DEFAULT 1,
                pick_close REAL,
                now_close REAL,
                fwd_pct REAL,
                vs20_then REAL,
                vs20_now REAL,
                verdict TEXT NOT NULL,
                note TEXT DEFAULT '',
                PRIMARY KEY (kind, as_of, check_as_of, sid, tag)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS dongzhu_pick_rates (
                kind TEXT NOT NULL DEFAULT 'dongzhu',
                tag TEXT NOT NULL,
                horizon INTEGER NOT NULL DEFAULT 1,
                n INTEGER DEFAULT 0,
                hit INTEGER DEFAULT 0,
                miss INTEGER DEFAULT 0,
                pending INTEGER DEFAULT 0,
                updated_at TEXT DEFAULT '',
                PRIMARY KEY (kind, tag, horizon)
            )
            """
        )
        _migrate_tape_schema(conn)
        conn.commit()
    finally:
        conn.close()


def _table_cols(conn: sqlite3.Connection, name: str) -> set:
    try:
        return {str(r[1]) for r in conn.execute(f"PRAGMA table_info({name})")}
    except sqlite3.Error:
        return set()


def _migrate_tape_schema(conn: sqlite3.Connection) -> None:
    """只加欄，不准 DROP 對質列。"""
    for table, col, spec in (
        ("dongzhu_pick_run", "kind", "TEXT DEFAULT 'dongzhu'"),
        ("dongzhu_pick_run", "sha", "TEXT DEFAULT ''"),
        ("dongzhu_pick_run", "encoding", "TEXT DEFAULT ''"),
        ("dongzhu_pick_tape", "kind", "TEXT DEFAULT 'dongzhu'"),
        ("dongzhu_pick_tape", "enc_id", "TEXT DEFAULT ''"),
        ("dongzhu_pick_tape", "encoding", "TEXT DEFAULT ''"),
        ("dongzhu_pick_score", "kind", "TEXT DEFAULT 'dongzhu'"),
        ("dongzhu_pick_score", "horizon", "INTEGER DEFAULT 1"),
        ("dongzhu_pick_rates", "kind", "TEXT DEFAULT 'dongzhu'"),
        ("dongzhu_pick_rates", "horizon", "INTEGER DEFAULT 1"),
    ):
        cols = _table_cols(conn, table)
        if cols and col not in cols:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {spec}")


def _now_iso() -> str:
    from datetime import datetime

    return datetime.now().isoformat(timespec="seconds")


def _sha() -> str:
    for key in ("RENDER_GIT_COMMIT", "WAYNE_GIT_SHA", "GITHUB_SHA"):
        val = str(os.environ.get(key) or "").strip()
        if val:
            return val[:12]
    return ""


def frozen_rule_catalog() -> Dict[str, Any]:
    """當下程式裡的選股編碼。落檔時整份凍住，之後改碼也不回寫舊列。"""
    max_pct = 5.0
    pre_vs20 = -8.0
    lag_n = 3
    lookback = 100
    win = 70.8
    try:
        from decision_card_signals import LEAVE_ZERO_SCREEN_MAX_PCT

        max_pct = float(LEAVE_ZERO_SCREEN_MAX_PCT)
    except Exception:
        pass
    try:
        from biaoke_field_scan import FLOW_LOOKBACK, LAG_CAPTURE_N, PRE_BUY_WIN_PCT, PRE_VS20

        pre_vs20 = float(PRE_VS20)
        lag_n = int(LAG_CAPTURE_N)
        lookback = int(FLOW_LOOKBACK)
        win = float(PRE_BUY_WIN_PCT)
    except Exception:
        pass
    return {
        "leave_zero": {
            "enc_id": "leave_zero.cal60_leave0_max5",
            "profit": "近60曆日收盤低",
            "just_left": "昨<=0.05今>0.05",
            "max_pct": max_pct,
            "not": "紅箭頭不是買訊",
        },
        "golden_buy": {
            "enc_id": "golden_buy.cal60_floor_observe",
            "at_60_low": True,
            "profit": [-1.5, 2.5],
            "bias_monthly_lt": -10.0,
            "not_buy": True,
        },
        "capture": {
            "enc_id": "dongzhu.chain_lag_vs20",
            "pre_vs20": pre_vs20,
            "n": lag_n,
            "not_buy": True,
        },
        "dongzhu_pre": {
            "enc_id": "dongzhu.share_up_not_first",
            "flow_lookback": lookback,
            "win": win,
        },
        "revenue_cross": {"enc_id": "screen.revenue_cross", "not_buy": True},
        "select_01": {"enc_id": "screen.select_01", "not_buy": True},
        "half_year_high": {"enc_id": "screen.half_year_high", "not_buy": True},
        "select_02": {"enc_id": "screen.select_02", "not_buy": True},
        "select_03": {"enc_id": "screen.select_03", "not_buy": True},
    }


def _enc_id_for(tag: str) -> str:
    spec = frozen_rule_catalog().get(str(tag) or "") or {}
    return str(spec.get("enc_id") or tag or "")


def _item_encoding(
    tag: str, item: Dict[str, Any], field: str, pre_sign: str
) -> Tuple[str, str]:
    enc_id = _enc_id_for(tag)
    payload: Dict[str, Any] = {
        "enc_id": enc_id,
        "sha": _sha(),
        "close": _f(item.get("close") or item.get("pick_close")),
        "profit": _f(item.get("profit") or item.get("profit_pct")),
        "yest_profit": _f(item.get("yest_profit_pct") or item.get("yest_profit")),
        "vs20": _f(item.get("vs20")),
        "vs60": _f(item.get("vs60")),
        "volr": _f(item.get("volr")),
        "vol_rank_120": _f(item.get("vol_rank_120")),
        "bias_monthly": _f(item.get("bias_monthly")),
        "at_60_low": item.get("at_60_low"),
        "field": field or str(item.get("field") or ""),
        "pre_sign": pre_sign or str(item.get("pre_sign") or ""),
        "role": str(item.get("role") or ""),
        "hl": str(item.get("hl") or item.get("hl_tag") or ""),
        "alert": str(item.get("alert") or item.get("today_alert") or ""),
        "reason": str(item.get("reason") or item.get("lz_reason") or ""),
        "leave_l20": item.get("leave_l20"),
        "chip_cap": str(item.get("chip_cap") or ""),
    }
    slim = {k: v for k, v in payload.items() if v is not None and v != ""}
    return enc_id, json.dumps(slim, ensure_ascii=False, separators=(",", ":"))


def _write_rule_catalog(conn: sqlite3.Connection, kind: str, cap: str) -> None:
    sha = _sha()
    catalog = frozen_rule_catalog()
    for tag, spec in catalog.items():
        conn.execute(
            """
            INSERT OR REPLACE INTO dongzhu_pick_rule(
                kind, as_of, tag, enc_id, spec, sha
            ) VALUES (?,?,?,?,?,?)
            """,
            (
                kind,
                cap,
                str(tag),
                str(spec.get("enc_id") or tag),
                json.dumps(spec, ensure_ascii=False, separators=(",", ":")),
                sha,
            ),
        )


def _why(tag: str, item: Dict[str, Any], field: str, pre_sign: str) -> str:
    vs = _f(item.get("vs20"))
    vs_s = f"距20高 {vs:+.1f}%" if vs is not None else ""
    bits = []
    if tag == "leave_zero":
        bits.append("黃金買點獲利剛離零")
    elif tag == "golden_buy":
        bits.append("60低超跌觀察不是買")
    else:
        bits.append("同鏈比價落後不是買訊")
    if field:
        bits.append(str(field))
    if pre_sign == "pre":
        bits.append("佔比升還沒第一")
    elif pre_sign == "chase":
        bits.append("已是當天第一偏晚")
    elif pre_sign == "leaving":
        bits.append("佔比在退")
    if vs_s:
        bits.append(vs_s)
    return "；".join(bits)


def _iter_pick_rows(data: Dict[str, Any]) -> List[Tuple[str, Dict[str, Any]]]:
    out: List[Tuple[str, Dict[str, Any]]] = []
    seen = set()
    for tag, key in (
        ("leave_zero", "buys"),
        ("golden_buy", "watches"),
        ("capture", "laggards"),
    ):
        for item in list(data.get(key) or []):
            sid = str(item.get("sid") or "").strip()
            if not sid or (sid, tag) in seen:
                continue
            close = _f(item.get("close") or item.get("pick_close"))
            if close is None or close <= 0:
                continue
            seen.add((sid, tag))
            out.append((tag, item))
    return out


def write_snapshot(db_path: str, data: Dict[str, Any], *, kind: str = KIND_DONGZHU) -> int:
    """把當日名單寫進進化庫。沒官方收盤的不上。不准刪舊日。"""
    if not db_path or not isinstance(data, dict):
        return 0
    cap = _ymd(data.get("cap") or data.get("chip_cap"))
    if not cap:
        return 0
    kind = str(kind or KIND_DONGZHU)
    ensure_dongzhu_tape_tables(db_path)
    store = tape_store_path(db_path)
    field = str(data.get("field") or "")
    pre_sign = str(data.get("pre_sign") or "")
    share_last = _f((data.get("flow") or {}).get("share_last")) or 0.0
    rows = _iter_pick_rows(data)
    buy_n = sum(1 for t, _ in rows if t == "leave_zero")
    watch_n = sum(1 for t, _ in rows if t == "golden_buy")
    cap_n = sum(1 for t, _ in rows if t == "capture")
    conn = sqlite3.connect(store, timeout=8.0)
    try:
        conn.execute(
            """
            INSERT OR REPLACE INTO dongzhu_pick_run(
                kind, as_of, field, pre_sign, share_last, buy_n, watch_n, capture_n,
                ran_at, sha, encoding
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                kind,
                cap,
                field,
                pre_sign,
                share_last,
                buy_n,
                watch_n,
                cap_n,
                _now_iso(),
                _sha(),
                json.dumps(frozen_rule_catalog(), ensure_ascii=False, separators=(",", ":")),
            ),
        )
        conn.execute(
            "DELETE FROM dongzhu_pick_tape WHERE kind=? AND as_of=?",
            (kind, cap),
        )
        for tag, item in rows:
            sid = str(item.get("sid") or "").strip()
            enc_id, enc_js = _item_encoding(tag, item, field, pre_sign)
            conn.execute(
                """
                INSERT OR REPLACE INTO dongzhu_pick_tape(
                    kind, as_of, sid, tag, name, field, role, close, vs20, vs60, volr,
                    why, enc_id, encoding
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    kind,
                    cap,
                    sid,
                    tag,
                    str(item.get("name") or sid),
                    field,
                    str(item.get("role") or ""),
                    _f(item.get("close") or item.get("pick_close")),
                    _f(item.get("vs20")),
                    _f(item.get("vs60")),
                    _f(item.get("volr")),
                    _why(tag, item, field, pre_sign),
                    enc_id,
                    enc_js,
                ),
            )
        _write_rule_catalog(conn, kind, cap)
        conn.commit()
    finally:
        conn.close()
    return len(rows)


def snapshot_dongzhu_picks(db_path: str, cap: str = "", *, spoken: str = "") -> int:
    """盤後自動跑，不等人按洞燭鈕。spoken 空＝機制名單，不被當下問句帶跑。"""
    if not db_path:
        return 0
    from biaoke_field_scan import _cap, dongzhu_picks

    data = dongzhu_picks(db_path, spoken=spoken)
    if cap:
        data["cap"] = _ymd(cap) or data.get("cap")
    elif not _ymd(data.get("cap")):
        data["cap"] = _cap(db_path)
    return write_snapshot(db_path, data, kind=KIND_DONGZHU)


def snapshot_screen_picks(
    db_path: str, cap: str = "", *, results: Optional[Dict[str, Any]] = None
) -> int:
    """海選黃金買點與其他選股桶，不必等人看海選。當沖／隔日沖不收。"""
    cap = _ymd(cap)
    if not db_path or not cap:
        return 0
    items: List[Tuple[str, Dict[str, Any]]] = []
    if isinstance(results, dict):
        for tag in SCREEN_TAGS:
            for raw in list(results.get(tag) or []):
                if not isinstance(raw, dict):
                    continue
                sid = str(raw.get("sid") or raw.get("stock_id") or raw.get("code") or "").strip()
                px = _f(raw.get("close") or raw.get("pick_close"))
                if not sid or px is None or px <= 0:
                    continue
                item = dict(raw)
                item["sid"] = sid
                item["name"] = str(raw.get("name") or raw.get("stock_name") or sid)
                item["close"] = px
                items.append((tag, item))
    else:
        from screen_sessions import ensure_screen_session_table

        ensure_screen_session_table(db_path)
        conn = sqlite3.connect(db_path, timeout=8.0)
        try:
            sess_row = conn.execute(
                """
                SELECT session FROM screen_sessions
                WHERE as_of=? AND session IN ('morning','evening')
                ORDER BY CASE session WHEN 'morning' THEN 0 ELSE 1 END
                LIMIT 1
                """,
                (cap,),
            ).fetchone()
            session = str(sess_row[0] if sess_row else "")
            if not session:
                return 0
            marks = ",".join("?" * len(SCREEN_TAGS))
            rows = conn.execute(
                f"""
                SELECT bucket, stock_id, stock_name, pick_close
                FROM screen_sessions
                WHERE as_of=? AND session=? AND bucket IN ({marks})
                """,
                (cap, session, *SCREEN_TAGS),
            ).fetchall()
        except sqlite3.Error:
            return 0
        finally:
            conn.close()
        for bucket, sid, name, close in rows:
            px = _f(close)
            s = str(sid or "").strip()
            if not s or px is None or px <= 0:
                continue
            items.append(
                (str(bucket or ""), {"sid": s, "name": str(name or s), "close": px})
            )
    data: Dict[str, Any] = {
        "cap": cap,
        "field": "",
        "pre_sign": "",
        "buys": [it for tag, it in items if tag == "leave_zero"],
        "watches": [it for tag, it in items if tag == "golden_buy"],
        "laggards": [],
    }
    n = write_snapshot(db_path, data, kind=KIND_SCREEN)
    extras = [(tag, it) for tag, it in items if tag not in ("leave_zero", "golden_buy")]
    if not extras:
        return n
    store = tape_store_path(db_path)
    conn = sqlite3.connect(store, timeout=8.0)
    try:
        for tag, item in extras:
            enc_id, enc_js = _item_encoding(tag, item, "", "")
            conn.execute(
                """
                INSERT OR REPLACE INTO dongzhu_pick_tape(
                    kind, as_of, sid, tag, name, field, role, close, vs20, vs60, volr,
                    why, enc_id, encoding
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    KIND_SCREEN,
                    cap,
                    item["sid"],
                    tag,
                    item["name"],
                    "",
                    "",
                    item["close"],
                    _f(item.get("vs20")),
                    _f(item.get("vs60")),
                    _f(item.get("volr")),
                    "海選選股不是買訊",
                    enc_id,
                    enc_js,
                ),
            )
            n += 1
        conn.commit()
    finally:
        conn.close()
    return n


def _quote_days(db_path: str, cap: str) -> List[str]:
    """有官方收>0 的交易日。沒有就不當交易日。"""
    cap = _ymd(cap)
    if not db_path or not cap:
        return []
    conn = sqlite3.connect(db_path, timeout=8.0)
    try:
        rows = conn.execute(
            """
            SELECT DISTINCT REPLACE(CAST(date AS TEXT),'-','')
            FROM daily_quotes
            WHERE close IS NOT NULL AND close > 0
              AND REPLACE(CAST(date AS TEXT),'-','') <= ?
            ORDER BY 1
            """,
            (cap,),
        ).fetchall()
    except sqlite3.Error:
        return []
    finally:
        conn.close()
    out: List[str] = []
    for (raw,) in rows:
        day = _ymd(raw)
        if day:
            out.append(day)
    return out


def _horizon_day(days: Sequence[str], as_of: str, horizon: int) -> str:
    """as_of 之後第 horizon 根官方交易日。不夠就不回。"""
    as_of = _ymd(as_of)
    if not as_of or horizon <= 0:
        return ""
    after = [d for d in days if d > as_of]
    if len(after) < horizon:
        return ""
    return after[horizon - 1]


def _verdict(tag: str, fwd: Optional[float], vs_delta: Optional[float]) -> Tuple[str, str]:
    """對／偏／還沒走完。只用官方收與當時 vs20，不 invent。"""
    if tag == "capture":
        if vs_delta is not None and vs_delta > 1.0:
            return "對", "距20高拉近＝補漲方向"
        if vs_delta is not None and vs_delta < -1.0:
            return "偏", "距20高更深"
        return "還沒走完", "補漲還沒走完"
    if fwd is None:
        return "還沒走完", "還沒官方收"
    if fwd > 0.5:
        return "對", f"收 {fwd:+.1f}%"
    if fwd < -0.5:
        return "偏", f"收 {fwd:+.1f}%"
    return "還沒走完", f"收 {fwd:+.1f}%"


def _official_close(db_path: str, sid: str, day: str) -> Optional[float]:
    """只認這檔這日官方收。沒有、0、負的都不當已知。"""
    day = _ymd(day)
    if not db_path or not sid or not day:
        return None
    conn = sqlite3.connect(db_path, timeout=8.0)
    try:
        row = conn.execute(
            "SELECT close FROM daily_quotes WHERE stock_id=? "
            "AND REPLACE(CAST(date AS TEXT),'-','')=?",
            (sid, day),
        ).fetchone()
    except sqlite3.Error:
        return None
    finally:
        conn.close()
    close = _f(row[0] if row else None)
    if close is None or close <= 0:
        return None
    return close


def _vs20_on(db_path: str, sid: str, day: str) -> Optional[float]:
    """vs20 必須是 check 當日那根官方柱算出來的，不准拿前一日冒充。"""
    day = _ymd(day)
    if not db_path or not sid or not day:
        return None
    from biaoke_field_scan import _bars, _stats

    st = _stats(_bars(db_path, sid, day)) or {}
    if _ymd(st.get("date")) != day:
        return None
    return _f(st.get("vs20"))


def score_dongzhu_picks(db_path: str, check_as_of: str) -> int:
    """每個盤後：對所有近期落檔，能對到的 1／5／10 日窗都寫。不用人操作。"""
    cap = _ymd(check_as_of)
    if not db_path or not cap:
        return 0
    ensure_dongzhu_tape_tables(db_path)
    store = tape_store_path(db_path)
    days = _quote_days(db_path, cap)
    if not days:
        return 0
    floor = days[-AS_OF_KEEP] if len(days) > AS_OF_KEEP else ""
    conn = sqlite3.connect(store, timeout=8.0)
    try:
        runs = [
            (str(r[0] or KIND_DONGZHU), _ymd(r[1]))
            for r in conn.execute(
                "SELECT kind, as_of FROM dongzhu_pick_run WHERE as_of < ? ORDER BY as_of",
                (cap,),
            ).fetchall()
        ]
    finally:
        conn.close()
    scored = 0
    conn = sqlite3.connect(store, timeout=8.0)
    try:
        for kind, as_of in runs:
            if not as_of or (floor and as_of < floor):
                continue
            picks = conn.execute(
                "SELECT sid, tag, close, vs20 FROM dongzhu_pick_tape WHERE kind=? AND as_of=?",
                (kind, as_of),
            ).fetchall()
            if not picks:
                continue
            for horizon in SCORE_HORIZONS:
                target = _horizon_day(days, as_of, horizon)
                if not target or target > cap:
                    continue
                scored += _score_rows(
                    conn, db_path, kind, as_of, target, int(horizon), picks
                )
        conn.commit()
    finally:
        conn.close()
    _refresh_rates(db_path)
    return scored


def _score_rows(
    conn: sqlite3.Connection,
    db_path: str,
    kind: str,
    as_of: str,
    check_as_of: str,
    horizon: int,
    picks: Sequence[Tuple[Any, ...]],
) -> int:
    n = 0
    for sid, tag, pick_close, vs20_then in picks:
        sid = str(sid or "").strip()
        tag = str(tag or "")
        px = _f(pick_close)
        if not sid or px is None or px <= 0:
            continue
        now_c = _official_close(db_path, sid, check_as_of)
        if now_c is None:
            continue
        fwd = (now_c / px - 1.0) * 100.0
        vs_now = _vs20_on(db_path, sid, check_as_of)
        vs_then = _f(vs20_then)
        vs_delta = (
            (vs_now - vs_then) if vs_now is not None and vs_then is not None else None
        )
        verdict, note = _verdict(tag, fwd, vs_delta)
        conn.execute(
            """
            INSERT OR REPLACE INTO dongzhu_pick_score(
                kind, as_of, check_as_of, sid, tag, horizon, pick_close, now_close,
                fwd_pct, vs20_then, vs20_now, verdict, note
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                kind,
                as_of,
                check_as_of,
                sid,
                tag,
                int(horizon),
                px,
                now_c,
                round(fwd, 2),
                vs_then,
                vs_now,
                verdict,
                note,
            ),
        )
        n += 1
    return n


def _refresh_rates(db_path: str) -> None:
    """各窗累計對質。這是紀錄，不是改黃金買點。"""
    store = tape_store_path(db_path)
    conn = sqlite3.connect(store, timeout=8.0)
    try:
        rows = conn.execute(
            """
            SELECT kind, tag, horizon,
                   SUM(CASE WHEN verdict='對' THEN 1 ELSE 0 END),
                   SUM(CASE WHEN verdict='偏' THEN 1 ELSE 0 END),
                   SUM(CASE WHEN verdict='還沒走完' THEN 1 ELSE 0 END),
                   COUNT(*)
            FROM dongzhu_pick_score
            GROUP BY kind, tag, horizon
            """
        ).fetchall()
        now = _now_iso()
        conn.execute("DELETE FROM dongzhu_pick_rates")
        for kind, tag, horizon, hit, miss, pending, n in rows:
            conn.execute(
                """
                INSERT OR REPLACE INTO dongzhu_pick_rates(
                    kind, tag, horizon, n, hit, miss, pending, updated_at
                ) VALUES (?,?,?,?,?,?,?,?)
                """,
                (
                    str(kind or KIND_DONGZHU),
                    str(tag),
                    int(horizon or 1),
                    int(n or 0),
                    int(hit or 0),
                    int(miss or 0),
                    int(pending or 0),
                    now,
                ),
            )
        conn.commit()
    finally:
        conn.close()


def snapshot_and_score_dongzhu(db_path: str, cap: str) -> Dict[str, Any]:
    """盤後齊了：先對近期落檔的 1／5／10 日，再寫洞燭＋海選檔。不推話筒。"""
    cap = _ymd(cap)
    if not db_path or not cap:
        return {"snap": 0, "scored": 0, "cap": cap, "screen": 0}
    scored = score_dongzhu_picks(db_path, cap)
    snap = snapshot_dongzhu_picks(db_path, cap, spoken="")
    screen = snapshot_screen_picks(db_path, cap)
    return {"snap": int(snap), "scored": int(scored), "screen": int(screen), "cap": cap}


def scoreboard_lines(db_path: str, cap: str = "") -> List[str]:
    """內部對質摘要。頁面不顯示。"""
    if not db_path:
        return []
    ensure_dongzhu_tape_tables(db_path)
    store = tape_store_path(db_path)
    cap = _ymd(cap)
    conn = sqlite3.connect(store, timeout=8.0)
    try:
        if not cap:
            row = conn.execute(
                "SELECT MAX(check_as_of) FROM dongzhu_pick_score"
            ).fetchone()
            cap = _ymd(row[0] if row else "")
        if not cap:
            return []
        scores = conn.execute(
            """
            SELECT sid, name, tag, verdict, COALESCE(s.horizon, 1)
            FROM dongzhu_pick_score s
            JOIN dongzhu_pick_tape t USING (kind, as_of, sid, tag)
            WHERE s.check_as_of=?
            ORDER BY COALESCE(s.horizon, 1),
                     CASE s.tag WHEN 'leave_zero' THEN 0 WHEN 'capture' THEN 1 ELSE 2 END,
                     s.sid
            """,
            (cap,),
        ).fetchall()
        rate_h = conn.execute(
            "SELECT MAX(horizon) FROM dongzhu_pick_rates WHERE n>0"
        ).fetchone()
        want_h = int(rate_h[0] or 1) if rate_h and rate_h[0] else 1
        rates = conn.execute(
            """
            SELECT tag, horizon, n, hit, miss, pending
            FROM dongzhu_pick_rates
            WHERE horizon=?
            ORDER BY tag
            """,
            (want_h,),
        ).fetchall()
        if not rates:
            rates = conn.execute(
                "SELECT tag, horizon, n, hit, miss, pending FROM dongzhu_pick_rates ORDER BY tag"
            ).fetchall()
            want_h = int(rates[0][1]) if rates else 1
    except sqlite3.Error:
        return []
    finally:
        conn.close()
    if not scores:
        return []
    lines = [f"{want_h}日對質 {cap[4:6]}/{cap[6:]}"]
    if len(lines[0]) > 18:
        lines = [f"{want_h}日對質", f"官方收 {cap[4:6]}/{cap[6:]}"]
    for sid, name, _tag, verdict, horizon in scores[:6]:
        nm = str(name or sid)
        h = int(horizon or 1)
        bit = f"{sid} {nm} {verdict}"
        if h != want_h:
            bit = f"{sid} {h}日{verdict}"
        lines.append(bit)
    titles = {"leave_zero": "買點", "capture": "捕捉", "golden_buy": "觀察"}
    for tag, horizon, n, hit, miss, pending in rates:
        if int(n or 0) <= 0:
            continue
        title = titles.get(str(tag), str(tag))
        lines.append(f"{title}對{int(hit)}偏{int(miss)}還沒{int(pending)}")
    lines.append("不是改黃金買點")
    return lines
