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
_TAIFEX_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Accept": "application/json",
    "Origin": "https://mis.taifex.com.tw",
    "Referer": "https://mis.taifex.com.tw/",
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
        logger.debug("期交所即時失敗 night=%s", night, exc_info=True)
        return None
