# -*- coding: utf-8 -*-
"""查股圖下「K線」：自家一頁。日K疊導航圖同一套高低箭頭，手指可對價。不是 TradingView。"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Optional

from stock_links import listed_kline_ok, quote_market

INTERVALS = ("D", "15", "60", "5D", "10D", "M", "Q")
_BAR_LIMIT = 1600
_PAGE = Path(__file__).with_name("kline_page.html").read_text(encoding="utf-8")

def normalize_interval(raw: str) -> str:
    s = str(raw or "D").strip().upper()
    aliases = {
        "DAY": "D",
        "1D": "D",
        "日": "D",
        "日K": "D",
        "15M": "15",
        "60M": "60",
        "5": "5D",
        "10": "10D",
        "MON": "M",
        "MONTH": "M",
        "QTR": "Q",
        "3M": "Q",
    }
    s = aliases.get(s, s)
    return s if s in INTERVALS else "D"


def plain_market_label(stock_id: str, db_path: Optional[str] = None) -> str:
    m = quote_market(stock_id, db_path)
    if m in ("TWO", "TPEX", "OTC", "ROCO"):
        return "上櫃"
    if m in ("EM", "ESB", "EMERGING"):
        return "興櫃"
    return "上市"


def _ymd(raw: str) -> str:
    d = str(raw or "").replace("-", "").replace("/", "")[:8]
    return d if len(d) == 8 and d.isdigit() else ""


def _merge_bars(chunk: List[Dict[str, Any]]) -> Dict[str, Any]:
    return {
        "t": chunk[-1]["t"],
        "o": chunk[0]["o"],
        "h": max(b["h"] for b in chunk),
        "l": min(b["l"] for b in chunk),
        "c": chunk[-1]["c"],
        "v": int(round(sum(float(b["v"]) for b in chunk))),
    }


def aggregate_n_day(bars: List[Dict[str, Any]], n: int) -> List[Dict[str, Any]]:
    """從最新往回每 n 根日K疊一根；最後一根是目前這段（可能不滿 n 日）。"""
    if n < 1 or not bars:
        return []
    chunks: List[List[Dict[str, Any]]] = []
    i = len(bars)
    while i > 0:
        start = max(0, i - n)
        chunks.append(bars[start:i])
        i = start
    chunks.reverse()
    return [_merge_bars(c) for c in chunks if c]


def aggregate_calendar(bars: List[Dict[str, Any]], kind: str) -> List[Dict[str, Any]]:
    groups: List[Dict[str, Any]] = []
    key = None
    chunk: List[Dict[str, Any]] = []

    def _key(t: str) -> str:
        d = _ymd(t)
        if not d:
            return ""
        if kind == "M":
            return d[:6]
        month = int(d[4:6])
        return f"{d[:4]}Q{(month - 1) // 3 + 1}"

    for b in bars:
        k = _key(str(b.get("t") or ""))
        if not k:
            continue
        if key is None:
            key = k
        if k != key:
            groups.append(_merge_bars(chunk))
            chunk = [b]
            key = k
        else:
            chunk.append(b)
    if chunk:
        groups.append(_merge_bars(chunk))
    return groups


def load_daily_bars(
    stock_id: str, db_path: Optional[str] = None, limit: int = _BAR_LIMIT
) -> List[Dict[str, Any]]:
    sid = str(stock_id or "").strip()
    if not sid or not db_path:
        return []
    try:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """
            SELECT date, open, high, low, close, volume
            FROM daily_quotes
            WHERE stock_id=?
            ORDER BY date DESC
            LIMIT ?;
            """,
            (sid, int(limit)),
        ).fetchall()
        conn.close()
    except Exception:
        return []
    out: List[Dict[str, Any]] = []
    for row in reversed(rows):
        d = _ymd(str(row["date"] or ""))
        try:
            o = float(row["open"])
            h = float(row["high"])
            l = float(row["low"])
            c = float(row["close"])
            v = float(row["volume"] or 0)
        except (TypeError, ValueError, KeyError):
            continue
        if not d or c <= 0:
            continue
        if h < max(o, c, l) or l > min(o, c, h):
            h = max(h, o, c)
            l = min(l, o, c)
        out.append({"t": d, "o": o, "h": h, "l": l, "c": c, "v": max(0, v)})
    return out


def _stock_name(stock_id: str, db_path: Optional[str] = None) -> str:
    sid = str(stock_id or "").strip()
    if not sid or not db_path:
        return ""
    try:
        conn = sqlite3.connect(db_path)
        row = conn.execute(
            "SELECT stock_name FROM daily_quotes WHERE stock_id=? ORDER BY date DESC LIMIT 1;",
            (sid,),
        ).fetchone()
        if not row:
            try:
                row = conn.execute(
                    "SELECT stock_name FROM stock_directory WHERE stock_id=? LIMIT 1;",
                    (sid,),
                ).fetchone()
            except Exception:
                row = None
        conn.close()
        return str((row[0] if row else "") or "").strip()
    except Exception:
        return ""


def packed_series(bars: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    return {
        "D": bars[-400:],
        "5D": aggregate_n_day(bars, 5),
        "10D": aggregate_n_day(bars, 10),
        "M": aggregate_calendar(bars, "M"),
        "Q": aggregate_calendar(bars, "Q"),
    }


def merge_live_daily(
    stock_id: str, bars: List[Dict[str, Any]], db_path: str
) -> List[Dict[str, Any]]:
    """盤中把今日即時列接在官方日K後面，不寫回資料庫。"""
    if not bars:
        return bars
    try:
        from config import taipei_today_str
        from live_quote import fetch_lookup_quote, is_live_merge_window

        if not is_live_merge_window():
            return bars
        today = str(taipei_today_str() or "").replace("-", "")[:8]
        last = str(bars[-1].get("t") or "")
        if not today or last >= today:
            return bars
        rt = fetch_lookup_quote(stock_id, "", db_path)
        if not rt or float(rt.get("close") or 0) <= 0:
            return bars
        out = list(bars)
        out.append(
            {
                "t": today,
                "o": float(rt.get("open") or rt["close"]),
                "h": float(rt.get("high") or rt["close"]),
                "l": float(rt.get("low") or rt["close"]),
                "c": float(rt["close"]),
                "v": float(rt.get("volume") or 0),
            }
        )
        return out
    except Exception:
        return bars


def parse_yahoo_chart_bars(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Yahoo chart JSON → 我們的 K 柱。量從股數換成張。"""
    from datetime import datetime, timezone
    from zoneinfo import ZoneInfo

    block = ((payload.get("chart") or {}).get("result") or [None])[0] or {}
    stamps = block.get("timestamp") or []
    q = ((block.get("indicators") or {}).get("quote") or [{}])[0]
    tz = ZoneInfo("Asia/Taipei")
    out: List[Dict[str, Any]] = []
    for ts, op, hi, lo, cl, vol in zip(
        stamps,
        q.get("open") or [],
        q.get("high") or [],
        q.get("low") or [],
        q.get("close") or [],
        q.get("volume") or [],
    ):
        if cl is None or op is None:
            continue
        try:
            dt = datetime.fromtimestamp(int(ts), tz=timezone.utc).astimezone(tz)
        except (TypeError, ValueError, OSError):
            continue
        c = float(cl)
        o = float(op)
        h = float(hi if hi is not None else max(o, c))
        l = float(lo if lo is not None else min(o, c))
        v = float(vol or 0) / 1000.0
        out.append(
            {
                "t": dt.strftime("%Y%m%d%H%M"),
                "o": o,
                "h": h,
                "l": l,
                "c": c,
                "v": max(0.0, v),
            }
        )
    return out


