"""盤中即時：證交所 MIS。不寫回 sqlite，只合併進記憶體內的日 K。"""
from __future__ import annotations

import logging
import os
import sqlite3
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, time as dt_time
from typing import Any, Dict, List, Optional, Sequence, Tuple, Union

import pandas as pd
import requests

from config import taipei_now, taipei_today_str

logger = logging.getLogger("WayneBot.LiveQuote")

_SESSION = requests.Session()
_QUOTE_LOCK = threading.Lock()
_QUOTE_CACHE: Dict[Tuple[str, str], Tuple[float, Optional[Dict[str, Any]]]] = {}
_QUOTE_TTL_SEC = 20.0
_MIS_TIMEOUT = float(os.getenv("WAYNE_MIS_TIMEOUT", "2.5"))
_MIS_CONNECT_TIMEOUT = float(os.getenv("WAYNE_MIS_CONNECT_TIMEOUT", "1.5"))
_SESSION.headers.update(
    {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        "Referer": "https://mis.twse.com.tw/stock/index.jsp",
    }
)


def _num(val, default: float = 0.0) -> float:
    s = str(val or "").replace(",", "").replace("+", "").strip()
    if s in ("", "-", "--", "N/A", "null", "None"):
        return default
    try:
        return float(s)
    except ValueError:
        return default


def _first_book(side: str) -> float:
    return _num(str(side or "").split("_")[0])


def _last_price(item: dict, yesterday: float) -> float:
    z = _num(item.get("z"))
    if z > 0:
        return z
    bid, ask = _first_book(item.get("b")), _first_book(item.get("a"))
    if bid > 0 and ask > 0:
        return round((bid + ask) / 2.0, 2)
    if ask > 0:
        return ask
    if bid > 0:
        return bid
    h, l = _num(item.get("h")), _num(item.get("l"))
    if h > 0 and l > 0:
        return round((h + l) / 2.0, 2)
    return yesterday


def _channels(stock_id: str, market: str = "") -> list:
    sid = str(stock_id).strip()
    m = (market or "").upper()
    tse, otc = f"tse_{sid}.tw", f"otc_{sid}.two"
    if m in ("TWO", "OTC", "ROCC", "上櫃"):
        return [otc, tse]
    return [tse, otc]


def _norm_date(val) -> str:
    return str(val or "").replace("-", "").strip()


def is_live_merge_window(now=None) -> bool:
    """08:50～16:30 台灣時間、週一～五：庫還沒今天官方收盤時，用 MIS／Yahoo 合併今日 K（不寫回 sqlite）。

    結束點對齊 16:30 融合，避免 16:00～16:30 既沒即時列、庫也還沒今天。
    """
    now = now or taipei_now()
    if now.weekday() >= 5:
        return False
    from trading_calendar import is_trading_weekday

    today = now.strftime("%Y%m%d")
    if not is_trading_weekday(today):
        return False
    t = now.time()
    return dt_time(8, 50) <= t < dt_time(16, 30)


def calc_vol_rank_120(
    volumes: Sequence[Union[int, float]],
    window: int = 120,
    *,
    closes: Sequence[Union[int, float]] | None = None,
) -> int:
    """這檔自己近 window 根成交量排名：1＝區間內最大量。"""
    from decision_card_signals import calc_volume_rank

    return calc_volume_rank(volumes, window, closes=closes)


