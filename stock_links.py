"""奇摩股市連結：網頁版 / 手機版。Telegram 點股名即開對應個股走勢。"""
from __future__ import annotations

import sqlite3
from typing import Dict, Optional, Tuple

try:
    from config import get_db_path
except Exception:
    def get_db_path():
        return "data/wayne_market.db"


_EX_CACHE: Dict[str, str] = {}
_EX_CACHE_MAX = 4096


def quote_market(stock_id: str, db_path: Optional[str] = None) -> str:
    """庫內市場標記：TW／TWO／EM。沒列就空字串。"""
    sid = str(stock_id or "").strip()
    path = db_path or get_db_path()
    key = f"m|{path}|{sid}"
    cached = _EX_CACHE.get(key)
    if cached is not None:
        return cached
    market = ""
    try:
        conn = sqlite3.connect(path)
        row = conn.execute(
            "SELECT market FROM daily_quotes WHERE stock_id=? ORDER BY date DESC LIMIT 1;",
            (sid,),
        ).fetchone()
        if not row:
            try:
                row = conn.execute(
                    "SELECT market FROM stock_directory WHERE stock_id=? LIMIT 1;",
                    (sid,),
                ).fetchone()
            except Exception:
                row = None
        if not row:
            try:
                row = conn.execute(
                    "SELECT market FROM emerging_quotes WHERE stock_id=? ORDER BY date DESC LIMIT 1;",
                    (sid,),
                ).fetchone()
            except Exception:
                row = None
        if not row:
            try:
                row = conn.execute(
                    "SELECT market_type FROM stock_universe WHERE stock_id=? LIMIT 1;",
                    (sid,),
                ).fetchone()
            except Exception:
                row = None
        conn.close()
        if row:
            market = str(row[0] or "")
    except Exception:
        market = ""
    m = str(market or "").strip().upper()
    if sid:
        if len(_EX_CACHE) >= _EX_CACHE_MAX:
            _EX_CACHE.clear()
        _EX_CACHE[key] = m
    return m


def yahoo_exchange(stock_id: str, db_path: Optional[str] = None) -> str:
    m = quote_market(stock_id, db_path)
    if m in ("TWO", "TPEX", "OTC", "ROCO", "EM", "ESB", "EMERGING"):
        return "TWO"
    return "TW"


def listed_kline_ok(stock_id: str, db_path: Optional[str] = None) -> bool:
    """有代號就掛奇摩日K。興櫃一樣開該檔技術分析頁。"""
    return bool(str(stock_id or "").strip())


def kline_page_url(
    stock_id: str,
    db_path: Optional[str] = None,
    base_url: str = "",
    *,
    span: int | None = None,
) -> str:
    """查股圖下 K線：開奇摩股市同一檔日K（技術分析頁預設日線）。不是 TradingView。"""
    sid = str(stock_id or "").strip()
    if not sid or not listed_kline_ok(sid, db_path):
        return ""
    _ = (base_url, span)
    ex = yahoo_exchange(sid, db_path)
    return f"https://tw.stock.yahoo.com/quote/{sid}.{ex}/technical-analysis"


def yahoo_urls(stock_id: str, db_path: Optional[str] = None) -> Tuple[str, str]:
    """兩個都回奇摩報價頁。K線鈕另開技術分析日K。"""
    sid = str(stock_id or "").strip()
    ex = yahoo_exchange(sid, db_path)
    web = f"https://tw.stock.yahoo.com/quote/{sid}.{ex}"
    return web, web


def yahoo_income_url(stock_id: str, db_path: Optional[str] = None) -> str:
    sid = str(stock_id or "").strip()
    ex = yahoo_exchange(sid, db_path)
    return f"https://tw.stock.yahoo.com/quote/{sid}.{ex}/income-statement"


def html_stock_anchor(stock_id: str, stock_name: str = "", db_path: Optional[str] = None) -> str:
    sid = str(stock_id or "").strip()
    name = str(stock_name or "").strip()
    label = f"{sid} {name}".strip() or sid
    web, _mobile = yahoo_urls(sid, db_path)
    esc = (
        label.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    )
    # 個股報價頁較易喚起奇摩股市 App；技術分析留給明確要圖時再用
    href = web.replace("&", "&amp;")
    tag = ""
    try:
        from universe import listing_industry_face

        tag = listing_industry_face(sid, db_path)
    except Exception:
        tag = ""
    if not tag:
        try:
            from wayne_db import listing_zh

            tag = listing_zh(quote_market(sid, db_path))
        except Exception:
            tag = ""
    suffix = f"　{tag}" if tag else ""
    return f'<a href="{href}">{esc}</a>{suffix}'


def ranked_stock_anchor(
    rank: int, stock_id: str, stock_name: str = "", db_path: Optional[str] = None
) -> str:
    """1. 代號 股名＝奇摩連結。"""
    return f"{int(rank)}. {html_stock_anchor(stock_id, stock_name, db_path)}"
