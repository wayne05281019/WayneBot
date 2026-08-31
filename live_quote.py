"""盤中即時：證交所 MIS。CaryBot 同類做法，不寫回 sqlite。"""
from __future__ import annotations

import logging
import threading
import time
from typing import Any, Dict, Optional, Tuple

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


def append_live_bar(df: pd.DataFrame, stock_id: str, market: str = "") -> pd.DataFrame:
    """若庫裡還沒有台灣今天這根 K，把 MIS 盤中／盤後未入庫價量接在最後。"""
    if df is None or df.empty:
        return df
    today = taipei_today_str()
    latest = str(df["date"].iloc[-1])
    if latest >= today:
        return df
    now = taipei_now().time()
    # 08:50～16:00 嘗試；週末也試（假日 API 會回昨收或空）
    if now.hour < 8:
        return df
    mkt = market or (str(df["market"].iloc[-1]) if "market" in df.columns else "")
    rt = fetch_mis_quote(stock_id, mkt)
    if not rt or rt["close"] <= 0:
        return df
    row = {col: df.iloc[-1][col] if col in df.columns else None for col in df.columns}
    row["date"] = today
    row["stock_id"] = str(stock_id)
    if "stock_name" in row and rt.get("stock_name"):
        row["stock_name"] = rt["stock_name"]
    for k in ("open", "high", "low", "close", "volume"):
        if k in row:
            row[k] = rt[k]
    if "pct_change" in row:
        row["pct_change"] = rt["pct_change"]
    if "change_pct" in row:
        row["change_pct"] = rt["pct_change"]
    if "turnover_k" in row:
        row["turnover_k"] = round(rt["volume"] * rt["close"], 2)
    if "avg_price" in row:
        row["avg_price"] = rt["close"]
    row["is_live"] = True
    row["_live_time"] = rt.get("update_time") or ""
    out = pd.concat([df, pd.DataFrame([row])], ignore_index=True)
    return out