def fetch_yahoo_minutes(
    stock_id: str, interval: str, db_path: Optional[str] = None
) -> List[Dict[str, Any]]:
    """15 分／60 分走 Yahoo 分K，同一檔代號，不開整站。"""
    import requests

    from stock_links import yahoo_exchange

    sid = str(stock_id or "").strip()
    iv = "15m" if normalize_interval(interval) == "15" else "60m"
    rng = "5d" if iv == "15m" else "1mo"
    if not sid:
        return []
    yid = f"{sid}.{yahoo_exchange(sid, db_path)}"
    url = (
        f"https://query1.finance.yahoo.com/v8/finance/chart/{yid}"
        f"?interval={iv}&range={rng}"
    )
    try:
        resp = requests.get(
            url,
            timeout=8,
            headers={"User-Agent": "WayneBot/1.0"},
        )
        resp.raise_for_status()
        return parse_yahoo_chart_bars(resp.json() or {})
    except Exception:
        return []


def render_kline_html(
    stock_id: str,
    db_path: str = "",
    interval: str = "D",
    *,
    live: bool = False,
) -> str:
    sid = str(stock_id or "").strip()
    if not sid:
        return (
            "<!DOCTYPE html><html lang='zh-Hant'><head><meta charset='utf-8'>"
            "<title>查無代號</title></head><body>查無代號</body></html>"
        )
    start = normalize_interval(interval)
    name = _stock_name(sid, db_path or None)
    head = f"{sid} {name}".strip()
    if not listed_kline_ok(sid, db_path or None):
        return (
            "<!DOCTYPE html><html lang='zh-Hant'><head><meta charset='utf-8'>"
            f"<meta name='viewport' content='width=device-width,initial-scale=1'>"
            f"<title>{_esc(head or sid)}</title></head><body>"
            f"<p style='font-family:sans-serif;margin:2em;text-align:center'>"
            f"{_esc(head or sid)}　興櫃沒有這張即時K，請回 Telegram 看介紹圖與決策卡。"
            "</p></body></html>"
        )
    market = plain_market_label(sid, db_path or None)
    bars = load_daily_bars(sid, db_path or None)
    if live:
        bars = merge_live_daily(sid, bars, db_path or "")
    packed = packed_series(bars)
    nav = {}
    try:
        from wayne_navigator import nav_overlay_from_bars

        nav = nav_overlay_from_bars(packed.get("D") or []) or {}
    except Exception:
        nav = {}
    payload = {
        "sid": sid,
        "start": start,
        "packed": packed,
        "nav": nav,
    }
    stamp = ""
    try:
        from decision_card_signals import format_card_query_stamp

        last_t = ""
        daily = packed.get("D") or []
        if daily:
            last_t = str(daily[-1].get("t") or "")[:8]
        date_s, clock_s = format_card_query_stamp(is_live=bool(live), latest_date=last_t)
        stamp = f"{date_s} {clock_s}　"
    except Exception:
        stamp = ""
    sub = (
        f"{market}　{stamp}日K 可滑動對價，高低箭頭跟導航圖同一套。"
        "可改 15 分／60 分，或五日／十日／月線／季線。"
    )
    page = (
        _PAGE.replace("@@TITLE@@", _esc(f"{head}　K線"))
        .replace("@@HEAD@@", _esc(head))
        .replace("@@SUB@@", _esc(sub))
        .replace("@@DATA@@", json.dumps(payload, ensure_ascii=False, separators=(",", ":")))
    )
    return page


def _esc(text: str) -> str:
    return (
        str(text or "")
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )
