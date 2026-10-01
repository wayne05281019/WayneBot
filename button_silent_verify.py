# -*- coding: utf-8 -*-
"""全鈕靜默落檔／對質清冊與缺鈕骨架。

選股對質 vs 個人本對照分開記、分開覆盤，勝率不准混（AGENTS §7）。
壓撐三軌（current／first／biaoke_silent）由 ``pressure_rank_verify`` 管，這裡只登記並存，不重發明。
失敗吞掉，不准打斷出卡／海選／查股／AI倉。過程／％不准進對話。
空名單不算有記；要真代號＋當日官方開高低收＋量。未收不當收。Asia/Taipei。
"""
from __future__ import annotations

import os
import sqlite3
from typing import Any, Dict, List, Optional, Sequence, Tuple

# 對質窗：與 judge_tape.score_live_judges 一致（隔日／五日官方已收）
VERIFY_HORIZONS = (1, 5)
# 改碼門檻（各軌各自算；個人本不進改碼）
OPTIMIZE_MIN_N = 20

CLASS_SCREEN = "screen_verify"  # 規則選股對質
CLASS_PERSONAL = "personal_book"  # 個人本對照（不是選股）
CLASS_CONTEXT = "context_freeze"  # 大盤／外圍佐證凍
CLASS_PRESSURE = "pressure_rank"  # 壓撐排序三軌（另模組）
CLASS_BIAOKE = "biaoke_tape"  # 飆大點名／近窗
CLASS_AI = "ai_desk"  # AI倉假錢對照

# kind 前綴／固定 kind：個人本對照（勝率不准混進選股）
BOOK_KINDS = frozenset({"book_hold", "book_watch", "book_buy"})
# 選股／規則對質（可各自算勝率，彼此仍不准混）
SCREEN_KINDS = frozenset(
    {
        "leave_zero",
        "golden_buy",
        "revenue_cross",
        "select_01",
        "select_02",
        "select_03",
        "day_trade",
        "overnight",
        "em_leave_zero",
        "em_golden_buy",
        "dongzhu",
        "streak_foreign",
        "streak_trust",
        "streak_both",
        "money_flow",
        "ai_desk",
        "biaoke_named",
        "intraday_leave_zero",
        "winrate_buypoint",
        "winrate_filter",
    }
)


def _ymd(raw: Any) -> str:
    t = str(raw or "").replace("-", "")[:8]
    return t if len(t) == 8 and t.isdigit() else ""


def _as_of(market_db: str, hint: str = "") -> str:
    day = _ymd(hint)
    if day:
        return day
    try:
        from import_health import latest_complete_quote_date

        return _ymd(latest_complete_quote_date(market_db))
    except Exception:
        return ""


def _watch_as_of(market_db: str, hint: str = "") -> str:
    """加入觀察個人本對照日：收盤後可到今日，不卡 fuse 16:30（對齊話筒 as_of）。"""
    day = _ymd(hint)
    if day:
        return day
    try:
        from wayne_db import resolve_watch_view_as_of

        as_of, _lag = resolve_watch_view_as_of(market_db)
        return _ymd(as_of)
    except Exception:
        return _as_of(market_db, hint)


