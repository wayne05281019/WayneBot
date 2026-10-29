#!/usr/bin/env python3
"""Preview-only v14：今日開→收墨線臉（查股第 5 張候選）。

對齊 docs/intraday-v14-tighten-gap-20261029.md：
時間戳旁黑標 → 頭欄空白消 → 十二格上移 → 價圖加高；
較昨日膠囊只漲停紅底／跌停綠底；今量額 ± 左右排；
主圖智能標＝方案 B（實心原點＋短虛線＋淨空完整標；含事件／量％）；
均＝現可併；不准線上大方框互壓。

格子三排維持 v12 欄位；框共線／真分量柱紅綠／12.4×9.35／興櫃 15:00 維持。
不准假資料、不准接話筒／合 main。
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
from datetime import datetime, timedelta, timezone
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

# v13 十檔抽測（含 2383／3595／6274 FAIL 錨＋八檔跨市）
PREVIEW_V13_SYMBOLS: Tuple[Tuple[str, str, str], ...] = (
    ("2383", "台光電", "TW"),
    ("3595", "山太士", "EM"),
    ("6274", "台燿", "TWO"),
    ("2330", "台積電", "TW"),
    ("2454", "聯發科", "TW"),
    ("2303", "聯電", "TW"),
    ("1303", "南亞", "TW"),
    ("3105", "穩懋", "TWO"),
    ("3081", "聯亞", "TWO"),
    ("7853", "政美應用", "EM"),
)

_SLUG = {
    "3595": "shantashi",
    "7853": "zhengmei",
    "2383": "taiguangdian",
    "6274": "taiyao",
    "1303": "nanya",
    "2330": "tsmc",
    "2454": "mtk",
    "2303": "umc",
    "3105": "winf",
    "3081": "lianya",
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
    # v10+ 加欄（無真數＝None → 畫面「—」；不准假湊）
    prev_volume_lots: Optional[float] = None  # 昨成交量（張）
    prev_turnover_k: Optional[float] = None  # 昨成交金額（千元）
    trade_count: Optional[int] = None  # 保留欄；v12 格改昨額，畫面不用
    limit_up: Optional[float] = None  # v12 取消停板格
    limit_down: Optional[float] = None


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


def _session_end_hm(market: str) -> int:
    return 1500 if str(market).upper() == "EM" else 1330


def _densify_1m_path(
    times: List[datetime],
    opens: List[float],
    highs: List[float],
    lows: List[float],
    closes: List[float],
    vols: List[float],
    *,
    ymd: str,
    sess_end_hm: int,
) -> Dict[str, List[Any]]:
    """盤中缺分：用前一分收盤平鋪（量 0）；不跨日、不捏新價。"""
    if len(closes) < 2:
        return {
            "times": times, "opens": opens, "highs": highs,
            "lows": lows, "closes": closes, "volumes_lots": vols,
        }
    by_min: Dict[datetime, Tuple[float, float, float, float, float]] = {}
    for t, o, h, lo, c, v in zip(times, opens, highs, lows, closes, vols):
        key = t.replace(second=0, microsecond=0)
        by_min[key] = (float(o), float(h), float(lo), float(c), float(v))
    y, m, d = int(ymd[:4]), int(ymd[4:6]), int(ymd[6:8])
    start = datetime(y, m, d, 9, 0, tzinfo=TZ)
    end_h, end_m = divmod(sess_end_hm, 100)
    end = datetime(y, m, d, end_h, end_m, tzinfo=TZ)
    out_t: List[datetime] = []
    out_o: List[float] = []
    out_h: List[float] = []
    out_l: List[float] = []
    out_c: List[float] = []
    out_v: List[float] = []
    cur = start
    last_c: Optional[float] = None
    # 先對齊到第一筆真資料，不往前捏開盤前空檔
    first_key = min(by_min.keys())
    while cur < first_key:
        cur += timedelta(minutes=1)
    while cur <= end:
        if cur in by_min:
            o, h, lo, c, v = by_min[cur]
            last_c = c
            out_t.append(cur)
            out_o.append(o)
            out_h.append(h)
            out_l.append(lo)
            out_c.append(c)
            out_v.append(v)
        elif last_c is not None:
            out_t.append(cur)
            out_o.append(last_c)
            out_h.append(last_c)
            out_l.append(last_c)
            out_c.append(last_c)
            out_v.append(0.0)
        cur += timedelta(minutes=1)
    return {
        "times": out_t,
        "opens": out_o,
        "highs": out_h,
        "lows": out_l,
        "closes": out_c,
        "volumes_lots": out_v,
    }


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
    sess_end = _session_end_hm(market)
    y, m, d = int(ymd[:4]), int(ymd[4:6]), int(ymd[6:8])
    # 台北開盤前後窗 → UTC epoch，逼 Yahoo 吐完整當日 1m
    p1 = int(datetime(y, m, d, 8, 50, tzinfo=TZ).timestamp())
    p2 = int(datetime(y, m, d, 15, 10, tzinfo=TZ).timestamp())
    for yid in _yahoo_ids(stock_id, market, db_path):
        urls = [
            (
                f"https://query1.finance.yahoo.com/v8/finance/chart/{url_quote(yid, safe='')}"
                f"?interval=1m&period1={p1}&period2={p2}"
            ),
            (
                f"https://query1.finance.yahoo.com/v8/finance/chart/{url_quote(yid, safe='')}"
                f"?interval=1m&range=1d"
            ),
        ]
        for url in urls:
            try:
                resp = requests.get(url, timeout=15, headers=_ua())
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
                dense = _densify_1m_path(
                    times, opens, highs, lows, closes, vols,
                    ymd=ymd, sess_end_hm=sess_end,
                )
                return {
                    "yahoo_symbol": yid,
                    "times": dense["times"],
                    "closes": dense["closes"],
                    "volumes_lots": dense["volumes_lots"],
                    "opens": dense["opens"],
                    "highs": dense["highs"],
                    "lows": dense["lows"],
                    "source": f"yahoo:chart:1m:{yid}",
                    "raw_n": len(closes),
                    "dense_n": len(dense["closes"]),
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
    dense = _densify_1m_path(
        list(agg["times"]), list(agg["opens"]), list(agg["highs"]),
        list(agg["lows"]), list(agg["closes"]), list(agg["volumes_lots"]),
        ymd=ymd, sess_end_hm=1500,
    )
    n_after = sum(1 for t in dense["times"] if t.hour * 100 + t.minute > 1330)
    return {
        "yahoo_symbol": yid,
        "times": dense["times"],
        "closes": dense["closes"],
        "volumes_lots": dense["volumes_lots"],
        "opens": dense["opens"],
        "highs": dense["highs"],
        "lows": dense["lows"],
        "source": f"yahoo:priceByTimes:1m:{yid}",
        "prints_n": len(ordered),
        "pages": pages,
        "raw_1m_n": len(agg["closes"]),
        "dense_n": len(dense["closes"]),
        "n_after_1330": n_after,
        "path_min": min(dense["lows"]),
        "path_max": max(dense["highs"]),
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


def _prev_day_vol_turn_db(
    stock_id: str, market: str, db_path: str, *, ymd: str
) -> Tuple[Optional[float], Optional[float]]:
    """上一開市日官方量（張）＋額（千元）。庫無則 (None, None)；不准編造。"""
    if not db_path or not os.path.isfile(db_path):
        return None, None
    table = "emerging_quotes" if str(market).upper() == "EM" else "daily_quotes"
    try:
        conn = sqlite3.connect(db_path, timeout=8.0)
        try:
            row = conn.execute(
                f"""
                SELECT volume, turnover_k FROM {table}
                WHERE stock_id=?
                  AND REPLACE(CAST(date AS TEXT),'-','') < ?
                ORDER BY REPLACE(CAST(date AS TEXT),'-','') DESC
                LIMIT 1
                """,
                (stock_id, ymd),
            ).fetchone()
        finally:
            conn.close()
    except sqlite3.Error:
        return None, None
    if not row:
        return None, None
    vol: Optional[float] = None
    to_k: Optional[float] = None
    try:
        if row[0] is not None and float(row[0]) > 0:
            vol = float(row[0])
    except (TypeError, ValueError):
        vol = None
    try:
        if row[1] is not None and float(row[1]) > 0:
            to_k = float(row[1])
    except (TypeError, ValueError):
        to_k = None
    return vol, to_k


def _prev_volume_lots_db(
    stock_id: str, market: str, db_path: str, *, ymd: str
) -> Optional[float]:
    """相容舊呼叫：只回昨量。"""
    vol, _to = _prev_day_vol_turn_db(stock_id, market, db_path, ymd=ymd)
    return vol


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
    # 興櫃：昨量／昨額＝庫內上一開市日；無則格「—」（不准捏）
    prev_vol, prev_to = _prev_day_vol_turn_db(stock_id, "EM", db_path, ymd=ymd)
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
        prev_volume_lots=prev_vol,
        prev_turnover_k=prev_to,
        trade_count=None,
        limit_up=None,
        limit_down=None,
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
    rows = list(data.get("data") or [])
    row = None
    row_idx = -1
    for i, r in enumerate(rows):
        d0 = str(r[0]).replace("／", "/")
        if d0.endswith(mmdd) or mmdd in d0:
            row = r
            row_idx = i
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
    # 昨量／昨額：同月 STOCK_DAY 上一列；缺則庫（不准捏）
    prev_vol: Optional[float] = None
    prev_to: Optional[float] = None
    if row_idx > 0:
        try:
            prev_vol = _f(rows[row_idx - 1][1]) / 1000.0
            if prev_vol <= 0:
                prev_vol = None
        except (TypeError, ValueError, IndexError):
            prev_vol = None
        try:
            prev_to = _f(rows[row_idx - 1][2]) / 1000.0
            if prev_to <= 0:
                prev_to = None
        except (TypeError, ValueError, IndexError):
            prev_to = None
    if prev_vol is None or prev_to is None:
        db_vol, db_to = _prev_day_vol_turn_db(stock_id, "TW", db_path, ymd=ymd)
        if prev_vol is None:
            prev_vol = db_vol
        if prev_to is None:
            prev_to = db_to
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
        prev_volume_lots=prev_vol,
        prev_turnover_k=prev_to,
        trade_count=None,
        limit_up=None,
        limit_down=None,
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
    # 昨量／昨額：庫內上一開市日（openapi 僅當日快照；無則 —）
    prev_vol, prev_to = _prev_day_vol_turn_db(stock_id, "TWO", db_path, ymd=ymd)
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
        prev_volume_lots=prev_vol,
        prev_turnover_k=prev_to,
        trade_count=None,
        limit_up=None,
        limit_down=None,
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


def _rects_overlap(
    a: Tuple[float, float, float, float],
    b: Tuple[float, float, float, float],
    *,
    pad: float = 0.0,
) -> bool:
    """軸座標盒 (x0,x1,y0,y1) 是否互壓。"""
    return not (
        a[1] + pad < b[0]
        or b[1] + pad < a[0]
        or a[3] + pad < b[2]
        or b[3] + pad < a[2]
    )


def _estimate_label_rect(
    cx: float, cy: float, text: str, *, fs: float, x_span: float, y_span: float, kind: str
) -> Tuple[float, float, float, float]:
    """粗估標盒（資料座標）。dot＝實心原點；chip＝舊雙行圓章；full＝完整標。"""
    n = max(len(text), 1)
    if kind == "dot":
        # 實心原點：極小佔位
        half_x = max(x_span * 0.008, 2.2)
        half_y = max(y_span * 0.008, abs(cy) * 0.0018, 0.35)
    elif kind == "chip":
        half_x = max(x_span * 0.028, 6.5)
        half_y = max(y_span * 0.028, abs(cy) * 0.0045, 1.2)
    else:
        half_x = max(x_span * (0.018 + 0.007 * min(n, 14)), 10.0)
        half_y = max(y_span * (0.022 + 0.001 * max(fs - 8.0, 0)), abs(cy) * 0.0035, 1.0)
    return (cx - half_x, cx + half_x, cy - half_y, cy + half_y)


def _path_hits_rect(
    xs, ys, rect: Tuple[float, float, float, float], *, y_pad: float
) -> bool:
    """價折線是否穿進標盒（圓章錨點允許貼線，完整標不准）。"""
    import numpy as np

    x0, x1, y0, y1 = rect
    arr_x = np.asarray(xs, dtype=float)
    arr_y = np.asarray(ys, dtype=float)
    mask = (arr_x >= x0) & (arr_x <= x1)
    if not np.any(mask):
        return False
    for y in arr_y[mask]:
        if (y0 - y_pad) <= float(y) <= (y1 + y_pad):
            return True
    return False


def _level_anchors(
    xs, ys, highs, lows, opens, off: OfficialDay
) -> List[Tuple[str, str, float, float, str]]:
    """回 (短名, 完整國字, x, y_price, color_key)。錨在走線對應點。

    v14 方案 B：錨＝實心原點（無字）；完整標＝`撐 4,935`／`壓 x`／`開盤 x`／`均 x`／`現價 x`。
    均價與現價顯示同價 → 併成「均＝現」一標。
    """
    import numpy as np

    xa = np.asarray(xs, dtype=float)
    ya = np.asarray(ys, dtype=float)
    ha = np.asarray(highs, dtype=float)
    la = np.asarray(lows, dtype=float)
    n = len(ya)
    out: List[Tuple[str, str, float, float, str]] = []
    if n == 0:
        return out
    i_hi = int(np.nanargmax(ha)) if np.any(np.isfinite(ha)) else int(np.argmax(ya))
    out.append(("壓", "壓", float(xa[i_hi]), float(off.high), "up"))
    out.append(("開", "開盤", float(xa[0]), float(off.open), "open"))
    i_lo = int(np.nanargmin(la)) if np.any(np.isfinite(la)) else int(np.argmin(ya))
    out.append(("撐", "撐", float(xa[i_lo]), float(off.low), "dn"))
    close_px = float(off.close)
    avg = float(off.avg_price) if off.avg_price and float(off.avg_price) > 0 else None
    merge_avg_close = (
        avg is not None and _fmt_face(avg) == _fmt_face(close_px)
    )
    if merge_avg_close:
        out.append(("均", "均＝現", float(xa[-1]), close_px, "close"))
    else:
        out.append(("現", "現價", float(xa[-1]), close_px, "close"))
        if avg is not None:
            i_avg = int(np.argmin(np.abs(ya - avg)))
            out.append(("均", "均", float(xa[i_avg]), avg, "avg"))
    return out


def _collect_event_marks(
    series: PathSeries, xs, ys, prev: float
) -> List[Tuple[float, float, str, str]]:
    """破昨收／急殺／爆量候選：(x, y, 國字, color_key)。尚未避讓。"""
    import numpy as np

    marks: List[Tuple[float, float, str, str]] = []
    for x, y in zip(xs, ys):
        if float(y) < prev:
            marks.append((float(x), float(y), "破昨收", "dn"))
            break
    if len(ys) >= 8:
        gap_cut = None
        if series.gap_after is not None:
            gap_cut = (series.gap_after.hour - 9) * 60 + series.gap_after.minute
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
            marks.append((best[1], best[2], "急殺", "dn"))
    vs = np.asarray(series.volumes_lots, dtype=float)
    if len(vs) and float(np.max(vs)) > 0:
        med = float(np.median(vs[vs > 0])) if np.any(vs > 0) else 0.0
        i = int(np.argmax(vs))
        if med > 0 and vs[i] >= med * 6:
            marks.append(
                (
                    float(xs[i]),
                    float(ys[i]),
                    "爆量",
                    "up" if ys[i] >= prev else "dn",
                )
            )
    # 近鄰去重（同名／同窗）
    kept: List[Tuple[float, float, str, str]] = []
    for m in marks:
        if any(abs(m[0] - k[0]) < 14 and m[2] == k[2] for k in kept):
            continue
        kept.append(m)
    return kept[:3]


def _paint_smart_level_labels(
    ax,
    xs,
    ys,
    highs,
    lows,
    opens,
    off: OfficialDay,
    *,
    close_col: str,
    up: str,
    dn: str,
    ink: str,
    paper: str,
    events: Optional[Sequence[Tuple[float, float, str, str]]] = None,
) -> Dict[str, Any]:
    """v14 方案 B：實心原點錨＋短虛線淨空完整標；事件標同閘避讓。

    硬閘：完整標（含破昨收／爆量／急殺）互不壓、不壓價線；必要位階標不省略。
    均＝現已併則 required 少 1。不准線上大方框。
    """
    from ink_chart_theme import fp
    import numpy as np

    x0, x1 = ax.get_xlim()
    y0, y1 = ax.get_ylim()
    x_span = max(float(x1 - x0), 1.0)
    y_span = max(float(y1 - y0), 1.0)
    color_map = {
        "up": up,
        "dn": dn,
        "open": "#5C5C5C",
        "close": close_col,
        "avg": "#5C6BC0",
        "ink": ink,
    }

    anchors = _level_anchors(xs, ys, highs, lows, opens, off)
    # 同價合併顯示仍各留標，但錨 x 必須分開（開／均／現常見擠價）
    used_x: List[float] = []
    min_x_sep = max(x_span * 0.06, 12.0)
    adj_anchors: List[Tuple[str, str, float, float, str]] = []
    for short, full, ax_, ay_, ck in anchors:
        xx = float(ax_)
        for _ in range(10):
            if all(abs(xx - u) >= min_x_sep for u in used_x):
                break
            # 往較空側推
            xx = xx + min_x_sep if xx < (x0 + x1) * 0.5 else xx - min_x_sep
            xx = min(max(xx, x0 + x_span * 0.04), x1 - x_span * 0.04)
        used_x.append(xx)
        adj_anchors.append((short, full, xx, float(ay_), ck))

    # 完整標候選 offset（資料座標）：短虛線「一點點」
    def _offset_cands(axp: float, ayp: float) -> List[Tuple[float, float]]:
        dxs = [x_span * 0.10, x_span * 0.14, -x_span * 0.10, -x_span * 0.14,
               x_span * 0.18, -x_span * 0.18, x_span * 0.07, -x_span * 0.07]
        dys = [y_span * 0.08, -y_span * 0.08, y_span * 0.12, -y_span * 0.12,
               y_span * 0.05, -y_span * 0.05, y_span * 0.16, -y_span * 0.16]
        out: List[Tuple[float, float]] = []
        for dx in dxs:
            for dy in dys:
                out.append((axp + dx, ayp + dy))
        # 偏好：錨在左半→標往右上／右下；右半→往左
        out.sort(key=lambda p: (
            0 if (axp < (x0 + x1) * 0.55 and p[0] > axp) or (axp >= (x0 + x1) * 0.55 and p[0] < axp) else 1,
            abs(p[1] - ayp) + abs(p[0] - axp) * 0.3,
        ))
        return out

    occupied: List[Tuple[float, float, float, float]] = []
    placed_meta: List[Dict[str, Any]] = []
    path_pad = y_span * 0.012
    box_pad = y_span * 0.008
    # 先只算位，全部定案再畫（方便互壓後 nudge）
    pending: List[Dict[str, Any]] = []

    for idx, (short, full, axp, ayp, ck) in enumerate(adj_anchors):
        col = color_map.get(ck, ink)
        px = _fmt_face(ayp)
        # v14 方案 B：錨＝實心原點（無字）；完整標只在淨空出現一次
        chip_txt = ""
        full_txt = f"{full} {px}"
        chip_ay = float(ayp)
        chip_rect = _estimate_label_rect(
            axp, chip_ay, "·", fs=6.0, x_span=x_span, y_span=y_span, kind="dot"
        )
        # 原點鎖在走線價位，不上下漂移（漂移會離錨失真）
        _ = idx  # 保留交錯偏好用

        # 完整標：字級可縮；掃淨空；上下交錯偏好
        prefer_up = idx % 2 == 0
        full_fs_options = (9.5, 8.5, 7.5, 7.0)
        chosen: Optional[Tuple[float, float, float, Tuple[float, float, float, float]]] = None
        cands = _offset_cands(axp, chip_ay)
        if prefer_up:
            cands = sorted(cands, key=lambda p: (0 if p[1] >= chip_ay else 1, abs(p[1] - chip_ay)))
        else:
            cands = sorted(cands, key=lambda p: (0 if p[1] < chip_ay else 1, abs(p[1] - chip_ay)))
        for full_fs in full_fs_options:
            for lx, ly in cands:
                if not (x0 + x_span * 0.02 <= lx <= x1 - x_span * 0.02):
                    continue
                if not (y0 + y_span * 0.03 <= ly <= y1 - y_span * 0.03):
                    continue
                dist = ((lx - axp) ** 2 + ((ly - chip_ay) / max(y_span / x_span, 1e-6)) ** 2) ** 0.5
                if dist > x_span * 0.32:
                    continue
                rect = _estimate_label_rect(
                    lx, ly, full_txt, fs=full_fs, x_span=x_span, y_span=y_span, kind="full"
                )
                if any(_rects_overlap(rect, o, pad=box_pad) for o in occupied):
                    continue
                if _rects_overlap(rect, chip_rect, pad=box_pad):
                    continue
                if _path_hits_rect(xs, ys, rect, y_pad=path_pad):
                    continue
                chosen = (lx, ly, full_fs, rect)
                break
            if chosen is not None:
                break

        if chosen is None:
            full_fs = 7.0
            fallback = None
            best_pen = 1e18
            for lx, ly in cands:
                lx = min(max(lx, x0 + x_span * 0.02), x1 - x_span * 0.02)
                ly = min(max(ly, y0 + y_span * 0.03), y1 - y_span * 0.03)
                # 強制拉開：依序上下左右大步
                for extra_dy in (0.0, y_span * 0.10, -y_span * 0.10, y_span * 0.16, -y_span * 0.16):
                    ly2 = min(max(ly + extra_dy, y0 + y_span * 0.03), y1 - y_span * 0.03)
                    rect = _estimate_label_rect(
                        lx, ly2, full_txt, fs=full_fs, x_span=x_span, y_span=y_span, kind="full"
                    )
                    ov = sum(1 for o in occupied if _rects_overlap(rect, o, pad=box_pad * 0.5))
                    ph = 1 if _path_hits_rect(xs, ys, rect, y_pad=path_pad * 0.4) else 0
                    pen = ov * 20 + ph * 8 + abs(lx - axp) / x_span
                    if pen < best_pen:
                        best_pen = pen
                        fallback = (lx, ly2, full_fs, rect)
            chosen = fallback

        assert chosen is not None
        lx, ly, full_fs, full_rect = chosen
        occupied.append(chip_rect)
        occupied.append(full_rect)
        pending.append(
            {
                "kind": "level",
                "short": short,
                "full": full,
                "full_txt": full_txt,
                "chip_txt": "",
                "price": float(ayp),
                "col": col,
                "anchor": (float(axp), float(chip_ay)),
                "label": (float(lx), float(ly)),
                "fs": full_fs,
                "chip_fs": 0.0,
                "chip_rect": chip_rect,
                "full_rect": full_rect,
            }
        )

    # v14 方案 B：破昨收／爆量／急殺＝實心原點＋虛線完整標（同閘避讓）
    for eidx, (ex, ey, elab, eck) in enumerate(list(events or [])):
        ecol = color_map.get(eck, ink)
        full_txt = str(elab)
        chip_ay = float(ey)
        chip_rect = _estimate_label_rect(
            float(ex), chip_ay, "·", fs=6.0, x_span=x_span, y_span=y_span, kind="dot"
        )
        prefer_up = eidx % 2 == 1
        full_fs_options = (11.0, 10.0, 9.0, 8.0, 7.0)
        chosen_e: Optional[Tuple[float, float, float, Tuple[float, float, float, float]]] = None
        cands = _offset_cands(float(ex), float(ey))
        if prefer_up:
            cands = sorted(cands, key=lambda p: (0 if p[1] >= ey else 1, abs(p[1] - ey)))
        else:
            cands = sorted(cands, key=lambda p: (0 if p[1] < ey else 1, abs(p[1] - ey)))
        for full_fs in full_fs_options:
            for lx, ly in cands:
                if not (x0 + x_span * 0.02 <= lx <= x1 - x_span * 0.02):
                    continue
                if not (y0 + y_span * 0.03 <= ly <= y1 - y_span * 0.03):
                    continue
                rect = _estimate_label_rect(
                    lx, ly, full_txt, fs=full_fs, x_span=x_span, y_span=y_span, kind="full"
                )
                if any(_rects_overlap(rect, o, pad=box_pad) for o in occupied):
                    continue
                if _rects_overlap(rect, chip_rect, pad=box_pad):
                    continue
                if _path_hits_rect(xs, ys, rect, y_pad=path_pad):
                    continue
                chosen_e = (lx, ly, full_fs, rect)
                break
            if chosen_e is not None:
                break
        if chosen_e is None:
            full_fs = 7.0
            best_pen = 1e18
            fallback_e = None
            for lx, ly in cands:
                for extra_dy in (0.0, y_span * 0.12, -y_span * 0.12, y_span * 0.20, -y_span * 0.20):
                    for extra_dx in (0.0, x_span * 0.10, -x_span * 0.10, x_span * 0.16, -x_span * 0.16):
                        lx2 = min(max(lx + extra_dx, x0 + x_span * 0.02), x1 - x_span * 0.02)
                        ly2 = min(max(ly + extra_dy, y0 + y_span * 0.03), y1 - y_span * 0.03)
                        rect = _estimate_label_rect(
                            lx2, ly2, full_txt, fs=full_fs, x_span=x_span, y_span=y_span, kind="full"
                        )
                        ov = sum(1 for o in occupied if _rects_overlap(rect, o, pad=box_pad * 0.5))
                        ph = 1 if _path_hits_rect(xs, ys, rect, y_pad=path_pad * 0.4) else 0
                        pen = ov * 20 + ph * 8 + abs(lx2 - ex) / x_span
                        if pen < best_pen:
                            best_pen = pen
                            fallback_e = (lx2, ly2, full_fs, rect)
            chosen_e = fallback_e
        if chosen_e is None:
            continue
        lx, ly, full_fs, full_rect = chosen_e
        occupied.append(chip_rect)
        occupied.append(full_rect)
        pending.append(
            {
                "kind": "event",
                "short": full_txt[:1],
                "full": full_txt,
                "full_txt": full_txt,
                "chip_txt": "",
                "price": float(ey),
                "col": ecol,
                "anchor": (float(ex), float(chip_ay)),
                "label": (float(lx), float(ly)),
                "fs": full_fs,
                "chip_fs": 0.0,
                "chip_rect": chip_rect,
                "full_rect": full_rect,
            }
        )

    def _try_set_full(k: int, lx: float, ly: float) -> bool:
        rect2 = _estimate_label_rect(
            lx, ly, pending[k]["full_txt"],
            fs=pending[k]["fs"], x_span=x_span, y_span=y_span, kind="full",
        )
        if _rects_overlap(rect2, pending[k]["chip_rect"], pad=box_pad * 0.3):
            return False
        for t, p in enumerate(pending):
            if t == k:
                continue
            if _rects_overlap(rect2, p["full_rect"], pad=box_pad * 0.5):
                return False
            if _rects_overlap(rect2, p["chip_rect"], pad=box_pad * 0.3):
                return False
        if _path_hits_rect(xs, ys, rect2, y_pad=path_pad * 0.45):
            return False
        pending[k]["label"] = (lx, ly)
        pending[k]["full_rect"] = rect2
        return True

    # 安置後 nudge：互壓推開；壓線則往外緣（軸頂／底淨空）撤離
    def _nudge_fulls() -> None:
        for _round in range(36):
            moved = False
            # 1) 互壓（位階＋事件同一閘）
            for i in range(len(pending)):
                for j in range(i + 1, len(pending)):
                    if not _rects_overlap(
                        pending[i]["full_rect"], pending[j]["full_rect"], pad=box_pad * 0.5
                    ):
                        continue
                    step = y_span * 0.04
                    order = (i, j) if pending[i]["price"] >= pending[j]["price"] else (j, i)
                    for k, sign in ((order[0], 1.0), (order[1], -1.0)):
                        lx, ly = pending[k]["label"]
                        ly2 = min(max(ly + sign * step, y0 + y_span * 0.03), y1 - y_span * 0.03)
                        if _try_set_full(k, lx, ly2):
                            moved = True
                        else:
                            # 再試水平錯開（事件黏角常見）
                            lx2 = min(
                                max(lx + sign * x_span * 0.05, x0 + x_span * 0.02),
                                x1 - x_span * 0.02,
                            )
                            if _try_set_full(k, lx2, ly2):
                                moved = True
            # 2) 壓價線 → 往軸頂／底淨空
            for k, p in enumerate(pending):
                if not _path_hits_rect(xs, ys, p["full_rect"], y_pad=path_pad * 0.45):
                    continue
                lx, ly = p["label"]
                targets = [
                    (lx, y1 - y_span * 0.06),
                    (lx, y0 + y_span * 0.06),
                    (lx + x_span * 0.06, y1 - y_span * 0.08),
                    (lx - x_span * 0.06, y0 + y_span * 0.08),
                    (lx + x_span * 0.08, ly + y_span * 0.06),
                    (lx - x_span * 0.08, ly - y_span * 0.06),
                ]
                for tx, ty in targets:
                    tx = min(max(tx, x0 + x_span * 0.02), x1 - x_span * 0.02)
                    ty = min(max(ty, y0 + y_span * 0.03), y1 - y_span * 0.03)
                    if _try_set_full(k, tx, ty):
                        moved = True
                        break
            if not moved:
                break

    _nudge_fulls()

    # 下筆：實心原點 → 短虛線 → 淨空完整標（方案 B；不准線上大方框）
    for p in pending:
        axp, ayp = p["anchor"]
        lx, ly = p["label"]
        col = p["col"]
        ax.plot(
            [axp, lx], [ayp, ly],
            linestyle=(0, (2, 2)), color=col, linewidth=0.85, alpha=0.85, zorder=9,
            solid_capstyle="round",
        )
        ax.plot(
            [axp], [ayp], "o",
            color=col, markersize=5.2, markeredgecolor=paper,
            markeredgewidth=0.7, zorder=11, clip_on=False,
        )
        if p.get("kind") == "event":
            face, edge, tc = "#FFF8E7", col, ink
        else:
            face, edge, tc = paper, col, col
        ax.text(
            lx, ly, p["full_txt"],
            ha="center", va="center",
            fontproperties=fp(p["fs"], True), color=tc, zorder=12, clip_on=False,
            bbox=dict(
                boxstyle="square,pad=0.18", facecolor=face, edgecolor=edge,
                linewidth=0.9, alpha=0.96,
            ),
        )
        placed_meta.append(p)

    level_meta = [m for m in placed_meta if m.get("kind") == "level"]
    event_meta = [m for m in placed_meta if m.get("kind") == "event"]
    full_rects = [m["full_rect"] for m in placed_meta]
    overlap_n = 0
    for i in range(len(full_rects)):
        for j in range(i + 1, len(full_rects)):
            if _rects_overlap(full_rects[i], full_rects[j], pad=box_pad * 0.25):
                overlap_n += 1
    path_hits = sum(
        1 for r in full_rects if _path_hits_rect(xs, ys, r, y_pad=path_pad * 0.5)
    )
    # 均＝現已併 → required=4；否則有均價=5、無均=4
    has_avg = bool(off.avg_price and float(off.avg_price) > 0)
    merged_avg = any(str(m.get("full") or "").startswith("均＝現") for m in level_meta)
    required = 4 if (not has_avg or merged_avg) else 5
    gate = {
        "n_labels": len(level_meta),
        "n_events": len(event_meta),
        "required": required,
        "full_overlap_pairs": overlap_n,
        "full_path_hits": path_hits,
        "merged_avg_close": merged_avg,
        "pass": bool(
            len(level_meta) >= required and overlap_n == 0 and path_hits == 0
        ),
        "labels": [
            {
                "kind": m.get("kind"),
                "short": m["short"],
                "full": m["full"],
                "price": m["price"],
                "fs": m["fs"],
            }
            for m in placed_meta
        ],
    }
    return gate


def _bars_hit_rect(
    xs,
    bar_tops,
    rect: Tuple[float, float, float, float],
    *,
    y_pad: float = 0.0,
) -> bool:
    """量柱頂是否穿進標盒（量％智能閘）。柱＝[0, top]；標底低於柱頂＝壓。"""
    import numpy as np

    rx0, rx1, ry0, ry1 = rect
    arr_x = np.asarray(xs, dtype=float)
    arr_t = np.asarray(bar_tops, dtype=float)
    # 略擴 x 窗（柱有寬度）
    pad_x = max((rx1 - rx0) * 0.15, 0.8)
    mask = (arr_x >= rx0 - pad_x) & (arr_x <= rx1 + pad_x) & (arr_t > 0)
    if not np.any(mask):
        return False
    max_top = float(np.max(arr_t[mask]))
    # 標盒底緣若仍在柱頂之下（含 pad）→ 壓柱
    return ry0 <= max_top + y_pad


def _paint_vol_ratio_smart(
    vol_ax,
    xs,
    bar_disp,
    vol_ratio: float,
    *,
    up: str,
    dn: str,
    ink: str,
    paper: str,
) -> Dict[str, Any]:
    """量／季均％：方案 B 實心原點錨高峰＋短虛線拉淨空「N%」；完整標不准壓柱。"""
    from ink_chart_theme import fp
    import numpy as np

    if vol_ratio is None or vol_ratio <= 0:
        return {"pass": True, "skipped": True}
    pct = int(round(float(vol_ratio) * 100))
    col = dn if vol_ratio >= 1 else up
    full_txt = f"{pct}%"
    xa = np.asarray(xs, dtype=float)
    ba = np.asarray(bar_disp, dtype=float)
    if len(xa) == 0 or len(ba) == 0 or float(np.max(ba)) <= 0:
        return {"pass": True, "skipped": True}
    i_peak = int(np.argmax(ba))
    axp = float(xa[i_peak])
    ayp = float(ba[i_peak])
    x0, x1 = vol_ax.get_xlim()
    y0, y1 = vol_ax.get_ylim()
    x_span = max(float(x1 - x0), 1.0)
    y_span = max(float(y1 - y0), 1e-6)
    # 實心原點貼峰頂略上（允許近柱；完整標必須離柱）
    chip_ay = min(ayp + y_span * 0.04, y1 - y_span * 0.10)
    chip_rect = _estimate_label_rect(
        axp, chip_ay, "·", fs=6.0, x_span=x_span, y_span=y_span, kind="dot"
    )
    # 完整標：只掃「高於全日最高柱」的帶（ylim 有 ~8% 頭頂），左右錯開峰
    max_bar = float(np.max(ba))
    clear_y0 = max_bar + y_span * 0.04  # 標底必須高於最高柱
    # 若頭頂不夠，略抬 ylim 由呼叫端負責；此處仍盡量貼頂
    top_band = [
        y1 - y_span * 0.08,
        y1 - y_span * 0.14,
        y1 - y_span * 0.20,
        max(clear_y0 + y_span * 0.02, y1 - y_span * 0.28),
    ]
    x_opts = [
        x0 + x_span * 0.10,
        x1 - x_span * 0.10,
        x0 + x_span * 0.22,
        x1 - x_span * 0.22,
        axp - x_span * 0.28,
        axp + x_span * 0.28,
        x0 + x_span * 0.35,
        x1 - x_span * 0.35,
    ]
    cands: List[Tuple[float, float]] = [(x, y) for y in top_band for x in x_opts]
    chosen = None
    for full_fs in (10.0, 9.0, 8.0, 7.0):
        for lx, ly in cands:
            lx = min(max(lx, x0 + x_span * 0.04), x1 - x_span * 0.04)
            ly = min(max(ly, clear_y0), y1 - y_span * 0.04)
            rect = _estimate_label_rect(
                lx, ly, full_txt, fs=full_fs, x_span=x_span, y_span=y_span, kind="full"
            )
            if rect[2] < clear_y0:  # 標底仍低於最高柱
                continue
            if _rects_overlap(rect, chip_rect, pad=y_span * 0.02):
                continue
            if _bars_hit_rect(xa, ba, rect, y_pad=y_span * 0.02):
                continue
            chosen = (lx, ly, full_fs, rect)
            break
        if chosen is not None:
            break
    if chosen is None:
        # 強制軸頂遠角，且標底鎖在 clear_y0 之上
        for lx in (x0 + x_span * 0.08, x1 - x_span * 0.08, x0 + x_span * 0.5):
            ly = max(clear_y0 + y_span * 0.02, y1 - y_span * 0.06)
            full_fs = 8.0
            rect = _estimate_label_rect(
                lx, ly, full_txt, fs=full_fs, x_span=x_span, y_span=y_span, kind="full"
            )
            # 若估盒仍壓柱，整盒上移
            if rect[2] < clear_y0:
                dy = clear_y0 - rect[2] + y_span * 0.01
                ly = min(ly + dy, y1 - y_span * 0.03)
                rect = _estimate_label_rect(
                    lx, ly, full_txt, fs=full_fs, x_span=x_span, y_span=y_span, kind="full"
                )
            if not _bars_hit_rect(xa, ba, rect, y_pad=y_span * 0.015):
                chosen = (lx, ly, full_fs, rect)
                break
        if chosen is None:
            lx = x1 - x_span * 0.08
            ly = min(max(clear_y0 + y_span * 0.05, y1 - y_span * 0.05), y1 - y_span * 0.03)
            full_fs = 7.5
            rect = _estimate_label_rect(
                lx, ly, full_txt, fs=full_fs, x_span=x_span, y_span=y_span, kind="full"
            )
            chosen = (lx, ly, full_fs, rect)
    lx, ly, full_fs, full_rect = chosen
    vol_ax.plot(
        [axp, lx], [chip_ay, ly],
        linestyle=(0, (2, 2)), color=col, linewidth=0.85, alpha=0.9, zorder=9,
        solid_capstyle="round",
    )
    vol_ax.plot(
        [axp], [chip_ay], "o",
        color=col, markersize=5.0, markeredgecolor=paper,
        markeredgewidth=0.7, zorder=11, clip_on=False,
    )
    vol_ax.text(
        lx, ly, full_txt,
        ha="center", va="center",
        fontproperties=fp(full_fs, True), color=col, zorder=12, clip_on=False,
        bbox=dict(boxstyle="square,pad=0.20", facecolor=paper, edgecolor=col, linewidth=0.95),
    )
    bar_hit = _bars_hit_rect(xa, ba, full_rect, y_pad=y_span * 0.02)
    return {
        "pass": not bar_hit,
        "pct": pct,
        "bar_hit": bar_hit,
        "chip_hit": False,  # 原點允許貼峰（同主圖錨貼線）
        "anchor": (axp, chip_ay),
        "label": (lx, ly),
    }


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


def _fmt_lots_signed(delta: float) -> str:
    """今−昨張數；正寫 +N張、負寫 −N張（真差）。"""
    d = float(delta)
    n = int(round(abs(d)))
    if d > 0:
        return f"+{n:,}張"
    if d < 0:
        return f"−{n:,}張"
    return "±0張"


def _vol_vs_prev_cell(off: OfficialDay, *, up: str, dn: str, ink: str) -> Tuple[str, str, Optional[str]]:
    """今成交量主字／色／副行（±張）。無昨量→主字黑、無副行（不准捏差）。"""
    main = _fmt_lots(off.volume_lots)
    pv = off.prev_volume_lots
    if pv is None or pv <= 0:
        return main, ink, None
    diff = float(off.volume_lots) - float(pv)
    if diff > 0:
        return main, up, _fmt_lots_signed(diff)
    if diff < 0:
        return main, dn, _fmt_lots_signed(diff)
    return main, ink, "±0張"


def _amt_vs_prev_cell(off: OfficialDay, *, up: str, dn: str, ink: str) -> Tuple[str, str, Optional[str]]:
    """今成交金額主字／色／副行（±％）。無昨額→主字黑、無副行（不准捏％）。"""
    if not off.turnover_k or off.turnover_k <= 0:
        return "—", ink, None
    main = _fmt_turnover(off.turnover_k)
    pt = off.prev_turnover_k
    if pt is None or pt <= 0:
        return main, ink, None
    pct = (float(off.turnover_k) - float(pt)) / float(pt) * 100.0
    if pct > 0:
        return main, up, f"+{pct:.1f}%"
    if pct < 0:
        return main, dn, f"{pct:.1f}%"
    return main, ink, "0.0%"


def _paint_quote_grid(quote_ax, off: OfficialDay) -> None:
    """v14：12 格；今量／今額主字與 ±張／±％左右並排（壓低格高）。不准假停板。"""
    from ink_chart_theme import DN, INK, MUTE, PAPER, UP, fp
    from matplotlib.patches import FancyBboxPatch

    quote_ax.set_xlim(0, 1)
    quote_ax.set_ylim(0, 1)
    quote_ax.set_autoscale_on(False)
    quote_ax.set_facecolor(PAPER)
    quote_ax.set_xticks([])
    quote_ax.set_yticks([])
    for sp in quote_ax.spines.values():
        sp.set_visible(False)

    avg_lab = "今日均價"
    avg_val = _fmt_face(off.avg_price) if off.avg_price and off.avg_price > 0 else "—"
    amp_val = f"{off.amplitude_pct:.2f}%" if off.amplitude_pct is not None else "—"
    prev_vol_val = (
        _fmt_lots(off.prev_volume_lots)
        if off.prev_volume_lots is not None and off.prev_volume_lots > 0
        else "—"
    )
    prev_amt_val = (
        _fmt_turnover(off.prev_turnover_k)
        if off.prev_turnover_k is not None and off.prev_turnover_k > 0
        else "—"
    )
    vol_main, vol_col, vol_sub = _vol_vs_prev_cell(off, up=UP, dn=DN, ink=INK)
    amt_main, amt_col, amt_sub = _amt_vs_prev_cell(off, up=UP, dn=DN, ink=INK)
    # (lab, main, color, sub_or_None, side_by_side)；lab="" 且 main=""＝留白格
    cells: List[Tuple[str, str, str, Optional[str], bool]] = [
        ("今開盤價", _fmt_face(off.open), INK, None, False),
        ("盤中最高", _fmt_face(off.high), UP, None, False),
        ("盤中最低", _fmt_face(off.low), DN, None, False),
        ("昨收盤價", _fmt_face(off.prev_close), INK, None, False),
        ("今成交量", vol_main, vol_col, vol_sub, True),
        ("今成交金額", amt_main, amt_col, amt_sub, True),
        ("昨成交量", prev_vol_val, INK, None, False),
        ("昨成交金額", prev_amt_val, INK, None, False),
        (avg_lab, avg_val, INK, None, False),
        ("今日振幅", amp_val, INK, None, False),
        ("", "", MUTE, None, False),  # 留白（取消漲停）
        ("", "", MUTE, None, False),  # 留白（取消跌停）
    ]

    cols = 4
    rows_n = 3
    has_note = off.close_label == "興櫃收" and not (off.low <= off.open <= off.high)
    pad_x, pad_top = 0.010, 0.028
    pad_bot = 0.12 if has_note else 0.022
    gap_x, gap_y = 0.008, 0.020
    usable_h = 1.0 - pad_top - pad_bot
    cell_h = (usable_h - gap_y * (rows_n - 1)) / float(rows_n)
    width = 1.0 - 2 * pad_x
    cell_w = (width - gap_x * (cols - 1)) / cols
    edge = "#9AA0A6"
    lab_col = "#3A3A3A"
    lab_fs, val_fs, sub_fs = 9.5, 12.0, 9.0
    for i, (lab, val, col, sub, side) in enumerate(cells):
        r, c = divmod(i, cols)
        x = pad_x + c * (cell_w + gap_x)
        y = 1.0 - pad_top - (r + 1) * cell_h - r * gap_y
        quote_ax.add_patch(
            FancyBboxPatch(
                (x, y), cell_w, cell_h,
                boxstyle="square,pad=0.003",
                facecolor=PAPER, edgecolor=edge, linewidth=1.15,
                clip_on=False, zorder=2,
            )
        )
        if not lab and not val:
            continue  # 留白格：只留框
        quote_ax.text(
            x + cell_w * 0.5, y + cell_h * 0.70, lab,
            fontproperties=fp(lab_fs, True), color=lab_col, ha="center", va="center",
            zorder=3, clip_on=False,
        )
        if sub and side:
            # v14：主數字與 +張／+％ 左右並排（一例：4,285張  +3,172張）
            line = f"{val}  {sub}"
            fs = val_fs if len(line) <= 16 else max(8.5, val_fs - 1.5)
            quote_ax.text(
                x + cell_w * 0.5, y + cell_h * 0.30, line,
                fontproperties=fp(fs, True), color=col, ha="center", va="center",
                zorder=3, clip_on=False,
            )
        elif sub:
            quote_ax.text(
                x + cell_w * 0.5, y + cell_h * 0.40, val,
                fontproperties=fp(val_fs, True), color=col, ha="center", va="center",
                zorder=3, clip_on=False,
            )
            quote_ax.text(
                x + cell_w * 0.5, y + cell_h * 0.16, sub,
                fontproperties=fp(sub_fs, True), color=col, ha="center", va="center",
                zorder=3, clip_on=False,
            )
        else:
            quote_ax.text(
                x + cell_w * 0.5, y + cell_h * 0.30, val,
                fontproperties=fp(val_fs, True), color=col, ha="center", va="center",
                zorder=3, clip_on=False,
            )
    if has_note:
        quote_ax.text(
            pad_x, 0.028,
            "註：興櫃開＝前日均價，可高於當日最高",
            fontproperties=fp(9.5, False), color=MUTE, ha="left", va="bottom",
            zorder=3, clip_on=False,
        )
    quote_ax.set_xlim(0, 1)
    quote_ax.set_ylim(0, 1)


def _paint_range_bars(fig, off: OfficialDay, *, y_bot: float, left: float, right: float) -> Optional[float]:
    """底部三條：量能／今日區間／52週。

    v8：％改量框內；**列與列之間零跨列字**——每列文字只在該條上方標題列，
    收／開小標貼條內側短劃旁（不垂降到下一列）。回傳量／季均比。
    """
    from ink_chart_theme import DN, INK, PAPER, RULE, UP, YELLOW, fp
    from matplotlib.patches import Rectangle

    bar_h = 0.020
    # 三列均分；標題只在條上，列縫留給下一列標題（不准跨列）
    row_pitch = 0.062
    width = right - left
    y = y_bot + 2 * row_pitch + 0.006
    last_lab = "日均" if off.close_label == "興櫃收" else "收盤"
    z = 30
    vol_ratio: Optional[float] = None

    def _tick(mf: float, yb: float) -> float:
        mf = max(0.0, min(1.0, float(mf)))
        mx = left + width * mf
        fig.patches.append(
            Rectangle(
                (mx - 0.0015, yb - 0.002), 0.0030, bar_h + 0.004,
                transform=fig.transFigure, facecolor=INK, edgecolor="none", clip_on=False, zorder=z,
            )
        )
        return mx

    def _inline_mark(mx: float, yb: float, text: str, *, ha: str = "center") -> None:
        """收／開標貼在條**上方標題帶**，不垂到下一列。"""
        fig.text(
            mx, yb + bar_h + 0.003, text,
            fontproperties=fp(10, True), color=INK, ha=ha, va="bottom",
            transform=fig.transFigure, zorder=z + 1,
            bbox=dict(boxstyle="square,pad=0.14", facecolor=PAPER, edgecolor="#9AA0A6", linewidth=0.8),
        )

    # —— 1) 量能：標題＋季均／當日全在條上方；條下空白給列縫（FAIL#1/#3） ——
    fig.text(
        left, y + bar_h + 0.003, "量能",
        fontproperties=fp(11, True), color=INK, ha="left", va="bottom",
        transform=fig.transFigure, zorder=z,
    )
    q_txt = (
        f"季均 {_fmt_lots(off.q_avg_vol_lots)}"
        if off.q_avg_vol_lots and off.q_avg_vol_lots > 0
        else "季均 —"
    )
    fig.text(
        left + 0.055, y + bar_h + 0.003, q_txt,
        fontproperties=fp(10, False), color="#3A3A3A", ha="left", va="bottom",
        transform=fig.transFigure, zorder=z,
    )
    fig.text(
        right, y + bar_h + 0.003, f"當日 {_fmt_lots(off.volume_lots)}",
        fontproperties=fp(11, True), color=INK, ha="right", va="bottom",
        transform=fig.transFigure, zorder=z,
    )
    fig.patches.append(
        Rectangle(
            (left, y), width, bar_h, transform=fig.transFigure,
            facecolor=RULE, edgecolor="#9AA0A6", linewidth=0.7, clip_on=False, zorder=z,
        )
    )
    if off.q_avg_vol_lots and off.q_avg_vol_lots > 0:
        vol_ratio = off.volume_lots / off.q_avg_vol_lots
        fill_w = width * min(vol_ratio, 1.0)
        fig.patches.append(
            Rectangle(
                (left, y), fill_w, bar_h,
                transform=fig.transFigure, facecolor=DN if vol_ratio >= 1 else UP,
                edgecolor="none", alpha=0.90, clip_on=False, zorder=z,
            )
        )
    y -= row_pitch

    # —— 2) 今日區間：日低／日高／收開全在本列上方帶 ——
    span = max(off.high - off.low, 1e-9)
    last_f = (off.close - off.low) / span
    open_in = off.low <= off.open <= off.high
    open_f = (off.open - off.low) / span if open_in else None
    fig.text(
        left, y + bar_h + 0.003, "今日區間",
        fontproperties=fp(11, True), color=INK, ha="left", va="bottom",
        transform=fig.transFigure, zorder=z,
    )
    fig.text(
        left + 0.078, y + bar_h + 0.003, f"日低 {_fmt_face(off.low)}",
        fontproperties=fp(11, True), color=DN, ha="left", va="bottom",
        transform=fig.transFigure, zorder=z,
    )
    fig.text(
        right, y + bar_h + 0.003, f"日高 {_fmt_face(off.high)}",
        fontproperties=fp(11, True), color=UP, ha="right", va="bottom",
        transform=fig.transFigure, zorder=z,
    )
    fig.patches.append(
        Rectangle(
            (left, y), width, bar_h, transform=fig.transFigure,
            facecolor=RULE, edgecolor="#9AA0A6", linewidth=0.7, clip_on=False, zorder=z,
        )
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
    # 收／開：置中帶，避開左右日低／日高字
    mid_lo, mid_hi = 0.22, 0.78
    marks: List[Tuple[float, str]] = []
    if open_f is not None and mid_lo <= open_f <= mid_hi:
        marks.append((open_f, f"開 {_fmt_face(off.open)}"))
    if mid_lo <= last_f <= mid_hi:
        marks.append((last_f, f"{last_lab} {_fmt_face(off.close)}"))
    elif abs(last_f - 0.5) < abs((open_f or 0.5) - 0.5):
        marks.append((max(mid_lo, min(mid_hi, last_f)), f"{last_lab} {_fmt_face(off.close)}"))
    # 兩標過近只留收／日均
    if len(marks) == 2 and abs(marks[0][0] - marks[1][0]) < 0.12:
        marks = [m for m in marks if last_lab in m[1] or m[1].startswith(last_lab)]
        if not marks:
            marks = [(last_f, f"{last_lab} {_fmt_face(off.close)}")]
    for mf, txt in marks:
        ha = "left" if mf <= 0.3 else ("right" if mf >= 0.7 else "center")
        _inline_mark(_tick(mf, y), y, txt, ha=ha)
    y -= row_pitch

    # —— 3) 52週：高低＋現價標都在本列上方 ——
    w_lo = off.w52_low if off.w52_low is not None else off.low
    w_hi = off.w52_high if off.w52_high is not None else off.high
    if w_hi <= w_lo:
        w_hi = w_lo + max(abs(w_lo) * 0.01, 1.0)
    span52 = w_hi - w_lo
    last_f52 = (off.close - w_lo) / span52
    fig.text(
        left, y + bar_h + 0.003, "52週",
        fontproperties=fp(11, True), color=INK, ha="left", va="bottom",
        transform=fig.transFigure, zorder=z,
    )
    fig.text(
        left + 0.048, y + bar_h + 0.003, f"低 {_fmt_face(w_lo)}",
        fontproperties=fp(11, True), color=DN, ha="left", va="bottom",
        transform=fig.transFigure, zorder=z,
    )
    fig.text(
        right, y + bar_h + 0.003, f"高 {_fmt_face(w_hi)}",
        fontproperties=fp(11, True), color=UP, ha="right", va="bottom",
        transform=fig.transFigure, zorder=z,
    )
    fig.patches.append(
        Rectangle(
            (left, y), width, bar_h, transform=fig.transFigure,
            facecolor=RULE, edgecolor="#9AA0A6", linewidth=0.7, clip_on=False, zorder=z,
        )
    )
    lf = max(0.0, min(1.0, last_f52))
    fig.patches.append(
        Rectangle(
            (left + width * lf - 0.005, y), 0.010, bar_h,
            transform=fig.transFigure, facecolor=YELLOW, edgecolor="none", alpha=0.95, clip_on=False, zorder=z,
        )
    )
    # 現價標：若貼左右端則省略（已有高低），否則置中上方
    if 0.18 < last_f52 < 0.82:
        ha = "center"
        _inline_mark(_tick(last_f52, y), y, f"{last_lab} {_fmt_face(off.close)}", ha=ha)

    return vol_ratio



def render_path(series: PathSeries, out_path: str, *, db_path: str = "") -> Tuple[str, Dict[str, Any]]:
    import numpy as np
    import matplotlib

    matplotlib.use("Agg", force=True)
    import matplotlib.pyplot as plt
    from matplotlib.patches import FancyBboxPatch

    from biaoke_chart import (
        BIAOKE_CHART_DPI,
        _FIG_BOTTOM,
        _FIG_LEFT,
        _HEADER_X_FB,
        _SPOT_X_NO_LOCATOR,
        _STRUCTURE_BOX_EC,
        _STRUCTURE_BOX_LW,
        _STRUCTURE_BOX_STYLE,
        _STRUCTURE_BOX_W,
        _STRUCTURE_BOX_X,
        _STRUCTURE_FIG_RIGHT,
        _STRUCTURE_LOOKUP_FIG,
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

    # v12：畫布＝大量區 NAV 12.4×9.35；外框共線維持 v9；報價帶 3×4＝12 格
    from vol_zone_chart import VOL_ZONE_FIG_H_NAV, VOL_ZONE_FIG_W

    fig_w = float(VOL_ZONE_FIG_W)  # 12.4
    fig_h = float(VOL_ZONE_FIG_H_NAV)  # 9.35＝圖四同系列；不准自成 10.85
    dpi = int(BIAOKE_CHART_DPI)  # 200
    fig = plt.figure(figsize=(fig_w, fig_h), dpi=dpi, facecolor=PAPER)

    # 外框：結構圖 `_STRUCTURE_BOX_*`（頭欄／報價格／價／量同一 left＋同一 width）
    frame_x = float(_STRUCTURE_BOX_X)  # 1.6（ov 0–100）
    frame_w = float(_STRUCTURE_BOX_W)  # 96.6 → 右緣 98.2
    frame_left = frame_x / 100.0  # 0.016
    frame_right = (frame_x + frame_w) / 100.0  # 0.982
    # axes：結構 subplots 同套；右標落在 axes 右～外框右的框內白邊（略窄可說明）
    left_f = float(_FIG_LEFT)  # 0.028
    right_f = float(_STRUCTURE_FIG_RIGHT)  # 0.905
    # v14：時間戳旁黑標 → 頭欄變矮 → 十二格上移 → 價圖加高（智能標不擠）
    bars_top = 0.195
    xlab_bot = 0.205
    xlab_top = 0.238
    vol_bot = 0.245
    vol_h = 0.082
    band_gap = 0.011
    main_bot = vol_bot + vol_h + band_gap
    main_top = 0.668  # v13 0.545 → 價圖加高
    quote_band_bot = main_top + band_gap
    quote_top = 0.858  # v13 0.755 → 格子頂進原頭欄空白
    assert quote_band_bot >= main_top + 0.010, "報價格底緣必須在價圖頂之上（不准疊進主題區）"
    assert xlab_bot >= bars_top + 0.008, "時軸專帶必須在底三條之上（09 不准被量能削）"
    assert abs(frame_right - frame_left - frame_w / 100.0) < 1e-9
    assert quote_top - quote_band_bot >= 0.165, "12 格報價帶高度不夠"

    ax = fig.add_axes([left_f, main_bot, right_f - left_f, main_top - main_bot], zorder=2)
    vol_ax = fig.add_axes([left_f, vol_bot, right_f - left_f, vol_h], sharex=ax, zorder=2)
    ax.set_facecolor(PAPER)
    vol_ax.set_facecolor(PAPER)
    # quote_ax 等頭欄 ov 建完再加（mpl 常依建立序後蓋前；見下方 zorder=25）

    ov = fig.add_axes([0, 0, 1, 1], facecolor="none", zorder=12)
    ov.set_xlim(0, 100)
    ov.set_ylim(0, 100)
    ov.axis("off")
    ov.patch.set_alpha(0)

    # 頭欄白底＋報價格／價／量外框：同一 frame_x／frame_w（系列感；不准頭欄獨寬）
    name_band_bot = quote_top * 100.0
    for y0, y1, fill in (
        (name_band_bot, 100.0 - float(_STRUCTURE_TOP_PAD) - 0.15, True),
        (quote_band_bot * 100.0, quote_top * 100.0, False),
        (main_bot * 100.0, main_top * 100.0, False),
        (vol_bot * 100.0, (vol_bot + vol_h) * 100.0, False),
    ):
        ov.add_patch(
            FancyBboxPatch(
                (frame_x, y0),
                frame_w,
                max(0.4, y1 - y0),
                boxstyle=_STRUCTURE_BOX_STYLE,
                facecolor="#ffffff" if fill else "none",
                edgecolor=_STRUCTURE_BOX_EC,
                linewidth=_STRUCTURE_BOX_LW,
                alpha=1.0 if fill else 0.98,
                zorder=1 if fill else 0,
                clip_on=False,
            )
        )

    plate = stock_nameplate(series.stock_id, series.name, db_path)
    header_x = float(_HEADER_X_FB)
    name_y = 95.6
    # v14：名牌自畫產業晶片 → 時間戳貼黑標右側同一列（不准獨占下一整行）
    from biaoke_chart import _ow, _paint_industry_chips

    _paint_nameplate(
        ov, plate, x=header_x, y=float(name_y),
        title_size=int(_STRUCTURE_TITLE_FS), industry_size=12, skip_industry=True,
    )
    title_s = f"{plate.get('sid') or ''} {plate.get('name') or ''}".strip()
    title_w = _ow(title_s, int(_STRUCTURE_TITLE_FS)) * 1.12
    gap_chip = (4.10 if int(_STRUCTURE_TITLE_FS) >= 28 else 3.40) / 3.0
    chip_end = _paint_industry_chips(
        ov, plate, x=header_x + title_w + gap_chip, y=float(name_y),
        align="left", size=12,
    )
    try:
        date_part = format_ymd_slash_weekday(ASOF_YMD)
    except Exception:
        date_part = f"{ASOF_YMD[:4]}/{ASOF_YMD[4:6]}/{ASOF_YMD[6:8]}"
    stamp = f"{date_part} {board_close_clock_label(emerging=is_em)}".strip()
    stamp_x = float(chip_end) + 1.35
    # 防撞右上價區：最多貼到 spot 左緩衝
    stamp_x = min(stamp_x, float(_SPOT_X_NO_LOCATOR) - 28.0)
    ov.text(
        stamp_x, float(name_y), stamp,
        color="#5C5C5C",
        fontproperties=_fp(max(11, int(_STRUCTURE_SPOT_STAMP_FS) - 3), "bold"),
        va="center", ha="left", zorder=22, clip_on=False,
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
    # 興櫃無漲跌停：spot 先以 0 漲跌畫（不判停），事後補真字＋透明底
    _paint_spot(
        ov, quote if not is_em else {**quote, "pct": 0.0, "change": 0.0},
        x=float(_SPOT_X_NO_LOCATOR), y=float(name_y), align="right",
        stamp="",  # 時間戳已在名牌右，不再佔第三行
        move_dy=float(_STRUCTURE_SPOT_ROW_GAP),
        price_size=int(_STRUCTURE_SPOT_FS),
        move_size=int(_STRUCTURE_SPOT_MOVE_FS),
        stamp_size=int(_STRUCTURE_SPOT_STAMP_FS),
        lab_size=int(_STRUCTURE_SPOT_LAB_FS),
    )
    if is_em:
        from tg_layout import format_move_plain
        from wayne_navigator import quote_move_ink

        move = format_move_plain(off.change, off.pct_change)
        col = quote_move_ink(
            off.change, close=off.close, prev=off.prev_close, pct=off.pct_change,
            up=UP, down=DN, flat=MUTE,
        )
        for t in ov.texts:
            s = str(t.get_text() or "")
            if s.startswith("較昨日"):
                t.set_text("較昨日　" + move)
                t.set_color(col)
                t.set_bbox(None)  # 興櫃永遠不上停板色底
            if re.fullmatch(r"[\d,.]+", s.strip()) and t.get_fontsize() >= 24:
                t.set_bbox(None)
                t.set_color(col)

    # 只做頭欄墨線（名牌黑標＋右漲跌），不准 apply_struct 動主圖 y 軸
    # 不准 close_struct_frame_seam：會消掉價／量縫並切斷時標
    ink = Ink(fig, "struct", lazy=True)
    ink.redraw()
    frames = struct_frames(ink, ov)
    struct_header(ink, ov, frames)
    if is_em:
        _scrub_em_limit_labels(fig)

    # 收／興櫃收：漲紅平黑跌綠（非漲停底）
    from wayne_navigator import quote_move_ink as _qmi

    close_col = _qmi(
        off.change, close=off.close, prev=off.prev_close, pct=off.pct_change,
        up=UP, down=DN, flat=INK,
    )
    for t in ov.texts:
        s = str(t.get_text() or "").strip()
        if re.fullmatch(r"[\d,.]+", s) and float(t.get_fontsize() or 0) >= 24:
            if t.get_bbox_patch() is None:
                t.set_color(close_col)

    # 12 格：獨立 axes；鋪滿共線外框內緣（與頭欄白底同寬），不畫進價圖 ax
    # 價／量 axes 維持 FIG_LEFT～STRUCTURE_FIG_RIGHT（略窄＝框內右標／Y 刻度；外框仍共線）
    q_pad = 0.004
    quote_ax = fig.add_axes(
        [
            frame_left + q_pad,
            quote_band_bot,
            (frame_right - frame_left) - 2 * q_pad,
            quote_top - quote_band_bot,
        ],
        zorder=25,
    )
    quote_ax.set_facecolor(PAPER)
    quote_ax.patch.set_alpha(1.0)
    _paint_quote_grid(quote_ax, off)
    # 硬閘：報價格底緣必須在價圖頂之上
    assert float(quote_ax.get_position().y0) >= float(main_top) - 1e-6

    # 路徑
    hi = float(max(float(np.max(ys)), prev, off.high, float(np.max(series.highs))))
    lo = float(min(float(np.min(ys)), prev, off.low, float(np.min(series.lows))))
    if off.avg_price and off.avg_price > 0:
        hi = max(hi, float(off.avg_price))
        lo = min(lo, float(off.avg_price))
    pad = max((hi - lo) * 0.10, abs(prev) * 0.002, 0.5)
    ax.set_ylim(lo - pad, hi + pad)
    ax.set_xlim(0.0, x_end)
    # 昨收參考虛線（填色基準）；五必標改 v13 圓章＋短虛線，不再拉滿幅水平線搶位
    ax.axhline(prev, color=MUTE, linestyle=(0, (4, 3)), linewidth=1.15, zorder=2, alpha=0.85)
    ax.fill_between(xs, prev, ys, where=ys >= prev, interpolate=True, color=UP, alpha=0.16, zorder=1)
    ax.fill_between(xs, prev, ys, where=ys <= prev, interpolate=True, color=DN, alpha=0.16, zorder=1)
    # 缺分已平鋪；僅跳超大斷層（不應再出現）。連續段用 plot 畫齊。
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

    # v14 主圖智能標（位階＋破昨收／爆量／急殺同閘避讓）
    events = _collect_event_marks(series, xs, ys, prev)
    label_gate = _paint_smart_level_labels(
        ax, xs, ys,
        list(series.highs), list(series.lows), list(series.opens),
        off,
        close_col=close_col, up=UP, dn=DN, ink=INK, paper=PAPER,
        events=events,
    )
    # 掛在 fig 上供 render 回傳／閘門
    fig._wayne_label_gate = label_gate  # type: ignore[attr-defined]

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

    # 量柱：只畫真量（Yahoo 1m／興櫃 priceByTimes 聚合）；不准造量。
    # 缺分＝平鋪前收＋vol 0 → 灰 stub（誠實，不是假成交）。
    # 色＝真該分收 vs 真前分收（首分 vs 昨收）：漲 UP 紅／跌 DN 綠／平灰。
    # 整段單向＝整排單色屬真象，不准為「看起來有紅有綠」捏點或改色。
    vs_arr = np.asarray(vs, dtype=float)
    ys_arr = np.asarray(ys, dtype=float)
    vs_log = np.log1p(np.maximum(vs_arr, 0.0))
    vmax_s = float(np.max(vs_log)) if len(vs_log) else 1.0
    vs_disp = np.power(vs_log / vmax_s, 0.55) * vmax_s if vmax_s > 0 else vs_log
    stub = max(vmax_s * 0.05, 0.15)
    width = 0.92
    flat_vol = "#9AA0A6"
    real_mask = vs_arr > 0  # 只著色真量柱；vol=0 一律灰 stub
    if np.any(real_mask):
        vol_cols: List[str] = []
        for i in np.where(real_mask)[0]:
            yi = float(ys_arr[i])
            # 前一分亦為路徑真值（缺分平鋪前收不算成交，但仍是誠實前收參考）
            ref = float(prev) if int(i) == 0 else float(ys_arr[int(i) - 1])
            if yi > ref:
                vol_cols.append(UP)
            elif yi < ref:
                vol_cols.append(DN)
            else:
                vol_cols.append(flat_vol)
        vol_ax.bar(
            xs[real_mask], vs_disp[real_mask], width=width,
            color=vol_cols, alpha=0.92, zorder=3, linewidth=0, align="center",
        )
    miss_mask = ~real_mask
    if np.any(miss_mask):
        vol_ax.bar(
            np.asarray(xs)[miss_mask], np.full(int(np.sum(miss_mask)), stub),
            width=width * 0.55, color="#D0D3D8", alpha=0.45, zorder=1, linewidth=0, align="center",
        )
    # v14：頭頂留白給量％完整標（實心錨仍貼峰；標虛線拉上）
    vol_ax.set_ylim(0, max(vmax_s * 1.28, stub * 4))

    tick_h = [9, 10, 11, 12, 13, 14, 15] if is_em else [9, 10, 11, 12, 13]
    tick_x = [(h - 9) * 60 for h in tick_h]
    for a in (ax, vol_ax):
        a.set_xticks(tick_x)
        a.tick_params(axis="x", length=0, labelbottom=False, bottom=False, top=False)
        # 外框交給共線 FancyBbox；藏 spines 避免雙框／左右緣差 1px
        for sp in a.spines.values():
            sp.set_visible(False)
        a.grid(True, axis="both", color=RULE, linewidth=0.7, zorder=0)
    # 價軸刻度改軸內左側，不戳出共線外框
    ax.tick_params(
        axis="y", colors=MUTE, length=3, labelsize=10,
        direction="in", left=True, labelleft=True, right=False, labelright=False, pad=2,
    )
    # 時間標：xlab 專帶（bars_top 之上、vol_bot 之下）；09／15 完整（FAIL#1/#2）
    ax.set_xticklabels([])
    vol_ax.set_xticklabels([])
    for lab in ax.get_yticklabels():
        lab.set_fontproperties(fp(10, False))
        lab.set_color(MUTE)
    vol_ax.set_yticks([])
    vol_ax.text(
        0.01, 0.92, "量(張)", transform=vol_ax.transAxes,
        fontproperties=fp(10, False), color=MUTE, va="top", ha="left",
    )

    # 底三條：左／右對齊共線外框（v8 用 left_f～0.82 與框錯位）
    vol_ratio = _paint_range_bars(
        fig, off, y_bot=0.016, left=frame_left, right=frame_right,
    )
    # v14 量％：高峰錨＋短虛線拉淨空（對齊主圖現價 OK；不准壓柱）
    vol_gate = _paint_vol_ratio_smart(
        vol_ax, xs, vs_disp, float(vol_ratio) if vol_ratio is not None else 0.0,
        up=UP, dn=DN, ink=INK, paper=PAPER,
    )
    label_gate = dict(getattr(fig, "_wayne_label_gate", {}) or {})
    label_gate["vol_ratio"] = vol_gate
    if vol_gate and vol_gate.get("pass") is False:
        label_gate["pass"] = False
    fig._wayne_label_gate = label_gate  # type: ignore[attr-defined]

    xlab_y = 0.5 * (xlab_bot + xlab_top)
    chart_w = right_f - left_f
    for h, tx in zip(tick_h, tick_x):
        xf = left_f + chart_w * (float(tx) / float(x_end))
        # 左端 09 略內縮、右端 15／13 略內縮，避免貼框削邊
        if h == tick_h[0]:
            xf = left_f + 0.006
            ha = "left"
        elif h == tick_h[-1]:
            xf = right_f - 0.006
            ha = "right"
        else:
            ha = "center"
        fig.text(
            xf, xlab_y, f"{h:02d}",
            fontproperties=fp(12, True), color="#3A3A3A", ha=ha, va="center",
            transform=fig.transFigure, clip_on=False, zorder=35,
        )

    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    fig.savefig(out_path, facecolor=PAPER, edgecolor="none")
    gate = getattr(fig, "_wayne_label_gate", {"pass": False, "n_labels": 0})
    plt.close(fig)
    return out_path, dict(gate)


def _paint_sparse_marks(ax, series: PathSeries, xs, ys, prev: float) -> None:
    """走勢重點稀疏標：offset 拉離價線，儘量不壓折線。"""
    from ink_chart_theme import DN, INK, UP, fp
    import numpy as np

    marks: List[Tuple[float, float, str, str, Tuple[float, float]]] = []
    for x, y in zip(xs, ys):
        if float(y) < prev:
            # 破昨收下偏，避開折線
            marks.append((float(x), float(y), "破昨收", DN, (14, -22)))
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
            marks.append((best[1], best[2], "急殺", DN, (16, -24)))
    vs = np.asarray(series.volumes_lots, dtype=float)
    if len(vs) and float(np.max(vs)) > 0:
        med = float(np.median(vs[vs > 0])) if np.any(vs > 0) else 0.0
        i = int(np.argmax(vs))
        if med > 0 and vs[i] >= med * 6:
            marks.append(
                (float(xs[i]), float(ys[i]), "爆量", UP if ys[i] >= prev else DN, (14, 22))
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
        "/cursor/stores/self/media/intraday-v14-solid-dot-20261029",
        "/cursor/stores/bc-01a0d9ba-b7e3-7f56-802d-4c6e57f8ad9e/media/intraday-v14-solid-dot-20261029",
        "/cursor/stores/self/media/intraday-v14-tighten-gap-20261029",
        "/cursor/stores/bc-01a0d9ba-b7e3-7f56-802d-4c6e57f8ad9e/media/intraday-v14-tighten-gap-20261029",
    ):
        parent = os.path.dirname(store)
        if os.path.isdir(parent) or os.path.isdir(store):
            return store
    return os.path.join(_ROOT, "artifacts", "intraday-open-close-preview")


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Preview ink 今日開→收 v14（不接話筒；真數；不合主）")
    ap.add_argument("--out-dir", default=default_out_dir())
    ap.add_argument("--db", default=os.path.join(_ROOT, "data", "wayne_market.db"))
    ap.add_argument("--ymd", default=ASOF_YMD)
    ap.add_argument("--prefix", default="preview-v14")
    ap.add_argument("--only", default="", help="comma stock ids; empty=all")
    ap.add_argument(
        "--set",
        default="v13",
        choices=("v13", "base"),
        help="v13=十檔抽測（含6274）；base=舊五檔",
    )
    args = ap.parse_args(list(argv) if argv is not None else None)

    out_dir = args.out_dir
    os.makedirs(out_dir, exist_ok=True)
    results: List[Dict[str, Any]] = []
    notices_all: Dict[str, List[str]] = {}
    gates: Dict[str, Any] = {}
    only = {s.strip() for s in str(args.only or "").split(",") if s.strip()}
    symbols = PREVIEW_V13_SYMBOLS if args.set == "v13" else PREVIEW_SYMBOLS

    for sid, name, market in symbols:
        if only and sid not in only:
            continue
        slug = _SLUG.get(sid, sid)
        out_path = os.path.join(out_dir, f"{args.prefix}-{sid}-{slug}.png")
        series = build_series(sid, name, market, db_path=args.db, ymd=args.ymd)
        if series is None:
            render_empty(out_path, stock_id=sid, name=name, market=market, reason="官方日值或路徑不可用")
            results.append({"stock_id": sid, "name": name, "market": market, "path": out_path, "ok": False, "n": 0})
            gates[sid] = {"pass": False, "reason": "no_series"}
            print(f"[empty] {sid} {name} -> {out_path}")
            continue
        _path, gate = render_path(series, out_path, db_path=args.db)
        notices_all[sid] = list(series.notices)
        gates[sid] = gate
        results.append(
            {
                "stock_id": sid,
                "name": name,
                "market": market,
                "path": out_path,
                "ok": True,
                "gate_pass": bool(gate.get("pass")),
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
                "prev_vol": series.official.prev_volume_lots,
                "prev_turnover_k": series.official.prev_turnover_k,
                "notices": series.notices,
                "label_gate": gate,
            }
        )
        gflag = "GATE_OK" if gate.get("pass") else "GATE_FAIL"
        print(
            f"[ok] {sid} {name} n={len(series.closes)} {gflag} "
            f"ov={gate.get('full_overlap_pairs')} path={gate.get('full_path_hits')} "
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
                f"gate={int(bool(r.get('gate_pass')))}\tn={r.get('n', 0)}\t{r['path']}\n"
            )
            for n in r.get("notices") or []:
                f.write(f"  notice\t{n}\n")
    with open(os.path.join(out_dir, f"{args.prefix}-notices-20261029.json"), "w", encoding="utf-8") as f:
        json.dump(notices_all, f, ensure_ascii=False, indent=2)
    class _GateEnc(json.JSONEncoder):
        def default(self, o: Any) -> Any:  # noqa: ANN401
            if hasattr(o, "item"):
                try:
                    return o.item()
                except Exception:
                    return str(o)
            if isinstance(o, (set, tuple)):
                return list(o)
            return str(o)

    with open(os.path.join(out_dir, f"{args.prefix}-label-gate-20261029.json"), "w", encoding="utf-8") as f:
        json.dump(gates, f, ensure_ascii=False, indent=2, cls=_GateEnc)
    print(f"[manifest] {manifest}")
    ok_all = all(r["ok"] for r in results) and all(
        bool((gates.get(r["stock_id"]) or {}).get("pass")) for r in results if r.get("ok")
    )
    if not ok_all:
        fails = [
            r["stock_id"] for r in results
            if not r.get("ok") or not (gates.get(r["stock_id"]) or {}).get("pass")
        ]
        print(f"[gate-fail] {fails}")
    return 0 if ok_all else 2


if __name__ == "__main__":
    raise SystemExit(main())
