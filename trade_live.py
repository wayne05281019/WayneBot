"""
當沖／隔日沖：盤中 MIS 複核 + 卡片顯示現價與報價時間（HH:MM）。
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from midday_review import fetch_mis_batch

logger = logging.getLogger(__name__)

DAYTRADE_PCT_MIN = 2.0
DAYTRADE_PCT_MAX = 8.5
OVERNIGHT_PCT_MIN = 2.5


def _pct_from_close(price: float, close: float) -> Optional[float]:
    if close <= 0 or price <= 0:
        return None
    return (price - close) / close * 100.0


def _quote_hhmm(update_time: str) -> str:
    s = (update_time or "").strip()
    if len(s) >= 5 and s[2] == ":":
        return s[:5]
    return s or "—"


def format_trade_live_line(live: Dict[str, Any]) -> str:
    """現價 + 漲跌 + 很小的報價時間。"""
    price = live.get("price")
    if price is None:
        return ""
    chg = live.get("change")
    pct = live.get("pct")
    hhmm = _quote_hhmm(live.get("update_time", ""))
    if chg is not None and pct is not None:
        sign = "+" if chg >= 0 else ""
        body = f"現價 <b>{price:.2f}</b>（{sign}{chg:.2f} / {sign}{pct:.2f}%）"
    elif pct is not None:
        sign = "+" if pct >= 0 else ""
        body = f"現價 <b>{price:.2f}</b>（{sign}{pct:.2f}%）"
    else:
        body = f"現價 <b>{price:.2f}</b>"
    return f"{body} <i>{hhmm}</i>"


def passes_daytrade_live(live: Dict[str, Any]) -> bool:
    price = live.get("price")
    close = live.get("yesterday_close")
    if price is None or close is None or close <= 0:
        return False
    pct = _pct_from_close(float(price), float(close))
    if pct is None:
        return False
    return DAYTRADE_PCT_MIN <= pct <= DAYTRADE_PCT_MAX


def passes_overnight_live(live: Dict[str, Any]) -> bool:
    price = live.get("price")
    close = live.get("yesterday_close")
    if price is None or close is None or close <= 0:
        return False
    pct = _pct_from_close(float(price), float(close))
    if pct is None:
        return False
    return pct >= OVERNIGHT_PCT_MIN


def apply_trade_live(
    rows: List[Dict[str, Any]],
    db_path: str,
    bucket: str,
) -> List[Dict[str, Any]]:
    """
    對候選名單批次 MIS 報價，只保留此刻仍符合條件的標的，並附上 live 欄位。
    bucket: 'daytrade' | 'overnight'
    """
    if not rows:
        return []

    codes = [str(r.get("code", "")).strip() for r in rows if r.get("code")]
    if not codes:
        return []

    try:
        quotes = fetch_mis_batch(codes, db_path)
    except Exception as e:
        logger.warning("apply_trade_live MIS failed: %s", e)
        quotes = {}

    if not quotes:
        logger.warning("apply_trade_live: MIS 無報價，改顯示昨收候選（未盤中複核）")
        return [dict(r, _live_skipped=True) for r in rows]

    checker = passes_daytrade_live if bucket == "daytrade" else passes_overnight_live
    out: List[Dict[str, Any]] = []
    pending_ranks: Dict[str, int] = {}
    for r in rows:
        code = str(r.get("code", "")).strip()
        q = quotes.get(code)
        if not q or q.get("price") is None and q.get("close") is None:
            continue
        close = q.get("yesterday_close")
        price = float(q.get("price") or q.get("close"))
        pct = _pct_from_close(price, float(close)) if close else q.get("pct")
        live = {
            "price": price,
            "change": q.get("change"),
            "pct": pct,
            "update_time": q.get("update_time", ""),
            "yesterday_close": close,
            "volume": q.get("volume"),
        }
        if not checker(live):
            continue
        item = dict(r)
        vol = int(q.get("volume") or 0)
        if vol > 0:
            pending_ranks[code] = vol
        item["live"] = live
        out.append(item)
    if pending_ranks:
        try:
            from live_quote import live_vol_rank_120_batch

            ranks = live_vol_rank_120_batch(db_path, pending_ranks)
            for item in out:
                code = str(item.get("code", "")).strip()
                rank = ranks.get(code)
                if rank is not None:
                    item["live"]["vol_rank_120"] = rank
                    item["vol_rank_120"] = rank
        except Exception:
            logger.debug("live vol rank batch failed", exc_info=True)
    if not out and rows and quotes:
        logger.info("apply_trade_live: 盤中條件全過濾，改顯示昨收候選")
        return [dict(r, _live_filtered=True) for r in rows]
    return out
