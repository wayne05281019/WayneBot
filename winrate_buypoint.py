# -*- coding: utf-8 -*-
"""勝率買點：盤後 leave_zero（藍▲紅框）名單＋21:00 推播＋隔日盤中篩。

訊號只認壓力圖藍▲紅框＝leave_zero（剛離零），不含還在零。
不准改黃金買點公式。盤中未收不當官方收。時區 Asia/Taipei。
"""
from __future__ import annotations

import logging
import os
import shutil
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Dict, List, Optional, Sequence, Tuple

logger = logging.getLogger(__name__)

# 一頁出圖：準備階段平行（DB／對齊）；paint 仍受 mpl 鎖。
_PAGE_PREPARE_WORKERS = 8
# 盤後日圖快取：同 SCAN_KIND＋as_of＋代號可跨人／跨次重用（內容相同）。
_PAIR_CACHE_DIRNAME = "wr_pair_cache"

PAGE_SIZE = 15
EMPTY_MSG = "今天無勝率買點股票出現"
NEXT_PAGE_LABEL = "下一個 15 檔"
BTN_LABEL = "勝率買點"
CALLBACK_PREFIX = "wr:"
# 掃版本：圖上今日藍▲紅框＝leave_zero_from_quote_df 且 _nav_trade_marks 最後一根仍畫買點。
# 舊版 screen_leave_zero_pick／只認公式不認出圖，會推「公式剛離零但圖被 watch／賣點剝掉紅框」的檔。
# ex5＝buy_exclude_v5（#481 結構＋當天額＜500萬；拿掉 live near_h20）＋**AI 生態系 ONLY**。
# 換鍵→roster_is_current 失敗→按鈕／開機 catch-up 強制重掃（同 #484 教訓）。
SCAN_KIND = "card_lz_paint_ex5"
# 靜默對質 kind（與 button_silent_verify／live_judge 對齊；勝率不准混海選／剛脫離零）
KIND_ROSTER = "winrate_buypoint"
KIND_FILTER = "winrate_filter"
KIND_NON_AI_CTRL = "winrate_non_ai_ctrl"  # 非 AI 生態系靜默對照；不進推播／按鈕
# pipeline_runs 鍵前綴；換鍵＝今日可再推一次（#472 晚於 21:00 上線後補掃）
PIPELINE_KEY_PREFIX = "winrate-bp"

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
            src = _tag_scan_source(it.get("quote_source") or "")
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
                (day, "__empty__", "", None, None, _tag_scan_source("empty"), stamp),
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
    # AI 生態系 ONLY（生技／醫療／傳產／非 AI 刪）；按鈕／推播／翻頁同一套
    try:
        from winrate_ai_priority import filter_winrate_rows_ai_only

        return filter_winrate_rows_ai_only(out, db_path)
    except Exception:
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


def _tag_scan_source(raw: str) -> str:
    src = str(raw or "").strip()
    if src.startswith(f"{SCAN_KIND}|"):
        return src
    return f"{SCAN_KIND}|{src or 'daily'}"


def roster_marked(db_path: str, as_of: str) -> bool:
    """當日已掃過（含空名單）就算有檔。"""
    day = _ymd(as_of)
    if not day:
        return False
    ensure_winrate_table(db_path)
    conn = sqlite3.connect(db_path)
    try:
        row = conn.execute(
            "SELECT 1 FROM winrate_buypoint_roster WHERE as_of=? LIMIT 1",
            (day,),
        ).fetchone()
        return bool(row)
    finally:
        conn.close()


def roster_is_current(db_path: str, as_of: str) -> bool:
    """當日名單已是現行掃版本（藍▲＝card_lz）。舊版／缺檔＝False → 應重掃。"""
    day = _ymd(as_of)
    if not day:
        return False
    ensure_winrate_table(db_path)
    conn = sqlite3.connect(db_path)
    try:
        row = conn.execute(
            "SELECT quote_source FROM winrate_buypoint_roster WHERE as_of=? LIMIT 1",
            (day,),
        ).fetchone()
    finally:
        conn.close()
    if not row:
        return False
    return str(row[0] or "").startswith(f"{SCAN_KIND}|")


def pipeline_run_key(as_of: str) -> str:
    day = _ymd(as_of) or "none"
    return f"{PIPELINE_KEY_PREFIX}-{day}"