# 話筒完整鍵盤清點（上七下七）＋記買入子路徑
# status: present=已有管線；gap_filled=本檔補骨架；external=他模組（壓撐三軌／飆大 tape／AI fills）
BUTTON_CATALOG: Tuple[Dict[str, Any], ...] = (
    {
        "btn": "勝率買點",
        "kinds": ("winrate_buypoint", "winrate_filter"),
        "class": CLASS_SCREEN,
        "status": "present",
        "pipe": "winrate_buypoint 21:00 roster＋隔日篩 → live_judge；button_silent_verify.snapshot_winrate_buypoint",
        "window": "盤後 leave_zero 官方柱 1／5；隔日篩結果另 kind",
        "note": "選股對質；只認藍▲紅框 leave_zero；未過關不准改黃金買點／買訊",
    },
    {
        "btn": "海選",
        "kinds": (
            "leave_zero",
            "golden_buy",
            "revenue_cross",
            "select_01",
            "select_02",
            "select_03",
            "em_leave_zero",
            "em_golden_buy",
        ),
        "class": CLASS_SCREEN,
        "status": "present",
        "pipe": "judge_tape.snapshot_button_lists + dongzhu_tape screen + screen_review",
        "window": "1／5 日官方收（live_judge）；洞燭／海選另有 1／5／10",
        "note": "選股對質；黃金買點未過關不准改",
    },
    {
        "btn": "持股",
        "kinds": ("book_hold",),
        "class": CLASS_PERSONAL,
        "status": "gap_filled",
        "pipe": "button_silent_verify.snapshot_book_hold",
        "window": "1／5 日官方收（個人本對照，不進選股勝率）",
        "note": "個人本對照；不是選股",
    },
    {
        "btn": "加入觀察",
        "kinds": ("book_watch",),
        "class": CLASS_PERSONAL,
        "status": "gap_filled",
        "pipe": "button_silent_verify.snapshot_book_watch（as_of＝watch_display_cap／resolve_watch_view_as_of）",
        "window": "1／5 日官方收（個人本對照，不進選股勝率；收盤後不卡 16:30）",
        "note": "個人本對照；不是選股；勝率不准混",
    },
    {
        "btn": "飆大",
        "kinds": ("biaoke_named",),
        "class": CLASS_BIAOKE,
        "status": "gap_filled",
        "pipe": "biaoke_tape（近窗柱）＋本檔每日點名凍結 live_judge",
        "window": "近窗官方 OHLC＋量；live_judge 再對 1／5",
        "note": "不是買訊；不准寫回黃金買點／海選",
    },
    {
        "btn": "台股大盤",
        "kinds": ("market", "fut", "us", "outer"),
        "class": CLASS_CONTEXT,
        "status": "present",
        "pipe": "judge_tape + silent_progress + biaoke_forecast",
        "window": "加權完整柱＋日夜盤／美指已收；試畫另軌",
        "note": "佐證凍；現在不准發明 5／9",
    },
    {
        "btn": "資金輪動",
        "kinds": ("money_flow",),
        "class": CLASS_SCREEN,
        "status": "gap_filled",
        "pipe": "button_silent_verify.snapshot_money_flow",
        "window": "1／5 日官方收；與海選勝率分開",
        "note": "外資／投信買超＋短線熱代表股；不是買訊",
    },
    {
        "btn": "當沖",
        "kinds": ("day_trade",),
        "class": CLASS_SCREEN,
        "status": "present",
        "pipe": "judge_tape screen bucket",
        "window": "1／5 日官方收",
        "note": "選股對質；非黃金買點",
    },
    {
        "btn": "隔日沖",
        "kinds": ("overnight",),
        "class": CLASS_SCREEN,
        "status": "present",
        "pipe": "judge_tape screen bucket",
        "window": "1／5 日官方收",
        "note": "選股對質；非黃金買點",
    },
    {
        "btn": "壓撐觀察",
        "kinds": ("pressure_sideways", "pressure_test_press", "pressure_stand_support"),
        "class": CLASS_PRESSURE,
        "status": "external",
        "pipe": "judge_tape 三標籤落檔＋pressure_rank_verify 四軌",
        "window": "前瞻 5 交易日；current／first／second／biaoke_silent 分開",
        "note": "first／second 過閘才改話筒排序；飆大軌永不自動上",
    },
    {
        "btn": "大量區×季線",
        "kinds": ("volzone_ma60",),
        "class": CLASS_PRESSURE,
        "status": "external",
        "pipe": "volzone_ma60_verify current／ma60_rising／ma60_rising_thin",
        "window": "前瞻 5 交易日；與壓撐／海選勝率分開",
        "note": "靜默對質；過閘也不自動改黃金買點／海選／買訊",
    },
    {
        "btn": "盤中剛離零→收盤",
        "kinds": ("intraday_leave_zero",),
        "class": CLASS_SCREEN,
        "status": "external",
        "pipe": "intraday_leave_zero_verify lookup／MIS hit → close_hold／next_1",
        "window": "當日官方收是否仍 leave_zero；選填隔日報酬",
        "note": "靜默對質；不是新鈕；過閘也不自動改黃金買點／買訊",
    },
    {
        "btn": "AI倉",
        "kinds": ("ai_desk",),
        "class": CLASS_AI,
        "status": "gap_filled",
        "pipe": "screen_review.ai_fills＋本檔當日 BUY 凍結 live_judge",
        "window": "ai_fills 隔日收；live_judge 1／5 另記，勝率不准混海選",
        "note": "假錢對照組；不准真下單",
    },
    {
        "btn": "連買區",
        "kinds": ("streak_foreign", "streak_trust", "streak_both"),
        "class": CLASS_SCREEN,
        "status": "present",
        "pipe": "judge_tape + buy_streak snapshot",
        "window": "1／5 日官方收",
        "note": "選股對質",
    },
    {
        "btn": "剛脫離零",
        "kinds": ("leave_zero",),
        "class": CLASS_SCREEN,
        "status": "present",
        "pipe": "judge_tape leave_zero pick + screen_review 星級",
        "window": "1／5 日官方收；星級隔日另檔",
        "note": "買點切入認 leave_zero；未過關不准改黃金買點公式",
    },
    {
        "btn": "洞燭先機",
        "kinds": ("dongzhu",),
        "class": CLASS_SCREEN,
        "status": "present",
        "pipe": "judge_tape + dongzhu_tape",
        "window": "1／5／10 日官方收（dongzhu_tape）；live_judge 1／5",
        "note": "與海選分開記、分開覆盤",
    },
    {
        "btn": "記買入",
        "kinds": ("book_buy",),
        "class": CLASS_PERSONAL,
        "status": "gap_filled",
        "pipe": "button_silent_verify.snapshot_book_buy",
        "window": "當日手記成交代號＋官方柱 1／5 對照",
        "note": "個人本對照（子路徑）；不是選股",
    },
)


