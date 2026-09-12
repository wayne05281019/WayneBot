# -*- coding: utf-8 -*-
"""期交所前 30 個交易日每筆成交 → 台指期近月 15／60 分（含夜盤）。

Yahoo／外站圖表沒有夜盤連續盤。這裡用官方 CSV zip，不是外站掛圖。
檔名 Daily_YYYY_MM_DD.zip：通常含前一晚盤後＋當日日盤。週末夜盤會掛在下一交易日檔。
已抓過的 zip 記在 taifex_tick_zips，不要用「檔名那天有沒有 15 分柱」當 skip
（週五夜盤的柱時間是週五／週六，檔名卻是下周一）。pytest 不打外網。
"""
from __future__ import annotations

import io
import logging
import os
import sqlite3
import time
import zipfile
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Sequence, Tuple
from zoneinfo import ZoneInfo

import requests

logger = logging.getLogger("WayneBot.TaifexTicks")

TAIPEI = ZoneInfo("Asia/Taipei")
_CSV_ZIP = (
    "https://www.taifex.com.tw/file/taifex/Dailydownload/"
    "DailydownloadCSV/Daily_{y}_{m}_{d}.zip"
)
_UA = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
    )
}
_TX = "TX"
CATCHUP_MIN_ZIPS = 22
CATCHUP_FETCH = 20
STEADY_FETCH = 3


def _ymd(raw: Any) -> str:
    t = str(raw or "").replace("-", "").replace("/", "").replace("_", "")[:8]
    return t if len(t) == 8 and t.isdigit() else ""


def zip_url(ymd: str) -> str:
    d = _ymd(ymd)
    return _CSV_ZIP.format(y=d[:4], m=d[4:6], d=d[6:8])


def parse_tx_ticks(text: str) -> List[Dict[str, Any]]:
    """只收臺股期貨近月單式（不要價差 202609/202610）。"""
    raw = text or ""
    if raw.startswith("\ufeff"):
        raw = raw[1:]
    out: List[Dict[str, Any]] = []
    for i, ln in enumerate(raw.splitlines()):
        if i == 0 and ("成交" in ln or "日期" in ln):
            continue
        parts = [p.strip() for p in ln.split(",")]
        if len(parts) < 6:
            continue
        if parts[1] != _TX:
            continue
        month = parts[2]
        if "/" in month:
            continue
        day = _ymd(parts[0])
        hms = "".join(ch for ch in parts[3] if ch.isdigit()).zfill(6)[:6]
        if len(day) != 8 or len(hms) != 6:
            continue
        try:
            px = float(parts[4])
            qty = float(parts[5] or 0)
        except (TypeError, ValueError):
            continue
        if px <= 0:
            continue
        out.append(
            {
                "date": day,
                "hms": hms,
                "month": month,
                "px": px,
                "qty": max(0.0, qty),
            }
        )
    if not out:
        return []
    out.sort(key=lambda r: (r["date"], r["hms"]))
    top = Counter(r["month"] for r in out).most_common(1)[0][0]
    return [r for r in out if r["month"] == top]


def _floor_hm(hms: str, step: int) -> str:
    hh = int(hms[:2])
    mm = int(hms[2:4])
    total = (hh * 60 + mm) // step * step
    h, m = divmod(total, 60)
    return f"{h:02d}{m:02d}"


def aggregate_minute_bars(
    ticks: Sequence[Dict[str, Any]], interval: int = 15
) -> List[Dict[str, Any]]:
    """逐筆 → 15／60 分 OHLC。量用成交檔的 B+S 口數。"""
    step = 15 if int(interval) == 15 else 60
    buckets: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for t in ticks:
        hm = _floor_hm(str(t.get("hms") or "000000"), step)
        key = str(t.get("date") or "") + hm
        if len(key) != 12:
            continue
        buckets[key].append(t)
    bars: List[Dict[str, Any]] = []
    for ts in sorted(buckets):
        chunk = sorted(
            buckets[ts], key=lambda x: (str(x.get("date") or ""), str(x.get("hms") or ""))
        )
        px = [float(x["px"]) for x in chunk]
        vol = sum(float(x.get("qty") or 0) for x in chunk)
        bars.append(
            {
                "t": ts,
                "o": px[0],
                "h": max(px),
                "l": min(px),
                "c": px[-1],
                "v": vol,
            }
        )
    return bars


