#!/usr/bin/env python3
"""Preview-only v5：今日開→收墨線臉（查股第 5 張候選）。

- 頭欄＝結構／大量區同款（nameplate＋spot）。
- 八格報價格畫在 overlay 高 z（頭欄名牌下／圖框上空白），國字＋數字加大；
  不准淡成幽靈字（v4 畫在 fig 被頭欄白底蓋住）。
- 底部三條：季均量 vs 當日量、日低–日高、52週低–高（端點＋最新必現）。
- 主圖右側：日高／昨收／日低必現（智慧去撞）。
- 興櫃路徑＝Yahoo ``priceByTimes``（.TWO）至 15:00；面值仍官方日表。
- 不准接話筒／不准合 main；臉不寫出處。
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Sequence, Tuple
from urllib.parse import quote as url_quote
from zoneinfo import ZoneInfo

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

TZ = ZoneInfo("Asia/Taipei")
ASOF_YMD = "20261029"

PREVIEW_SYMBOLS: Tuple[Tuple[str, str, str], ...] = (
    ("3595", "山太士", "EM"),
    ("7853", "政美應用", "EM"),
    ("2383", "台光電", "TW"),
    ("6274", "台燿", "TWO"),
    ("1303", "南亞", "TW"),
)

_SLUG = {
    "3595": "shantashi",
    "7853": "zhengmei",
    "2383": "taiguangdian",
    "6274": "taiyao",
    "1303": "nanya",
}


@dataclass
class OfficialDay:
    stock_id: str
    open: float
    high: float
    low: float
    close: float
    prev_close: float
    volume_lots: float
    turnover_k: Optional[float]  # 千元；無則 None
    avg_price: Optional[float]
    pct_change: float
    change: float
    amplitude_pct: Optional[float]
    q_avg_vol_lots: Optional[float]
    w52_high: Optional[float]
    w52_low: Optional[float]
    source: str
    close_label: str  # 收盤 / 興櫃收


@dataclass
class PathSeries:
    stock_id: str
    name: str
    market: str
    times: List[datetime]
    closes: List[float]
    volumes_lots: List[float]
    opens: List[float]
    highs: List[float]
    lows: List[float]
    path_source: str
    path_end: datetime
    gap_after: Optional[datetime]
    official: OfficialDay
    notices: List[str] = field(default_factory=list)
    fetched_at: datetime = field(default_factory=lambda: datetime.now(TZ))


def _ua() -> Dict[str, str]:
    return {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
        )
    }


def _yahoo_ids(stock_id: str, market: str, db_path: Optional[str]) -> List[str]:
    from kline_hop import yahoo_chart_symbol

    primary = yahoo_chart_symbol(stock_id, db_path)
    alts: List[str] = [primary]
    for sfx in ("TW", "TWO"):
        cand = f"{stock_id}.{sfx}"
        if cand not in alts:
            alts.append(cand)
    if str(market).upper() == "EM":
        alts = sorted(alts, key=lambda s: (0 if s.endswith(".TWO") else 1, s))
    return alts


def fetch_yahoo_1m_path(
    stock_id: str,
    market: str,
    *,
    db_path: Optional[str] = None,
    ymd: str = ASOF_YMD,
) -> Optional[Dict[str, Any]]:
    import requests
    from kline_hop import parse_yahoo_chart_bars

    last_err = ""
    for yid in _yahoo_ids(stock_id, market, db_path):
        url = (
            f"https://query1.finance.yahoo.com/v8/finance/chart/{url_quote(yid, safe='')}"
            f"?interval=1m&range=1d"
        )
        try:
            resp = requests.get(url, timeout=12, headers=_ua())
            if resp.status_code != 200:
                last_err = f"HTTP {resp.status_code}"
                continue
            bars = parse_yahoo_chart_bars(resp.json() or {})
            times: List[datetime] = []
            closes: List[float] = []
            vols: List[float] = []
            opens: List[float] = []
            highs: List[float] = []
            lows: List[float] = []
            sess_end = 1500 if str(market).upper() == "EM" else 1330
            for b in bars:
                t_raw = str(b.get("t") or "")
                if len(t_raw) < 12 or not t_raw.startswith(ymd):
                    continue
                dt = datetime.strptime(t_raw, "%Y%m%d%H%M").replace(tzinfo=TZ)
                hm = dt.hour * 100 + dt.minute
                if hm < 900 or hm > sess_end:
                    continue
                c = float(b["c"])
                times.append(dt)
                closes.append(c)
                vols.append(float(b.get("v") or 0.0))
                opens.append(float(b.get("o") or c))
                highs.append(float(b.get("h") or c))
                lows.append(float(b.get("l") or c))
            if len(closes) < 2:
                last_err = f"{yid} today points<{2}"
                continue
            return {
                "yahoo_symbol": yid,
                "times": times,
                "closes": closes,
                "volumes_lots": vols,
                "opens": opens,
                "highs": highs,
                "lows": lows,
                "source": f"yahoo:chart:1m:{yid}",
            }
        except Exception as exc:  # noqa: BLE001
            last_err = str(exc)
            continue
    sys.stderr.write(f"[path-skip] {stock_id}: {last_err}\n")
    return None


def _parse_yahoo_utc(ts: str) -> Optional[datetime]:
    raw = str(ts or "").strip()
    if not raw:
        return None
    try:
        if raw.endswith("Z"):
            dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        else:
            dt = datetime.fromisoformat(raw)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(TZ)
    except Exception:  # noqa: BLE001
        return None


def _aggregate_prints_to_1m(
    prints: List[Tuple[datetime, float, float]],
    *,
    ymd: str,
    sess_end_hm: int = 1500,
) -> Dict[str, List[Any]]:
    """5 秒彙整價 → 1 分 OHLC；volumeK（千股＝張）加總。"""
    buckets: Dict[datetime, List[Tuple[float, float]]] = {}
    for dt, price, vol_k in prints:
        if not dt.strftime("%Y%m%d").startswith(ymd):
            continue
        hm = dt.hour * 100 + dt.minute
        if hm < 900 or hm > sess_end_hm:
            continue
        key = dt.replace(second=0, microsecond=0)
        buckets.setdefault(key, []).append((price, vol_k))
    times: List[datetime] = []
    opens: List[float] = []
    highs: List[float] = []
    lows: List[float] = []
    closes: List[float] = []
    vols: List[float] = []
    for key in sorted(buckets.keys()):
        rows = buckets[key]
        prices = [p for p, _ in rows]
        times.append(key)
        opens.append(prices[0])
        highs.append(max(prices))
        lows.append(min(prices))
        closes.append(prices[-1])
        vols.append(sum(v for _, v in rows))
    return {
        "times": times,
        "opens": opens,
        "highs": highs,
        "lows": lows,
        "closes": closes,
        "volumes_lots": vols,
    }


def fetch_yahoo_price_by_times(
    stock_id: str,
    *,
    ymd: str = ASOF_YMD,
    yahoo_suffix: str = "TWO",
    max_pages: int = 120,
) -> Optional[Dict[str, Any]]:
    """興櫃分時：Yahoo TW ``StockServices.priceByTimes``（約 5 秒彙整，可到 15:00）。

    面值仍走官方日表；此路徑只負責折線形狀。非官方逐筆。
    """
    import requests

    yid = f"{stock_id}.{yahoo_suffix}"
    headers = {
        **_ua(),
        "Referer": f"https://tw.stock.yahoo.com/quote/{yid}/time-sales",
        "Accept": "application/json,text/plain,*/*",
    }
    prints: List[Tuple[datetime, float, float]] = []
    offset: Optional[str] = "0"
    pages = 0
    last_err = ""
    seen_offsets: set = set()
    while offset is not None and pages < max_pages:
        if offset in seen_offsets:
            break
        seen_offsets.add(offset)
        url = (
            "https://tw.stock.yahoo.com/_td-stock/api/resource/"
            f"StockServices.priceByTimes;symbol={url_quote(yid, safe='')};offset={offset}"
        )
        try:
            resp = requests.get(url, timeout=20, headers=headers)
            if resp.status_code != 200:
                last_err = f"HTTP {resp.status_code}"
                break
            payload = resp.json() or {}
        except Exception as exc:  # noqa: BLE001
            last_err = str(exc)
            break
        rows = payload.get("priceByTimes") or []
        if not isinstance(rows, list):
            last_err = "bad priceByTimes shape"
            break
        for row in rows:
            if not isinstance(row, dict):
                continue
            dt = _parse_yahoo_utc(str(row.get("time") or ""))
            if dt is None:
                continue
            try:
                price = float(str(row.get("price") or "").replace(",", ""))
            except Exception:  # noqa: BLE001
                continue
            try:
                vol_k = float(str(row.get("volumeK") or "0").replace(",", "") or "0")
            except Exception:  # noqa: BLE001
                vol_k = 0.0
            prints.append((dt, price, vol_k))
        pages += 1
        pag = payload.get("pagination") or {}
        nxt = pag.get("nextOffset")
        if nxt is None or nxt == "" or str(nxt) == str(offset):
            offset = None
        else:
            offset = str(nxt)
            time.sleep(0.05)
    if len(prints) < 2:
        sys.stderr.write(f"[priceByTimes-skip] {stock_id}: {last_err or 'points<2'}\n")
        return None
    # API 由新到舊；去重後升序
    uniq: Dict[datetime, Tuple[float, float]] = {}
    for dt, price, vol_k in prints:
        uniq[dt] = (price, vol_k)
    ordered = [(dt, uniq[dt][0], uniq[dt][1]) for dt in sorted(uniq.keys())]
    agg = _aggregate_prints_to_1m(ordered, ymd=ymd, sess_end_hm=1500)
    if len(agg["closes"]) < 2:
        sys.stderr.write(f"[priceByTimes-skip] {stock_id}: 1m bars<2\n")
        return None
    n_after = sum(1 for t in agg["times"] if t.hour * 100 + t.minute > 1330)
    return {
        "yahoo_symbol": yid,
        "times": agg["times"],
        "closes": agg["closes"],
        "volumes_lots": agg["volumes_lots"],
        "opens": agg["opens"],
        "highs": agg["highs"],
        "lows": agg["lows"],
        "source": f"yahoo:priceByTimes:1m:{yid}",
        "prints_n": len(ordered),
        "pages": pages,
        "n_after_1330": n_after,
        "path_min": min(agg["lows"]),
        "path_max": max(agg["highs"]),
    }


def fetch_intraday_path(
    stock_id: str,
    market: str,
    *,
    db_path: Optional[str] = None,
    ymd: str = ASOF_YMD,
) -> Optional[Dict[str, Any]]:
    """上市櫃＝Yahoo 1m chart；興櫃＝priceByTimes（午後可到 15:00）。"""
    if str(market).upper() == "EM":
        path = fetch_yahoo_price_by_times(stock_id, ymd=ymd, yahoo_suffix="TWO")
        if path is not None:
            return path
        sys.stderr.write(f"[em-fallback-1m] {stock_id}: priceByTimes miss → chart 1m\n")
    return fetch_yahoo_1m_path(stock_id, market, db_path=db_path, ymd=ymd)


def _hist_stats(stock_id: str, market: str, db_path: str, *, ymd: str) -> Tuple[Optional[float], Optional[float], Optional[float]]:
    """回 (q_avg_vol_lots, w52_high, w52_low)；庫無則 None。含當日官方高低時由呼叫端再併。"""
    if not db_path or not os.path.isfile(db_path):
        return None, None, None
    table = "emerging_quotes" if str(market).upper() == "EM" else "daily_quotes"
    # 52 週窗：約 365 曆日
    y, m, d = int(ymd[:4]), int(ymd[4:6]), int(ymd[6:8])
    from datetime import date, timedelta

    start = (date(y, m, d) - timedelta(days=365)).strftime("%Y%m%d")
    try:
        conn = sqlite3.connect(db_path, timeout=8.0)
        try:
            qavg = conn.execute(
                f"""
                SELECT AVG(volume) FROM (
                  SELECT volume FROM {table}
                  WHERE stock_id=? AND volume>0 AND REPLACE(CAST(date AS TEXT),'-','') < ?
                  ORDER BY REPLACE(CAST(date AS TEXT),'-','') DESC LIMIT 60
                )
                """,
                (stock_id, ymd),
            ).fetchone()
            w52 = conn.execute(
                f"""
                SELECT MAX(high), MIN(low) FROM {table}
                WHERE stock_id=? AND high>0 AND low>0
                  AND REPLACE(CAST(date AS TEXT),'-','') >= ?
                  AND REPLACE(CAST(date AS TEXT),'-','') < ?
                """,
                (stock_id, start, ymd),
            ).fetchone()
        finally:
            conn.close()
    except sqlite3.Error:
        return None, None, None
    q = float(qavg[0]) if qavg and qavg[0] is not None else None
    hi = float(w52[0]) if w52 and w52[0] is not None else None
    lo = float(w52[1]) if w52 and w52[1] is not None else None
    return q, hi, lo


def _amp(high: float, low: float, prev: float) -> Optional[float]:
    if prev <= 0:
        return None
    return (high - low) / prev * 100.0


_EM_DAY_CACHE: Dict[str, List[dict]] = {}


def fetch_official_em(stock_id: str, *, ymd: str, db_path: str) -> Optional[OfficialDay]:
    import time
    from emerging_quotes import fetch_emerging_csv_day

    rows = _EM_DAY_CACHE.get(ymd)
    if rows is None:
        last_err = ""
        for attempt in range(4):
            try:
                _as_of, rows = fetch_emerging_csv_day(ymd)
                if rows:
                    _EM_DAY_CACHE[ymd] = rows
                    break
                last_err = "empty"
            except Exception as exc:  # noqa: BLE001
                last_err = str(exc)
                rows = None
            time.sleep(1.2 * (attempt + 1))
        if not rows:
            sys.stderr.write(f"[em-miss] {stock_id}: {last_err}\n")
            return None
    hit = next((r for r in rows if str(r.get("stock_id")) == stock_id), None)
    if not hit or hit.get("no_trade"):
        return None
    o = float(hit["open"])
    h = float(hit["high"])
    lo = float(hit["low"])
    c = float(hit["close"])
    pct = float(hit.get("pct_change") or 0.0)
    prev = o if o > 0 else (c / (1.0 + pct / 100.0) if pct != -100 else c)
    chg = c - prev
    qavg, w52h, w52l = _hist_stats(stock_id, "EM", db_path, ymd=ymd)
    if w52h is not None:
        w52h = max(w52h, h)
    else:
        w52h = h
    if w52l is not None:
        w52l = min(w52l, lo)
    else:
        w52l = lo
    avg = float(hit["avg_price"]) if hit.get("avg_price") not in (None, "") else c
    to_k = float(hit["turnover_k"]) if hit.get("turnover_k") not in (None, "") else None
    return OfficialDay(
        stock_id=stock_id,
        open=o,
        high=h,
        low=lo,
        close=c,
        prev_close=prev,
        volume_lots=float(hit.get("volume") or 0.0),
        turnover_k=to_k,
        avg_price=avg,
        pct_change=pct,
        change=chg,
        amplitude_pct=_amp(h, lo, prev),
        q_avg_vol_lots=qavg,
        w52_high=w52h,
        w52_low=w52l,
        source=str(hit.get("source") or "tpex_esb_csv"),
        close_label="興櫃收",
    )


def fetch_official_twse(stock_id: str, *, ymd: str, db_path: str) -> Optional[OfficialDay]:
    import requests

    url = (
        "https://www.twse.com.tw/exchangeReport/STOCK_DAY"
        f"?response=json&date={ymd}&stockNo={stock_id}"
    )
    resp = requests.get(url, timeout=15, headers=_ua())
    if resp.status_code != 200:
        return None
    data = resp.json() or {}
    if str(data.get("stat") or "") != "OK":
        return None
    mmdd = f"{int(ymd[4:6])}/{int(ymd[6:8])}"
    row = None
    for r in data.get("data") or []:
        d0 = str(r[0]).replace("／", "/")
        if d0.endswith(mmdd) or mmdd in d0:
            row = r
            break
    if not row:
        return None

    def _f(s: str) -> float:
        return float(str(s).replace(",", "").strip())

    o, h, lo, c = _f(row[3]), _f(row[4]), _f(row[5]), _f(row[6])
    chg_raw = str(row[7]).replace(",", "").replace("＋", "+").replace("－", "-").replace("X", "").strip()
    try:
        chg = float(chg_raw) if chg_raw not in ("", "+", "-") else 0.0
    except ValueError:
        chg = 0.0
    prev = c - chg
    vol_shares = _f(row[1])
    turnover_ntd = _f(row[2])
    pct = (chg / prev * 100.0) if prev else 0.0
    qavg, w52h, w52l = _hist_stats(stock_id, "TW", db_path, ymd=ymd)
    if w52h is not None:
        w52h = max(w52h, h)
    else:
        w52h = h
    if w52l is not None:
        w52l = min(w52l, lo)
    else:
        w52l = lo
    avg = (turnover_ntd / vol_shares) if vol_shares > 0 else None
    return OfficialDay(
        stock_id=stock_id,
        open=o,
        high=h,
        low=lo,
        close=c,
        prev_close=prev,
        volume_lots=vol_shares / 1000.0,
        turnover_k=turnover_ntd / 1000.0,
        avg_price=avg,
        pct_change=pct,
        change=chg,
        amplitude_pct=_amp(h, lo, prev),
        q_avg_vol_lots=qavg,
        w52_high=w52h,
        w52_low=w52l,
        source="twse:STOCK_DAY",
        close_label="收盤",
    )


_TPEX_DAY_CACHE: Optional[List[dict]] = None


def fetch_official_tpex(stock_id: str, *, ymd: str, db_path: str) -> Optional[OfficialDay]:
    import time
    import requests

    global _TPEX_DAY_CACHE
    url = "https://www.tpex.org.tw/openapi/v1/tpex_mainboard_daily_close_quotes"
    data = _TPEX_DAY_CACHE
    if data is None:
        last_err = ""
        for attempt in range(4):
            try:
                resp = requests.get(url, timeout=45, headers=_ua())
                if resp.status_code != 200:
                    last_err = f"HTTP {resp.status_code}"
                    time.sleep(1.5 * (attempt + 1))
                    continue
                data = resp.json()
                if isinstance(data, list) and data:
                    _TPEX_DAY_CACHE = data
                    break
                last_err = "empty list"
            except Exception as exc:  # noqa: BLE001
                last_err = str(exc)
                time.sleep(1.5 * (attempt + 1))
                data = None
        if not isinstance(data, list) or not data:
            sys.stderr.write(f"[tpex-miss] {stock_id}: {last_err}\n")
            return None
    hit = next((r for r in data if str(r.get("SecuritiesCompanyCode") or "") == stock_id), None)
    if not hit:
        return None

    def _f(s: Any) -> float:
        return float(str(s).replace(",", "").strip())

    o, h, lo, c = _f(hit["Open"]), _f(hit["High"]), _f(hit["Low"]), _f(hit["Close"])
    chg = _f(str(hit.get("Change") or "0").replace(" ", ""))
    prev = c - chg
    vol_shares = _f(hit.get("TradingShares") or 0)
    turnover_ntd = _f(hit.get("TransactionAmount") or 0)
    pct = (chg / prev * 100.0) if prev else 0.0
    avg_s = str(hit.get("Average") or "").strip()
    avg = _f(avg_s) if avg_s not in ("", "--", "-") else (
        (turnover_ntd / vol_shares) if vol_shares > 0 else None
    )
    qavg, w52h, w52l = _hist_stats(stock_id, "TWO", db_path, ymd=ymd)
    if w52h is not None:
        w52h = max(w52h, h)
    else:
        w52h = h
    if w52l is not None:
        w52l = min(w52l, lo)
    else:
        w52l = lo
    return OfficialDay(
        stock_id=stock_id,
        open=o,
        high=h,
        low=lo,
        close=c,
        prev_close=prev,
        volume_lots=vol_shares / 1000.0,
        turnover_k=turnover_ntd / 1000.0 if turnover_ntd else None,
        avg_price=avg,
        pct_change=pct,
        change=chg,
        amplitude_pct=_amp(h, lo, prev),
        q_avg_vol_lots=qavg,
        w52_high=w52h,
        w52_low=w52l,
        source="tpex:mainboard_daily_close",
        close_label="收盤",
    )


def fetch_official(stock_id: str, market: str, *, ymd: str, db_path: str) -> Optional[OfficialDay]:
    import time

    m = str(market).upper()
    last: Optional[OfficialDay] = None
    for attempt in range(3):
        try:
            if m == "EM":
                last = fetch_official_em(stock_id, ymd=ymd, db_path=db_path)
            elif m == "TWO":
                last = fetch_official_tpex(stock_id, ymd=ymd, db_path=db_path)
            else:
                last = fetch_official_twse(stock_id, ymd=ymd, db_path=db_path)
            if last is not None:
                return last
        except Exception as exc:  # noqa: BLE001
            sys.stderr.write(f"[official-retry] {stock_id} {attempt}: {exc}\n")
            time.sleep(1.5 * (attempt + 1))
    return last


def _fmt_face(v: float) -> str:
    from wayne_navigator import _fmt_price

    return _fmt_price(v)


def _fmt_turnover(turnover_k: float) -> str:
    """千元 → 億／萬可讀。"""
    ntd = float(turnover_k) * 1000.0
    if ntd >= 1e8:
        return f"{ntd / 1e8:.2f}億".rstrip("0").rstrip(".")
    if ntd >= 1e4:
        return f"{ntd / 1e4:.2f}萬".rstrip("0").rstrip(".")
    return f"{ntd:,.0f}"


def _fmt_lots(v: float) -> str:
    return f"{int(round(float(v))):,}張"


def _detect_notices(
    series_times: List[datetime],
    closes: List[float],
    vols: List[float],
    off: OfficialDay,
    *,
    market: str,
) -> List[str]:
    out: List[str] = []
    if not closes:
        return out
    prev = float(off.prev_close)
    crossed = None
    for t, c in zip(series_times, closes):
        if c < prev:
            crossed = t
            break
    if off.close < prev:
        if crossed is not None:
            out.append(f"破昨收　{crossed.strftime('%H:%M')} 起跌破 {_fmt_face(prev)}")
        else:
            out.append(f"破昨收　官方收 {_fmt_face(off.close)} ＜ 昨收 {_fmt_face(prev)}")
    # 急殺＝路徑內最陡 8–20 分跌幅（與臉上標同規則）；缺資料邊界不算
    kill = None
    for i, c0 in enumerate(closes):
        if c0 <= 0:
            continue
        t0 = series_times[i]
        for j in range(i + 1, len(closes)):
            mins = (series_times[j] - t0).total_seconds() / 60.0
            if mins > 20:
                break
            if mins < 8:
                continue
            drop_pct = (closes[j] - c0) / c0 * 100.0
            if drop_pct <= -5.0 and (kill is None or drop_pct < kill[2]):
                kill = (t0, series_times[j], drop_pct)
    if kill:
        out.append(
            f"急殺段　{kill[0].strftime('%H:%M')}→{kill[1].strftime('%H:%M')}　{kill[2]:+.1f}%"
        )
    if vols and sum(vols) > 0:
        import numpy as np

        arr = np.asarray(vols, dtype=float)
        med = float(np.median(arr[arr > 0])) if np.any(arr > 0) else 0.0
        total = float(arr.sum())
        peak_i = int(np.argmax(arr))
        if med > 0 and arr[peak_i] >= med * 6 and arr[peak_i] / total >= 0.04:
            out.append(
                f"爆量窗　{series_times[peak_i].strftime('%H:%M')}　{arr[peak_i]:,.0f}張／分"
            )
    if len(closes) >= 10 and off.close < prev:
        below = touched = failed = False
        for c in closes:
            if c < prev * 0.998:
                below = True
            if below and abs(c - prev) / prev <= 0.003:
                touched = True
            if touched and c < prev * 0.985:
                failed = True
                break
        if failed:
            out.append("回測失敗　反彈未站回昨收")
    if str(market).upper() == "EM" and series_times:
        t1 = series_times[-1]
        n_aft = sum(1 for t in series_times if t.hour * 100 + t.minute > 1330)
        if n_aft <= 0 and t1.hour * 100 + t1.minute <= 1330:
            out.insert(0, f"缺資料　路徑末 {t1.strftime('%H:%M')}→15:00（未捏點）")
        path_lo = min(closes)
        if off.low < path_lo * 0.98:
            out.append(f"官方低 {_fmt_face(off.low)} ＜ 路徑低 {_fmt_face(path_lo)}")
    return out


def build_series(
    stock_id: str,
    name: str,
    market: str,
    *,
    db_path: str,
    ymd: str = ASOF_YMD,
) -> Optional[PathSeries]:
    off = fetch_official(stock_id, market, ymd=ymd, db_path=db_path)
    if off is None:
        sys.stderr.write(f"[official-miss] {stock_id}\n")
        return None
    path = fetch_intraday_path(stock_id, market, db_path=db_path, ymd=ymd)
    if path is None:
        return None
    times = list(path["times"])
    closes = list(path["closes"])
    notices = _detect_notices(times, closes, list(path["volumes_lots"]), off, market=market)
    gap_after = None
    if str(market).upper() == "EM":
        t1 = times[-1]
        # 有午後點＝真路徑到／過 13:30 → 不畫缺資料灰帶
        n_aft = int(path.get("n_after_1330") or 0)
        if n_aft <= 0 and t1.hour * 100 + t1.minute < 1500:
            gap_after = t1
        elif n_aft <= 0 and t1.hour * 100 + t1.minute <= 1330:
            gap_after = t1
    return PathSeries(
        stock_id=stock_id,
        name=name,
        market=market,
        times=times,
        closes=closes,
        volumes_lots=list(path["volumes_lots"]),
        opens=list(path["opens"]),
        highs=list(path["highs"]),
        lows=list(path["lows"]),
        path_source=str(path["source"]),
        path_end=times[-1],
        gap_after=gap_after,
        official=off,
        notices=notices,
        fetched_at=datetime.now(TZ),
    )


def render_empty(out_path: str, *, stock_id: str, name: str, market: str, reason: str) -> str:
    import matplotlib

    matplotlib.use("Agg", force=True)
    import matplotlib.pyplot as plt
    from matplotlib.patches import FancyBboxPatch
    from ink_chart_theme import INK, INK2, MUTE, PAPER, fp

    fig = plt.figure(figsize=(12.8, 7.2), dpi=160, facecolor=PAPER)
    ax = fig.add_axes([0.06, 0.08, 0.88, 0.82])
    ax.axis("off")
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.add_patch(
        FancyBboxPatch(
            (0.05, 0.18), 0.90, 0.62, boxstyle="square,pad=0.012",
            facecolor=PAPER, edgecolor=INK, linewidth=1.4, transform=ax.transAxes,
        )
    )
    ax.text(0.5, 0.62, f"{stock_id}　{name}", fontproperties=fp(28, True), color=INK, ha="center", va="center", transform=ax.transAxes)
    ax.text(0.5, 0.48, "暫無今日路徑資料", fontproperties=fp(22, True), color=INK2, ha="center", va="center", transform=ax.transAxes)
    ax.text(0.5, 0.36, f"{reason}　｜　{market}", fontproperties=fp(12, False), color=MUTE, ha="center", va="center", transform=ax.transAxes)
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    fig.savefig(out_path, facecolor=PAPER, edgecolor="none")
    plt.close(fig)
    return out_path


def _scrub_em_limit_labels(fig) -> None:
    """興櫃無上市櫃漲跌停；墨線誤標要清。"""
    for ax in fig.axes:
        for t in list(ax.texts):
            s = str(t.get_text() or "")
            if "漲停" in s or "跌停" in s:
                t.set_text(s.replace("　漲停", "").replace("　跌停", "").replace(" 漲停", "").replace(" 跌停", "").replace("漲停", "").replace("跌停", ""))
    for t in list(fig.texts):
        s = str(t.get_text() or "")
        if "漲停" in s or "跌停" in s:
            t.set_text(s.replace("　漲停", "").replace("　跌停", "").replace(" 漲停", "").replace(" 跌停", "").replace("漲停", "").replace("跌停", ""))


def _paint_quote_grid(ov, off: OfficialDay, *, y_top: float, left: float, right: float) -> None:
    """八格報價格：畫在 overlay（0–100），高 z，不准被頭欄白底蓋成幽靈字。

    格序：今開／最高／成交量／昨收／最低／成交額／日均價｜均價／振幅。
    """
    from ink_chart_theme import DN, INK, MUTE, PAPER, UP, fp
    from matplotlib.patches import FancyBboxPatch

    avg_lab = "日均價" if off.close_label == "興櫃收" else "均價"
    avg_val = _fmt_face(off.avg_price) if off.avg_price and off.avg_price > 0 else "—"
    turn_val = _fmt_turnover(off.turnover_k) if off.turnover_k and off.turnover_k > 0 else "—"
    amp_val = f"{off.amplitude_pct:.2f}%" if off.amplitude_pct is not None else "—"
    cells: List[Tuple[str, str, str]] = [
        ("今開", _fmt_face(off.open), INK),
        ("最高", _fmt_face(off.high), UP),
        ("成交量", _fmt_lots(off.volume_lots), INK),
        ("昨收", _fmt_face(off.prev_close), INK),
        ("最低", _fmt_face(off.low), DN),
        ("成交額", turn_val, INK),
        (avg_lab, avg_val, INK),
        ("振幅", amp_val, INK),
    ]

    cols = 4
    gap_x, gap_y = 0.55, 0.55
    cell_h = 5.6  # 0–100 ov units；約兩列清楚可讀
    width = right - left
    cell_w = (width - gap_x * (cols - 1)) / cols
    edge = "#9AA0A6"
    lab_col = "#3A3A3A"
    for i, (lab, val, col) in enumerate(cells):
        r, c = divmod(i, cols)
        x = left + c * (cell_w + gap_x)
        y = y_top - (r + 1) * (cell_h + gap_y)
        ov.add_patch(
            FancyBboxPatch(
                (x, y), cell_w, cell_h,
                boxstyle="square,pad=0.04",
                facecolor=PAPER, edgecolor=edge, linewidth=1.15,
                alpha=1.0, zorder=40, clip_on=False,
            )
        )
        ov.text(
            x + 0.55, y + cell_h * 0.52, lab,
            fontproperties=fp(13, True), color=lab_col, ha="left", va="center",
            zorder=41, clip_on=False,
        )
        ov.text(
            x + cell_w - 0.55, y + cell_h * 0.52, val,
            fontproperties=fp(18, True), color=col, ha="right", va="center",
            zorder=41, clip_on=False,
        )
    if off.close_label == "興櫃收" and not (off.low <= off.open <= off.high):
        note_y = y_top - 2 * (cell_h + gap_y) - 0.8
        ov.text(
            left, note_y,
            "註：興櫃開＝前日均價，可高於當日最高",
            fontproperties=fp(11, False), color=MUTE, ha="left", va="top",
            zorder=41, clip_on=False,
        )


def _paint_range_bars(fig, off: OfficialDay, *, y_bot: float, left: float, right: float) -> None:
    """底部三條：量能％、今日區間、52週；端點＋最新／收盤必現，不准空白帶。"""
    from ink_chart_theme import DN, INK, MUTE, PAPER, RULE, UP, YELLOW, fp
    from matplotlib.patches import FancyBboxPatch, Rectangle

    bar_h = 0.028
    row_pitch = 0.074
    width = right - left
    y = y_bot + 2 * row_pitch + 0.014
    last_lab = "日均" if off.close_label == "興櫃收" else "收盤"
    z = 30

    def _tick(mf: float, yb: float) -> float:
        mf = max(0.0, min(1.0, float(mf)))
        mx = left + width * mf
        fig.patches.append(
            Rectangle(
                (mx - 0.0018, yb - 0.005), 0.0036, bar_h + 0.010,
                transform=fig.transFigure, facecolor=INK, edgecolor="none", clip_on=False, zorder=z,
            )
        )
        return mx

    def _bubble(mx: float, yb: float, text: str, *, side: str, ha: str = "center") -> None:
        ty = yb + bar_h + 0.007 if side == "above" else yb - 0.007
        va = "bottom" if side == "above" else "top"
        fig.text(
            mx, ty, text, fontproperties=fp(12, True), color=INK, ha=ha, va=va,
            transform=fig.transFigure, zorder=z + 1,
            bbox=dict(boxstyle="square,pad=0.22", facecolor=PAPER, edgecolor="#9AA0A6", linewidth=1.0),
        )

    # —— 1) 量能（無季均仍畫當日量，不准空白） ——
    fig.text(left, y + bar_h + 0.009, "量能", fontproperties=fp(12, True), color=INK, ha="left", va="bottom", transform=fig.transFigure, zorder=z)
    fig.patches.append(
        Rectangle((left, y), width, bar_h, transform=fig.transFigure, facecolor=RULE, edgecolor="#9AA0A6", linewidth=0.7, clip_on=False, zorder=z)
    )
    if off.q_avg_vol_lots and off.q_avg_vol_lots > 0:
        ratio = off.volume_lots / off.q_avg_vol_lots
        pct = int(round(ratio * 100))
        fill_w = width * min(ratio, 1.0)
        fig.patches.append(
            Rectangle(
                (left, y), fill_w, bar_h,
                transform=fig.transFigure, facecolor=DN if ratio >= 1 else UP, edgecolor="none", alpha=0.90, clip_on=False, zorder=z,
            )
        )
        badge_x = left + min(max(fill_w, width * 0.12), width * 0.92)
        fig.patches.append(
            FancyBboxPatch(
                (badge_x - 0.034, y + bar_h + 0.002), 0.068, 0.026,
                boxstyle="square,pad=0.002",
                facecolor=DN if ratio >= 1 else UP, edgecolor=INK, linewidth=0.9,
                transform=fig.transFigure, clip_on=False, zorder=z,
            )
        )
        fig.text(
            badge_x, y + bar_h + 0.015, f"{pct}%",
            fontproperties=fp(12, True), color=PAPER, ha="center", va="center", transform=fig.transFigure, zorder=z + 1,
        )
        fig.text(
            left, y - 0.005, f"季均 {_fmt_lots(off.q_avg_vol_lots)}",
            fontproperties=fp(11, False), color="#3A3A3A", ha="left", va="top", transform=fig.transFigure, zorder=z,
        )
    else:
        fig.text(
            left, y - 0.005, "季均 —",
            fontproperties=fp(11, False), color="#3A3A3A", ha="left", va="top", transform=fig.transFigure, zorder=z,
        )
    fig.text(
        right, y - 0.005, f"當日 {_fmt_lots(off.volume_lots)}",
        fontproperties=fp(13, True), color=INK, ha="right", va="top", transform=fig.transFigure, zorder=z,
    )
    y -= row_pitch

    # —— 2) 今日區間（高低必標） ——
    span = max(off.high - off.low, 1e-9)
    last_f = (off.close - off.low) / span
    open_in = off.low <= off.open <= off.high
    open_f = (off.open - off.low) / span if open_in else None
    fig.text(left, y + bar_h + 0.009, "今日區間", fontproperties=fp(12, True), color=INK, ha="left", va="bottom", transform=fig.transFigure, zorder=z)
    fig.patches.append(
        Rectangle((left, y), width, bar_h, transform=fig.transFigure, facecolor=RULE, edgecolor="#9AA0A6", linewidth=0.7, clip_on=False, zorder=z)
    )
    if open_f is not None:
        a, b = sorted([open_f, last_f])
        fig.patches.append(
            Rectangle(
                (left + width * a, y), max(width * (b - a), 0.004), bar_h,
                transform=fig.transFigure,
                facecolor=(DN if off.close < off.open else UP),
                edgecolor="none", alpha=0.92, clip_on=False, zorder=z,
            )
        )
    else:
        lf = max(0.0, min(1.0, last_f))
        fig.patches.append(
            Rectangle(
                (left + width * lf - 0.006, y), 0.012, bar_h,
                transform=fig.transFigure,
                facecolor=DN if off.close < off.prev_close else UP,
                edgecolor="none", alpha=0.95, clip_on=False, zorder=z,
            )
        )
    fig.text(left, y - 0.005, f"日低 {_fmt_face(off.low)}", fontproperties=fp(13, True), color=DN, ha="left", va="top", transform=fig.transFigure, zorder=z)
    fig.text(right, y - 0.005, f"日高 {_fmt_face(off.high)}", fontproperties=fp(13, True), color=UP, ha="right", va="top", transform=fig.transFigure, zorder=z)
    ha_last = "left" if last_f <= 0.12 else ("right" if last_f >= 0.88 else "center")
    if open_f is not None and abs(open_f - last_f) < 0.08:
        _bubble(
            _tick(last_f, y), y,
            f"{last_lab} {_fmt_face(off.close)} ≈ 開 {_fmt_face(off.open)}",
            side="above", ha=ha_last,
        )
    else:
        if open_f is not None:
            _bubble(_tick(open_f, y), y, f"開盤 {_fmt_face(off.open)}", side="below")
        _bubble(_tick(last_f, y), y, f"{last_lab} {_fmt_face(off.close)}", side="above", ha=ha_last)
    y -= row_pitch

    # —— 3) 52週 ——
    w_lo = off.w52_low if off.w52_low is not None else off.low
    w_hi = off.w52_high if off.w52_high is not None else off.high
    if w_hi <= w_lo:
        w_hi = w_lo + max(abs(w_lo) * 0.01, 1.0)
    span52 = w_hi - w_lo
    open_f = (off.open - w_lo) / span52
    last_f = (off.close - w_lo) / span52
    fig.text(left, y + bar_h + 0.009, "52週", fontproperties=fp(12, True), color=INK, ha="left", va="bottom", transform=fig.transFigure, zorder=z)
    fig.patches.append(
        Rectangle((left, y), width, bar_h, transform=fig.transFigure, facecolor=RULE, edgecolor="#9AA0A6", linewidth=0.7, clip_on=False, zorder=z)
    )
    lf = max(0.0, min(1.0, last_f))
    fig.patches.append(
        Rectangle(
            (left + width * lf - 0.005, y), 0.010, bar_h,
            transform=fig.transFigure, facecolor=YELLOW, edgecolor="none", alpha=0.95, clip_on=False, zorder=z,
        )
    )
    fig.text(left, y - 0.005, f"52週低 {_fmt_face(w_lo)}", fontproperties=fp(13, True), color=DN, ha="left", va="top", transform=fig.transFigure, zorder=z)
    fig.text(right, y - 0.005, f"52週高 {_fmt_face(w_hi)}", fontproperties=fp(13, True), color=UP, ha="right", va="top", transform=fig.transFigure, zorder=z)
    ha = "left" if last_f <= 0.18 else ("right" if last_f >= 0.82 else "center")
    _bubble(_tick(last_f, y), y, f"{last_lab} {_fmt_face(off.close)}", side="above", ha=ha)
    if abs(open_f - last_f) >= 0.08 and off.low <= off.open <= off.high:
        _bubble(_tick(open_f, y), y, f"開盤 {_fmt_face(off.open)}", side="below")



def render_path(series: PathSeries, out_path: str, *, db_path: str = "") -> str:
    import numpy as np
    import matplotlib

    matplotlib.use("Agg", force=True)
    import matplotlib.pyplot as plt
    from matplotlib.patches import FancyBboxPatch

    from biaoke_chart import (
        _HEADER_X_FB,
        _SPOT_X_NO_LOCATOR,
        _STRUCTURE_BOX_EC,
        _STRUCTURE_BOX_LW,
        _STRUCTURE_BOX_STYLE,
        _STRUCTURE_BOX_W,
        _STRUCTURE_BOX_X,
        _STRUCTURE_META_FS,
        _STRUCTURE_SPOT_FS,
        _STRUCTURE_SPOT_LAB_FS,
        _STRUCTURE_SPOT_MOVE_FS,
        _STRUCTURE_SPOT_ROW_GAP,
        _STRUCTURE_SPOT_STAMP_FS,
        _STRUCTURE_TITLE_FS,
        _STRUCTURE_TOP_PAD,
        _TEXT,
        _fp,
        _paint_nameplate,
        _paint_spot,
        stock_nameplate,
    )
    from decision_card_signals import board_close_clock_label, format_ymd_slash_weekday
    from ink_chart_theme import (
        DN,
        INK,
        MUTE,
        PAPER,
        RULE,
        UP,
        Ink,
        close_struct_frame_seam,
        fp,
        struct_frames,
        struct_header,
    )

    off = series.official
    is_em = str(series.market).upper() == "EM"
    times = series.times
    ys = np.asarray(series.closes, dtype=float)
    vs = np.asarray(series.volumes_lots, dtype=float)
    prev = float(off.prev_close)

    def _x(dt: datetime) -> float:
        return (dt.hour - 9) * 60 + dt.minute

    xs = np.asarray([_x(t) for t in times], dtype=float)
    x_end = 360.0 if is_em else 270.0

    # v5：底≈24%；頭欄＝名牌＋八格（overlay 高 z）；右緣留白給日高／昨收／日低
    fig_w, fig_h, dpi = 13.2, 12.0, 200
    fig = plt.figure(figsize=(fig_w, fig_h), dpi=dpi, facecolor=PAPER)

    left_f, right_f = 0.055, 0.86
    range_top = 0.250
    vol_h = 0.078
    vol_bot = range_top + 0.012
    main_bot = vol_bot + vol_h + 0.012
    main_top = 0.60  # 頭欄名牌＋八格在上
    ax = fig.add_axes([left_f, main_bot, right_f - left_f, main_top - main_bot])
    vol_ax = fig.add_axes([left_f, vol_bot, right_f - left_f, vol_h], sharex=ax)
    ax.set_facecolor(PAPER)
    vol_ax.set_facecolor(PAPER)

    ov = fig.add_axes([0, 0, 1, 1], facecolor="none", zorder=12)
    ov.set_xlim(0, 100)
    ov.set_ylim(0, 100)
    ov.axis("off")
    ov.patch.set_alpha(0)

    band_bot = main_top * 100.0
    ov.add_patch(
        FancyBboxPatch(
            (_STRUCTURE_BOX_X, band_bot + 0.35),
            _STRUCTURE_BOX_W,
            100.0 - band_bot - float(_STRUCTURE_TOP_PAD) - 0.15,
            boxstyle=_STRUCTURE_BOX_STYLE,
            facecolor="#ffffff",
            edgecolor=_STRUCTURE_BOX_EC,
            linewidth=_STRUCTURE_BOX_LW,
            alpha=1.0,
            zorder=1,
            clip_on=False,
        )
    )
    for y0, y1 in (
        (main_bot * 100.0, band_bot - 0.2),
        (vol_bot * 100.0, (vol_bot + vol_h) * 100.0),
    ):
        ov.add_patch(
            FancyBboxPatch(
                (_STRUCTURE_BOX_X, y0),
                _STRUCTURE_BOX_W,
                max(0.4, y1 - y0),
                boxstyle=_STRUCTURE_BOX_STYLE,
                facecolor="none",
                edgecolor=_STRUCTURE_BOX_EC,
                linewidth=_STRUCTURE_BOX_LW,
                alpha=0.98,
                zorder=0,
                clip_on=False,
            )
        )

    plate = stock_nameplate(series.stock_id, series.name, db_path)
    header_x = float(_HEADER_X_FB)
    name_y = 95.6
    _paint_nameplate(
        ov, plate, x=header_x, y=float(name_y),
        title_size=int(_STRUCTURE_TITLE_FS), industry_size=12,
    )

    quote = {
        "open": off.open,
        "high": off.high,
        "low": off.low,
        "close": off.close,
        "prev": off.prev_close,
        "change": off.change,
        "pct": off.pct_change,
        "label": off.close_label,
        "is_live": False,
    }
    try:
        date_part = format_ymd_slash_weekday(ASOF_YMD)
    except Exception:
        date_part = f"{ASOF_YMD[:4]}/{ASOF_YMD[4:6]}/{ASOF_YMD[6:8]}"
    stamp = f"{date_part} {board_close_clock_label(emerging=is_em)}".strip()
    # 興櫃無漲跌停：暫把 pct 藏起來讓 spot 不貼漲跌停底，畫完還原數字在 move 列
    spot_quote = dict(quote)
    if is_em:
        spot_quote["pct"] = None  # quote_limit_side 無 pct 就不判停
        # change 仍在，format_move_plain 要 pct — 改手動
        spot_quote["change"] = off.change
        spot_quote["pct"] = off.pct_change * 0.0  # 0 → 不判停；move 列改事後補
    _paint_spot(
        ov, spot_quote if not is_em else {**quote, "pct": 0.0, "change": 0.0},
        x=float(_SPOT_X_NO_LOCATOR), y=float(name_y), align="right",
        stamp=stamp, move_dy=float(_STRUCTURE_SPOT_ROW_GAP),
        price_size=int(_STRUCTURE_SPOT_FS),
        move_size=int(_STRUCTURE_SPOT_MOVE_FS),
        stamp_size=int(_STRUCTURE_SPOT_STAMP_FS),
        lab_size=int(_STRUCTURE_SPOT_LAB_FS),
    )
    if is_em:
        # 補回真實漲跌字（無漲跌停底）
        from tg_layout import format_move_plain
        from wayne_navigator import quote_move_ink

        move = format_move_plain(off.change, off.pct_change)
        col = quote_move_ink(off.change, close=off.close, prev=off.prev_close, pct=off.pct_change, up=UP, down=DN, flat=MUTE)
        # 找到「較昨日」列改字色
        for t in ov.texts:
            s = str(t.get_text() or "")
            if s.startswith("較昨日"):
                t.set_text("較昨日　" + move)
                t.set_color(col)
                if t.get_bbox_patch() is not None:
                    t.set_bbox(dict(boxstyle="square,pad=0.28", facecolor=col, edgecolor=INK, linewidth=1.2))
                    t.set_color(PAPER)
            # 清大價任何漲跌停底
            if re.fullmatch(r"[\d,.]+", s.strip()) and t.get_fontsize() >= 24:
                t.set_bbox(None)
                t.set_color(col)

    # 只做頭欄墨線（名牌黑標＋右漲跌），不准 apply_struct 動主圖 y 軸
    ink = Ink(fig, "struct", lazy=True)
    ink.redraw()
    frames = struct_frames(ink, ov)
    close_struct_frame_seam(frames)
    struct_header(ink, ov, frames)
    if is_em:
        _scrub_em_limit_labels(fig)

    # 八格：overlay 高 z，落在名牌／時間戳下、主圖框上（不准幽靈字）
    _paint_quote_grid(
        ov, off,
        y_top=83.8,
        left=left_f * 100.0,
        right=right_f * 100.0,
    )

    # 路徑
    hi = float(max(float(np.max(ys)), prev, off.high, float(np.max(series.highs))))
    lo = float(min(float(np.min(ys)), prev, off.low, float(np.min(series.lows))))
    pad = max((hi - lo) * 0.10, abs(prev) * 0.002, 0.5)
    ax.set_ylim(lo - pad, hi + pad)
    ax.set_xlim(0.0, x_end)
    ax.axhline(prev, color=MUTE, linestyle=(0, (4, 3)), linewidth=1.35, zorder=2)
    ax.axhline(off.high, color=UP, linestyle=(0, (2, 3)), linewidth=0.9, alpha=0.7, zorder=2)
    # 官方日低虛線（興櫃路徑未必碰到）
    ax.axhline(off.low, color=DN, linestyle=(0, (2, 3)), linewidth=1.0, alpha=0.75, zorder=2)
    ax.fill_between(xs, prev, ys, where=ys >= prev, interpolate=True, color=UP, alpha=0.16, zorder=1)
    ax.fill_between(xs, prev, ys, where=ys <= prev, interpolate=True, color=DN, alpha=0.16, zorder=1)
    for i in range(len(ys) - 1):
        a, b = float(ys[i]), float(ys[i + 1])
        x0, x1 = float(xs[i]), float(xs[i + 1])
        if x1 - x0 > 8:
            continue
        if (a >= prev and b >= prev) or (a < prev and b < prev):
            ax.plot([x0, x1], [a, b], color=(UP if a >= prev else DN), lw=2.05, solid_capstyle="round", zorder=3)
        else:
            if b == a:
                continue
            t = (prev - a) / (b - a)
            xc = x0 + t * (x1 - x0)
            ax.plot([x0, xc], [a, prev], color=(UP if a >= prev else DN), lw=2.05, zorder=3)
            ax.plot([xc, x1], [prev, b], color=(UP if b >= prev else DN), lw=2.05, zorder=3)

    # 右側三層必現：日高／昨收／日低（價近合併；貼右緣外，不准空）
    y_span = (hi + pad) - (lo - pad)
    low_lab = f"官方日低 {_fmt_face(off.low)}" if is_em else f"日低 {_fmt_face(off.low)}"
    right_labs: List[Tuple[float, str, str]] = []
    if abs(off.high - prev) / max(y_span, 1e-9) < 0.08:
        mid = (off.high + prev) * 0.5
        right_labs.append((mid, f"昨收 {_fmt_face(prev)}／日高 {_fmt_face(off.high)}", "#3A3A3A"))
    else:
        right_labs.append((off.high, f"日高 {_fmt_face(off.high)}", UP))
        right_labs.append((prev, f"昨收 {_fmt_face(prev)}", "#3A3A3A"))
    right_labs.append((off.low, low_lab, DN))
    right_labs.sort(key=lambda t: t[0])
    placed_y: List[float] = []
    min_gap = max(y_span * 0.10, abs(prev) * 0.008)
    for px, lab, col in right_labs:
        yy = float(px)
        for py in placed_y:
            if abs(yy - py) < min_gap:
                yy = py + min_gap if yy >= py else py - min_gap
        yy = min(max(yy, lo - pad * 0.05), hi + pad * 0.05)
        placed_y.append(yy)
        ax.text(
            1.012, yy, lab,
            fontproperties=fp(11.5, True), color=col, ha="left", va="center",
            transform=ax.get_yaxis_transform(), zorder=8,
            bbox=dict(boxstyle="square,pad=0.28", facecolor=PAPER, edgecolor=col, linewidth=1.05),
            clip_on=False,
        )

    if series.gap_after is not None:
        import matplotlib.patches as mpatches

        gx0 = _x(series.gap_after)
        # 斜線底紋灰帶（必改 6.3）
        for a in (ax, vol_ax):
            a.axvspan(gx0, x_end, facecolor="#E8EAED", alpha=0.85, zorder=0)
            a.add_patch(
                mpatches.Rectangle(
                    (gx0, a.get_ylim()[0]), x_end - gx0, a.get_ylim()[1] - a.get_ylim()[0],
                    fill=False, hatch="///", edgecolor="#9AA0A6", linewidth=0.0, zorder=0.5,
                )
            )
        ax.text(
            (gx0 + x_end) * 0.5, hi - (hi - lo) * 0.05, "缺資料",
            fontproperties=fp(14, True), color="#3A3A3A", ha="center", va="top", zorder=6,
        )
        ax.text(
            (gx0 + x_end) * 0.5, hi - (hi - lo) * 0.12, "13:30–15:00 無分時",
            fontproperties=fp(9, False), color="#5C5C5C", ha="center", va="top", zorder=6,
        )
        # 路徑末圓點
        ax.plot([xs[-1]], [ys[-1]], "o", color=INK, markersize=5.5, zorder=8)

    _paint_sparse_marks(ax, series, xs, ys, prev)

    if len(xs) >= 2:
        width = max(float(np.median(np.diff(xs))) * 0.75, 0.6)
    else:
        width = 1.0
    vol_ax.bar(xs, vs, width=width, color=[UP if float(y) >= prev else DN for y in ys], alpha=0.85, zorder=2, linewidth=0)
    vol_ax.set_ylim(0, max(float(np.max(vs)) * 1.15, 1.0))

    tick_h = [9, 10, 11, 12, 13, 14, 15] if is_em else [9, 10, 11, 12, 13]
    tick_x = [(h - 9) * 60 for h in tick_h]
    for a in (ax, vol_ax):
        a.set_xticks(tick_x)
        a.tick_params(colors=MUTE, length=3, labelsize=10)
        for sp in a.spines.values():
            sp.set_color(INK)
            sp.set_linewidth(0.95)
        a.grid(True, axis="both", color=RULE, linewidth=0.7, zorder=0)
    ax.set_xticklabels([])
    vol_ax.set_xticklabels([f"{h:02d}" for h in tick_h], fontproperties=fp(10, False), color=MUTE)
    for lab in ax.get_yticklabels():
        lab.set_fontproperties(fp(10, False))
        lab.set_color(MUTE)
    vol_ax.set_yticks([])
    vol_ax.text(0.01, 0.92, "量(張)", transform=vol_ax.transAxes, fontproperties=fp(9, False), color=MUTE, va="top", ha="left")

    # 底部三條用圖框同寬（含右標外的視覺對齊用 chart 右緣）
    _paint_range_bars(fig, off, y_bot=0.022, left=left_f, right=min(right_f + 0.04, 0.94))

    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    fig.savefig(out_path, facecolor=PAPER, edgecolor="none")
    plt.close(fig)
    return out_path


def _paint_sparse_marks(ax, series: PathSeries, xs, ys, prev: float) -> None:
    """Smart labels：避開缺資料邊界假急殺；offset 不蓋折線。"""
    from ink_chart_theme import DN, INK, UP, fp
    import numpy as np

    marks: List[Tuple[float, float, str, str, Tuple[float, float]]] = []
    for x, y in zip(xs, ys):
        if float(y) < prev:
            marks.append((float(x), float(y), "破昨收", DN, (10, 14)))
            break
    # 急殺：真跌段；缺資料邊界前 5 分內的路徑低點不算（避免假崖）
    if len(ys) >= 8:
        gap_cut = None
        if series.gap_after is not None:
            gap_cut = (series.gap_after.hour - 9) * 60 + series.gap_after.minute
        # 找最大 8–20 分跌幅窗
        best = None
        for i in range(len(ys)):
            for j in range(i + 1, len(ys)):
                mins = float(xs[j] - xs[i])
                if mins > 20:
                    break
                if mins < 8:
                    continue
                if gap_cut is not None and float(xs[j]) >= gap_cut - 5:
                    continue
                drop = (float(ys[j]) - float(ys[i])) / float(ys[i]) if ys[i] else 0.0
                if drop <= -0.05 and (best is None or drop < best[0]):
                    best = (drop, float(xs[j]), float(ys[j]))
        if best is not None:
            marks.append((best[1], best[2], "急殺", DN, (8, -16)))
    vs = np.asarray(series.volumes_lots, dtype=float)
    if len(vs) and float(np.max(vs)) > 0:
        med = float(np.median(vs[vs > 0])) if np.any(vs > 0) else 0.0
        i = int(np.argmax(vs))
        if med > 0 and vs[i] >= med * 6:
            marks.append(
                (float(xs[i]), float(ys[i]), "爆量", UP if ys[i] >= prev else DN, (8, 16))
            )
    kept: List[Tuple[float, float, str, str, Tuple[float, float]]] = []
    for m in marks:
        if any(abs(m[0] - k[0]) < 22 and m[2] == k[2] for k in kept):
            continue
        # 同類近鄰也避開
        if any(abs(m[0] - k[0]) < 14 for k in kept):
            # 改 offset 方向
            ox, oy = m[4]
            m = (m[0], m[1], m[2], m[3], (ox, -oy if oy > 0 else 18))
        kept.append(m)
    for x, y, lab, col, (ox, oy) in kept[:3]:
        # 事件標加大（交叉必改 3.1 ≈28–32px @200dpi → ~11.5–12pt）
        ax.annotate(
            lab, xy=(x, y), xytext=(ox, oy), textcoords="offset points",
            fontproperties=fp(12, True), color=INK,
            bbox=dict(boxstyle="square,pad=0.32", facecolor="#FFF8E7", edgecolor=col, linewidth=1.15),
            arrowprops=dict(arrowstyle="-", color=col, lw=0.85, shrinkA=0, shrinkB=2),
            zorder=7,
            annotation_clip=False,
        )


def default_out_dir() -> str:
    env = os.environ.get("WAYNE_INTRADAY_PREVIEW_DIR", "").strip()
    if env:
        return env
    for store in (
        "/cursor/stores/self/media/intraday-open-close-chart-20261029",
        "/cursor/stores/bc-01a0d9ba-b7e3-7f56-802d-4c6e57f8ad9e/media/intraday-open-close-chart-20261029",
    ):
        if os.path.isdir(os.path.dirname(store)) or os.path.isdir(store):
            return store
    return os.path.join(_ROOT, "artifacts", "intraday-open-close-preview")


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Preview ink 今日開→收 v5（不接話筒）")
    ap.add_argument("--out-dir", default=default_out_dir())
    ap.add_argument("--db", default=os.path.join(_ROOT, "data", "wayne_market.db"))
    ap.add_argument("--ymd", default=ASOF_YMD)
    ap.add_argument("--prefix", default="preview-v5")
    ap.add_argument("--only", default="", help="comma stock ids; empty=all")
    args = ap.parse_args(list(argv) if argv is not None else None)

    out_dir = args.out_dir
    os.makedirs(out_dir, exist_ok=True)
    results: List[Dict[str, Any]] = []
    notices_all: Dict[str, List[str]] = {}
    only = {s.strip() for s in str(args.only or "").split(",") if s.strip()}

    for sid, name, market in PREVIEW_SYMBOLS:
        if only and sid not in only:
            continue
        slug = _SLUG.get(sid, sid)
        out_path = os.path.join(out_dir, f"{args.prefix}-{sid}-{slug}.png")
        series = build_series(sid, name, market, db_path=args.db, ymd=args.ymd)
        if series is None:
            render_empty(out_path, stock_id=sid, name=name, market=market, reason="官方日值或路徑不可用")
            results.append({"stock_id": sid, "name": name, "market": market, "path": out_path, "ok": False, "n": 0})
            print(f"[empty] {sid} {name} -> {out_path}")
            continue
        render_path(series, out_path, db_path=args.db)
        notices_all[sid] = list(series.notices)
        results.append(
            {
                "stock_id": sid,
                "name": name,
                "market": market,
                "path": out_path,
                "ok": True,
                "n": len(series.closes),
                "path_source": series.path_source,
                "official_source": series.official.source,
                "t0": series.times[0].isoformat(),
                "t1": series.times[-1].isoformat(),
                "gap": series.gap_after.isoformat() if series.gap_after else "",
                "close": series.official.close,
                "prev": series.official.prev_close,
                "turnover_k": series.official.turnover_k,
                "avg": series.official.avg_price,
                "amp": series.official.amplitude_pct,
                "qavg": series.official.q_avg_vol_lots,
                "w52h": series.official.w52_high,
                "w52l": series.official.w52_low,
                "notices": series.notices,
            }
        )
        print(
            f"[ok] {sid} {name} n={len(series.closes)} "
            f"{series.times[0].strftime('%H:%M')}→{series.times[-1].strftime('%H:%M')} "
            f"off={series.official.close} -> {out_path}"
        )

    manifest = os.path.join(out_dir, f"{args.prefix}-manifest-20261029.txt")
    with open(manifest, "w", encoding="utf-8") as f:
        f.write(f"as_of_taipei={datetime.now(TZ).isoformat()}\n")
        f.write(f"version={args.prefix}\n")
        f.write("not_buy_signal=1\n")
        f.write("phone_wired=0\n")
        for r in results:
            f.write(
                f"{r['stock_id']}\t{r['name']}\t{r['market']}\tok={int(r['ok'])}\t"
                f"n={r.get('n', 0)}\t{r['path']}\n"
            )
            for n in r.get("notices") or []:
                f.write(f"  notice\t{n}\n")
    with open(os.path.join(out_dir, f"{args.prefix}-notices-20261029.json"), "w", encoding="utf-8") as f:
        json.dump(notices_all, f, ensure_ascii=False, indent=2)
    print(f"[manifest] {manifest}")
    return 0 if all(r["ok"] for r in results) else 2


if __name__ == "__main__":
    raise SystemExit(main())
