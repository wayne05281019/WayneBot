# -*- coding: utf-8 -*-
"""查股圖下「K線」：自家一頁。日K疊導航圖同一套高低箭頭，手指可對價。不是 TradingView。"""
from __future__ import annotations

import json
import os
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
        rows = []
    out: List[Dict[str, Any]] = []
    for row in reversed(rows or []):
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
    if not out:
        return _load_emerging_daily_bars(sid, db_path, limit)
    return out


def _load_emerging_daily_bars(
    stock_id: str, db_path: str, limit: int
) -> List[Dict[str, Any]]:
    """興櫃官方日均價：前日均價＝open、日最高／最低、日均價＝close。"""
    try:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """
            SELECT date, open, high, low, close, volume
            FROM emerging_quotes
            WHERE stock_id=?
            ORDER BY date DESC
            LIMIT ?;
            """,
            (stock_id, int(limit)),
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
                    "SELECT stock_name FROM emerging_quotes WHERE stock_id=? ORDER BY date DESC LIMIT 1;",
                    (sid,),
                ).fetchone()
            except Exception:
                row = None
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


def ensure_minute_bars_table(db_path: Optional[str]) -> None:
    if not db_path:
        return
    conn = sqlite3.connect(db_path)
    try:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS minute_bars (
                stock_id TEXT NOT NULL,
                interval TEXT NOT NULL,
                ts TEXT NOT NULL,
                o REAL NOT NULL,
                h REAL NOT NULL,
                l REAL NOT NULL,
                c REAL NOT NULL,
                v REAL NOT NULL DEFAULT 0,
                source TEXT NOT NULL DEFAULT 'yahoo',
                PRIMARY KEY (stock_id, interval, ts)
            );
            CREATE INDEX IF NOT EXISTS idx_minute_bars_sid_iv ON minute_bars(stock_id, interval, ts);
            """
        )
        conn.commit()
    finally:
        conn.close()


def merge_minute_bars(
    stored: List[Dict[str, Any]], remote: List[Dict[str, Any]]
) -> List[Dict[str, Any]]:
    """同一根遠端蓋過庫內；回傳時間由舊到新。"""
    by_ts: Dict[str, Dict[str, Any]] = {}
    for chunk in (stored, remote):
        for raw in chunk or []:
            ts = str((raw or {}).get("t") or "")
            if not ts:
                continue
            by_ts[ts] = raw
    return [by_ts[k] for k in sorted(by_ts)]


def load_minute_bars(
    stock_id: str, interval: str, db_path: Optional[str] = None
) -> List[Dict[str, Any]]:
    sid = str(stock_id or "").strip()
    iv = "15" if normalize_interval(interval) == "15" else "60"
    if not sid or not db_path:
        return []
    ensure_minute_bars_table(db_path)
    try:
        conn = sqlite3.connect(db_path)
        rows = conn.execute(
            """
            SELECT ts, o, h, l, c, v FROM minute_bars
            WHERE stock_id=? AND interval=?
            ORDER BY ts
            """,
            (sid, iv),
        ).fetchall()
        conn.close()
    except Exception:
        return []
    out: List[Dict[str, Any]] = []
    for ts, o, h, l, c, v in rows:
        try:
            out.append(
                {
                    "t": str(ts),
                    "o": float(o),
                    "h": float(h),
                    "l": float(l),
                    "c": float(c),
                    "v": float(v or 0),
                }
            )
        except (TypeError, ValueError):
            continue
    return out


def save_minute_bars(
    stock_id: str,
    interval: str,
    bars: List[Dict[str, Any]],
    db_path: Optional[str] = None,
    *,
    source: str = "yahoo",
) -> int:
    sid = str(stock_id or "").strip()
    iv = "15" if normalize_interval(interval) == "15" else "60"
    if not sid or not db_path or not bars:
        return 0
    ensure_minute_bars_table(db_path)
    written = 0
    conn = sqlite3.connect(db_path)
    try:
        for b in bars:
            ts = str((b or {}).get("t") or "")
            try:
                o = float(b["o"])
                h = float(b["h"])
                l = float(b["l"])
                c = float(b["c"])
                v = float(b.get("v") or 0)
            except (TypeError, ValueError, KeyError):
                continue
            if not ts or c <= 0:
                continue
            conn.execute(
                """
                INSERT INTO minute_bars(stock_id, interval, ts, o, h, l, c, v, source)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(stock_id, interval, ts) DO UPDATE SET
                    o=excluded.o, h=excluded.h, l=excluded.l,
                    c=excluded.c, v=excluded.v, source=excluded.source
                """,
                (sid, iv, ts, o, h, l, c, v, source),
            )
            written += 1
        conn.commit()
    finally:
        conn.close()
    return written


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


def _yahoo_minute_ranges(yahoo_iv: str) -> tuple:
    if yahoo_iv == "15m":
        return ("60d", "3mo", "1mo", "5d")
    return ("2y", "1y", "6mo", "1mo")


def yahoo_chart_symbol(stock_id: str, db_path: Optional[str] = None) -> str:
    """Yahoo chart 代號。加權／費半是 ^ 指數，不是 .TW。"""
    sid = str(stock_id or "").strip()
    key = sid.upper()
    if key in {"TWII", "TWA00", "^TWII", "TAIEX"}:
        return "^TWII"
    if key in {"SOX", "^SOX"}:
        return "^SOX"
    if sid.startswith("^"):
        return sid
    from stock_links import yahoo_exchange

    return f"{sid}.{yahoo_exchange(sid, db_path)}"


def _download_yahoo_minutes(
    stock_id: str, interval: str, db_path: Optional[str] = None
) -> List[Dict[str, Any]]:
    """Yahoo 分 K：長 range 失敗再縮。不寫庫。"""
    import requests

    sid = str(stock_id or "").strip()
    if not sid:
        return []
    yahoo_iv = "15m" if normalize_interval(interval) == "15" else "60m"
    yid = yahoo_chart_symbol(sid, db_path)
    last: List[Dict[str, Any]] = []
    ua = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
        )
    }
    for rng in _yahoo_minute_ranges(yahoo_iv):
        url = (
            f"https://query1.finance.yahoo.com/v8/finance/chart/{yid}"
            f"?interval={yahoo_iv}&range={rng}"
        )
        try:
            resp = requests.get(url, timeout=8, headers=ua)
            if resp.status_code != 200:
                continue
            bars = parse_yahoo_chart_bars(resp.json() or {})
            if bars:
                return bars
            last = bars
        except Exception:
            continue
    return last


def fetch_yahoo_minutes(
    stock_id: str, interval: str, db_path: Optional[str] = None
) -> List[Dict[str, Any]]:
    """15 分／60 分：Yahoo 新柱併進庫，回傳庫內舊柱 ∪ 遠端。不開整站回補。"""
    sid = str(stock_id or "").strip()
    if not sid:
        return []
    stored = load_minute_bars(sid, interval, db_path) if db_path else []
    remote = _download_yahoo_minutes(sid, interval, db_path)
    if db_path and remote:
        save_minute_bars(sid, interval, remote, db_path)
    return merge_minute_bars(stored, remote)


BIAOKE_MINUTE_SIDS = ("TWII", "2330", "SOX")
BIAOKE_MINUTE_IVS = ("15", "60")
_LAST_BIAOKE_MINUTES = 0.0


def _minute_px(val: Any) -> str:
    try:
        n = float(val)
    except (TypeError, ValueError):
        return ""
    if abs(n - round(n)) < 0.05:
        return str(int(round(n)))
    return f"{n:.2f}".rstrip("0").rstrip(".")


def minute_day_cover(
    stock_id: str,
    interval: str,
    ymd: str,
    db_path: Optional[str] = None,
) -> Dict[str, Any]:
    """某日日盤 09:00～13:45 的 15／60 分覆蓋。沒庫或根數不夠回空。"""
    day = _ymd(ymd)
    if not day or not db_path:
        return {}
    bars = load_minute_bars(stock_id, interval, db_path)
    cash: List[Dict[str, Any]] = []
    for b in bars:
        ts = str(b.get("t") or "")
        if len(ts) < 12 or ts[:8] != day:
            continue
        try:
            hm = int(ts[8:12])
        except ValueError:
            continue
        if 900 <= hm <= 1345:
            cash.append(b)
    if len(cash) < 8:
        return {}
    return {
        "n": len(cash),
        "high": max(float(b["h"]) for b in cash),
        "low": min(float(b["l"]) for b in cash),
        "from": str(cash[0].get("t") or ""),
        "to": str(cash[-1].get("t") or ""),
        "session": "day",
        "stock_id": str(stock_id),
        "interval": "15" if normalize_interval(interval) == "15" else "60",
    }


def minute_night_cover(
    ymd: str,
    db_path: Optional[str] = None,
    *,
    stock_id: str = "TX",
    interval: str = "15",
) -> Dict[str, Any]:
    """某日夜盤：當日 15:00～23:45＋次日 00:00～05:00。來源期交所成交，不是 Yahoo。"""
    from datetime import datetime, timedelta

    day = _ymd(ymd)
    if not day or not db_path:
        return {}
    try:
        nxt = (datetime.strptime(day, "%Y%m%d") + timedelta(days=1)).strftime("%Y%m%d")
    except ValueError:
        return {}
    bars = load_minute_bars(stock_id, interval, db_path)
    night: List[Dict[str, Any]] = []
    for b in bars:
        ts = str(b.get("t") or "")
        if len(ts) < 12:
            continue
        d, hm_s = ts[:8], ts[8:12]
        try:
            hm = int(hm_s)
        except ValueError:
            continue
        if d == day and 1500 <= hm <= 2345:
            night.append(b)
        elif d == nxt and 0 <= hm <= 500:
            night.append(b)
    if len(night) < 8:
        return {}
    return {
        "n": len(night),
        "high": max(float(b["h"]) for b in night),
        "low": min(float(b["l"]) for b in night),
        "from": str(night[0].get("t") or ""),
        "to": str(night[-1].get("t") or ""),
        "session": "night",
        "stock_id": str(stock_id),
        "interval": "15" if normalize_interval(interval) == "15" else "60",
        "source": "taifex",
    }


def minute_cover_note(
    cover: Optional[Dict[str, Any]],
    *,
    night: bool,
) -> str:
    """給建檔／判斷卡。有柱只報高低，不准數他圖上的段。"""
    session = str((cover or {}).get("session") or "")
    n = int((cover or {}).get("n") or 0)
    have = bool(cover) and n >= 8
    if night:
        if have and session == "night":
            h = _minute_px((cover or {}).get("high"))
            l = _minute_px((cover or {}).get("low"))
            return (
                f"夜盤 15 分官方（期交所成交）{n} 根，高 {h} 低 {l}；"
                f"不發明他圖上哪幾段。"
            )
        return "夜盤 15 分官方還沒進這段，不數這則的段。"
    if have and session != "night":
        h = _minute_px((cover or {}).get("high"))
        l = _minute_px((cover or {}).get("low"))
        return f"日盤 15 分庫有 {n} 根，高 {h} 低 {l}；不發明他圖上哪幾段。"
    return "庫沒 15 分，不數這則的段。"


def refresh_biaoke_minutes(
    db_path: str,
    *,
    min_age_s: int = 1800,
) -> Dict[str, Any]:
    """飆大對質用：Yahoo 日盤 15＋60 分，外加期交所台指期夜盤成交。pytest 不打外網。

    期交所 zip 還沒補滿 30 日窗時，不受 30 分冷卻擋住。
    """
    global _LAST_BIAOKE_MINUTES
    import time

    stats: Dict[str, Any] = {"ok": False, "saved": 0, "sids": []}
    path = str(db_path or "").strip()
    if not path:
        return stats
    if os.getenv("PYTEST_CURRENT_TEST") and os.getenv("WAYNE_ALLOW_MINUTES") != "1":
        return {**stats, "skipped": "pytest"}
    from taifex_ticks import CATCHUP_MIN_ZIPS, refresh_tx_minutes, zip_count

    catching = zip_count(path) < CATCHUP_MIN_ZIPS
    now = time.monotonic()
    yahoo_fresh = bool(
        _LAST_BIAOKE_MINUTES
        and now - _LAST_BIAOKE_MINUTES < max(60, int(min_age_s))
    )
    if yahoo_fresh and not catching:
        return {**stats, "ok": True, "skipped": "fresh"}
    ensure_minute_bars_table(path)
    saved = 0
    got: List[str] = []
    if not yahoo_fresh:
        for sid in BIAOKE_MINUTE_SIDS:
            for iv in BIAOKE_MINUTE_IVS:
                remote = _download_yahoo_minutes(sid, iv, path)
                if not remote:
                    continue
                saved += save_minute_bars(sid, iv, remote, path, source="yahoo")
                got.append(f"{sid}:{iv}:{len(remote)}")
        saved += _refresh_qincheng_60(path)
    tx: Dict[str, Any] = {}
    try:
        tx = refresh_tx_minutes(path)
        saved += int(tx.get("saved") or 0)
        if tx.get("days"):
            got.append("TX:" + ",".join(str(x) for x in tx.get("days") or []))
    except Exception:
        tx = {"ok": False}
    if int(tx.get("saved") or 0) > 0:
        try:
            from biaoke_claims import refresh_wave_minute_hits

            stats["wave_hits"] = refresh_wave_minute_hits(path)
        except Exception:
            stats["wave_hits"] = 0
        try:
            from biaoke_why import refresh_minute_why_cards

            stats["why_cards"] = refresh_minute_why_cards(path)
        except Exception:
            stats["why_cards"] = 0
    if not yahoo_fresh:
        _LAST_BIAOKE_MINUTES = time.monotonic()
    stats.update({"ok": True, "saved": saved, "sids": got, "tx": tx})
    return stats


def _refresh_qincheng_60(db_path: str) -> int:
    """勤誠 2025-06-19 他看 60 分。Yahoo 長 range 有那天就進庫；沒有不准編。"""
    have = load_minute_bars("8210", "60", db_path)
    if any(str(b.get("t") or "").startswith("20250619") for b in have):
        return 0
    if have:
        return 0
    remote = _download_yahoo_minutes("8210", "60", db_path)
    if not remote:
        return 0
    return save_minute_bars("8210", "60", remote, db_path, source="yahoo")


def render_kline_html(
    stock_id: str,
    db_path: str = "",
    interval: str = "D",
    *,
    live: bool = False,
    span: int | None = None,
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
            f"{_esc(head or sid)}　沒有這張 K 線頁。"
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
    try:
        span_n = int(span) if span is not None else 0
    except (TypeError, ValueError):
        span_n = 0
    if span_n < 0:
        span_n = 0
    if span_n > 400:
        span_n = 400
    payload = {
        "sid": sid,
        "start": start,
        "packed": packed,
        "nav": nav,
        "span": span_n,
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
    if market == "興櫃":
        extra = (
            "官方日均價約 180 根，輕點對價、左右拖、雙指縮放；紫／綠箭頭跟高低卡同一套。"
            if span_n >= 120
            else "官方日均價，輕點對價、左右拖移動；高低箭頭跟導航圖同一套。"
        )
    else:
        extra = (
            "導航約 180 根日K，輕點對價、左右拖、雙指縮放；紫／綠箭頭跟高低卡同一套。"
            if span_n >= 120
            else "日K 輕點對價、左右拖移動；高低箭頭跟導航圖同一套。"
        ) + "可改 15 分／60 分，或五日／十日／月線／季線。"
    if market == "興櫃":
        extra += "五日／十日／月線／季線可改；15 分／60 分有資料才有。"
    sub = f"{market}　{stamp}" + extra
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
