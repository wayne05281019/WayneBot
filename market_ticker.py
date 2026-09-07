"""大盤頁頂部時段跑馬燈。Telegram 氣泡不能捲字，改送循環 GIF。

沒接到的市場不寫。加權／櫃買用證交所 MIS 最後一筆（delay=0）；
台指期用期交所即時報價，沒接到才退庫內；
日經／韓國／滬指與美股指數／盤前期貨用 Yahoo 1 分鐘 spark（與隔夜美股同一路）。
強弱族群只用官方日 K 均漲或盤中 MIS 熱快取、法人張數；警語只用廣度／恐慌指數／期貨領跌。不編新聞、不編成本。
"""
from __future__ import annotations

import logging
import math
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, time as dt_time
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import quote as url_quote
from zoneinfo import ZoneInfo

import requests

logger = logging.getLogger("WayneBot.MarketTicker")

TW = ZoneInfo("Asia/Taipei")
NY = ZoneInfo("America/New_York")

# 名稱, Yahoo 代號（沒有官方即時列才走這條）
ASIA_INDEX = (
    ("日經", "^N225"),
    ("韓國", "^KS11"),
    ("滬指", "000001.SS"),
)
US_CASH = (
    ("道瓊", "^DJI"),
    ("標普", "^GSPC"),
    ("那斯達克", "^IXIC"),
    ("費半", "^SOX"),
)
US_PRE_FUT = (
    ("標普期", "ES=F"),
    ("那斯達克期", "NQ=F"),
    ("道瓊期", "YM=F"),
)

SLOT_TITLE = {
    "tw_pre": "開盤倒數",
    "tw_match": "試搓中",
    "tw_open": "台股開盤",
    "tw_after": "日盤已收",
    "tw_settled": "收盤",
    "asia_pm": "亞股午後",
    "us_pre": "美股盤前",
    "us_night": "美股時段",
    "weekend": "休市對照",
}

# 試搓 08:30、台指期日盤 08:45–13:45、現股 09:00–13:30、加權盤後到 14:30、櫃買到 15:00。
_MATCH_AT = dt_time(8, 30)
_TX_DAY_OPEN = dt_time(8, 45)
_CASH_OPEN = dt_time(9, 0)
_CASH_CLOSE = dt_time(13, 30)
_TX_DAY_CLOSE = dt_time(13, 45)
_TW_AH_END = dt_time(14, 30)
_OTC_CLOSE = dt_time(15, 0)

_UP = (232, 72, 72)
_DOWN = (46, 168, 96)
_INK = (236, 242, 248)
_MUTED = (168, 186, 204)
_BG = (18, 26, 38)
_LABEL_BG = (28, 52, 78)
_LABEL_FG = (140, 210, 255)
_RULE = (70, 96, 122)

_TAIFEX_QUOTE_URL = "https://mis.taifex.com.tw/futures/api/getQuoteList"
_YAHOO_SPARK = "https://query1.finance.yahoo.com/v8/finance/spark"

_SESSION = requests.Session()
_SESSION.headers.update(
    {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        "Accept": "application/json",
    }
)
_TAIFEX_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Accept": "application/json",
    "Origin": "https://mis.taifex.com.tw",
    "Referer": "https://mis.taifex.com.tw/",
}


def ticker_slot(now: Optional[datetime] = None) -> str:
    """依台北時段＋美股盤別決定跑馬燈。交易日早上 8 點起改走開盤倒數／試搓，不再當成美股時段。"""
    from config import taipei_now
    from trading_calendar import is_tw_equity_session, is_tw_market_holiday

    dt = now or taipei_now()
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=TW)
    else:
        dt = dt.astimezone(TW)
    if is_tw_equity_session(dt):
        return "tw_open"
    t = dt.time()
    tw_off = dt.weekday() >= 5 or is_tw_market_holiday(dt.strftime("%Y%m%d"))
    if not tw_off:
        if dt_time(8, 0) <= t < _MATCH_AT:
            return "tw_pre"
        if _MATCH_AT <= t < _CASH_OPEN:
            return "tw_match"
        if _CASH_CLOSE < t < _OTC_CLOSE:
            return "tw_after"
        if _OTC_CLOSE <= t < dt_time(16, 0):
            return "tw_settled"
        if dt_time(16, 0) <= t < dt_time(21, 30):
            return "us_pre"
    try:
        from us_overnight import us_tape_phase

        if us_tape_phase(dt) in ("regular", "post"):
            return "us_night"
    except Exception:
        pass
    if not tw_off and (t >= dt_time(21, 30) or t < dt_time(8, 0)):
        return "us_night"
    return "weekend"


def _countdown_to(dt: datetime, target: dt_time) -> Optional[str]:
    hit = dt.replace(hour=target.hour, minute=target.minute, second=target.second, microsecond=0)
    if dt >= hit:
        return None
    sec = int((hit - dt).total_seconds())
    if sec < 0:
        return None
    m, s = divmod(sec, 60)
    h, m = divmod(m, 60)
    if h:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m:02d}:{s:02d}"


def _side_zh(pct) -> str:
    if pct is None:
        return ""
    n = float(pct)
    if n > 0:
        return "漲"
    if n < 0:
        return "跌"
    return "平"


def _ticker_item(
    name: str,
    label: str,
    *,
    digits: str = "",
    pct=None,
    kind: str = "text",
) -> Dict[str, Any]:
    text = f"{label} {digits}".strip() if digits else label
    return {
        "name": name,
        "text": text,
        "label": label,
        "digits": digits,
        "pct": pct,
        "kind": kind,
    }


def _fmt_px(px: float) -> str:
    if abs(px) >= 1000:
        return f"{px:,.0f}"
    if abs(px) >= 100:
        return f"{px:,.1f}"
    return f"{px:,.2f}"