def catalog() -> List[Dict[str, Any]]:
    return [dict(row) for row in BUTTON_CATALOG]


def coverage_counts() -> Dict[str, int]:
    rows = catalog()
    out = {"present": 0, "gap_filled": 0, "external": 0, "missing": 0, "total": len(rows)}
    for row in rows:
        key = str(row.get("status") or "missing")
        if key not in out:
            key = "missing"
        out[key] = int(out.get(key) or 0) + 1
    return out


def is_personal_book_kind(kind: str) -> bool:
    return str(kind or "").strip() in BOOK_KINDS


def is_screen_kind(kind: str) -> bool:
    k = str(kind or "").strip()
    if k in BOOK_KINDS:
        return False
    if k.startswith("pressure_"):
        return False
    if k in ("market", "fut", "us", "outer"):
        return False
    return k in SCREEN_KINDS or k.startswith("streak_")


def _remember(market_db: str, kind: str, rows: Sequence[Dict[str, Any]], *, as_of: str, pick: str, src: str) -> int:
    try:
        from judge_tape import remember_rows

        return int(remember_rows(market_db, kind, rows, as_of=as_of, pick=pick, src=src) or 0)
    except Exception:
        return 0


def _row_from_quote(sid: str, name: str = "", **extra: Any) -> Dict[str, Any]:
    out: Dict[str, Any] = {"stock_id": str(sid).strip(), "stock_name": str(name or "")}
    out.update(extra)
    return out


def snapshot_money_flow(market_db: str, as_of: str = "") -> int:
    """資金輪動沒按也落檔：外資買超／投信買超／短線熱代表股。空名單＝0。"""
    day = _as_of(market_db, as_of)
    if not market_db or not day or not os.path.isfile(market_db):
        return 0
    rows: List[Dict[str, Any]] = []
    seen = set()
    try:
        conn = sqlite3.connect(market_db, timeout=8.0)
        conn.row_factory = sqlite3.Row
        try:
            packs = []
            for col, desc in (("foreign_net", True), ("trust_net", True)):
                order = "DESC" if desc else "ASC"
                packs.append(
                    conn.execute(
                        f"""
                        SELECT stock_id, stock_name, close, pct_change, volume,
                               foreign_net, trust_net, dealer_net
                        FROM daily_quotes
                        WHERE REPLACE(CAST(date AS TEXT),'-','')=? AND length(stock_id)=4
                        ORDER BY {col} {order}
                        LIMIT 6
                        """,
                        (day,),
                    ).fetchall()
                )
            packs.append(
                conn.execute(
                    """
                    SELECT stock_id, stock_name, close, pct_change, volume,
                           foreign_net, trust_net, dealer_net
                    FROM daily_quotes
                    WHERE REPLACE(CAST(date AS TEXT),'-','')=? AND length(stock_id)=4
                      AND volume>=3000 AND ABS(pct_change)>=1.5
                    ORDER BY ABS(foreign_net) DESC
                    LIMIT 6
                    """,
                    (day,),
                ).fetchall()
            )
        finally:
            conn.close()
        for pack in packs:
            for r in pack:
                sid = str(r["stock_id"] or "").strip()
                if not sid or sid in seen:
                    continue
                seen.add(sid)
                rows.append(
                    _row_from_quote(
                        sid,
                        str(r["stock_name"] or ""),
                        close=r["close"],
                        pct_change=r["pct_change"],
                        volume=r["volume"],
                        foreign_net=r["foreign_net"],
                        trust_net=r["trust_net"],
                        dealer_net=r["dealer_net"],
                    )
                )
    except Exception:
        return 0
    return _remember(market_db, "money_flow", rows, as_of=day, pick="rule", src="flow")