def live_vol_rank_120_batch(
    db_path: str,
    code_volumes: Dict[str, Union[int, float]],
    window: int = 120,
) -> Dict[str, int]:
    """多檔一次查歷史量，避免當沖複核逐檔開連線。"""
    if not code_volumes:
        return {}
    codes = [str(c).strip() for c in code_volumes if str(c).strip()]
    if not codes:
        return {}
    today = taipei_today_str()
    limit = window + 2
    conn = sqlite3.connect(db_path)
    try:
        placeholders = ",".join("?" * len(codes))
        rows = conn.execute(
            f"""
            SELECT stock_id, date, volume FROM daily_quotes
            WHERE stock_id IN ({placeholders})
            ORDER BY stock_id, date DESC
            """,
            codes,
        ).fetchall()
    finally:
        conn.close()
    by_code: Dict[str, List[float]] = {c: [] for c in codes}
    counts: Dict[str, int] = {c: 0 for c in codes}
    for sid, d, v in rows:
        code = str(sid)
        if code not in by_code:
            continue
        if counts[code] >= limit:
            continue
        counts[code] += 1
        if _norm_date(d) >= today:
            continue
        by_code[code].append(float(v or 0))
    out: Dict[str, int] = {}
    for code, live_vol in code_volumes.items():
        sid = str(code).strip()
        if not sid:
            continue
        vols = list(reversed(by_code.get(sid) or []))
        vols.append(float(live_vol or 0))
        if len(vols) > window:
            vols = vols[-window:]
        out[sid] = calc_vol_rank_120(vols, window)
    return out


def live_vol_rank_120(
    db_path: str,
    stock_id: str,
    live_volume: Union[int, float],
    window: int = 120,
) -> int:
    """用庫裡歷史量 + MIS 此刻累積張數，算盤中 120 日量排名。"""
    sid = str(stock_id).strip()
    if not sid:
        return 99
    today = taipei_today_str()
    conn = sqlite3.connect(db_path)
    try:
        rows = conn.execute(
            """
            SELECT date, volume FROM daily_quotes
            WHERE stock_id = ?
            ORDER BY date DESC
            LIMIT ?
            """,
            (sid, window + 2),
        ).fetchall()
    finally:
        conn.close()
    vols: List[float] = []
    for d, v in reversed(rows):
        if _norm_date(d) >= today:
            continue
        vols.append(float(v or 0))
    vols.append(float(live_volume or 0))
    if len(vols) > window:
        vols = vols[-window:]
    return calc_vol_rank_120(vols, window)


def mis_session_label(update_time: str) -> str:
    """上市櫃現股 13:30 收。MIS 停在 13:30:00 就是收盤價，不要再寫盤中。"""
    t = str(update_time or "").strip().replace("：", ":")
    if not t:
        return "盤中"
    parts = t.split(":")
    try:
        hour = int(parts[0])
        minute = int(parts[1]) if len(parts) > 1 else 0
    except (TypeError, ValueError):
        return "盤中"
    if (hour, minute) >= (13, 30) or hour < 9:
        return "收盤"
    return "盤中"


def format_mis_clock_line(update_time: str) -> str:
    t = str(update_time or "").strip()
    if not t:
        return ""
    return f"{mis_session_label(t)}　{t}　證交所 MIS"


def live_clock_suffix(is_live: bool, update_time: str = "") -> str:
    """決策卡／介紹圖日期旁：盤中 13:25 或 收盤 13:30。"""
    if not is_live:
        return ""
    t = str(update_time or "").strip()
    label = mis_session_label(t)
    clock = t[:5] if len(t) >= 5 else t
    if clock:
        return f" {label} {clock}"
    return f" {label}"


def mis_volume_sheets(raw_v) -> int:
    """MIS 累積成交量：證交所欄位為張（與 daily_quotes.volume 一致）。"""
    return int(_num(raw_v, 0))


def sanitize_ohlc(open_, high, low, close) -> Tuple[float, float, float, float]:
    """保證 open／close 落在 [low, high]。MIS 偶發 Op>Hi（如 5590／5515）。"""
    c = float(close or 0)
    o = float(open_ or 0) or c
    h = float(high or 0) or c
    l = float(low or 0) or c
    if c > 0:
        h = max(o, h, c)
        lows = [x for x in (o, l, c) if x > 0]
        if lows:
            l = min(lows)
    return o, h, l, c