def _fmt_pct(pct: Optional[float]) -> str:
    if pct is None:
        return ""
    return f"{pct:+.2f}%"


def _seg(name: str, px=None, pct=None, extra: str = "") -> Optional[Dict[str, Any]]:
    if extra:
        side_pct = 1.0 if extra == "漲" else (-1.0 if extra == "跌" else None)
        return {"name": name, "text": f"{name} {extra}", "pct": side_pct}
    if px is None:
        return None
    body = f"{name} {_fmt_px(float(px))}"
    p = None if pct is None else float(pct)
    if p is not None:
        body += f" {_fmt_pct(p)}"
    return {"name": name, "text": body, "pct": p, "px": float(px)}


def _yahoo_quote(sym: str, timeout: float = 2.2) -> Optional[Dict[str, Any]]:
    url = (
        f"https://query1.finance.yahoo.com/v8/finance/chart/"
        f"{url_quote(sym, safe='')}?interval=1m&range=1d&includePrePost=true"
    )
    try:
        resp = _SESSION.get(url, timeout=timeout)
        resp.raise_for_status()
        result = (resp.json().get("chart") or {}).get("result") or []
        if not result:
            return None
        return _quote_from_yahoo_chart(result[0], sym)
    except Exception:
        logger.debug("跑馬燈 Yahoo 沒接到 %s", sym, exc_info=True)
        return None


def _last_non_null(vals) -> Optional[float]:
    for v in reversed(list(vals or [])):
        if v is None:
            continue
        try:
            n = float(v)
        except (TypeError, ValueError):
            continue
        if n == n:  # not NaN
            return n
    return None


def _quote_from_yahoo_chart(block: Dict[str, Any], sym: str) -> Optional[Dict[str, Any]]:
    meta = (block or {}).get("meta") or {}
    qblock = (((block or {}).get("indicators") or {}).get("quote") or [{}])[0]
    last_1m = _last_non_null((qblock or {}).get("close"))
    px = last_1m
    if px is None:
        try:
            px = float(meta.get("regularMarketPrice"))
        except (TypeError, ValueError):
            px = None
    if px is None or px <= 0:
        return None
    prev = meta.get("chartPreviousClose") or meta.get("previousClose")
    try:
        prev_f = float(prev) if prev is not None else None
    except (TypeError, ValueError):
        prev_f = None
    pct = meta.get("regularMarketChangePercent")
    if prev_f and prev_f > 0:
        pct = (px - prev_f) / prev_f * 100.0
    try:
        pct_f = float(pct) if pct is not None else None
    except (TypeError, ValueError):
        pct_f = None
    return {"px": px, "pct": pct_f, "symbol": meta.get("symbol") or sym}


def _quote_from_spark_block(block: Dict[str, Any], sym: str) -> Optional[Dict[str, Any]]:
    last_1m = _last_non_null((block or {}).get("close"))
    px = last_1m
    if px is None:
        try:
            px = float(block.get("fulldayPrice"))
        except (TypeError, ValueError):
            px = None
    if px is None or px <= 0:
        return None
    prev = block.get("chartPreviousClose") or block.get("previousClose")
    try:
        prev_f = float(prev) if prev is not None else None
    except (TypeError, ValueError):
        prev_f = None
    pct = block.get("fulldayChangePercent")
    if last_1m is not None and prev_f and prev_f > 0:
        pct = (last_1m - prev_f) / prev_f * 100.0
    try:
        pct_f = float(pct) if pct is not None else None
    except (TypeError, ValueError):
        pct_f = None
    return {"px": float(px), "pct": pct_f, "symbol": block.get("symbol") or sym}


def _yahoo_spark(pairs: Tuple[Tuple[str, str], ...], timeout: float = 2.4) -> List[Dict[str, Any]]:
    """一次抓多檔 1 分鐘 spark；沒接到的不寫。失敗再逐檔 1 分鐘圖。"""
    if not pairs:
        return []
    syms = [sym for _n, sym in pairs]
    by_sym: Dict[str, Dict[str, Any]] = {}
    try:
        resp = _SESSION.get(
            _YAHOO_SPARK,
            params={"symbols": ",".join(syms), "range": "1d", "interval": "1m"},
            timeout=timeout,
        )
        resp.raise_for_status()
        payload = resp.json() or {}
        for sym in syms:
            block = payload.get(sym)
            if not isinstance(block, dict):
                continue
            q = _quote_from_spark_block(block, sym)
            if q:
                by_sym[sym] = q
    except Exception:
        logger.debug("跑馬燈 Yahoo spark 失敗", exc_info=True)
    missing = [(name, sym) for name, sym in pairs if sym not in by_sym]
    if missing:
        with ThreadPoolExecutor(max_workers=min(6, len(missing))) as ex:
            futs = {ex.submit(_yahoo_quote, sym, timeout): (name, sym) for name, sym in missing}
            for fut in as_completed(futs):
                name, sym = futs[fut]
                try:
                    q = fut.result()
                except Exception:
                    q = None
                if q:
                    by_sym[sym] = q
    out: List[Dict[str, Any]] = []
    for name, sym in pairs:
        q = by_sym.get(sym)
        if not q:
            continue
        seg = _seg(name, q.get("px"), q.get("pct"))
        if seg:
            out.append(seg)
    return out


def _yahoo_many(pairs: Tuple[Tuple[str, str], ...], timeout: float = 2.4) -> List[Dict[str, Any]]:
    return _yahoo_spark(pairs, timeout=timeout)