def decode_tick_bytes(blob: bytes) -> str:
    data = blob or b""
    for enc in ("utf-8-sig", "utf-8", "big5", "cp950"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    return data.decode("latin1", errors="replace")


def unzip_csv(blob: bytes) -> str:
    if blob[:2] != b"PK":
        return decode_tick_bytes(blob)
    with zipfile.ZipFile(io.BytesIO(blob)) as zf:
        names = zf.namelist()
        if not names:
            return ""
        return decode_tick_bytes(zf.read(names[0]))


def looks_like_tick_csv(text: str) -> bool:
    head = (text or "")[:400]
    return "商品代號" in head or "成交日期" in head


def bars_from_zip_bytes(blob: bytes) -> Optional[List[Dict[str, Any]]]:
    """None＝不是成交檔。空 list＝檔是真的但沒 TX。"""
    if not blob or len(blob) < 64:
        return None
    try:
        text = unzip_csv(blob)
    except Exception:
        return None
    if not looks_like_tick_csv(text):
        return None
    return aggregate_minute_bars(parse_tx_ticks(text), 15)


def _candidate_zip_dates(*, days: int = 45) -> List[str]:
    """含未來兩三天：週五夜盤 zip 常掛下一個交易日檔名。"""
    now = datetime.now(TAIPEI)
    out: List[str] = []
    for i in range(-3, max(1, int(days))):
        out.append((now + timedelta(days=-i)).strftime("%Y%m%d"))
    return out


def ensure_tick_zips_table(db_path: str) -> None:
    path = str(db_path or "").strip()
    if not path:
        return
    conn = sqlite3.connect(path)
    try:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS taifex_tick_zips (
                ymd TEXT PRIMARY KEY,
                n INTEGER,
                updated_at TEXT
            )
            """
        )
        conn.commit()
    finally:
        conn.close()


def _zip_done(db_path: str, ymd: str) -> bool:
    day = _ymd(ymd)
    if not day or not db_path:
        return False
    ensure_tick_zips_table(db_path)
    conn = sqlite3.connect(db_path)
    try:
        row = conn.execute(
            "SELECT 1 FROM taifex_tick_zips WHERE ymd=?", (day,)
        ).fetchone()
        return bool(row)
    except sqlite3.Error:
        return False
    finally:
        conn.close()


def _mark_zip(db_path: str, ymd: str, n: int) -> None:
    day = _ymd(ymd)
    if not day or not db_path:
        return
    ensure_tick_zips_table(db_path)
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            """
            INSERT INTO taifex_tick_zips(ymd, n, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(ymd) DO UPDATE SET n=excluded.n, updated_at=excluded.updated_at
            """,
            (day, int(n), datetime.now(TAIPEI).strftime("%Y-%m-%d %H:%M:%S")),
        )
        conn.commit()
    finally:
        conn.close()


def fetch_daily_zip(ymd: str, timeout: int = 40) -> Tuple[int, bytes]:
    d = _ymd(ymd)
    if not d:
        return 0, b""
    url = zip_url(d)
    try:
        resp = requests.get(url, headers=_UA, timeout=timeout)
        return int(getattr(resp, "status_code", 0) or 0), resp.content or b""
    except Exception:
        logger.debug("期交所成交 zip 讀不到 %s", d, exc_info=True)
        return 0, b""


def download_tx_minute_bars(ymd: str, timeout: int = 40) -> List[Dict[str, Any]]:
    """抓一天 zip → 近月 15 分柱。失敗回空。"""
    status, blob = fetch_daily_zip(ymd, timeout=timeout)
    if status != 200:
        return []
    bars = bars_from_zip_bytes(blob)
    return bars or []


def _rollup_60(bars15: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    buckets: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for b in bars15:
        ts = str(b.get("t") or "")
        if len(ts) < 12:
            continue
        key = ts[:8] + _floor_hm(ts[8:12] + "00", 60)
        buckets[key].append(b)
    out: List[Dict[str, Any]] = []
    for ts in sorted(buckets):
        chunk = buckets[ts]
        out.append(
            {
                "t": ts,
                "o": float(chunk[0]["o"]),
                "h": max(float(x["h"]) for x in chunk),
                "l": min(float(x["l"]) for x in chunk),
                "c": float(chunk[-1]["c"]),
                "v": sum(float(x.get("v") or 0) for x in chunk),
            }
        )
    return out


def zip_count(db_path: str) -> int:
    path = str(db_path or "").strip()
    if not path:
        return 0
    ensure_tick_zips_table(path)
    conn = sqlite3.connect(path)
    try:
        row = conn.execute("SELECT COUNT(*) FROM taifex_tick_zips").fetchone()
        return int((row or [0])[0] or 0)
    except sqlite3.Error:
        return 0
    finally:
        conn.close()


def fetch_budget(db_path: str, *, limit_zips: Optional[int] = None) -> int:
    """沒補滿 30 日窗就一次多抓；補滿後每輪 3 檔。"""
    if limit_zips is not None:
        return max(1, int(limit_zips))
    return CATCHUP_FETCH if zip_count(db_path) < CATCHUP_MIN_ZIPS else STEADY_FETCH


def tx_health_stats(db_path: str) -> Dict[str, Any]:
    """給 /health：根數、zip 數、時間窗、最新一晚高低。表沒有就全 0。"""
    out: Dict[str, Any] = {
        "tx_15_n": 0,
        "tx_zip_n": 0,
        "tx_15_from": "",
        "tx_15_to": "",
        "tx_night_n": 0,
        "tx_night_high": "",
        "tx_night_low": "",
        "tx_night_date": "",
    }
    path = str(db_path or "").strip()
    if not path:
        return out
    conn = sqlite3.connect(path, timeout=2.0)
    try:
        has_bars = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='minute_bars'"
        ).fetchone()
        has_zips = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='taifex_tick_zips'"
        ).fetchone()
        if has_zips:
            out["tx_zip_n"] = int(
                (conn.execute("SELECT COUNT(*) FROM taifex_tick_zips").fetchone() or [0])[0]
                or 0
            )
        if not has_bars:
            return out
        row = conn.execute(
            """
            SELECT COUNT(*), MIN(ts), MAX(ts) FROM minute_bars
            WHERE stock_id='TX' AND interval='15'
            """
        ).fetchone()
        n, lo, hi = (row or (0, "", ""))[:3]
        out["tx_15_n"] = int(n or 0)
        out["tx_15_from"] = str(lo or "")
        out["tx_15_to"] = str(hi or "")
        last = str(hi or "")
        if len(last) >= 12:
            from datetime import datetime, timedelta

            d, hm = last[:8], int(last[8:12])
            sess = d
            if hm <= 500 or 845 <= hm <= 1345:
                sess = (datetime.strptime(d, "%Y%m%d") - timedelta(days=1)).strftime(
                    "%Y%m%d"
                )
            nxt = (datetime.strptime(sess, "%Y%m%d") + timedelta(days=1)).strftime(
                "%Y%m%d"
            )
            night = conn.execute(
                """
                SELECT ts, h, l FROM minute_bars
                WHERE stock_id='TX' AND interval='15'
                  AND (
                    (ts >= ? AND ts <= ?)
                    OR (ts >= ? AND ts <= ?)
                  )
                ORDER BY ts
                """,
                (sess + "1500", sess + "2345", nxt + "0000", nxt + "0500"),
            ).fetchall()
            if len(night) >= 8:
                out["tx_night_n"] = len(night)
                out["tx_night_high"] = str(int(round(max(float(r[1]) for r in night))))
                out["tx_night_low"] = str(int(round(min(float(r[2]) for r in night))))
                out["tx_night_date"] = f"{sess[:4]}-{sess[4:6]}-{sess[6:8]}"
    except Exception:
        return out
    finally:
        conn.close()
    return out


def refresh_tx_minutes(
    db_path: str,
    *,
    limit_zips: Optional[int] = None,
    days: int = 45,
) -> Dict[str, Any]:
    """缺哪檔 zip 抓哪檔。沒補滿一次多抓。已記在 taifex_tick_zips 就跳過。pytest 不打外網。"""
    stats: Dict[str, Any] = {"ok": False, "saved": 0, "fetched": 0, "days": []}
    path = str(db_path or "").strip()
    if not path:
        return stats
    if os.getenv("PYTEST_CURRENT_TEST") and os.getenv("WAYNE_ALLOW_MINUTES") != "1":
        return {**stats, "skipped": "pytest"}
    from kline_hop import save_minute_bars

    ensure_tick_zips_table(path)
    fetched = 0
    attempts = 0
    saved = 0
    got: List[str] = []
    max_fetch = fetch_budget(path, limit_zips=limit_zips)
    max_attempts = max(8, max_fetch * 5)
    for ymd in _candidate_zip_dates(days=days):
        if fetched >= max_fetch or attempts >= max_attempts:
            break
        if _zip_done(path, ymd):
            continue
        attempts += 1
        status, blob = fetch_daily_zip(ymd)
        if status != 200:
            continue
        bars15 = bars_from_zip_bytes(blob)
        if bars15 is None:
            continue
        _mark_zip(path, ymd, len(bars15))
        fetched += 1
        if bars15:
            bars60 = _rollup_60(bars15)
            saved += save_minute_bars("TX", "15", bars15, path, source="taifex")
            saved += save_minute_bars("TX", "60", bars60, path, source="taifex")
        got.append(f"{ymd}:{len(bars15)}")
        time.sleep(0.4)
    stats.update(
        {
            "ok": True,
            "saved": saved,
            "fetched": fetched,
            "attempts": attempts,
            "days": got,
            "budget": max_fetch,
            "zips": zip_count(path),
        }
    )
    return stats
