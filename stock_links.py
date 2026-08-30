"""奇摩股市連結：網頁版 / 手機版。Telegram 點股名即開對應個股走勢。"""
from __future__ import annotations

import sqlite3
from typing import Optional, Tuple

try:
    from config import get_db_path
except Exception:
    def get_db_path():
        return "data/wayne_market.db"


def yahoo_exchange(stock_id: str, db_path: Optional[str] = None) -> str:
    sid = str(stock_id or "").strip()
    path = db_path or get_db_path()
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
        return "TWO"
    return "TW"


def yahoo_urls(stock_id: str, db_path: Optional[str] = None) -> Tuple[str, str]:
    sid = str(stock_id or "").strip()
    ex = yahoo_exchange(sid, db_path)
    web = f"https://tw.stock.yahoo.com/quote/{sid}.{ex}"
    # 奇摩股市為 RWD；手機另給技術分析頁，避免桌機/手機點同一則卻對不到線圖
    mobile = f"https://tw.stock.yahoo.com/quote/{sid}.{ex}/technical-analysis"
    return web, mobile


def html_stock_anchor(stock_id: str, stock_name: str = "", db_path: Optional[str] = None) -> str:
    sid = str(stock_id or "").strip()
    name = str(stock_name or "").strip()
    label = f"{sid} {name}".strip() or sid
    web, mobile = yahoo_urls(sid, db_path)
    esc = (
        label.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    )
    return (
        f'<a href="{web}">{esc}</a> '
        f'<a href="{web}">網頁</a>／<a href="{mobile}">手機技術線</a>'
    )