def _chart_paints_buy_mark_today(profit_df, card: Optional[Dict[str, Any]]) -> bool:
    """壓力區／導航出圖最後一根是否畫藍▲紅框（含 card 剝 watch／no／賣點）。"""
    if profit_df is None or len(profit_df) < 2:
        return False
    try:
        from wayne_navigator import _nav_trade_marks

        use_card = card if isinstance(card, dict) and not card.get("error") else None
        buy_is, _sell_i = _nav_trade_marks(profit_df, use_card)
        last = len(profit_df) - 1
        return last in {int(i) for i in (buy_is or [])}
    except Exception:
        return False


def scan_winrate_leave_zero(
    db_path: str,
    *,
    as_of: Optional[str] = None,
) -> Tuple[str, List[Dict[str, Any]]]:
    """盤後官方母體：上市／上櫃／興櫃，今日收盤圖會畫藍▲紅框者。

    1) 柱公式＝leave_zero_from_quote_df（與導航買點標同一條；含雙綠脫離）
    2) 出圖＝_nav_trade_marks 最後一根仍留買點（watch／no／直接減碼會剝紅框→不准進名單）
    3) 另套 buy_exclude（與剛脫離零／導航藍▲ paint 同一套）：鎖跌停／結構破底／量縮／當天額等
    4) AI 生態系＋電機機械＋光電 ONLY（生技／醫療／傳產刪）
    不准改黃金買點本身。盤中未收不當收。最後一根 date 必須＝as_of。
    """
    from decision_card_signals import (
        cal60_low_close_at,
        leave_zero_from_quote_df,
        profit_pct_cal60_series,
    )
    from screening_engine import ScreeningEngine
    from universe import is_screen_equity
    from wayne_navigator import NavigatorEngine, frame_for_cal60_profit

    engine = ScreeningEngine(db_path)
    day = _ymd(as_of) or _ymd(engine.get_latest_trading_date())
    if not day:
        return "", []
    frames, em_ids = engine._load_profit_scan_frames(day)
    em_ids = em_ids or set()
    types: Dict[str, str] = {}
    try:
        conn = sqlite3.connect(db_path)
        try:
            types = {
                str(sid): str(atype or "")
                for sid, atype in conn.execute(
                    "SELECT stock_id, asset_type FROM stock_universe"
                )
            }
        finally:
            conn.close()
    except Exception:
        types = {}

    try:
        nav = NavigatorEngine(db_path)
    except Exception:
        nav = None

    cleaned: List[Dict[str, Any]] = []
    for sid, df in (frames or {}).items():
        sid = str(sid or "").strip()
        if not sid or df is None or len(df) < 2:
            continue
        name = ""
        try:
            name = str(df["stock_name"].iloc[-1] or "")
        except Exception:
            name = ""
        if not is_screen_equity(sid, name, types.get(sid)):
            continue
        last_day = _ymd(df["date"].iloc[-1] if "date" in df.columns else "")
        # 興櫃／上市櫃一律要求最後一根＝基準日，避免 em_as_of 落後時拿舊日當今日。
        if last_day != day:
            continue
        try:
            profit_df = frame_for_cal60_profit(df, db_path)
        except Exception:
            profit_df = df
        if not leave_zero_from_quote_df(profit_df):
            continue
        card: Dict[str, Any] = {}
        if nav is not None:
            try:
                card = (
                    nav.get_decision_card(
                        sid, lookback=20, merge_live=False, live_quote=None
                    )
                    or {}
                )
            except Exception:
                card = {}
        if not _chart_paints_buy_mark_today(profit_df, card):
            continue
        if isinstance(card, dict) and not card.get("error"):
            name = str(card.get("stock_name") or card.get("name") or name or sid)
        try:
            profits = profit_pct_cal60_series(profit_df)
            profit_f = float(profits.iloc[-1])
        except Exception:
            profit_f = None
        try:
            close_f = float(df["close"].iloc[-1] or 0)
        except Exception:
            continue
        if close_f <= 0:
            continue
        try:
            floor = float(cal60_low_close_at(profit_df, -1) or 0)
        except Exception:
            floor = 0.0
        src = "emerging_quotes" if sid in em_ids else "daily_quotes"
        cleaned.append(
            {
                "stock_id": sid,
                "stock_name": name,
                "close": close_f,
                "pick_close": close_f,
                "profit_pct": profit_f,
                "cal60_low": floor,
                "quote_source": src,
                "_live_skipped": False,
            }
        )
    # 雙保險：導航 paint 已走 buy_exclude；名單再濾一次
    try:
        from buy_exclude import filter_leave_zero_rows

        cleaned = filter_leave_zero_rows(cleaned, frames or {}, db_path=db_path)
    except Exception:
        pass
    # AI 生態系 ONLY：非 AI（生技／醫療／傳產等）刪除不推；對照臂靜默記
    try:
        from winrate_ai_priority import partition_winrate_ai_rows

        ai_rows, non_ai = partition_winrate_ai_rows(cleaned, db_path)
        if non_ai:
            try:
                silent_remember_non_ai_ctrl(db_path, day, non_ai)
            except Exception:
                logger.debug("勝率非 AI 對照落檔略過", exc_info=True)
        cleaned = ai_rows
    except Exception:
        cleaned.sort(key=lambda r: str(r.get("stock_id") or ""))
    return day, cleaned


