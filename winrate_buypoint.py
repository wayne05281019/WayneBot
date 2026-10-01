# -*- coding: utf-8 -*-
"""勝率買點：盤後 leave_zero（藍▲紅框）名單＋21:00 推播＋隔日盤中篩。

訊號只認壓力圖藍▲紅框＝leave_zero（剛離零），不含還在零。
不准改黃金買點公式。盤中未收不當官方收。時區 Asia/Taipei。
"""
from __future__ import annotations

import logging
import os
import sqlite3
from typing import Any, Dict, List, Optional, Sequence, Tuple

logger = logging.getLogger(__name__)

PAGE_SIZE = 15
EMPTY_MSG = "今天無勝率買點股票出現"
NEXT_PAGE_LABEL = "下一個 15 檔"
BTN_LABEL = "勝率買點"
CALLBACK_PREFIX = "wr:"
# 靜默對質 kind（與 button_silent_verify／live_judge 對齊；勝率不准混海選／剛脫離零）
KIND_ROSTER = "winrate_buypoint"
KIND_FILTER = "winrate_filter"

try:
    from config import get_db_path
except Exception:  # pragma: no cover

    def get_db_path():
        return os.getenv("WAYNE_DB_PATH") or os.getenv("DB_PATH") or "data/wayne_market.db"


def ensure_winrate_table(db_path: str = None) -> None:
    path = db_path or get_db_path()
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    conn = sqlite3.connect(path)
    try:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS winrate_buypoint_roster (
                as_of TEXT NOT NULL,
                stock_id TEXT NOT NULL,
                stock_name TEXT DEFAULT '',
                pick_close REAL,
                profit_pct REAL,
                quote_source TEXT DEFAULT '',
                created_at TEXT DEFAULT '',
                PRIMARY KEY (as_of, stock_id)
            );
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_winrate_roster_asof "
            "ON winrate_buypoint_roster(as_of);"
        )
        conn.commit()
    finally:
        conn.close()


def _ymd(raw: Any) -> str:
    return str(raw or "").replace("-", "").strip()[:8]


def save_winrate_roster(
    db_path: str,
    as_of: str,
    rows: Sequence[Dict[str, Any]],
) -> int:
    """同一日同一規則只留一列；空名單也落檔（sentinel），隔日按鈕才找得到基準日。"""
    day = _ymd(as_of)
    if not day:
        return 0
    ensure_winrate_table(db_path)
    from config import taipei_now

    stamp = taipei_now().strftime("%Y-%m-%d %H:%M:%S")
    conn = sqlite3.connect(db_path)
    try:
        conn.execute("DELETE FROM winrate_buypoint_roster WHERE as_of=?", (day,))
        n = 0
        seen: set[str] = set()
        for it in rows or []:
            if not isinstance(it, dict):
                continue
            sid = str(it.get("stock_id") or it.get("code") or "").strip()
            if not sid or sid in seen or sid == "__empty__":
                continue
            seen.add(sid)
            name = str(it.get("stock_name") or it.get("name") or "")
            close = it.get("close")
            if close is None:
                close = it.get("pick_close")
            try:
                close_f = float(close) if close is not None else None
            except (TypeError, ValueError):
                close_f = None
            profit = it.get("profit_pct")
            if profit is None:
                profit = it.get("profit")
            try:
                profit_f = float(profit) if profit is not None else None
            except (TypeError, ValueError):
                profit_f = None
            src = str(it.get("quote_source") or "")
            conn.execute(
                """
                INSERT OR REPLACE INTO winrate_buypoint_roster(
                    as_of, stock_id, stock_name, pick_close, profit_pct,
                    quote_source, created_at
                ) VALUES (?,?,?,?,?,?,?)
                """,
                (day, sid, name, close_f, profit_f, src, stamp),
            )
            n += 1
        if n == 0:
            conn.execute(
                """
                INSERT OR REPLACE INTO winrate_buypoint_roster(
                    as_of, stock_id, stock_name, pick_close, profit_pct,
                    quote_source, created_at
                ) VALUES (?,?,?,?,?,?,?)
                """,
                (day, "__empty__", "", None, None, "empty", stamp),
            )
        conn.commit()
        return n
    finally:
        conn.close()