def sanitize_ohlc_frame(df: pd.DataFrame) -> pd.DataFrame:
    """畫 K 前把每一根 high／low 夾到能包住 open／close（導航圖／指數圖防 Op>Hi）。"""
    if df is None or getattr(df, "empty", True):
        return df
    out = df.copy()
    for col in ("open", "high", "low", "close"):
        if col not in out.columns:
            return df
    o = pd.to_numeric(out["open"], errors="coerce").fillna(0.0)
    h = pd.to_numeric(out["high"], errors="coerce").fillna(0.0)
    l = pd.to_numeric(out["low"], errors="coerce").fillna(0.0)
    c = pd.to_numeric(out["close"], errors="coerce").fillna(0.0)
    o = o.where(o > 0, c)
    h = h.where(h > 0, c)
    l = l.where(l > 0, c)
    hi = pd.concat([o, h, c], axis=1).max(axis=1)
    lo_parts = pd.concat([o, l, c], axis=1)
    lo = lo_parts.mask(lo_parts <= 0).min(axis=1).fillna(c)
    valid = c > 0
    out.loc[valid, "open"] = o[valid]
    out.loc[valid, "high"] = hi[valid]
    out.loc[valid, "low"] = lo[valid]
    return out


def session_bar_from_mis(rt: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """自開盤至 MIS 回報時刻的當日 K（開高低收量），僅供記憶體合併、不寫庫。"""
    if not rt or float(rt.get("close") or 0) <= 0:
        return None
    o, h, l, c = sanitize_ohlc(rt.get("open"), rt.get("high"), rt.get("low"), rt["close"])
    return {
        "open": o,
        "high": h,
        "low": l,
        "close": c,
        "volume": mis_volume_sheets(rt.get("volume")),
        "pct_change": float(rt.get("pct_change") or 0),
        "yesterday_close": float(rt.get("yesterday_close") or 0),
        "update_time": str(rt.get("update_time") or ""),
    }


def is_lookup_trading_day(now=None) -> bool:
    """週一～五台股日曆日（假日靠庫判斷）；查股即時源用。"""
    now = now or taipei_now()
    if now.weekday() >= 5:
        return False
    from trading_calendar import is_trading_weekday

    return is_trading_weekday(now.strftime("%Y%m%d"))


def is_tw_quote_gap_window(now=None) -> bool:
    """13:30～16:30 融合前：庫內常還沒今天，MIS 收盤後也常空白，需外源補價。"""
    now = now or taipei_now()
    if now.weekday() >= 5:
        return False
    from trading_calendar import is_trading_weekday

    today = now.strftime("%Y%m%d")
    if not is_trading_weekday(today):
        return False
    t = now.time()
    return dt_time(13, 30) <= t < dt_time(16, 30)


def _db_latest_close(db_path: str, stock_id: str) -> Optional[float]:
    if not db_path or not stock_id:
        return None
    try:
        from quote_integrity import db_as_of_trading_date

        as_of = db_as_of_trading_date(db_path)
        if not as_of:
            return None
        import sqlite3

        conn = sqlite3.connect(db_path)
        row = conn.execute(
            "SELECT close FROM daily_quotes WHERE stock_id=? AND replace(date,'-','')=? LIMIT 1;",
            (str(stock_id).strip(), str(as_of).replace("-", "")[:8]),
        ).fetchone()
        conn.close()
        if row and row[0] is not None:
            c = float(row[0])
            return c if c > 0 else None
    except Exception:
        logger.debug("庫內昨收查詢失敗 %s", stock_id, exc_info=True)
    return None


def reconcile_lookup_quote(
    rt: Dict[str, Any],
    db_path: str = None,
    stock_id: str = "",
    db_hit: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """用庫內最後官方收盤當基準重算漲跌（Yahoo previousClose 常與台股昨收不一致）。"""
    out = dict(rt)
    sid = str(stock_id or out.get("stock_id") or "").strip()
    prev = None
    if db_hit:
        try:
            prev = float(db_hit.get("close") or 0)
        except (TypeError, ValueError):
            prev = None
    if not prev and db_path and sid:
        prev = _db_latest_close(db_path, sid)
    try:
        px = float(out.get("close") or 0)
    except (TypeError, ValueError):
        px = 0.0
    if prev and prev > 0 and px > 0:
        out["yesterday_close"] = prev
        out["pct_change"] = round((px - prev) / prev * 100.0, 2)
        out["change"] = round(px - prev, 2)
    return out


def fetch_yahoo_tw_quote(stock_id: str, db_path: str = None) -> Optional[Dict[str, Any]]:
    """MIS 收盤後空白時的備援（Yahoo 台股代號 .TW / .TWO）。不寫庫。"""
    from urllib.parse import quote as url_quote

    from stock_links import yahoo_exchange

    sid = str(stock_id or "").strip()
    if not sid:
        return None
    sym = f"{sid}.{yahoo_exchange(sid, db_path)}"
    url = (
        f"https://query1.finance.yahoo.com/v8/finance/chart/{url_quote(sym, safe='')}"
        "?interval=1d&range=5d"
    )
    try:
        resp = _SESSION.get(url, timeout=(_MIS_CONNECT_TIMEOUT, 4.0))
        resp.raise_for_status()
        result = (resp.json().get("chart") or {}).get("result") or []
        if not result:
            return None
        meta = result[0].get("meta") or {}
        qblock = ((result[0].get("indicators") or {}).get("quote") or [{}])[0]
        closes = qblock.get("close") or []
        vols = qblock.get("volume") or []
        px = _num(meta.get("regularMarketPrice"))
        if px <= 0 and closes:
            for c in reversed(closes):
                if c is not None and float(c) > 0:
                    px = float(c)
                    break
        if px <= 0:
            return None
        vol = 0
        if vols:
            for v in reversed(vols):
                if v is not None and float(v) > 0:
                    vol = int(float(v))
                    break
        y = _num(meta.get("chartPreviousClose") or meta.get("previousClose"))
        pct = meta.get("regularMarketChangePercent")
        chg = meta.get("regularMarketChange")
        try:
            pct_f = round(float(pct), 2) if pct is not None else None
        except (TypeError, ValueError):
            pct_f = None
        try:
            chg_f = round(float(chg), 2) if chg is not None else None
        except (TypeError, ValueError):
            chg_f = None
        if pct_f is None and y > 0:
            pct_f = round((px - y) / y * 100.0, 2)
        if chg_f is None and y > 0:
            chg_f = round(px - y, 2)
        update_time = ""
        ts = meta.get("regularMarketTime")
        if ts:
            from zoneinfo import ZoneInfo

            update_time = datetime.fromtimestamp(int(ts), tz=ZoneInfo("Asia/Taipei")).strftime(
                "%H:%M:%S"
            )
        return {
            "stock_id": sid,
            "stock_name": str(meta.get("longName") or meta.get("shortName") or ""),
            "open": px,
            "high": px,
            "low": px,
            "close": px,
            "volume": vol,
            "pct_change": pct_f or 0.0,
            "change": chg_f if chg_f is not None else 0.0,
            "yesterday_close": y,
            "update_time": update_time,
            "is_realtime": True,
            "source": "yahoo",
        }
    except Exception:
        logger.debug("Yahoo 台股報價失敗 %s", sym, exc_info=True)
        return None


def fetch_lookup_quote(
    stock_id: str,
    market: str = "",
    db_path: str = None,
    *,
    now=None,
    db_hit: Optional[Dict[str, Any]] = None,
) -> Optional[Dict[str, Any]]:
    """查股用：MIS → Yahoo；交易日 MIS 空白必走外源，不拿過期庫當現價。"""
    now = now or taipei_now()
    sid = str(stock_id or "").strip()
    rt = fetch_mis_quote(sid, market)
    if rt and float(rt.get("close") or 0) > 0:
        return rt
    if is_lookup_trading_day(now):
        y = fetch_yahoo_tw_quote(sid, db_path)
        if y and float(y.get("close") or 0) > 0:
            return reconcile_lookup_quote(y, db_path, sid, db_hit=db_hit)
    return None


def fetch_mis_quote(stock_id: str, market: str = "") -> Optional[Dict[str, Any]]:
    sid = str(stock_id).strip()
    if not sid:
        return None
    key = (sid, str(market or "").upper())
    now = time.time()
    with _QUOTE_LOCK:
        hit = _QUOTE_CACHE.get(key)
        if hit and now - hit[0] < _QUOTE_TTL_SEC:
            return hit[1]
    ts = int(time.time() * 1000)
    channels = _channels(sid, market)

    def _fetch_channel(ch: str) -> Optional[Dict[str, Any]]:
        url = f"https://mis.twse.com.tw/stock/api/getStockInfo.jsp?ex_ch={ch}&json=1&delay=0&_={ts}"
        try:
            resp = _SESSION.get(url, timeout=(_MIS_CONNECT_TIMEOUT, _MIS_TIMEOUT))
            if resp.status_code != 200:
                return None
            arr = (resp.json() or {}).get("msgArray") or []
            if not arr:
                return None
            item = arr[0]
            y = _num(item.get("y"))
            px = _last_price(item, y)
            if px <= 0:
                return None
            vol = mis_volume_sheets(item.get("v"))
            pct = round((px - y) / y * 100.0, 2) if y > 0 else 0.0
            chg = round(px - y, 2) if y > 0 else 0.0
            o, h, l, _c = sanitize_ohlc(
                _num(item.get("o")) or px,
                _num(item.get("h")) or px,
                _num(item.get("l")) or px,
                px,
            )
            return {
                "stock_id": item.get("c") or sid,
                "stock_name": item.get("n") or "",
                "open": o,
                "high": h,
                "low": l,
                "close": px,
                "volume": vol,
                "pct_change": pct,
                "change": chg,
                "yesterday_close": y,
                "update_time": item.get("t") or "",
                "is_realtime": True,
            }
        except requests.Timeout:
            logger.debug("MIS 逾時 %s", ch)
            return None
        except Exception:
            logger.debug("MIS 失敗 %s", ch, exc_info=True)
            return None

    found: Optional[Dict[str, Any]] = None
    for ch in channels:
        hit = _fetch_channel(ch)
        if hit:
            found = hit
            break
    with _QUOTE_LOCK:
        _QUOTE_CACHE[key] = (time.time(), found)
    return found


def _apply_rt_to_row(row: dict, rt: Dict[str, Any], stock_id: str) -> dict:
    out = dict(row)
    out["date"] = taipei_today_str()
    out["stock_id"] = str(stock_id)
    if "stock_name" in out and rt.get("stock_name"):
        out["stock_name"] = rt["stock_name"]
    sess = session_bar_from_mis(rt) or {}
    for k in ("open", "high", "low", "close", "volume"):
        if k in out and sess.get(k) is not None:
            out[k] = sess[k]
        elif k in rt:
            out[k] = rt[k]
    if "pct_change" in out:
        out["pct_change"] = sess.get("pct_change", rt.get("pct_change"))
    if "change_pct" in out:
        out["change_pct"] = sess.get("pct_change", rt.get("pct_change"))
    if sess.get("yesterday_close") or rt.get("yesterday_close"):
        out["yesterday_close"] = sess.get("yesterday_close") or rt.get("yesterday_close")
    if "turnover_k" in out:
        out["turnover_k"] = round(float(out.get("volume") or 0) * float(out.get("close") or 0), 2)
    if "avg_price" in out:
        out["avg_price"] = out["close"]
    out["is_live"] = True
    out["_live_time"] = sess.get("update_time") or rt.get("update_time") or ""
    return out


def append_live_bar(
    df: pd.DataFrame,
    stock_id: str,
    market: str = "",
    merge_live: bool = True,
    live_quote: Optional[Dict[str, Any]] = None,
) -> pd.DataFrame:
    """盤中用 MIS 合併今日 K：開盤→查詢當下的開高低收量（不寫回 sqlite）。"""
    if not merge_live or df is None or df.empty:
        return df
    if not is_live_merge_window():
        return df
    today = taipei_today_str()
    latest = _norm_date(df["date"].iloc[-1])
    mkt = market or (str(df["market"].iloc[-1]) if "market" in df.columns else "")
    if live_quote is not None:
        rt = live_quote
    else:
        try:
            from config import get_db_path

            rt = fetch_lookup_quote(stock_id, mkt, get_db_path())
        except Exception:
            rt = fetch_mis_quote(stock_id, mkt)
    if not rt or rt.get("close", 0) <= 0:
        return df
    if latest > today:
        return df
    if latest == today:
        official = "is_live" not in df.columns or not bool(df["is_live"].iloc[-1])
        if official:
            # 16:30 融合後列上已是官方收盤，不要用 MIS／Yahoo 蓋掉。
            return df
        out = df.copy()
        idx = len(out) - 1
        row = _apply_rt_to_row(out.iloc[idx].to_dict(), rt, stock_id)
        for col, val in row.items():
            if col not in out.columns:
                out[col] = None
            out.at[idx, col] = val
        return out
    try:
        from trading_calendar import is_trading_weekday

        if not is_trading_weekday(today):
            return df
    except Exception:
        return df
    row = {col: df.iloc[-1][col] if col in df.columns else None for col in df.columns}
    row = _apply_rt_to_row(row, rt, stock_id)
    return pd.concat([df, pd.DataFrame([row])], ignore_index=True)


_INDEX_MIS_CHANNELS = ("tse_t00.tw", "tse_t01.tw")
_INDEX_CACHE: Tuple[float, Optional[Dict[str, Any]]] = (0.0, None)
_MIS_INDEX_TIMEOUT = float(os.getenv("WAYNE_MIS_INDEX_TIMEOUT", "1.2"))


def fetch_mis_index_quote() -> Optional[Dict[str, Any]]:
    """盤中加權指數 MIS 即時（不寫庫）。非盤中時回 None。"""
    if not is_live_merge_window():
        return None
    now = time.time()
    global _INDEX_CACHE
    cached_at, cached = _INDEX_CACHE
    if cached and now - cached_at < _QUOTE_TTL_SEC:
        return cached
    ts = int(now * 1000)
    found: Optional[Dict[str, Any]] = None
    for ch in _INDEX_MIS_CHANNELS:
        url = f"https://mis.twse.com.tw/stock/api/getStockInfo.jsp?ex_ch={ch}&json=1&delay=0&_={ts}"
        try:
            resp = _SESSION.get(
                url,
                timeout=(_MIS_CONNECT_TIMEOUT, min(_MIS_TIMEOUT, _MIS_INDEX_TIMEOUT)),
            )
            if resp.status_code != 200:
                continue
            arr = (resp.json() or {}).get("msgArray") or []
            if not arr:
                continue
            item = arr[0]
            y = _num(item.get("y"))
            px = _last_price(item, y)
            if px <= 0:
                continue
            pct = round((px - y) / y * 100.0, 2) if y > 0 else _num(item.get("zf") or item.get("ch"))
            found = {
                "close": px,
                "pct_change": pct,
                "yesterday_close": y if y > 0 else None,
                "open": _num(item.get("o")),
                "high": _num(item.get("h")),
                "low": _num(item.get("l")),
                "volume": _num(item.get("v")),
                "update_time": item.get("t") or "",
                "name": item.get("n") or "加權指數",
                "is_realtime": True,
            }
            break
        except requests.Timeout:
            logger.debug("MIS 指數逾時 %s", ch)
        except Exception:
            logger.debug("MIS 指數失敗 %s", ch, exc_info=True)
    _INDEX_CACHE = (now, found)
    return found