def ensure_winrate_roster(
    db_path: str,
    *,
    as_of: Optional[str] = None,
    force: bool = False,
) -> Tuple[str, List[Dict[str, Any]]]:
    """基準日 roster 缺檔或掃版本舊 → 用最新官方收重掃 leave_zero（藍▲）再建檔。"""
    day = _ymd(as_of)
    if not day:
        try:
            from import_health import latest_complete_quote_date

            day = _ymd(latest_complete_quote_date(db_path))
        except Exception:
            day = ""
    if not day:
        return "", []
    if not force and roster_is_current(db_path, day):
        return day, load_winrate_roster(db_path, day)
    day2, rows = scan_winrate_leave_zero(db_path, as_of=day)
    if not day2:
        return "", []
    save_winrate_roster(db_path, day2, rows)
    try:
        silent_remember_roster(db_path, day2, rows)
    except Exception:
        logger.debug("勝率買點 ensure 靜默落檔略過", exc_info=True)
    return day2, load_winrate_roster(db_path, day2)


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
    """按鈕按下：回 (as_of, rows, mode)。mode＝full|filter|empty。

    優先用最新完整官方收基準日；當日 roster 缺／掃版本舊就當場補掃再建檔。
    """
    complete = ""
    try:
        from import_health import latest_complete_quote_date

        complete = _ymd(latest_complete_quote_date(db_path))
    except Exception:
        complete = ""
    as_of = complete or latest_roster_as_of(db_path)
    if not as_of:
        return "", [], "empty"
    if complete and not roster_is_current(db_path, complete):
        as_of, roster = ensure_winrate_roster(db_path, as_of=complete)
    else:
        roster = load_winrate_roster(db_path, as_of)
    if not as_of:
        return "", [], "empty"
    if should_apply_intraday_filter(as_of=as_of, now=now):
        filtered = filter_intraday_from_roster(db_path, roster, quotes=quotes)
        return as_of, filtered, "filter"
    return as_of, roster, "full"


def _pair_cache_dir(charts_dir: str, as_of: str) -> str:
    day = _ymd(as_of)
    return os.path.join(
        charts_dir or ".",
        _PAIR_CACHE_DIRNAME,
        SCAN_KIND,
        day or "none",
    )


def _cache_pair_paths(cache_dir: str, stock_id: str) -> Tuple[str, str]:
    sid = str(stock_id or "").strip()
    return (
        os.path.join(cache_dir, f"{sid}_vz.jpg"),
        os.path.join(cache_dir, f"{sid}_card.jpg"),
    )


def _cache_file_ok(path: str, *, min_bytes: int = 20_000) -> bool:
    try:
        return bool(path) and os.path.isfile(path) and os.path.getsize(path) >= int(min_bytes)
    except OSError:
        return False


def _copy_into(src: str, dest: str) -> str:
    if not src or not os.path.isfile(src):
        return ""
    if os.path.abspath(src) == os.path.abspath(dest):
        return dest
    parent = os.path.dirname(dest)
    if parent:
        os.makedirs(parent, exist_ok=True)
    try:
        shutil.copy2(src, dest)
        return dest if os.path.isfile(dest) else src
    except Exception:
        return src