def load_winrate_roster(db_path: str, as_of: str) -> List[Dict[str, Any]]:
    day = _ymd(as_of)
    if not day:
        return []
    ensure_winrate_table(db_path)
    conn = sqlite3.connect(db_path)
    try:
        rows = conn.execute(
            """
            SELECT as_of, stock_id, stock_name, pick_close, profit_pct, quote_source
            FROM winrate_buypoint_roster
            WHERE as_of=? AND stock_id != '__empty__'
            ORDER BY stock_id
            """,
            (day,),
        ).fetchall()
    finally:
        conn.close()
    out: List[Dict[str, Any]] = []
    for as_of_v, sid, name, close, profit, src in rows:
        out.append(
            {
                "as_of": str(as_of_v or day),
                "stock_id": str(sid or ""),
                "stock_name": str(name or ""),
                "pick_close": close,
                "close": close,
                "profit_pct": profit,
                "quote_source": str(src or ""),
            }
        )
    return out


def latest_roster_as_of(db_path: str) -> str:
    ensure_winrate_table(db_path)
    conn = sqlite3.connect(db_path)
    try:
        row = conn.execute(
            "SELECT MAX(as_of) FROM winrate_buypoint_roster"
        ).fetchone()
    finally:
        conn.close()
    return _ymd(row[0] if row else "")


def roster_marked(db_path: str, as_of: str) -> bool:
    """當日已掃過（含空名單）就算有檔。"""
    day = _ymd(as_of)
    if not day:
        return False
    ensure_winrate_table(db_path)
    conn = sqlite3.connect(db_path)
    try:
        # 空名單：save 仍 DELETE 後 0 insert；用 pipeline 或 sentinel？
        # 改：另查是否有任何列；空名單靠 pipeline_runs。這裡只答「有代號列」。
        row = conn.execute(
            "SELECT 1 FROM winrate_buypoint_roster WHERE as_of=? LIMIT 1",
            (day,),
        ).fetchone()
        return bool(row)
    finally:
        conn.close()


def scan_winrate_leave_zero(
    db_path: str,
    *,
    as_of: Optional[str] = None,
) -> Tuple[str, List[Dict[str, Any]]]:
    """盤後官方母體：上市／上櫃／興櫃 leave_zero only。不改黃金買點公式。

    另套 buy_exclude（與剛脫離零同一套）：鎖跌停／明顯空頭／同根賣點警告不推薦。
    不改圖標畫法；#478 圖上藍▲一致邏輯合進 main 後以此為準再 rebase。
    """
    from screening_engine import ScreeningEngine

    engine = ScreeningEngine(db_path)
    day = _ymd(as_of) or _ymd(engine.get_latest_trading_date())
    rows = engine.screen_leave_zero_pick(target_date=day, pick="0") or []
    # 盤後掃：丟掉盤中 live 欄，只留官方收。
    cleaned: List[Dict[str, Any]] = []
    for it in rows:
        if not isinstance(it, dict):
            continue
        sid = str(it.get("stock_id") or it.get("code") or "").strip()
        if not sid:
            continue
        item = dict(it)
        item.pop("live", None)
        item["_live_skipped"] = False
        cleaned.append(item)
    # 雙保險：剛脫離零路徑已排除；此處再濾一次，#478 改掃法時勿拿掉。
    try:
        from buy_exclude import filter_leave_zero_rows

        frames, _em = engine._load_profit_scan_frames(day)
        cleaned = filter_leave_zero_rows(cleaned, frames or {}, db_path=db_path)
    except Exception:
        pass
    return day, cleaned


def page_slice(
    rows: Sequence[Dict[str, Any]],
    offset: int = 0,
    *,
    limit: int = PAGE_SIZE,
) -> Tuple[List[Dict[str, Any]], int, bool]:
    """回傳 (本頁列, 正規化 offset, 是否還有下一頁)。"""
    total = len(rows or [])
    off = max(0, int(offset or 0))
    if off >= total and total > 0:
        off = max(0, total - (total % limit or limit))
    chunk = list(rows[off : off + limit])
    has_next = (off + limit) < total
    return chunk, off, has_next


def next_page_callback(offset: int) -> str:
    return f"{CALLBACK_PREFIX}n:{max(0, int(offset))}"


def parse_next_page_callback(data: str) -> Optional[int]:
    raw = str(data or "").strip()
    if not raw.startswith(f"{CALLBACK_PREFIX}n:"):
        return None
    try:
        return max(0, int(raw.split(":", 2)[2]))
    except (TypeError, ValueError, IndexError):
        return None


def should_apply_intraday_filter(*, as_of: str, now=None) -> bool:
    """隔日盤中才篩；同基準日盤後重看＝全名單。"""
    from config import taipei_now
    from live_quote import is_live_merge_window

    day = _ymd(as_of)
    if not day:
        return False
    now = now or taipei_now()
    today = now.strftime("%Y%m%d")
    if today <= day:
        return False
    return bool(is_live_merge_window(now=now))


