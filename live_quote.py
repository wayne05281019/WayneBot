"""盤中即時：證交所 MIS。不寫回 sqlite，只合併進記憶體內的日 K。"""
from __future__ import annotations

import logging
import sqlite3
import threading
import time
from datetime import time as dt_time
from typing import Any, Dict, List, Optional, Sequence, Tuple, Union

import pandas as pd
import requests

from config import taipei_now, taipei_today_str

logger = logging.getLogger("WayneBot.LiveQuote")

_SESSION = requests.Session()
_QUOTE_LOCK = threading.Lock()
_QUOTE_CACHE: Dict[Tuple[str, str], Tuple[float, Optional[Dict[str, Any]]]] = {}
_QUOTE_TTL_SEC = 20.0
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
    """08:50～16:00 台灣時間：允許用 MIS 覆寫／追加今日 K（不寫回 sqlite）。"""
    now = now or taipei_now()
    t = now.time()
    return dt_time(8, 50) <= t < dt_time(16, 0)


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
    found: Optional[Dict[str, Any]] = None
    for ch in _channels(sid, market):
        url = f"https://mis.twse.com.tw/stock/api/getStockInfo.jsp?ex_ch={ch}&json=1&delay=0&_={ts}"
        try:
            resp = _SESSION.get(url, timeout=6)
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
            vol = int(_num(item.get("v"), 0))
            pct = round((px - y) / y * 100.0, 2) if y > 0 else 0.0
            chg = round(px - y, 2) if y > 0 else 0.0
            found = {
                "stock_id": item.get("c") or sid,
                "stock_name": item.get("n") or "",
                "open": _num(item.get("o")) or px,
                "high": _num(item.get("h")) or px,
                "low": _num(item.get("l")) or px,
                "close": px,
                "volume": vol,
                "pct_change": pct,
                "change": chg,
                "yesterday_close": y,
                "update_time": item.get("t") or "",
                "is_realtime": True,
            }
            break
        except Exception:
            logger.exception("MIS 即時報價失敗 %s", ch)
    with _QUOTE_LOCK:
        _QUOTE_CACHE[key] = (time.time(), found)
    return found


def _apply_rt_to_row(row: dict, rt: Dict[str, Any], stock_id: str) -> dict:
    out = dict(row)
    out["date"] = taipei_today_str()
    out["stock_id"] = str(stock_id)
    if "stock_name" in out and rt.get("stock_name"):
        out["stock_name"] = rt["stock_name"]
    for k in ("open", "high", "low", "close", "volume"):
        if k in out:
            out[k] = rt[k]
    if "pct_change" in out:
        out["pct_change"] = rt["pct_change"]
    if "change_pct" in out:
        out["change_pct"] = rt["pct_change"]
    if "turnover_k" in out:
        out["turnover_k"] = round(rt["volume"] * rt["close"], 2)
    if "avg_price" in out:
        out["avg_price"] = rt["close"]
    out["is_live"] = True
    out["_live_time"] = rt.get("update_time") or ""
    return out


def append_live_bar(df: pd.DataFrame, stock_id: str, market: str = "") -> pd.DataFrame:
    """盤中用 MIS 價量合併今日 K：庫裡沒有就追加；已有就覆寫最後一根。"""
    if df is None or df.empty:
        return df
    if not is_live_merge_window():
        return df
    today = taipei_today_str()
    latest = _norm_date(df["date"].iloc[-1])
    mkt = market or (str(df["market"].iloc[-1]) if "market" in df.columns else "")
    rt = fetch_mis_quote(stock_id, mkt)
    if not rt or rt["close"] <= 0:
        return df
    if latest > today:
        return df
    if latest == today:
        out = df.copy()
        idx = len(out) - 1
        row = _apply_rt_to_row(out.iloc[idx].to_dict(), rt, stock_id)
        for col, val in row.items():
            if col not in out.columns:
                out[col] = None
            out.at[idx, col] = val
        return out
    row = {col: df.iloc[-1][col] if col in df.columns else None for col in df.columns}
    row = _apply_rt_to_row(row, rt, stock_id)
    return pd.concat([df, pd.DataFrame([row])], ignore_index=True)