def _distinct_uids(market_db: str, table: str, col: str = "user_id") -> List[str]:
    if not market_db or not os.path.isfile(market_db):
        return []
    try:
        conn = sqlite3.connect(market_db, timeout=8.0)
        try:
            names = {str(r[0]) for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if table not in names:
                return []
            rows = conn.execute(f"SELECT DISTINCT {col} FROM {table} WHERE {col}!=''").fetchall()
        finally:
            conn.close()
        return [str(r[0]).strip() for r in rows if str(r[0] or "").strip()]
    except Exception:
        return []


def snapshot_book_hold(market_db: str, as_of: str = "") -> int:
    """持股＝個人本對照。有真代號才記；空本不算有記。"""
    day = _as_of(market_db, as_of)
    if not day:
        return 0
    n = 0
    for uid in _distinct_uids(market_db, "user_holdings"):
        try:
            from wayne_db import get_user_portfolio

            items = get_user_portfolio(market_db, uid) or []
        except Exception:
            items = []
        rows = []
        for raw in items:
            sid = str(raw.get("stock_code") or raw.get("stock_id") or "").strip()
            if not sid:
                continue
            rows.append(_row_from_quote(sid, str(raw.get("stock_name") or "")))
        n += _remember(market_db, "book_hold", rows, as_of=day, pick=uid, src="book")
    return n


def snapshot_book_watch(market_db: str, as_of: str = "") -> int:
    """加入觀察＝個人本對照。有真代號才記。as_of 對齊話筒收盤後 cap。"""
    day = _watch_as_of(market_db, as_of)
    if not day:
        return 0
    n = 0
    for uid in _distinct_uids(market_db, "user_watchlist"):
        try:
            from wayne_db import get_user_watchlist

            items = get_user_watchlist(market_db, uid) or []
        except Exception:
            items = []
        rows = []
        for raw in items:
            sid = str(raw.get("stock_code") or raw.get("stock_id") or "").strip()
            if not sid:
                continue
            rows.append(_row_from_quote(sid, str(raw.get("stock_name") or "")))
        n += _remember(market_db, "book_watch", rows, as_of=day, pick=uid, src="book")
    return n


def snapshot_book_buy(market_db: str, as_of: str = "") -> int:
    """記買入＝當日手記成交個人本對照。"""
    day = _as_of(market_db, as_of)
    if not market_db or not day or not os.path.isfile(market_db):
        return 0
    n = 0
    try:
        conn = sqlite3.connect(market_db, timeout=8.0)
        try:
            names = {str(r[0]) for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if "user_trade_logs" not in names:
                return 0
            rows = conn.execute(
                """
                SELECT user_id, stock_code, stock_name, action, price
                FROM user_trade_logs
                WHERE REPLACE(CAST(trade_date AS TEXT),'-','')=?
                """,
                (day,),
            ).fetchall()
        finally:
            conn.close()
    except Exception:
        return 0
    by_uid: Dict[str, List[Dict[str, Any]]] = {}
    for uid, code, name, action, price in rows:
        sid = str(code or "").strip()
        if not sid:
            continue
        key = str(uid or "").strip() or "_"
        by_uid.setdefault(key, []).append(
            _row_from_quote(sid, str(name or ""), close=price, action=str(action or ""))
        )
    for uid, items in by_uid.items():
        n += _remember(market_db, "book_buy", items, as_of=day, pick=uid, src="book")
    return n


def snapshot_ai_desk(market_db: str, as_of: str = "") -> int:
    """AI倉當日 BUY 凍結進 live_judge（與 ai_fills 分開表，勝率不准混海選）。"""
    day = _as_of(market_db, as_of)
    if not market_db or not day or not os.path.isfile(market_db):
        return 0
    try:
        from screen_review import ensure_ai_fills_table

        ensure_ai_fills_table(market_db)
    except Exception:
        pass
    try:
        conn = sqlite3.connect(market_db, timeout=8.0)
        try:
            names = {str(r[0]) for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if "ai_fills" not in names:
                return 0
            hits = conn.execute(
                """
                SELECT user_id, stock_id, stock_name, price, bucket
                FROM ai_fills
                WHERE action='BUY' AND REPLACE(CAST(as_of AS TEXT),'-','')=?
                """,
                (day,),
            ).fetchall()
        finally:
            conn.close()
    except Exception:
        return 0
    by_uid: Dict[str, List[Dict[str, Any]]] = {}
    for uid, sid, name, price, bucket in hits:
        code = str(sid or "").strip()
        if not code:
            continue
        key = str(uid or "").strip() or "wayne_ai"
        by_uid.setdefault(key, []).append(
            _row_from_quote(
                code,
                str(name or ""),
                close=price,
                bucket_key=str(bucket or ""),
            )
        )
    n = 0
    for uid, items in by_uid.items():
        n += _remember(market_db, "ai_desk", items, as_of=day, pick=uid, src="ai")
    return n


def snapshot_biaoke_named(market_db: str, as_of: str = "") -> int:
    """飆大當日點名檔凍結（讀 biaoke_tape；沒有真代號不算）。"""
    day = _as_of(market_db, as_of)
    if not market_db or not day or not os.path.isfile(market_db):
        return 0
    rows: List[Dict[str, Any]] = []
    seen = set()
    try:
        conn = sqlite3.connect(market_db, timeout=8.0)
        try:
            names = {str(r[0]) for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if "biaoke_tape" not in names:
                return 0
            hits = conn.execute(
                """
                SELECT stock_id, stock_name, open, high, low, close, volume, bar_date
                FROM biaoke_tape
                WHERE REPLACE(CAST(post_date AS TEXT),'-','')=?
                   OR REPLACE(CAST(bar_date AS TEXT),'-','')=?
                """,
                (day, day),
            ).fetchall()
        finally:
            conn.close()
        for sid, name, o, h, l, c, v, _bar in hits:
            code = str(sid or "").strip()
            if not code or code in seen:
                continue
            seen.add(code)
            rows.append(
                _row_from_quote(
                    code,
                    str(name or ""),
                    open=o,
                    high=h,
                    low=l,
                    close=c,
                    volume=v,
                )
            )
    except Exception:
        return 0
    return _remember(market_db, "biaoke_named", rows, as_of=day, pick="rule", src="biaoke")


def snapshot_winrate_buypoint(market_db: str, as_of: str = "") -> int:
    """勝率買點盤後名單靜默凍（讀 winrate_buypoint_roster；空名單不算）。"""
    day = _as_of(market_db, as_of)
    if not market_db or not day:
        return 0
    try:
        from winrate_buypoint import silent_remember_roster

        return int(silent_remember_roster(market_db, day) or 0)
    except Exception:
        return 0


def snapshot_all_button_gaps(market_db: str, as_of: str = "") -> Dict[str, int]:
    """補缺鈕骨架一輪。一條失敗不擋其他。"""
    day = _as_of(market_db, as_of)
    stats: Dict[str, int] = {}
    if not day:
        return stats
    runners = (
        ("money_flow", snapshot_money_flow),
        ("book_hold", snapshot_book_hold),
        ("book_watch", snapshot_book_watch),
        ("book_buy", snapshot_book_buy),
        ("ai_desk", snapshot_ai_desk),
        ("biaoke_named", snapshot_biaoke_named),
        ("winrate_buypoint", snapshot_winrate_buypoint),
    )
    for key, fn in runners:
        try:
            stats[key] = int(fn(market_db, day) or 0)
        except Exception:
            stats[key] = 0
    return stats


def pressure_coexists() -> bool:
    """壓撐三軌模組是否可匯入（與本骨架並存）。"""
    try:
        from pressure_rank_verify import (
            VARIANT_BIAOKE_SILENT,
            VARIANT_CURRENT,
            VARIANT_FIRST,
            night_tick,
        )

        return bool(VARIANT_CURRENT and VARIANT_FIRST and VARIANT_BIAOKE_SILENT and night_tick)
    except Exception:
        return False


def optimize_status_one_liner(market_db: str = "") -> str:
    """報告唯一准講的明確優化狀態一句（不含過程／％細節堆砌）。"""
    cov = coverage_counts()
    pressure_ok = pressure_coexists()
    pressure_line = ""
    if pressure_ok and market_db:
        try:
            from pressure_rank_verify import optimize_status_one_liner as pressure_line_fn

            pressure_line = str(pressure_line_fn(market_db) or "").strip()
        except Exception:
            pressure_line = ""
    if not pressure_line:
        pressure_line = (
            "壓撐三軌並存可跑"
            if pressure_ok
            else "壓撐三軌模組未載入"
        )
    # 各選股軌改碼：骨架階段一律繼續收集；個人本永不改買訊
    return (
        f"明確優化狀態：全鈕靜默骨架已齊"
        f"（有{cov['present']}／補{cov['gap_filled']}／壓撐外軌{cov['external']}／缺{cov['missing']}）；"
        f"各選股軌 n 仍收集、未過 n≥{OPTIMIZE_MIN_N} 且贏現況→不改碼；"
        f"個人本只對照不改買訊；{pressure_line}"
    )
