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


def tradingview_exchange(stock_id: str, db_path: Optional[str] = None) -> str:
    """TradingView 交易所前綴。興櫃沒有可靠代號就不給。"""
    m = quote_market(stock_id, db_path)
    if m in ("EM", "ESB", "EMERGING"):
        return ""
    if m in ("TWO", "TPEX", "OTC", "ROCO"):
        return "TPEX"
    return "TWSE"


def tradingview_widget_symbol(stock_id: str, db_path: Optional[str] = None) -> str:
    """圖表元件內部代號。使用者看得見的文案仍寫上市／上櫃，不要把此外掛到說明書。"""
    sid = str(stock_id or "").strip()
    if not sid:
        return ""
    ex = tradingview_exchange(sid, db_path)
    if not ex:
        return ""
    return f"{ex}:{sid}"


def tradingview_chart_url(
    stock_id: str, db_path: Optional[str] = None, base_url: str = ""
) -> str:
    """查股圖下 K線：開自家這一檔圖（先進日K）。興櫃不給。"""
    sid = str(stock_id or "").strip()
    if not sid:
        return ""
    if not tradingview_exchange(sid, db_path):
        return ""
    from config import get_public_base_url

    base = (base_url or get_public_base_url()).rstrip("/")
    return f"{base}/k/{sid}"


def yahoo_urls(stock_id: str, db_path: Optional[str] = None) -> Tuple[str, str]:
    sid = str(stock_id or "").strip()
    ex = yahoo_exchange(sid, db_path)
    web = f"https://tw.stock.yahoo.com/quote/{sid}.{ex}"
    # 技術線另開技術分析頁；LINE／股名點進去要用報價頁（第一屏股名＋現價），見 line_yahoo_quote_url。
    mobile = f"https://tw.stock.yahoo.com/quote/{sid}.{ex}/technical-analysis"
    return web, mobile


def yahoo_income_url(stock_id: str, db_path: Optional[str] = None) -> str:
    sid = str(stock_id or "").strip()
    ex = yahoo_exchange(sid, db_path)
    return f"https://tw.stock.yahoo.com/quote/{sid}.{ex}/income-statement"


def line_yahoo_quote_url(stock_id: str, db_path: Optional[str] = None) -> str:
    """奇摩個股報價（RWD）。手機第一屏是這檔股名＋現價。不要改成 /technical-analysis。
    不要把這個網址直接塞進 LINE 正文，會出大圖預覽；LINE 走 yahoo_hop_url。"""
    sid = str(stock_id or "").strip()
    if not sid:
        return ""
    ex = yahoo_exchange(sid, db_path)
    return f"https://tw.stock.yahoo.com/quote/{sid}.{ex}"


def yahoo_hop_url(stock_id: str, base_url: str = "") -> str:
    """LINE 可點的自家中轉；正文不出現 yahoo.com，才不會出奇摩縮圖。"""
    sid = str(stock_id or "").strip()
    if not sid:
        return ""
    from config import get_public_base_url

    base = (base_url or get_public_base_url()).rstrip("/")
    return f"{base}/y/{sid}"


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
