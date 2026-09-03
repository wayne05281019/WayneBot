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


def yahoo_exchange(stock_id: str, db_path: Optional[str] = None) -> str:
    sid = str(stock_id or "").strip()
    path = db_path or get_db_path()
    key = f"{path}|{sid}"
    cached = _EX_CACHE.get(key)
    if cached:
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
        conn.close()
        if row:
            market = str(row[0] or "")
    except Exception:
        market = ""
    m = market.upper()
    if m in ("TWO", "TPEX", "OTC", "ROCO", "EM", "ESB", "EMERGING"):
        ex = "TWO"
    else:
        ex = "TW"
    if sid:
        if len(_EX_CACHE) >= _EX_CACHE_MAX:
            _EX_CACHE.clear()
        _EX_CACHE[key] = ex
    return ex


def yahoo_urls(stock_id: str, db_path: Optional[str] = None) -> Tuple[str, str]:
    sid = str(stock_id or "").strip()
    ex = yahoo_exchange(sid, db_path)
    web = f"https://tw.stock.yahoo.com/quote/{sid}.{ex}"
    # 奇摩股市為 RWD；手機另給技術分析頁，避免桌機/手機點同一則卻對不到線圖
    mobile = f"https://tw.stock.yahoo.com/quote/{sid}.{ex}/technical-analysis"
    return web, mobile


def yahoo_income_url(stock_id: str, db_path: Optional[str] = None) -> str:
    sid = str(stock_id or "").strip()
    ex = yahoo_exchange(sid, db_path)
    return f"https://tw.stock.yahoo.com/quote/{sid}.{ex}/income-statement"


def line_yahoo_quote_url(stock_id: str, db_path: Optional[str] = None) -> str:
    """LINE 轉傳：手機點連結開奇摩股市個股頁。"""
    sid = str(stock_id or "").strip()
    if not sid:
        return ""
    ex = yahoo_exchange(sid, db_path)
    return f"https://tw.stock.yahoo.com/quote/{sid}.{ex}"


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
    return f'<a href="{href}">{esc}</a>'


def ranked_stock_anchor(
    rank: int, stock_id: str, stock_name: str = "", db_path: Optional[str] = None
) -> str:
    """1. 代號 股名＝奇摩連結。"""
    return f"{int(rank)}. {html_stock_anchor(stock_id, stock_name, db_path)}"