def _still_leave_zero_live(
    db_path: str,
    sid: str,
    *,
    live_price: float,
    frames: Dict[str, Any],
) -> bool:
    """現價複核：買點（leave_zero）仍在。買點消失＝False。"""
    from decision_card_signals import (
        cal60_low_close_at,
        card_alerts_for_df,
        leave_zero_screen_ok,
        profit_pct_cal60_series,
    )

    df = frames.get(sid)
    if df is None or len(df) < 2:
        return False
    try:
        from wayne_navigator import frame_for_cal60_profit

        profit_df = frame_for_cal60_profit(df, db_path)
        profits = profit_pct_cal60_series(profit_df)
        floor = float(cal60_low_close_at(profit_df, -1) or 0)
        official_pt = float(profits.iloc[-1])
        _ya, ta_off = card_alerts_for_df(profit_df)
    except Exception:
        return False
    if floor <= 0 or live_price <= 0:
        return False
    live_profit = round((float(live_price) - floor) / floor * 100.0, 1)
    today_alert = "60低" if float(live_price) <= floor * 1.005 else "No"
    ok, _ = leave_zero_screen_ok(
        official_pt,
        live_profit,
        yest_alert=ta_off,
        today_alert=today_alert,
    )
    return bool(ok)


def filter_intraday_from_roster(
    db_path: str,
    roster: Sequence[Dict[str, Any]],
    *,
    quotes: Optional[Dict[str, Dict[str, Any]]] = None,
) -> List[Dict[str, Any]]:
    """昨盤後勝率名單 → 買點仍在且現價更低才留；買點消失就不出現。"""
    rows = [r for r in (roster or []) if isinstance(r, dict) and str(r.get("stock_id") or "").strip()]
    if not rows:
        return []
    codes = [str(r["stock_id"]).strip() for r in rows]
    from screening_engine import ScreeningEngine

    engine = ScreeningEngine(db_path)
    as_of = _ymd(rows[0].get("as_of")) or _ymd(engine.get_latest_trading_date())
    frames = engine._load_close_frames(codes, as_of) or {}
    live_quotes = quotes
    if live_quotes is None:
        try:
            from midday_review import fetch_mis_batch

            live_quotes = fetch_mis_batch(codes, db_path) or {}
        except Exception:
            live_quotes = {}
    out: List[Dict[str, Any]] = []
    for row in rows:
        sid = str(row.get("stock_id") or "").strip()
        try:
            pick_close = float(row.get("pick_close") if row.get("pick_close") is not None else row.get("close"))
        except (TypeError, ValueError):
            continue
        if pick_close <= 0:
            continue
        q = (live_quotes or {}).get(sid) or {}
        raw_px = q.get("price") if q.get("price") is not None else q.get("close")
        if raw_px is None:
            continue
        try:
            price = float(raw_px)
        except (TypeError, ValueError):
            continue
        if price <= 0 or price >= pick_close:
            continue
        if not _still_leave_zero_live(db_path, sid, live_price=price, frames=frames):
            continue
        item = dict(row)
        item["live_price"] = price
        item["close"] = price
        out.append(item)
    return out


def resolve_button_rows(
    db_path: str,
    *,
    now=None,
    quotes: Optional[Dict[str, Dict[str, Any]]] = None,
) -> Tuple[str, List[Dict[str, Any]], str]:
    """按鈕按下：回 (as_of, rows, mode)。mode＝full|filter|empty。"""
    as_of = latest_roster_as_of(db_path)
    if not as_of:
        return "", [], "empty"
    roster = load_winrate_roster(db_path, as_of)
    if should_apply_intraday_filter(as_of=as_of, now=now):
        filtered = filter_intraday_from_roster(db_path, roster, quotes=quotes)
        return as_of, filtered, "filter"
    return as_of, roster, "full"


