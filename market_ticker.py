"""台指期即時報價 helper（期交所 MIS）。

跑馬燈面（GIF／html／collect）已下架；話筒大盤頁不再送 ticker。
本檔只留 `biaoke_verify.fetch_tx_ohlc` 等仍在用的 TAIFEX 取價工具。
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Tuple

import requests

logger = logging.getLogger("WayneBot.MarketTicker")

_TAIFEX_QUOTE_URL = "https://mis.taifex.com.tw/futures/api/getQuoteList"
_TAIFEX_CHART_1M_URL = "https://mis.taifex.com.tw/futures/api/getChartData1M"
_TAIFEX_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Accept": "application/json",
    "Origin": "https://mis.taifex.com.tw",
    "Referer": "https://mis.taifex.com.tw/",
    "Content-Type": "application/json",
}


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


def _taifex_quote_payload(*, night: bool) -> Dict[str, str]:
    return {
        "MarketType": "1" if night else "0",
        "SymbolType": "F",
        "KindID": "1",
        "CID": "",
        "ExpireMonth": "",
        "SymbolID": "",
        "Fcode": "",
    }


def fetch_tx_quote_row(*, night: bool = False, timeout: float = 2.2) -> Optional[Dict[str, Any]]:
    """期交所 MIS 近月臺指期原始列（日盤 *-F／夜盤 *-M）。沒接到回 None。"""
    try:
        resp = requests.post(
            _TAIFEX_QUOTE_URL,
            json=_taifex_quote_payload(night=night),
            headers=_TAIFEX_HEADERS,
            timeout=timeout,
        )
        resp.raise_for_status()
        rows = ((resp.json() or {}).get("RtData") or {}).get("QuoteList") or []
        return pick_tx_quote_row(rows, night=night)
    except Exception:
        logger.debug("期交所報價列失敗 night=%s", night, exc_info=True)
        return None


def fetch_tx_live(*, night: bool = False, timeout: float = 2.2) -> Optional[Dict[str, Any]]:
    """期交所即時報價（不寫庫）。沒接到回 None。"""
    try:
        row = fetch_tx_quote_row(night=night, timeout=timeout)
        if not row:
            return None
        px = _num_or_none(row.get("CLastPrice"))
        if not px or px <= 0:
            return None
        pct = _num_or_none(row.get("CDiffRate"))
        # 官方漲跌對照＝CRefPrice（日盤結算／參考價），不准用前一夜盤收
        ref = _num_or_none(row.get("CRefPrice"))
        t = str(row.get("CTime") or "").strip()
        clock = f"{t[0:2]}:{t[2:4]}:{t[4:6]}" if len(t) >= 6 else t
        out = {
            "close": px,
            "pct_change": pct,
            "update_time": clock,
            "symbol": row.get("SymbolID"),
            "is_realtime": True,
        }
        if ref and ref > 0:
            out["ref"] = float(ref)
            out["prev_close"] = float(ref)
        return out
    except Exception:
        logger.debug("期交所即時失敗 night=%s", night, exc_info=True)
        return None


def fetch_tx_night_chart_1m(
    *,
    timeout: float = 6.0,
) -> Optional[Dict[str, Any]]:
    """夜盤進行中：MIS 近月 TX *-M 的 1 分官方柱（15:00→05:00）。

    回 {symbol, date, update_time, open, high, low, close, volume, ref, ticks}
    ticks＝[[HHMMSS, o, h, l, c, v], ...]；沒接到或不夠兩根回 None。不准捏假柱。
    """
    row = fetch_tx_quote_row(night=True, timeout=min(3.0, float(timeout)))
    if not row:
        return None
    sid = str(row.get("SymbolID") or "").strip()
    if not sid.endswith("-M"):
        return None
    last = _num_or_none(row.get("CLastPrice"))
    if not last or last <= 0:
        return None
    try:
        resp = requests.post(
            _TAIFEX_CHART_1M_URL,
            json={"MarketType": "1", "SymbolID": sid},
            headers=_TAIFEX_HEADERS,
            timeout=timeout,
        )
        resp.raise_for_status()
        data = ((resp.json() or {}).get("RtData") or {})
        raw_ticks = data.get("Ticks") or []
    except Exception:
        logger.debug("期交所夜盤 1 分圖失敗 sid=%s", sid, exc_info=True)
        return None
    ticks: List[List[str]] = []
    for item in raw_ticks:
        if not isinstance(item, (list, tuple)) or len(item) < 5:
            continue
        stamp = str(item[0] or "").strip()
        if len(stamp) == 4 and stamp.isdigit():
            stamp = stamp + "00"
        if len(stamp) < 6 or not stamp[:6].isdigit():
            continue
        # 夜盤窗：15:00 起或 05:00 前
        if not (stamp >= "150000" or stamp < "050000"):
            continue
        try:
            o = float(item[1])
            h = float(item[2])
            lo = float(item[3])
            c = float(item[4])
            v = float(item[5]) if len(item) > 5 else 0.0
        except (TypeError, ValueError):
            continue
        if c <= 0:
            continue
        ticks.append([stamp[:6], f"{o:.2f}", f"{h:.2f}", f"{lo:.2f}", f"{c:.2f}", str(int(round(v)))])
    if len(ticks) < 2:
        return None
    t = str(row.get("CTime") or "").strip()
    clock = f"{t[0:2]}:{t[2:4]}:{t[4:6]}" if len(t) >= 6 else t
    return {
        "symbol": sid,
        "date": str(row.get("CDate") or "").replace("-", "")[:8],
        "update_time": clock,
        "open": _num_or_none(row.get("COpenPrice")),
        "high": _num_or_none(row.get("CHighPrice")),
        "low": _num_or_none(row.get("CLowPrice")),
        "close": last,
        "volume": int(_num_or_none(row.get("CTotalVolume")) or 0),
        "ref": _num_or_none(row.get("CRefPrice")),
        "ticks": ticks,
        "source": "taifex_mis",
        "is_realtime": True,
    }
