# -*- coding: utf-8 -*-
"""洞燭／海選各自落檔與 1／5／10 日官方收對質。

寫在與行情庫同碟的另一檔，公開 zip 帶不走。軟體更新不准 DROP。
不准話筒講、不准當買訊、不准改黃金買點、不准改現有選股公式。
功能分開：洞燭≠海選；官方收可共用。
"""
from __future__ import annotations

import json
import os
import sqlite3
from typing import Any, Dict, List, Optional, Sequence, Tuple

SCORE_HORIZONS: Tuple[int, ...] = (1, 5, 10)
AS_OF_KEEP = 30
OPTIMIZE_MIN_N = 20
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


def _now_iso() -> str:
    from datetime import datetime

    return datetime.now().isoformat(timespec="seconds")


def _sha() -> str:
    for key in ("RENDER_GIT_COMMIT", "WAYNE_GIT_SHA", "GITHUB_SHA"):
        val = str(os.environ.get(key) or "").strip()
        if val:
            return val[:12]
    return ""


def _table_cols(conn: sqlite3.Connection, name: str) -> set:
    try:
        return {str(r[1]) for r in conn.execute(f"PRAGMA table_info({name})")}
    except sqlite3.Error:
        return set()


def ensure_dongzhu_tape_tables(db_path: str) -> None:
    store = tape_store_path(db_path) if db_path else ""
    if not store:
        return
    parent = os.path.dirname(store)
    if parent:
        os.makedirs(parent, exist_ok=True)
    conn = sqlite3.connect(store, timeout=8.0)
    try:
        _create_dongzhu_tables(conn)
        _create_screen_tables(conn)
        _migrate_tape_schema(conn)
        _copy_mixed_screen_rows(conn)
        conn.commit()
    finally:
        conn.close()


def _create_dongzhu_tables(conn: sqlite3.Connection) -> None:
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