def warm_winrate_cards(
    db_path: str,
    rows: Sequence[Dict[str, Any]],
) -> Dict[str, Dict[str, Any]]:
    """平行預熱高低卡（掃完／出圖前）。掃版過程 memo 可能被擠掉，這裡補回本頁。"""
    from wayne_navigator import NavigatorEngine

    items = [
        str(r.get("stock_id") or "").strip()
        for r in (rows or [])
        if isinstance(r, dict) and str(r.get("stock_id") or "").strip()
    ]
    if not items:
        return {}

    def _one(sid: str) -> Tuple[str, Dict[str, Any]]:
        try:
            eng = NavigatorEngine(db_path)
            card = eng.get_decision_card(
                sid, lookback=20, merge_live=False, live_quote=None
            ) or {}
            if isinstance(card, dict):
                card.pop("_ohlc", None)
                if card.get("error"):
                    return sid, {}
                return sid, card
        except Exception:
            logger.exception("勝率買點預熱高低卡失敗 code=%s", sid)
        return sid, {}

    out: Dict[str, Dict[str, Any]] = {}
    workers = max(1, min(_PAGE_PREPARE_WORKERS, len(items)))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for sid, card in pool.map(_one, items):
            out[sid] = card if isinstance(card, dict) else {}
    return out


def render_page_pairs(
    db_path: str,
    rows: Sequence[Dict[str, Any]],
    *,
    charts_dir: str = "",
    uid: str = "winrate",
    as_of: str = "",
    reuse_cache: bool = True,
) -> List[Tuple[str, str, str]]:
    """一頁（≤15）壓力區＋高低卡：快取重用／平行準備／卡圖與壓力區重疊出圖。

    回傳與 rows 同序的 (vz_path, card_path, caption_name)；失敗格空字串。
    同 as_of＋SCAN_KIND 的官方日圖跨人共用磁碟快取；uid 只影響工作檔名，不拆內容。
    """
    from vol_zone_chart import render_volume_zone_result
    from wayne_navigator import render_decision_card_png

    charts = charts_dir or os.path.join(os.path.dirname(db_path) or ".", "charts")
    os.makedirs(charts, exist_ok=True)
    safe_uid = str(uid or "winrate").replace("/", "_")[:32]
    day = _ymd(as_of) or _ymd((rows[0] or {}).get("as_of") if rows else "")
    cache_dir = _pair_cache_dir(charts, day) if day else ""
    if cache_dir:
        os.makedirs(cache_dir, exist_ok=True)

    jobs: List[Dict[str, Any]] = []
    for row in rows or []:
        if not isinstance(row, dict):
            jobs.append({"sid": "", "name": "", "skip": True})
            continue
        sid = str(row.get("stock_id") or "").strip()
        name = str(row.get("stock_name") or row.get("name") or "")
        if not sid:
            jobs.append({"sid": "", "name": name, "skip": True})
            continue
        vz_work = os.path.join(charts, f"{sid}_wr_vz_{safe_uid}.jpg")
        card_work = os.path.join(charts, f"{sid}_wr_card_{safe_uid}.jpg")
        cvz = ccard = ""
        if reuse_cache and cache_dir:
            cvz, ccard = _cache_pair_paths(cache_dir, sid)
        jobs.append(
            {
                "sid": sid,
                "name": name,
                "vz_work": vz_work,
                "card_work": card_work,
                "cache_vz": cvz,
                "cache_card": ccard,
                "skip": False,
            }
        )
    if not jobs:
        return []

    out: List[Tuple[str, str, str]] = [("", "", "")] * len(jobs)
    need_idx: List[int] = []
    for i, job in enumerate(jobs):
        if job.get("skip"):
            out[i] = ("", "", str(job.get("name") or ""))
            continue
        cvz, ccard = job["cache_vz"], job["cache_card"]
        if (
            reuse_cache
            and _cache_file_ok(cvz)
            and _cache_file_ok(ccard, min_bytes=8_000)
        ):
            vpath = _copy_into(cvz, job["vz_work"])
            cpath = _copy_into(ccard, job["card_work"])
            out[i] = (vpath, cpath, job["name"] or job["sid"])
        else:
            need_idx.append(i)

    if not need_idx:
        return out

    # 冷路徑用串行（mpl 鎖下平行準備幾乎省不到，還多開銷）；
    # 高低卡 PNG 與下一檔壓力區準備可重疊一點點。
    from wayne_navigator import NavigatorEngine

    eng = NavigatorEngine(db_path)
    with ThreadPoolExecutor(max_workers=1) as card_pool:
        prev_card_fut = None
        prev_i = None
        prev_meta: Tuple[str, str, str] = ("", "", "")
        for i in need_idx:
            job = jobs[i]
            sid = job["sid"]
            card: Dict[str, Any] = {}
            try:
                card = eng.get_decision_card(
                    sid, lookback=20, merge_live=False, live_quote=None
                ) or {}
                if isinstance(card, dict):
                    card.pop("_ohlc", None)
                    if card.get("error"):
                        card = {}
                else:
                    card = {}
            except Exception:
                logger.exception("勝率買點高低卡失敗 code=%s", sid)
                card = {}
            name = str(
                (card.get("stock_name") or card.get("name") or job["name"] or sid)
                if card
                else (job["name"] or sid)
            )
            vpath = ""
            try:
                vpath, _cap = render_volume_zone_result(
                    sid,
                    name,
                    db_path,
                    job["vz_work"],
                    card=card or None,
                    with_nav_signals=True,
                )
            except Exception:
                logger.exception("勝率買點壓力區失敗 code=%s", sid)
                vpath = ""
            # 收前一檔高低卡
            if prev_card_fut is not None and prev_i is not None:
                cpath_prev = ""
                try:
                    cpath_prev = str(prev_card_fut.result() or "")
                except Exception:
                    logger.exception(
                        "勝率買點決策卡 PNG 失敗 code=%s", jobs[prev_i]["sid"]
                    )
                pv, _pc, pn = prev_meta
                if reuse_cache and cache_dir:
                    if _cache_file_ok(pv):
                        _copy_into(pv, jobs[prev_i]["cache_vz"])
                    if _cache_file_ok(cpath_prev, min_bytes=8_000):
                        _copy_into(cpath_prev, jobs[prev_i]["cache_card"])
                out[prev_i] = (pv, cpath_prev, pn)
            if card:
                prev_card_fut = card_pool.submit(
                    render_decision_card_png, card, job["card_work"]
                )
            else:
                prev_card_fut = None
            prev_i = i
            prev_meta = (str(vpath or ""), "", name)
        if prev_card_fut is not None and prev_i is not None:
            cpath_prev = ""
            try:
                cpath_prev = str(prev_card_fut.result() or "")
            except Exception:
                logger.exception(
                    "勝率買點決策卡 PNG 失敗 code=%s", jobs[prev_i]["sid"]
                )
            pv, _pc, pn = prev_meta
            if reuse_cache and cache_dir:
                if _cache_file_ok(pv):
                    _copy_into(pv, jobs[prev_i]["cache_vz"])
                if _cache_file_ok(cpath_prev, min_bytes=8_000):
                    _copy_into(cpath_prev, jobs[prev_i]["cache_card"])
            out[prev_i] = (pv, cpath_prev, pn)
        elif prev_i is not None:
            pv, _pc, pn = prev_meta
            if reuse_cache and cache_dir and _cache_file_ok(pv):
                _copy_into(pv, jobs[prev_i]["cache_vz"])
            out[prev_i] = (pv, "", pn)
    return out