def render_stock_pair(
    db_path: str,
    stock_id: str,
    stock_name: str = "",
    *,
    charts_dir: str = "",
    uid: str = "winrate",
) -> Tuple[str, str, str]:
    """壓力區間圖＋高低溫度卡。回 (vol_path, card_path, caption_name)。"""
    from vol_zone_chart import render_volume_zone_result
    from wayne_navigator import NavigatorEngine, render_decision_card_png

    sid = str(stock_id or "").strip()
    if not sid:
        return "", "", ""
    charts = charts_dir or os.path.join(os.path.dirname(db_path) or ".", "charts")
    os.makedirs(charts, exist_ok=True)
    safe_uid = str(uid or "winrate").replace("/", "_")[:32]
    vz_path = os.path.join(charts, f"{sid}_wr_vz_{safe_uid}.jpg")
    card_path = os.path.join(charts, f"{sid}_wr_card_{safe_uid}.jpg")
    card: Dict[str, Any] = {}
    try:
        engine = NavigatorEngine(db_path)
        card = engine.get_decision_card(
            sid, lookback=20, merge_live=False, live_quote=None
        ) or {}
        if isinstance(card, dict):
            card.pop("_ohlc", None)
    except Exception:
        logger.exception("勝率買點高低卡失敗 code=%s", sid)
        card = {}
    name = str(stock_name or "")
    if isinstance(card, dict) and not card.get("error"):
        name = str(card.get("stock_name") or card.get("name") or name or sid)
    else:
        card = {}
        name = name or sid
    try:
        vpath, _cap = render_volume_zone_result(
            sid,
            name,
            db_path,
            vz_path,
            card=card or None,
            with_nav_signals=True,
        )
    except Exception:
        logger.exception("勝率買點壓力區失敗 code=%s", sid)
        vpath = ""
    cpath = ""
    if card:
        try:
            cpath = render_decision_card_png(card, card_path) or ""
        except Exception:
            logger.exception("勝率買點決策卡 PNG 失敗 code=%s", sid)
            cpath = ""
    return str(vpath or ""), str(cpath or ""), name


def header_html(as_of: str, total: int, *, mode: str = "full", offset: int = 0) -> str:
    from html import escape as html_escape

    day = _ymd(as_of)
    day_disp = f"{day[4:6]}/{day[6:8]}" if len(day) == 8 else day
    if total <= 0:
        return EMPTY_MSG
    start = int(offset) + 1
    end = min(int(offset) + PAGE_SIZE, total)
    mode_note = "隔日盤中篩（買點仍在且現價更低）" if mode == "filter" else "盤後 leave_zero（藍▲紅框）"
    return (
        f"<b>勝率買點</b>　基準日 {html_escape(day_disp)}　"
        f"{start}–{end}/{total}　<i>{html_escape(mode_note)}</i>"
    )


def silent_remember_roster(db_path: str, as_of: str = "", rows: Optional[Sequence[Dict[str, Any]]] = None) -> int:
    """盤後勝率名單靜默凍進 live_judge（官方柱）。空名單不算。失敗吞掉。不准改買訊。"""
    day = _ymd(as_of)
    items = list(rows) if rows is not None else load_winrate_roster(db_path, day)
    if not day:
        day = latest_roster_as_of(db_path)
    if not day or not items:
        return 0
    payload: List[Dict[str, Any]] = []
    for it in items:
        if not isinstance(it, dict):
            continue
        sid = str(it.get("stock_id") or it.get("code") or "").strip()
        if not sid or sid == "__empty__":
            continue
        row = dict(it)
        row["stock_id"] = sid
        row["bucket_key"] = KIND_ROSTER
        row["why"] = "leave_zero"
        payload.append(row)
    if not payload:
        return 0
    try:
        from judge_tape import remember_rows

        return int(
            remember_rows(
                db_path,
                KIND_ROSTER,
                payload,
                as_of=day,
                pick="rule",
                src="winrate",
            )
            or 0
        )
    except Exception:
        return 0


def silent_remember_filter(
    db_path: str,
    *,
    roster_as_of: str,
    kept: Sequence[Dict[str, Any]],
    filter_as_of: str = "",
) -> int:
    """隔日盤中篩結果靜默凍：只記仍在且現價更低的真代號。失敗吞掉。"""
    day = _ymd(filter_as_of)
    if not day:
        try:
            from config import taipei_today_str

            day = _ymd(taipei_today_str())
        except Exception:
            day = ""
    roster_day = _ymd(roster_as_of)
    payload: List[Dict[str, Any]] = []
    for it in kept or []:
        if not isinstance(it, dict):
            continue
        sid = str(it.get("stock_id") or it.get("code") or "").strip()
        if not sid:
            continue
        row = dict(it)
        row["stock_id"] = sid
        row["bucket_key"] = KIND_FILTER
        row["src_as_of"] = roster_day
        row["why"] = "leave_zero_still"
        if row.get("live_price") is not None and row.get("close") is None:
            row["close"] = row.get("live_price")
        payload.append(row)
    if not day or not payload:
        return 0
    try:
        from judge_tape import remember_rows

        return int(
            remember_rows(
                db_path,
                KIND_FILTER,
                payload,
                as_of=day,
                pick=roster_day or "rule",
                src="winrate_filter",
            )
            or 0
        )
    except Exception:
        return 0