def _create_screen_tables(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS screen_pick_run (
            as_of TEXT NOT NULL PRIMARY KEY,
            n INTEGER DEFAULT 0,
            ran_at TEXT DEFAULT '',
            sha TEXT DEFAULT '',
            encoding TEXT DEFAULT ''
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS screen_pick_tape (
            as_of TEXT NOT NULL,
            sid TEXT NOT NULL,
            tag TEXT NOT NULL,
            name TEXT DEFAULT '',
            close REAL,
            vs20 REAL,
            vs60 REAL,
            volr REAL,
            why TEXT DEFAULT '',
            enc_id TEXT DEFAULT '',
            encoding TEXT DEFAULT '',
            PRIMARY KEY (as_of, sid, tag)
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS screen_pick_rule (
            as_of TEXT NOT NULL,
            tag TEXT NOT NULL,
            enc_id TEXT NOT NULL,
            spec TEXT DEFAULT '',
            sha TEXT DEFAULT '',
            PRIMARY KEY (as_of, tag)
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS screen_pick_score (
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
            PRIMARY KEY (as_of, check_as_of, sid, tag)
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS screen_pick_rates (
            tag TEXT NOT NULL,
            horizon INTEGER NOT NULL DEFAULT 1,
            n INTEGER DEFAULT 0,
            hit INTEGER DEFAULT 0,
            miss INTEGER DEFAULT 0,
            pending INTEGER DEFAULT 0,
            updated_at TEXT DEFAULT '',
            PRIMARY KEY (tag, horizon)
        )
        """
    )


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


def _insert_common(
    conn: sqlite3.Connection, src: str, dst: str, where: str
) -> None:
    src_cols = _table_cols(conn, src)
    dst_cols = _table_cols(conn, dst)
    if not src_cols or not dst_cols:
        return
    order = (
        "as_of",
        "sid",
        "tag",
        "name",
        "close",
        "vs20",
        "vs60",
        "volr",
        "why",
        "enc_id",
        "encoding",
        "check_as_of",
        "horizon",
        "pick_close",
        "now_close",
        "fwd_pct",
        "vs20_then",
        "vs20_now",
        "verdict",
        "note",
        "ran_at",
        "sha",
        "n",
        "hit",
        "miss",
        "pending",
        "updated_at",
        "spec",
    )
    common = [c for c in order if c in src_cols and c in dst_cols]
    if not common:
        return
    cols = ",".join(common)
    conn.execute(
        f"INSERT OR IGNORE INTO {dst} ({cols}) SELECT {cols} FROM {src} WHERE {where}"
    )


def _copy_mixed_screen_rows(conn: sqlite3.Connection) -> None:
    """舊版誤寫進洞燭表的海選列，抄到海選自己的表。不准刪舊列。"""
    if "kind" not in _table_cols(conn, "dongzhu_pick_tape"):
        return
    _insert_common(conn, "dongzhu_pick_run", "screen_pick_run", "kind='screen'")
    _insert_common(conn, "dongzhu_pick_tape", "screen_pick_tape", "kind='screen'")
    _insert_common(conn, "dongzhu_pick_rule", "screen_pick_rule", "kind='screen'")
    _insert_common(conn, "dongzhu_pick_score", "screen_pick_score", "kind='screen'")
    _insert_common(conn, "dongzhu_pick_rates", "screen_pick_rates", "kind='screen'")


def _leave_zero_spec(*, scope: str, enc_id: str) -> Dict[str, Any]:
    max_pct = 5.0
    try:
        from decision_card_signals import LEAVE_ZERO_SCREEN_MAX_PCT

        max_pct = float(LEAVE_ZERO_SCREEN_MAX_PCT)
    except Exception:
        pass
    return {
        "enc_id": enc_id,
        "scope": scope,
        "profit": "近60曆日收盤低",
        "just_left": "昨<=0.05今>0.05",
        "max_pct": max_pct,
        "not": "紅箭頭不是買訊",
    }


def _golden_buy_spec(*, scope: str, enc_id: str) -> Dict[str, Any]:
    return {
        "enc_id": enc_id,
        "scope": scope,
        "at_60_low": True,
        "profit": [-1.5, 2.5],
        "bias_monthly_lt": -10.0,
        "not_buy": True,
    }


def frozen_dongzhu_catalog() -> Dict[str, Any]:
    """洞燭當下編碼。落檔凍住，之後改碼不回寫舊列。"""
    pre_vs20 = -8.0
    lag_n = 3
    lookback = 100
    win = 70.8
    try:
        from biaoke_field_scan import FLOW_LOOKBACK, LAG_CAPTURE_N, PRE_BUY_WIN_PCT, PRE_VS20

        pre_vs20 = float(PRE_VS20)
        lag_n = int(LAG_CAPTURE_N)
        lookback = int(FLOW_LOOKBACK)
        win = float(PRE_BUY_WIN_PCT)
    except Exception:
        pass
    return {
        "leave_zero": _leave_zero_spec(
            scope="先機∩高低卡", enc_id="dongzhu.leave_zero.cal60_leave0_max5"
        ),
        "golden_buy": _golden_buy_spec(
            scope="先機觀察", enc_id="dongzhu.golden_buy.cal60_floor_observe"
        ),
        "capture": {
            "enc_id": "dongzhu.chain_lag_vs20",
            "scope": "洞燭捕捉",
            "pre_vs20": pre_vs20,
            "n": lag_n,
            "not_buy": True,
        },
        "dongzhu_pre": {
            "enc_id": "dongzhu.share_up_not_first",
            "scope": "洞燭先機",
            "flow_lookback": lookback,
            "win": win,
        },
    }


def frozen_screen_catalog() -> Dict[str, Any]:
    """海選當下編碼。與洞燭分開凍。"""
    return {
        "leave_zero": _leave_zero_spec(
            scope="海選全市場", enc_id="screen.leave_zero.cal60_leave0_max5"
        ),
        "golden_buy": _golden_buy_spec(
            scope="海選全市場", enc_id="screen.golden_buy.cal60_floor_observe"
        ),
        "revenue_cross": {
            "enc_id": "screen.revenue_cross",
            "scope": "海選",
            "need": "營收轉強×量價突破",
            "trend_up": True,
            "not_buy": True,
        },
        "select_01": {
            "enc_id": "screen.select_01",
            "scope": "海選",
            "break_hi5": True,
            "q60r_ge": 2.0,
            "pct_gt": 0.5,
            "trend_up": True,
            "not_buy": True,
        },
        "half_year_high": {
            "enc_id": "screen.half_year_high",
            "scope": "海選",
            "c_ge_hi120": True,
            "q60r_ge": 2.5,
            "pct_ge": 3.0,
            "trend_up": True,
            "not_buy": True,
        },
        "select_02": {
            "enc_id": "screen.select_02",
            "scope": "海選",
            "prev_below_ma60": True,
            "close_ge_ma60": True,
            "pct_gt": 0,
            "q60r_ge": 1.0,
            "trend_up": True,
            "not_buy": True,
        },
        "select_03": {
            "enc_id": "screen.select_03",
            "scope": "海選",
            "near_low20_max": 1.06,
            "q60r_ge": 1.0,
            "pct_gt": 0,
            "ma5_hook_or_red": True,
            "trend_up": True,
            "not_buy": True,
        },
    }


def frozen_rule_catalog() -> Dict[str, Any]:
    """洞燭編碼。海選請用 frozen_screen_catalog。"""
    return frozen_dongzhu_catalog()


def _enc_id_for(tag: str, catalog: Dict[str, Any]) -> str:
    spec = catalog.get(str(tag) or "") or {}
    return str(spec.get("enc_id") or tag or "")


def _item_encoding(
    tag: str,
    item: Dict[str, Any],
    field: str,
    pre_sign: str,
    catalog: Dict[str, Any],
) -> Tuple[str, str]:
    spec = catalog.get(str(tag) or "") or {}
    enc_id = str(spec.get("enc_id") or tag or "")
    payload: Dict[str, Any] = {
        "enc_id": enc_id,
        "sha": _sha(),
        "scope": spec.get("scope") or "",
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
        "hi20": _f(item.get("hi20_close") or item.get("hi20")),
        "entry": _f(item.get("entry_price")),
        "defense": _f(item.get("defense_price")),
        "chase_warning": item.get("chase_warning"),
        "q60r": _f(item.get("q60r")),
        "hi5": _f(item.get("hi5")),
        "hi120": _f(item.get("hi120")),
        "hi480": _f(item.get("hi480")),
        "pct_change": _f(item.get("pct_change")),
        "ma20": _f(item.get("ma20")),
        "ma60": _f(item.get("ma60")),
        "low20": _f(item.get("low20")),
        "d20": _f(item.get("d20")),
        "pattern": str(item.get("pattern") or ""),
    }
    slim = {k: v for k, v in payload.items() if v is not None and v != ""}
    return enc_id, json.dumps(slim, ensure_ascii=False, separators=(",", ":"))


def _write_dongzhu_rules(conn: sqlite3.Connection, cap: str) -> None:
    sha = _sha()
    for tag, spec in frozen_dongzhu_catalog().items():
        conn.execute(
            """
            INSERT OR REPLACE INTO dongzhu_pick_rule(
                kind, as_of, tag, enc_id, spec, sha
            ) VALUES (?,?,?,?,?,?)
            """,
            (
                KIND_DONGZHU,
                cap,
                str(tag),
                str(spec.get("enc_id") or tag),
                json.dumps(spec, ensure_ascii=False, separators=(",", ":")),
                sha,
            ),
        )


def _write_screen_rules(conn: sqlite3.Connection, cap: str) -> None:
    sha = _sha()
    for tag, spec in frozen_screen_catalog().items():
        conn.execute(
            """
            INSERT OR REPLACE INTO screen_pick_rule(
                as_of, tag, enc_id, spec, sha
            ) VALUES (?,?,?,?,?)
            """,
            (
                cap,
                str(tag),
                str(spec.get("enc_id") or tag),
                json.dumps(spec, ensure_ascii=False, separators=(",", ":")),
                sha,
            ),
        )


def _why_dongzhu(tag: str, item: Dict[str, Any], field: str, pre_sign: str) -> str:
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


def _why_screen(tag: str) -> str:
    if tag == "leave_zero":
        return "海選黃金買點獲利剛離零"
    if tag == "golden_buy":
        return "海選60低超跌觀察不是買"
    return "海選選股不是買訊"


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
    """洞燭當日名單。海選不准走這條。沒官方收盤的不上。不准刪舊日。"""
    if not db_path or not isinstance(data, dict):
        return 0
    if str(kind or KIND_DONGZHU) != KIND_DONGZHU:
        return 0
    cap = _ymd(data.get("cap") or data.get("chip_cap"))
    if not cap:
        return 0
    ensure_dongzhu_tape_tables(db_path)
    store = tape_store_path(db_path)
    field = str(data.get("field") or "")
    pre_sign = str(data.get("pre_sign") or "")
    share_last = _f((data.get("flow") or {}).get("share_last")) or 0.0
    rows = _iter_pick_rows(data)
    buy_n = sum(1 for t, _ in rows if t == "leave_zero")
    watch_n = sum(1 for t, _ in rows if t == "golden_buy")
    cap_n = sum(1 for t, _ in rows if t == "capture")
    catalog = frozen_dongzhu_catalog()
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
                KIND_DONGZHU,
                cap,
                field,
                pre_sign,
                share_last,
                buy_n,
                watch_n,
                cap_n,
                _now_iso(),
                _sha(),
                json.dumps(catalog, ensure_ascii=False, separators=(",", ":")),
            ),
        )
        conn.execute(
            "DELETE FROM dongzhu_pick_tape WHERE as_of=? AND kind=?",
            (cap, KIND_DONGZHU),
        )
        for tag, item in rows:
            sid = str(item.get("sid") or "").strip()
            enc_id, enc_js = _item_encoding(tag, item, field, pre_sign, catalog)
            conn.execute(
                """
                INSERT OR REPLACE INTO dongzhu_pick_tape(
                    kind, as_of, sid, tag, name, field, role, close, vs20, vs60, volr,
                    why, enc_id, encoding
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    KIND_DONGZHU,
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
                    _why_dongzhu(tag, item, field, pre_sign),
                    enc_id,
                    enc_js,
                ),
            )
        _write_dongzhu_rules(conn, cap)
        conn.commit()
    finally:
        conn.close()
    return len(rows)


def snapshot_dongzhu_picks(db_path: str, cap: str = "", *, spoken: str = "") -> int:
    """盤後自動跑，不等人按洞燭鈕。spoken 空＝機制名單。不准回寫現有佔比帶。"""
    if not db_path:
        return 0
    from biaoke_field_scan import _cap, dongzhu_picks

    data = dongzhu_picks(db_path, spoken=spoken, record_flow=False)
    if cap:
        data["cap"] = _ymd(cap) or data.get("cap")
    elif not _ymd(data.get("cap")):
        data["cap"] = _cap(db_path)
    return write_snapshot(db_path, data)


def _screen_items_from_results(results: Dict[str, Any]) -> List[Tuple[str, Dict[str, Any]]]:
    items: List[Tuple[str, Dict[str, Any]]] = []
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
    return items


def _screen_items_from_sessions(db_path: str, cap: str) -> List[Tuple[str, Dict[str, Any]]]:
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
            return []
        marks = ",".join("?" * len(SCREEN_TAGS))
        rows = conn.execute(
            f"""
            SELECT bucket, stock_id, stock_name, pick_close,
                   hi20_close, entry_price, defense_price, chase_warning
            FROM screen_sessions
            WHERE as_of=? AND session=? AND bucket IN ({marks})
            """,
            (cap, session, *SCREEN_TAGS),
        ).fetchall()
    except sqlite3.Error:
        return []
    finally:
        conn.close()
    items: List[Tuple[str, Dict[str, Any]]] = []
    for bucket, sid, name, close, hi20, entry, defense, chase in rows:
        px = _f(close)
        s = str(sid or "").strip()
        if not s or px is None or px <= 0:
            continue
        items.append(
            (
                str(bucket or ""),
                {
                    "sid": s,
                    "name": str(name or s),
                    "close": px,
                    "hi20_close": hi20,
                    "entry_price": entry,
                    "defense_price": defense,
                    "chase_warning": chase,
                },
            )
        )
    return items


def write_screen_snapshot(
    db_path: str, cap: str, items: Sequence[Tuple[str, Dict[str, Any]]]
) -> int:
    cap = _ymd(cap)
    if not db_path or not cap:
        return 0
    ensure_dongzhu_tape_tables(db_path)
    store = tape_store_path(db_path)
    catalog = frozen_screen_catalog()
    rows = []
    seen = set()
    for tag, item in items:
        tag = str(tag or "")
        if tag not in SCREEN_TAGS:
            continue
        sid = str(item.get("sid") or "").strip()
        px = _f(item.get("close") or item.get("pick_close"))
        if not sid or px is None or px <= 0 or (sid, tag) in seen:
            continue
        seen.add((sid, tag))
        rows.append((tag, item, sid, px))
    conn = sqlite3.connect(store, timeout=8.0)
    try:
        conn.execute(
            """
            INSERT OR REPLACE INTO screen_pick_run(
                as_of, n, ran_at, sha, encoding
            ) VALUES (?,?,?,?,?)
            """,
            (
                cap,
                len(rows),
                _now_iso(),
                _sha(),
                json.dumps(catalog, ensure_ascii=False, separators=(",", ":")),
            ),
        )
        conn.execute("DELETE FROM screen_pick_tape WHERE as_of=?", (cap,))
        for tag, item, sid, px in rows:
            enc_id, enc_js = _item_encoding(tag, item, "", "", catalog)
            conn.execute(
                """
                INSERT OR REPLACE INTO screen_pick_tape(
                    as_of, sid, tag, name, close, vs20, vs60, volr, why, enc_id, encoding
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    cap,
                    sid,
                    tag,
                    str(item.get("name") or sid),
                    px,
                    _f(item.get("vs20")),
                    _f(item.get("vs60")),
                    _f(item.get("volr")),
                    _why_screen(tag),
                    enc_id,
                    enc_js,
                ),
            )
        _write_screen_rules(conn, cap)
        conn.commit()
    finally:
        conn.close()
    return len(rows)


def snapshot_screen_picks(
    db_path: str, cap: str = "", *, results: Optional[Dict[str, Any]] = None
) -> int:
    """海選桶自己落檔。當沖／隔日沖不收。不准寫進洞燭表。"""
    cap = _ymd(cap)
    if not db_path or not cap:
        return 0
    if isinstance(results, dict):
        items = _screen_items_from_results(results)
        return write_screen_snapshot(db_path, cap, items)
    items = _screen_items_from_sessions(db_path, cap)
    return write_screen_snapshot(db_path, cap, items)


def _quote_days(db_path: str, cap: str) -> List[str]:
    """有官方收>0 的交易日。沒有就不當交易日。洞燭／海選共用。"""
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
    """只認這檔這日官方收。沒有、0、負的都不當已知。洞燭／海選共用。"""
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


def _score_picks(
    conn: sqlite3.Connection,
    db_path: str,
    as_of: str,
    check_as_of: str,
    horizon: int,
    picks: Sequence[Tuple[Any, ...]],
    *,
    score_sql: str,
    extra: Tuple[Any, ...] = (),
    capture_vs20: bool = False,
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
        vs_now = _vs20_on(db_path, sid, check_as_of) if capture_vs20 and tag == "capture" else None
        vs_then = _f(vs20_then) if capture_vs20 else None
        vs_delta = (
            (vs_now - vs_then) if vs_now is not None and vs_then is not None else None
        )
        verdict, note = _verdict(tag, fwd, vs_delta)
        conn.execute(
            score_sql,
            extra
            + (
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


def score_dongzhu_picks(db_path: str, check_as_of: str) -> int:
    """只對洞燭近期落檔。海選不走這裡。"""
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
            _ymd(r[0])
            for r in conn.execute(
                "SELECT as_of FROM dongzhu_pick_run WHERE as_of < ? AND kind=? ORDER BY as_of",
                (cap, KIND_DONGZHU),
            ).fetchall()
        ]
    finally:
        conn.close()
    scored = 0
    score_sql = """
        INSERT OR REPLACE INTO dongzhu_pick_score(
            kind, as_of, check_as_of, sid, tag, horizon, pick_close, now_close,
            fwd_pct, vs20_then, vs20_now, verdict, note
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
    """
    conn = sqlite3.connect(store, timeout=8.0)
    try:
        for as_of in runs:
            if not as_of or (floor and as_of < floor):
                continue
            picks = conn.execute(
                "SELECT sid, tag, close, vs20 FROM dongzhu_pick_tape "
                "WHERE kind=? AND as_of=?",
                (KIND_DONGZHU, as_of),
            ).fetchall()
            if not picks:
                continue
            for horizon in SCORE_HORIZONS:
                target = _horizon_day(days, as_of, horizon)
                if not target or target > cap:
                    continue
                scored += _score_picks(
                    conn,
                    db_path,
                    as_of,
                    target,
                    int(horizon),
                    picks,
                    score_sql=score_sql,
                    extra=(KIND_DONGZHU,),
                    capture_vs20=True,
                )
        conn.commit()
    finally:
        conn.close()
    _refresh_dongzhu_rates(db_path)
    return scored


def score_screen_picks(db_path: str, check_as_of: str) -> int:
    """只對海選近期落檔。洞燭不走這裡。捕捉 vs20 不准套上來。"""
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
            _ymd(r[0])
            for r in conn.execute(
                "SELECT as_of FROM screen_pick_run WHERE as_of < ? ORDER BY as_of",
                (cap,),
            ).fetchall()
        ]
    finally:
        conn.close()
    scored = 0
    score_sql = """
        INSERT OR REPLACE INTO screen_pick_score(
            as_of, check_as_of, sid, tag, horizon, pick_close, now_close,
            fwd_pct, vs20_then, vs20_now, verdict, note
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
    """
    conn = sqlite3.connect(store, timeout=8.0)
    try:
        for as_of in runs:
            if not as_of or (floor and as_of < floor):
                continue
            picks = conn.execute(
                "SELECT sid, tag, close, vs20 FROM screen_pick_tape WHERE as_of=?",
                (as_of,),
            ).fetchall()
            if not picks:
                continue
            for horizon in SCORE_HORIZONS:
                target = _horizon_day(days, as_of, horizon)
                if not target or target > cap:
                    continue
                scored += _score_picks(
                    conn,
                    db_path,
                    as_of,
                    target,
                    int(horizon),
                    picks,
                    score_sql=score_sql,
                    extra=(),
                    capture_vs20=False,
                )
        conn.commit()
    finally:
        conn.close()
    _refresh_screen_rates(db_path)
    return scored


def _refresh_dongzhu_rates(db_path: str) -> None:
    """洞燭各窗累計。不是改黃金買點。不准把海選算進來。"""
    store = tape_store_path(db_path)
    conn = sqlite3.connect(store, timeout=8.0)
    try:
        rows = conn.execute(
            """
            SELECT tag, horizon,
                   SUM(CASE WHEN verdict='對' THEN 1 ELSE 0 END),
                   SUM(CASE WHEN verdict='偏' THEN 1 ELSE 0 END),
                   SUM(CASE WHEN verdict='還沒走完' THEN 1 ELSE 0 END),
                   COUNT(*)
            FROM dongzhu_pick_score
            WHERE kind=?
            GROUP BY tag, horizon
            """,
            (KIND_DONGZHU,),
        ).fetchall()
        now = _now_iso()
        conn.execute("DELETE FROM dongzhu_pick_rates WHERE kind=?", (KIND_DONGZHU,))
        for tag, horizon, hit, miss, pending, n in rows:
            conn.execute(
                """
                INSERT OR REPLACE INTO dongzhu_pick_rates(
                    kind, tag, horizon, n, hit, miss, pending, updated_at
                ) VALUES (?,?,?,?,?,?,?,?)
                """,
                (
                    KIND_DONGZHU,
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


def _refresh_screen_rates(db_path: str) -> None:
    """海選各窗累計。與洞燭勝率分開。"""
    store = tape_store_path(db_path)
    conn = sqlite3.connect(store, timeout=8.0)
    try:
        rows = conn.execute(
            """
            SELECT tag, horizon,
                   SUM(CASE WHEN verdict='對' THEN 1 ELSE 0 END),
                   SUM(CASE WHEN verdict='偏' THEN 1 ELSE 0 END),
                   SUM(CASE WHEN verdict='還沒走完' THEN 1 ELSE 0 END),
                   COUNT(*)
            FROM screen_pick_score
            GROUP BY tag, horizon
            """
        ).fetchall()
        now = _now_iso()
        conn.execute("DELETE FROM screen_pick_rates")
        for tag, horizon, hit, miss, pending, n in rows:
            conn.execute(
                """
                INSERT OR REPLACE INTO screen_pick_rates(
                    tag, horizon, n, hit, miss, pending, updated_at
                ) VALUES (?,?,?,?,?,?,?)
                """,
                (
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


def _safe_int(fn, *a, **k) -> int:
    try:
        return int(fn(*a, **k) or 0)
    except Exception:
        return 0


def snapshot_and_score_dongzhu(db_path: str, cap: str) -> Dict[str, Any]:
    """盤後齊了：洞燭與海選各自對質、各自落檔。不推話筒。一條失敗不准擋另一條。"""
    cap = _ymd(cap)
    if not db_path or not cap:
        return {"snap": 0, "scored": 0, "cap": cap, "screen": 0, "screen_scored": 0}
    scored = _safe_int(score_dongzhu_picks, db_path, cap)
    screen_scored = _safe_int(score_screen_picks, db_path, cap)
    snap = _safe_int(snapshot_dongzhu_picks, db_path, cap, spoken="")
    screen = _safe_int(snapshot_screen_picks, db_path, cap)
    return {
        "snap": snap,
        "scored": scored,
        "screen": screen,
        "screen_scored": screen_scored,
        "cap": cap,
    }


def optimize_ready(n: int) -> bool:
    """自己排優化：樣本不夠不准改編碼。這裡只判斷，不改黃金買點。"""
    return int(n or 0) >= OPTIMIZE_MIN_N


def scoreboard_lines(db_path: str, cap: str = "") -> List[str]:
    """內部對質摘要。頁面不顯示。只看洞燭。"""
    if not db_path:
        return []
    ensure_dongzhu_tape_tables(db_path)
    store = tape_store_path(db_path)
    cap = _ymd(cap)
    conn = sqlite3.connect(store, timeout=8.0)
    try:
        if not cap:
            row = conn.execute(
                "SELECT MAX(check_as_of) FROM dongzhu_pick_score WHERE kind=?",
                (KIND_DONGZHU,),
            ).fetchone()
            cap = _ymd(row[0] if row else "")
        if not cap:
            return []
        scores = conn.execute(
            """
            SELECT sid, name, tag, verdict, COALESCE(s.horizon, 1)
            FROM dongzhu_pick_score s
            JOIN dongzhu_pick_tape t USING (kind, as_of, sid, tag)
            WHERE s.check_as_of=? AND s.kind=?
            ORDER BY COALESCE(s.horizon, 1),
                     CASE s.tag WHEN 'leave_zero' THEN 0 WHEN 'capture' THEN 1 ELSE 2 END,
                     s.sid
            """,
            (cap, KIND_DONGZHU),
        ).fetchall()
        rate_h = conn.execute(
            "SELECT MAX(horizon) FROM dongzhu_pick_rates WHERE n>0 AND kind=?",
            (KIND_DONGZHU,),
        ).fetchone()
        want_h = int(rate_h[0] or 1) if rate_h and rate_h[0] else 1
        rates = conn.execute(
            """
            SELECT tag, horizon, n, hit, miss, pending
            FROM dongzhu_pick_rates
            WHERE horizon=? AND kind=?
            ORDER BY tag
            """,
            (want_h, KIND_DONGZHU),
        ).fetchall()
        if not rates:
            rates = conn.execute(
                "SELECT tag, horizon, n, hit, miss, pending FROM dongzhu_pick_rates "
                "WHERE kind=? ORDER BY tag",
                (KIND_DONGZHU,),
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