def _tw_index_seg(live: Optional[Dict[str, Any]], snap: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    live = live or {}
    snap = snap or {}
    px = float(live.get("close") or 0) or float(snap.get("close") or 0)
    if px <= 0:
        return None
    pct = live.get("pct_change")
    if pct is None:
        pct = snap.get("chg1_pct")
    return _seg("加權", px, pct)


def _tx_seg(snap: Optional[Dict[str, Any]], *, night: bool = False, live: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
    if live and float(live.get("close") or 0) > 0:
        label = "台指期夜盤" if night else "台指期"
        return _seg(label, live.get("close"), live.get("pct_change"))
    snap = snap or {}
    fut = (snap.get("futures_night") if night else None) or snap.get("futures") or {}
    if night:
        from taiwan_market import resolve_futures_night

        db = snap.get("_db_path")
        night_row = snap.get("futures_night")
        if not night_row and db:
            try:
                night_row = resolve_futures_night(db, snap.get("as_of"))
            except Exception:
                night_row = None
        fut = night_row or fut
    px = float((fut or {}).get("close") or 0)
    if px <= 0:
        return None
    pct = fut.get("pct_change")
    label = "台指期夜盤" if night else "台指期"
    return _seg(label, px, pct)


def _num_or_none(val) -> Optional[float]:
    s = str(val or "").replace(",", "").replace("+", "").replace("%", "").strip()
    if s in ("", "-", "--", "N/A", "null", "None"):
        return None
    try:
        return float(s)
    except ValueError:
        return None


def pick_tx_quote_row(rows: List[Dict[str, Any]], *, night: bool) -> Optional[Dict[str, Any]]:
    """近月臺指期：日盤 *-F、夜盤 *-M。量最大者；沒量就取第一筆有成交價的。"""
    suffix = "-M" if night else "-F"
    cands: List[Tuple[float, Dict[str, Any]]] = []
    for row in rows or []:
        sid = str(row.get("SymbolID") or "")
        if not sid.startswith("TXF") or sid.endswith("-S") or sid.endswith("-P"):
            continue
        if not sid.endswith(suffix):
            continue
        px = _num_or_none(row.get("CLastPrice"))
        if not px or px <= 0:
            continue
        vol = _num_or_none(row.get("CTotalVolume")) or 0.0
        cands.append((vol, row))
    if not cands:
        return None
    cands.sort(key=lambda kv: kv[0], reverse=True)
    return cands[0][1]


def fetch_tx_live(*, night: bool = False, timeout: float = 2.2) -> Optional[Dict[str, Any]]:
    """期交所即時報價（不寫庫）。沒接到回 None。"""
    payload = {
        "MarketType": "1" if night else "0",
        "SymbolType": "F",
        "KindID": "1",
        "CID": "",
        "ExpireMonth": "",
        "SymbolID": "",
        "Fcode": "",
    }
    try:
        resp = requests.post(
            _TAIFEX_QUOTE_URL,
            json=payload,
            headers=_TAIFEX_HEADERS,
            timeout=timeout,
        )
        resp.raise_for_status()
        rows = ((resp.json() or {}).get("RtData") or {}).get("QuoteList") or []
        row = pick_tx_quote_row(rows, night=night)
        if not row:
            return None
        px = _num_or_none(row.get("CLastPrice"))
        if not px or px <= 0:
            return None
        pct = _num_or_none(row.get("CDiffRate"))
        t = str(row.get("CTime") or "").strip()
        clock = f"{t[0:2]}:{t[2:4]}:{t[4:6]}" if len(t) >= 6 else t
        return {
            "close": px,
            "pct_change": pct,
            "update_time": clock,
            "symbol": row.get("SymbolID"),
            "is_realtime": True,
        }
    except Exception:
        logger.debug("跑馬燈期交所即時失敗 night=%s", night, exc_info=True)
        return None


def _us_from_snap(us: Dict[str, Any], keys) -> List[Dict[str, Any]]:
    out = []
    mapping = (
        ("道瓊", "dji_px", "dji_pct"),
        ("標普", "spx_px", "spx_pct"),
        ("那斯達克", "ixic_px", "ixic_pct"),
        ("費半", "sox_px", "sox_pct"),
        ("標普期", "es_f_px", "es_f_pct"),
        ("那斯達克期", "nq_f_px", "nq_f_pct"),
        ("道瓊期", "ym_f_px", "ym_f_pct"),
    )
    want = set(keys)
    for name, px_k, pct_k in mapping:
        if name not in want:
            continue
        px = us.get(px_k)
        pct = us.get(pct_k)
        if px is None and pct is None:
            continue
        if px is None:
            # 只有漲跌％也寫，不編造價格
            out.append({"name": name, "text": f"{name} {_fmt_pct(pct)}", "pct": pct})
        else:
            seg = _seg(name, px, pct)
            if seg:
                out.append(seg)
    return out


def _load_us(db_path: str) -> Dict[str, Any]:
    try:
        from us_overnight import load_us_overnight
        from taiwan_market import resolve_market_as_of

        as_of = resolve_market_as_of(db_path)
        us = load_us_overnight(db_path, as_of) if as_of else {}
        if us.get("ok") or us.get("vix") is not None or us.get("dji_pct") is not None:
            return us
    except Exception:
        logger.debug("跑馬燈讀美股快取失敗", exc_info=True)
    return {}


def _short_industry(name: str) -> str:
    try:
        from money_flow import _sector_short_name

        return _sector_short_name(name)
    except Exception:
        ind = str(name or "").strip()
        if ind.endswith("業") and len(ind) > 2:
            return ind[:-1]
        return ind or "產業"


def _ticker_as_of(snap: Optional[Dict[str, Any]], db_path: Optional[str]) -> str:
    for key in ("as_of", "sector_flow_as_of", "chips_as_of", "breadth_as_of"):
        raw = str((snap or {}).get(key) or "").replace("-", "")[:8]
        if len(raw) == 8 and raw.isdigit():
            return raw
    if not db_path:
        return ""
    try:
        from taiwan_market import resolve_market_as_of

        return str(resolve_market_as_of(db_path) or "").replace("-", "")[:8]
    except Exception:
        return ""


def _sector_rank_rows(db_path: str, as_of: str) -> List[Dict[str, Any]]:
    if not db_path or not as_of:
        return []
    import sqlite3

    conn = sqlite3.connect(db_path, timeout=8.0)
    try:
        has = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='daily_sector_flow'"
        ).fetchone()
        if has:
            rows = conn.execute(
                """
                SELECT industry, avg_pct, three_net, COALESCE(stock_n, 0)
                FROM daily_sector_flow
                WHERE date=? AND industry IS NOT NULL AND industry <> '' AND industry <> '未分類'
                """,
                (as_of,),
            ).fetchall()
            out = []
            for ind, avg, three, n in rows or []:
                try:
                    out.append(
                        {
                            "industry": str(ind),
                            "avg_pct": float(avg or 0),
                            "three_net": int(three or 0),
                            "stock_n": int(n or 0),
                        }
                    )
                except (TypeError, ValueError):
                    continue
            if out:
                return out
        from money_flow import compute_sector_rows

        return list(compute_sector_rows(conn, as_of) or [])
    except Exception:
        logger.debug("跑馬燈讀產業列失敗", exc_info=True)
        return []
    finally:
        conn.close()


def _ticker_sector_items(
    db_path: Optional[str],
    snap: Optional[Dict[str, Any]],
    slot: str,
    dt: datetime,
    *,
    live_sectors: Optional[List[Dict[str, Any]]] = None,
) -> List[Dict[str, Any]]:
    """強勢／弱勢族群。盤中只用 MIS 熱快取，不在跑馬燈路徑新打 40 檔。沒列就不寫。"""
    rows = list(live_sectors or [])
    live = bool(rows)
    if not rows and db_path:
        try:
            from money_flow import peek_live_sector_rows

            rows = list(peek_live_sector_rows(db_path) or [])
            live = bool(rows)
        except Exception:
            rows = []
            live = False
    as_of = _ticker_as_of(snap, db_path)
    if not rows:
        rows = _sector_rank_rows(db_path or "", as_of)
    strong: List[Dict[str, Any]] = []
    weak: List[Dict[str, Any]] = []
    if rows:
        ranked = sorted(rows, key=lambda r: float(r.get("avg_pct") or 0), reverse=True)
        strong = [r for r in ranked if float(r.get("avg_pct") or 0) >= 0.15][:2]
        weak = [r for r in reversed(ranked) if float(r.get("avg_pct") or 0) <= -0.15][:2]
    if not strong and not weak:
        inflow = list((snap or {}).get("sector_inflow") or [])[:2]
        outflow = list((snap or {}).get("sector_outflow") or [])[:2]
        today = dt.strftime("%Y%m%d")
        stale = bool(as_of and as_of < today and slot in ("tw_pre", "tw_match", "tw_open"))
        buy_lab = "昨收法人買超" if stale else "法人買超"
        sell_lab = "昨收法人賣超" if stale else "法人賣超"
        items: List[Dict[str, Any]] = []
        for pair in inflow:
            name = pair[0] if isinstance(pair, (list, tuple)) else str(pair)
            short = _short_industry(str(name))
            if short:
                items.append(_ticker_item("法人買超", f"{buy_lab} {short}", kind="status", pct=1.0))
        for pair in outflow:
            name = pair[0] if isinstance(pair, (list, tuple)) else str(pair)
            short = _short_industry(str(name))
            if short:
                items.append(_ticker_item("法人賣超", f"{sell_lab} {short}", kind="status", pct=-1.0))
        return items
    today = dt.strftime("%Y%m%d")
    stale = (not live) and bool(as_of and as_of < today and slot in ("tw_pre", "tw_match", "tw_open"))
    strong_lab = "昨收強勢" if stale else "強勢"
    weak_lab = "昨收弱勢" if stale else "弱勢"
    items = []
    for r in strong:
        short = _short_industry(str(r.get("industry") or ""))
        pct = float(r.get("avg_pct") or 0)
        items.append(_ticker_item(strong_lab, f"{strong_lab} {short}", digits=_fmt_pct(pct), pct=pct, kind="quote"))
    for r in weak:
        short = _short_industry(str(r.get("industry") or ""))
        pct = float(r.get("avg_pct") or 0)
        items.append(_ticker_item(weak_lab, f"{weak_lab} {short}", digits=_fmt_pct(pct), pct=pct, kind="quote"))
    return items


def _ticker_alert_items(
    snap: Optional[Dict[str, Any]],
    db_path: Optional[str],
) -> List[Dict[str, Any]]:
    """只寫有官方數字的警語。沒有真數就不上。"""
    items: List[Dict[str, Any]] = []
    ob = (snap or {}).get("official_breadth") or {}
    if not isinstance(ob, dict):
        ob = {}
    try:
        up = int(ob.get("up_count") or 0)
        down = int(ob.get("down_count") or 0)
        lu = int(ob.get("limit_up") or 0)
        ld = int(ob.get("limit_down") or 0)
    except (TypeError, ValueError):
        up = down = lu = ld = 0
    if up and down and down >= up * 2 and down >= 400:
        items.append(_ticker_item("警語", f"跌家 {down}、漲家 {up}", kind="status", pct=-1.0))
    elif up and down and up >= down * 2 and up >= 400:
        items.append(_ticker_item("廣度", f"漲家 {up}、跌家 {down}", kind="status", pct=1.0))
    if ld >= 30:
        items.append(_ticker_item("警語", f"跌停 {ld} 家", kind="status", pct=-1.0))
    elif lu >= 40:
        items.append(_ticker_item("廣度", f"漲停 {lu} 家", kind="status", pct=1.0))
    lead = (snap or {}).get("futures_lead") or {}
    if isinstance(lead, dict) and str(lead.get("label") or "") == "期貨領跌":
        items.append(_ticker_item("警語", "近20日偏期貨領跌", kind="status", pct=-1.0))
    if str((snap or {}).get("risk_zone") or "") == "elevated":
        items.append(_ticker_item("警語", "加權在相對高檔", kind="status", pct=-0.5))
    if str((snap or {}).get("support_zone") or "") == "building":
        items.append(_ticker_item("觀察", "加權在低檔築底觀察", kind="status", pct=0.5))
    try:
        fr = int((snap or {}).get("falling_risk") or 0)
    except (TypeError, ValueError):
        fr = 0
    if fr >= 60:
        items.append(_ticker_item("警語", "下跌風險偏高", kind="status", pct=-1.0))
    us = {}
    if db_path:
        us = _load_us(db_path)
    try:
        vix = float(us["vix"]) if us.get("vix") is not None else None
    except (TypeError, ValueError):
        vix = None
    if vix is not None and vix >= 25:
        mood = "偏高" if vix < 28 else "恐慌"
        items.append(
            _ticker_item("警語", f"恐慌指數{mood}", digits=f"{vix:.1f}", pct=-1.0, kind="quote")
        )
    return items[:3]


def _ticker_context_items(
    db_path: Optional[str],
    snap: Optional[Dict[str, Any]],
    slot: str,
    dt: datetime,
    *,
    live_sectors: Optional[List[Dict[str, Any]]] = None,
) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    out.extend(_ticker_sector_items(db_path, snap, slot, dt, live_sectors=live_sectors))
    out.extend(_ticker_alert_items(snap, db_path))
    return [x for x in out if x and x.get("text")]


def collect_ticker(
    db_path: str = None,
    *,
    live: Optional[Dict[str, Any]] = None,
    snap: Optional[Dict[str, Any]] = None,
    now: Optional[datetime] = None,
    yahoo: bool = True,
    live_otc: Optional[Dict[str, Any]] = None,
    live_tx: Optional[Dict[str, Any]] = None,
    live_sectors: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """組時段項目。yahoo=False 時不打外網。沒接到的不寫。"""
    from config import taipei_now

    dt = now or taipei_now()
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=TW)
    else:
        dt = dt.astimezone(TW)
    slot = ticker_slot(dt)
    title = SLOT_TITLE.get(slot) or "跑馬燈"
    snap = dict(snap or {})
    if db_path:
        snap["_db_path"] = db_path
    items: List[Dict[str, Any]] = []
    clock = dt.strftime("%H:%M:%S")
    t = dt.time()
    items.append(_ticker_item("此刻", "此刻", digits=clock, kind="clock"))

    want_tx = slot in ("tw_match", "tw_open", "tw_after", "tw_settled", "us_pre", "us_night") and t >= _TX_DAY_OPEN
    want_otc = slot in ("tw_open", "tw_after")
    night_tx = slot in ("us_pre", "us_night", "tw_settled") or t >= _OTC_CLOSE

    if yahoo:
        try:
            from live_quote import fetch_mis_index_quote, fetch_mis_otc_index_quote

            if slot in ("tw_open", "tw_settled", "us_pre") and (live is None or not float((live or {}).get("close") or 0)):
                live = fetch_mis_index_quote(fresh=True, require_session=False) or live
            if want_otc and live_otc is None:
                live_otc = fetch_mis_otc_index_quote(fresh=True)
            if slot in ("tw_settled", "us_pre") and live_otc is None:
                live_otc = fetch_mis_otc_index_quote(fresh=True)
            if want_tx and live_tx is None:
                live_tx = fetch_tx_live(night=bool(night_tx and t >= _OTC_CLOSE))
                if live_tx is None and t < _OTC_CLOSE:
                    live_tx = fetch_tx_live(night=False)
        except Exception:
            logger.debug("跑馬燈補即時失敗", exc_info=True)

    extras = _ticker_context_items(db_path, snap, slot, dt, live_sectors=live_sectors)

    if slot == "tw_pre":
        match_left = _countdown_to(dt, _MATCH_AT)
        tx_left = _countdown_to(dt, _TX_DAY_OPEN)
        if match_left:
            items.append(_ticker_item("試搓", "距離試搓", digits=match_left, kind="count"))
        if tx_left:
            items.append(_ticker_item("台指期開盤", "距離台指期開盤", digits=tx_left, kind="count"))
        items.extend(extras)
        return _ticker_bundle(slot, title, items, clock)

    if slot == "tw_match":
        items.append(_ticker_item("試搓中", "個股試搓價格中", kind="status"))
        tx_left = _countdown_to(dt, _TX_DAY_OPEN)
        if tx_left:
            items.append(_ticker_item("台指期開盤", "距離台指期開盤", digits=tx_left, kind="count"))
        elif t >= _TX_DAY_OPEN:
            tx = _tx_seg(snap, night=False, live=live_tx)
            if tx:
                items.append(_quote_item("台指期", tx))
        items.extend(extras)
        return _ticker_bundle(slot, title, items, clock)

    if slot == "tw_open":
        tw = _tw_index_seg(live, snap)
        if tw:
            items.append(_quote_item("加權", tw))
        otc = _seg("櫃買", (live_otc or {}).get("close"), (live_otc or {}).get("pct_change")) if live_otc else None
        if otc:
            items.append(_quote_item("櫃買", otc))
        tx = _tx_seg(snap, night=False, live=live_tx)
        if tx:
            items.append(_quote_item("台指期", tx))
        items.extend(extras)
        if yahoo:
            items.extend(_quote_item(x["name"], x) for x in _yahoo_many(ASIA_INDEX))
        return _ticker_bundle(slot, title, items, clock)

    if slot == "tw_after":
        items.append(_ticker_item("日盤", "台股日盤收盤", kind="status"))
        if t < _TW_AH_END:
            items.append(_ticker_item("盤後", "加權盤後交易中", kind="status"))
        else:
            items.append(_ticker_item("盤後", "加權盤後已收", kind="status"))
        otc = _seg("櫃買", (live_otc or {}).get("close"), (live_otc or {}).get("pct_change")) if live_otc else None
        if otc:
            items.append(_quote_item("櫃買", otc))
        if t < _TX_DAY_CLOSE:
            tx = _tx_seg(snap, night=False, live=live_tx)
            if tx:
                items.append(_quote_item("台指期", tx))
        items.extend(extras)
        if yahoo:
            items.extend(_quote_item(x["name"], x) for x in _yahoo_many(ASIA_INDEX))
        return _ticker_bundle(slot, title, items, clock)

    if slot == "tw_settled":
        items.extend(_close_pair(live, live_otc, snap))
        if live_tx or (snap or {}).get("futures_night"):
            tx = _tx_seg(snap, night=True, live=live_tx)
            if tx:
                items.append(_quote_item("台指期夜盤", tx))
        items.extend(extras)
        if yahoo:
            items.extend(_quote_item(x["name"], x) for x in _yahoo_many(ASIA_INDEX))
        return _ticker_bundle(slot, title, items, clock)

    if slot == "us_pre":
        items.extend(_close_pair(live, live_otc, snap))
        if yahoo:
            fut = _yahoo_many(US_PRE_FUT)
            if not fut:
                us = _load_us(db_path) if db_path else {}
                fut = _us_from_snap(us, ("標普期", "那斯達克期", "道瓊期"))
            items.extend(_quote_item(x["name"], x) for x in fut)
        else:
            us = _load_us(db_path) if db_path else {}
            items.extend(_quote_item(x["name"], x) for x in _us_from_snap(us, ("標普期", "那斯達克期", "道瓊期")))
        tx = _tx_seg(snap, night=True, live=live_tx)
        if tx:
            items.append(_quote_item("台指期夜盤", tx))
        items.extend(extras)
        return _ticker_bundle(slot, title, items, clock)

    if slot == "us_night":
        cash: List[Dict[str, Any]] = []
        if yahoo:
            cash = _yahoo_many(US_CASH)
        if not cash:
            us = _load_us(db_path) if db_path else {}
            cash = _us_from_snap(us, ("道瓊", "標普", "那斯達克", "費半"))
        items.extend(_quote_item(x["name"], x) for x in cash)
        try:
            from us_overnight import electronics_night_side

            us = _load_us(db_path) if db_path else {}
            side = electronics_night_side(us)
            if side:
                extra = _seg("電子夜盤", extra=side)
                if extra:
                    items.append(_ticker_item("電子夜盤", extra["text"], kind="status", pct=extra.get("pct")))
        except Exception:
            pass
        night = _tx_seg(snap, night=True, live=live_tx)
        if night:
            items.append(_quote_item("台指期夜盤", night))
        items.extend(extras)
        return _ticker_bundle(slot, title, items, clock)

    tw = _tw_index_seg(live, snap)
    if tw:
        items.append(_quote_item("加權", tw, label="加權收盤"))
    otc = _seg("櫃買", (live_otc or {}).get("close"), (live_otc or {}).get("pct_change")) if live_otc else None
    if otc:
        items.append(_quote_item("櫃買", otc, label="櫃買收盤"))
    items.extend(extras)
    return _ticker_bundle(slot, title, items, clock)


def _quote_item(name: str, seg: Dict[str, Any], *, label: str = None) -> Dict[str, Any]:
    body = str(seg.get("text") or "")
    prefix = (label or name) + " "
    if body.startswith(prefix):
        digits = body[len(prefix):]
    else:
        digits = body.replace(name, "", 1).strip()
    return _ticker_item(name, label or name, digits=digits, pct=seg.get("pct"), kind="quote")


def _close_pair(live, live_otc, snap) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    tw = _tw_index_seg(live, snap)
    if tw:
        side = _side_zh(tw.get("pct"))
        lab = f"加權收盤{(' ' + side) if side else ''}"
        out.append(_quote_item("加權", tw, label=lab))
    otc = None
    if live_otc:
        otc = _seg("櫃買", live_otc.get("close"), live_otc.get("pct_change"))
    if not otc:
        otc = _seg("櫃買", (snap or {}).get("otc_close"), (snap or {}).get("otc_chg1_pct"))
    if otc:
        side = _side_zh(otc.get("pct"))
        lab = f"櫃買收盤{(' ' + side) if side else ''}"
        out.append(_quote_item("櫃買", otc, label=lab))
    return out


def _ticker_bundle(slot: str, title: str, items: List[Dict[str, Any]], clock: str) -> Dict[str, Any]:
    items = [x for x in items if x]
    if not any(x.get("name") != "此刻" for x in items):
        return {"slot": slot, "title": title, "items": [], "clock": clock}
    return {"slot": slot, "title": title, "items": items, "clock": clock}



def ticker_plain(bundle: Dict[str, Any]) -> str:
    title = str(bundle.get("title") or "")
    bits = [str(x.get("text") or "") for x in (bundle.get("items") or []) if x.get("text")]
    if not bits:
        return ""
    return f"{title}　" + "　·　".join(bits)


def ticker_html(bundle: Dict[str, Any]) -> str:
    from tg_layout import html_escape

    plain = ticker_plain(bundle)
    if not plain:
        return ""
    return f"<i>{html_escape(plain)}</i>"


def _ticker_font(size: int, *, bold: bool = False):
    from PIL import ImageFont

    try:
        from wayne_navigator import _WEIGHT_BOLD, _WEIGHT_TEXT, _weight_font_path

        path = _weight_font_path(_WEIGHT_BOLD if bold else _WEIGHT_TEXT)
        if path:
            return ImageFont.truetype(path, size)
    except Exception:
        pass
    for path in (
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
    ):
        try:
            return ImageFont.truetype(path, size, index=0)
        except Exception:
            continue
    return ImageFont.load_default()


def _ink_color(pct) -> tuple:
    if pct is None:
        return _INK
    if float(pct) > 0:
        return _UP
    if float(pct) < 0:
        return _DOWN
    return _INK


TICKER_W = 1080
TICKER_H = 96
TICKER_FRAMES = 40
TICKER_FRAME_MS = 55
# 頂底青線各 4px；字與七段從內緣貼齊，避免卡在中間難讀。
TICKER_INK_PAD = 4

_CASIO_ON = (186, 214, 168)
_CASIO_OFF = (32, 44, 52)
_CASIO_MAP = {
    "0": "abcdef",
    "1": "bc",
    "2": "abged",
    "3": "abgcd",
    "4": "fgbc",
    "5": "afgcd",
    "6": "afgcde",
    "7": "abc",
    "8": "abcdefg",
    "9": "abfgcd",
    "-": "g",
}


def _font_bbox(font, text: str):
    try:
        return font.getbbox(text)
    except Exception:
        w = 0.0
        try:
            w = float(font.getlength(text))
        except Exception:
            w = float(len(text or "") * 12)
        size = int(getattr(font, "size", 42) or 42)
        return (0, 0, w, size)


def _ticker_inner_band(h: int = TICKER_H) -> tuple:
    y0 = TICKER_INK_PAD
    y1 = h - TICKER_INK_PAD
    return y0, y1, max(24, y1 - y0)


def _fit_ticker_body_font(inner_h: int):
    """把中文墨水高度拉到幾乎填滿內緣，不要只佔條的中間三分之一。"""
    samples = ("盤", "加", "權", "收", "距", "試", "搓", "台")
    lo, hi = 20, inner_h + 48
    best = _ticker_font(max(24, inner_h - 6), bold=True)
    while lo <= hi:
        mid = (lo + hi) // 2
        font = _ticker_font(mid, bold=True)
        ink_h = 0
        for ch in samples:
            b = _font_bbox(font, ch)
            ink_h = max(ink_h, b[3] - b[1])
        if ink_h <= inner_h - 1:
            best = font
            lo = mid + 1
        else:
            hi = mid - 1
    return best


def _label_sprite(text: str, font, fill, target_h: int):
    """中文墨水垂直拉滿內緣；標點太扁就不硬拉，避免圓點變成長條。"""
    from PIL import Image, ImageDraw

    th = max(1, int(target_h))
    if not text:
        return Image.new("RGBA", (1, th), (0, 0, 0, 0))
    b = _font_bbox(font, text)
    x0, y0b, x1, y1b = b
    w = max(1, int(math.ceil(x1 - x0)) + 2)
    h = max(1, int(math.ceil(y1b - y0b)) + 2)
    tmp = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    ImageDraw.Draw(tmp).text(
        (1 - x0, 1 - y0b),
        text,
        font=font,
        fill=(int(fill[0]), int(fill[1]), int(fill[2]), 255),
    )
    ink = tmp.getbbox()
    if ink:
        tmp = tmp.crop(ink)
    if tmp.size[1] >= max(8, int(th * 0.45)):
        nw = max(1, int(round(tmp.size[0] * th / tmp.size[1])))
        resample = getattr(Image, "Resampling", Image).LANCZOS
        return tmp.resize((nw, th), resample)
    canvas = Image.new("RGBA", (tmp.size[0], th), (0, 0, 0, 0))
    canvas.paste(tmp, (0, (th - tmp.size[1]) // 2), tmp)
    return canvas


def _casio_digit_w(h: int) -> int:
    return max(18, int(round(h * 0.58)))


def _casio_width(text: str, h: int) -> int:
    dw = _casio_digit_w(h)
    gap = max(3, h // 16)
    n = 0
    for ch in str(text or ""):
        if ch == ":":
            n += max(8, dw // 3) + gap
        elif ch in ".,":
            n += max(6, dw // 4) + gap
        elif ch == " ":
            n += dw // 2
        elif ch == "%":
            n += dw + gap
        else:
            n += dw + gap
    return max(1, n)


def _draw_seg_poly(draw, pts, fill):
    draw.polygon(pts, fill=fill)


def _draw_casio_digit(draw, x: float, y: float, w: int, h: int, ch: str, on, off) -> None:
    t = max(3, int(h * 0.14))
    s = 1
    xa, xb = x + t, x + w - t
    ya, yb, yc = y + t, y + h / 2, y + h - t
    segs = {
        "a": [(xa + s, y), (xb - s, y), (xb - s - t, y + t), (xa + s + t, y + t)],
        "g": [
            (xa + s + t, yb - t / 2),
            (xb - s - t, yb - t / 2),
            (xb - s, yb),
            (xb - s - t, yb + t / 2),
            (xa + s + t, yb + t / 2),
            (xa + s, yb),
        ],
        "d": [(xa + s + t, yc), (xb - s - t, yc), (xb - s, y + h), (xa + s, y + h)],
        "f": [(x, ya + s), (x + t, ya + s + t), (x + t, yb - s - t / 2), (x, yb - s)],
        "b": [(x + w, ya + s), (x + w - t, ya + s + t), (x + w - t, yb - s - t / 2), (x + w, yb - s)],
        "e": [(x, yb + s), (x + t, yb + s + t / 2), (x + t, yc - s - t), (x, yc - s)],
        "c": [(x + w, yb + s), (x + w - t, yb + s + t / 2), (x + w - t, yc - s - t), (x + w, yc - s)],
    }
    active = set(_CASIO_MAP.get(ch, ""))
    for name, pts in segs.items():
        _draw_seg_poly(draw, pts, on if name in active else off)


def _draw_casio_text(draw, x: float, y: float, h: int, text: str, on) -> float:
    dw = _casio_digit_w(h)
    gap = max(3, h // 16)
    cx = x
    off = _CASIO_OFF
    for ch in str(text or ""):
        if ch == ":":
            r = max(2, h // 12)
            draw.ellipse((cx, y + h * 0.28 - r, cx + r * 2, y + h * 0.28 + r), fill=on)
            draw.ellipse((cx, y + h * 0.72 - r, cx + r * 2, y + h * 0.72 + r), fill=on)
            cx += max(8, dw // 3) + gap
            continue
        if ch in ".,":
            r = max(2, h // 14)
            draw.ellipse((cx, y + h - r * 2 - 2, cx + r * 2, y + h - 2), fill=on)
            cx += max(6, dw // 4) + gap
            continue
        if ch == " ":
            cx += dw / 2
            continue
        if ch == "%":
            r = max(2, h // 10)
            draw.ellipse((cx, y + 4, cx + r * 2, y + 4 + r * 2), outline=on, width=2)
            draw.line((cx + 2, y + h - 6, cx + dw - 2, y + 8), fill=on, width=2)
            draw.ellipse((cx + dw - r * 2, y + h - 4 - r * 2, cx + dw, y + h - 4), outline=on, width=2)
            cx += dw + gap
            continue
        if ch == "+":
            mid = y + h / 2
            draw.rectangle((cx + dw * 0.2, mid - 2, cx + dw * 0.8, mid + 2), fill=on)
            draw.rectangle((cx + dw * 0.45, y + h * 0.22, cx + dw * 0.55, y + h * 0.78), fill=on)
            cx += dw + gap
            continue
        _draw_casio_digit(draw, cx, y, dw, h, ch if ch in _CASIO_MAP else "8", on, off)
        cx += dw + gap
    return cx


def render_ticker_gif(bundle: Dict[str, Any], save_path: str) -> str:
    """整條從最左跑到最右。中文標籤＋Casio 電子數字。沒有項目就不畫。"""
    from PIL import Image, ImageDraw

    items = [x for x in (bundle.get("items") or []) if x.get("text")]
    if not items:
        return ""
    title = str(bundle.get("title") or "跑馬燈")
    W, H = TICKER_W, TICKER_H
    y0, y1, inner_h = _ticker_inner_band(H)
    body_f = _fit_ticker_body_font(inner_h)
    digit_h = inner_h
    gap = 28

    pieces: List[Tuple[Any, str, tuple, int]] = []
    title_lab = title + "    ·    "
    title_sprite = _label_sprite(title_lab, body_f, _LABEL_FG, inner_h)
    pieces.append((title_sprite, "", _LABEL_FG, title_sprite.size[0]))
    for it in items:
        label = str(it.get("label") or it.get("name") or "")
        digits = str(it.get("digits") or "")
        kind = str(it.get("kind") or "")
        color = _ink_color(it.get("pct"))
        if kind in ("clock", "count"):
            color = _CASIO_ON
        lab = (label + " ") if digits else (str(it.get("text") or label) + "    ·    ")
        fill = _LABEL_FG if digits else color
        sprite = _label_sprite(lab, body_f, fill, inner_h)
        dw = _casio_width(digits, digit_h) if digits else 0
        tw = sprite.size[0] + dw + (gap if digits else 0)
        pieces.append((sprite, digits, color, tw))

    unit_w = max(1, int(round(sum(p[3] for p in pieces))))
    copies = max(3, (W + unit_w + unit_w - 1) // unit_w)
    strip_w = unit_w * copies + 8
    strip = Image.new("RGB", (strip_w, H), _BG)
    sd = ImageDraw.Draw(strip)
    x = 0
    for _copy in range(copies):
        for sprite, digits, color, tw in pieces:
            strip.paste(sprite, (x, y0), sprite)
            if digits:
                _draw_casio_text(sd, x + sprite.size[0], y0, digit_h, digits, color)
            x += tw

    n = TICKER_FRAMES
    frames = []
    for i in range(n):
        ox = int(round(i * unit_w / float(n))) % unit_w
        crop = strip.crop((ox, 0, ox + W, H))
        frame = Image.new("RGB", (W, H), _BG)
        frame.paste(crop, (0, 0))
        dr = ImageDraw.Draw(frame)
        dr.rectangle((0, 0, W - 1, 3), fill=_LABEL_FG)
        dr.rectangle((0, H - 4, W - 1, H - 1), fill=_LABEL_FG)
        frames.append(frame)

    os.makedirs(os.path.dirname(save_path) or ".", exist_ok=True)
    frames[0].save(
        save_path,
        save_all=True,
        append_images=frames[1:],
        duration=TICKER_FRAME_MS,
        loop=0,
        optimize=True,
        disposal=2,
    )
    return save_path


def build_market_ticker(
    db_path: str,
    *,
    live: Optional[Dict[str, Any]] = None,
    snap: Optional[Dict[str, Any]] = None,
    save_dir: str = None,
    now: Optional[datetime] = None,
    yahoo: bool = True,
) -> Dict[str, Any]:
    """回傳 bundle + gif 路徑；失敗就空路徑，頁面仍可送。"""
    bundle = collect_ticker(db_path, live=live, snap=snap, now=now, yahoo=yahoo)
    gif = ""
    if bundle.get("items"):
        try:
            from config import get_charts_dir

            folder = save_dir or get_charts_dir()
            os.makedirs(folder, exist_ok=True)
            path = os.path.join(folder, f"market_ticker_{int(time.time() * 1000)}.gif")
            gif = render_ticker_gif(bundle, path)
        except Exception:
            logger.exception("跑馬燈 GIF 失敗")
            gif = ""
    bundle["gif"] = gif
    bundle["plain"] = ticker_plain(bundle)
    bundle["html"] = ticker_html(bundle)
    return bundle
