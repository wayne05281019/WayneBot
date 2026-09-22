"""奇摩／期交所連結：網頁版。Telegram 點藍字即開對應走勢。"""
from __future__ import annotations

import sqlite3
from typing import Dict, Optional, Tuple

_YQ = "https://tw.stock.yahoo.com/quote/"
TWII_QUOTE_URL = _YQ + "%5ETWII"
TX_DAY_URL = "https://www.taifex.com.tw/cht/3/futDailyMarketView"
TX_NIGHT_URL = "https://www.taifex.com.tw/cht/3/futAfterhoursMarketView"
T86_URL = "https://www.twse.com.tw/zh/page/trading/fund/T86.html"
MI_INDEX_URL = "https://www.twse.com.tw/zh/page/trading/exchange/MI_INDEX.html"
US_BOARD_URL = "https://tw.stock.yahoo.com/us"

# 名稱→公開頁。Telegram 沒有任意色，藍字只能靠超連結。
NAMED_URLS = {
    "加權指數": TWII_QUOTE_URL,
    "加權": TWII_QUOTE_URL,
    "加權收盤": TWII_QUOTE_URL,
    "加權昨收": TWII_QUOTE_URL,
    "夜盤": TX_NIGHT_URL,
    "台指期": TX_DAY_URL,
    "電子期": TX_DAY_URL,
    "電子期夜盤": TX_NIGHT_URL,
    "美股": US_BOARD_URL,
    "美股收盤": US_BOARD_URL,
    "道瓊": _YQ + "%5EDJI",
    "道指期": _YQ + "YM%3DF",
    "道瓊期貨": _YQ + "YM%3DF",
    "標普": _YQ + "%5EGSPC",
    "標指期": _YQ + "ES%3DF",
    "標普期貨": _YQ + "ES%3DF",
    "那斯達克": _YQ + "%5EIXIC",
    "那指期": _YQ + "NQ%3DF",
    "那斯達克期貨": _YQ + "NQ%3DF",
    "費半": _YQ + "%5ESOX",
    "費半後": _YQ + "%5ESOX",
    "費半盤後": _YQ + "%5ESOX",
    "恐慌": _YQ + "%5EVIX",
    "恐慌指數": _YQ + "%5EVIX",
    "台積": _YQ + "TSM",
    "台積後": _YQ + "TSM",
    "台積美股": _YQ + "TSM",
    "台積美股收盤": _YQ + "TSM",
    "台積美股盤後": _YQ + "TSM",
    "輝達": _YQ + "NVDA",
    "輝達後": _YQ + "NVDA",
    "輝達收盤": _YQ + "NVDA",
    "輝達盤後": _YQ + "NVDA",
    "三大法人": T86_URL,
    "外資": T86_URL,
    "投信": T86_URL,
    "自營": T86_URL,
    "法人": T86_URL,
    "漲跌家數": MI_INDEX_URL,
    "外資台指期": "https://www.taifex.com.tw/cht/3/futContractsDate",
}

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
    from tg_layout import html_listing_suffix

    return f'<a href="{href}">{esc}</a>{html_listing_suffix(tag)}'


def html_named(label: str) -> str:
    """市場／指數名＝藍字超連結；沒登錄的名稱維持黑字。"""
    from tg_layout import html_escape, html_href

    lab = str(label or "").strip()
    url = NAMED_URLS.get(lab)
    if not url:
        return html_escape(lab)
    return html_href(url, lab)


def html_index_anchor(label: str = "加權指數") -> str:
    return html_named(label or "加權指數")


def html_tx_anchor(label: str, *, night: bool = False) -> str:
    lab = str(label or "").strip() or ("夜盤" if night else "台指期")
    if lab in NAMED_URLS:
        return html_named(lab)
    from tg_layout import html_href

    return html_href(TX_NIGHT_URL if night else TX_DAY_URL, lab)


def ranked_stock_anchor(
    rank: int, stock_id: str, stock_name: str = "", db_path: Optional[str] = None
) -> str:
    """1. 代號 股名＝奇摩連結。"""
    return f"{int(rank)}. {html_stock_anchor(stock_id, stock_name, db_path)}"