def render_stock_pair(
    db_path: str,
    stock_id: str,
    stock_name: str = "",
    *,
    charts_dir: str = "",
    uid: str = "winrate",
    as_of: str = "",
    reuse_cache: bool = True,
) -> Tuple[str, str, str]:
    """壓力區間圖＋高低溫度卡。回 (vol_path, card_path, caption_name)。"""
    pairs = render_page_pairs(
        db_path,
        [{"stock_id": stock_id, "stock_name": stock_name, "as_of": as_of}],
        charts_dir=charts_dir,
        uid=uid,
        as_of=as_of,
        reuse_cache=reuse_cache,
    )
    if not pairs:
        return "", "", ""
    return pairs[0]


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


def silent_remember_non_ai_ctrl(
    db_path: str,
    as_of: str,
    rows: Sequence[Dict[str, Any]],
) -> int:
    """非 AI 生態系靜默對照（live 已刪不推）。空不算。失敗吞掉。不准改買訊。"""
    day = _ymd(as_of)
    payload: List[Dict[str, Any]] = []
    for it in rows or []:
        if not isinstance(it, dict):
            continue
        sid = str(it.get("stock_id") or it.get("code") or "").strip()
        if not sid or sid == "__empty__":
            continue
        row = dict(it)
        row["stock_id"] = sid
        row["bucket_key"] = KIND_NON_AI_CTRL
        row["why"] = "non_ai_ctrl"
        payload.append(row)
    if not day or not payload:
        return 0
    try:
        from judge_tape import remember_rows

        return int(
            remember_rows(
                db_path,
                KIND_NON_AI_CTRL,
                payload,
                as_of=day,
                pick="rule",
                src="winrate_non_ai",
            )
            or 0
        )
    except Exception:
        return 0