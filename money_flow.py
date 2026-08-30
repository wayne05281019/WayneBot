"""每日資金移動：用庫裡三大法人張數，不抓分點（分點量大，不能先打崩日 K）。"""
from __future__ import annotations

import sqlite3
from typing import Any, Dict, List, Optional

try:
    from config import get_db_path
except Exception:
    def get_db_path():
        return "data/wayne_market.db"


def _latest_date(conn: sqlite3.Connection) -> str:
    row = conn.execute("SELECT MAX(date) FROM daily_quotes").fetchone()
    return str(row[0] or "")


def _top(conn: sqlite3.Connection, ymd: str, col: str, desc: bool, limit: int = 6) -> List[sqlite3.Row]:
    order = "DESC" if desc else "ASC"
    conn.row_factory = sqlite3.Row
    return conn.execute(
        f"""
        SELECT stock_id, stock_name, market, close, pct_change, volume,
               foreign_net, trust_net, dealer_net,
               (foreign_net+trust_net+dealer_net) AS three_net
        FROM daily_quotes
        WHERE date=? AND length(stock_id)=4
        ORDER BY {col} {order}
        LIMIT ?
        """,
        (ymd, limit),
    ).fetchall()


def _quotes_for(conn: sqlite3.Connection, ymd: str, sids: List[str]) -> Dict[str, sqlite3.Row]:
    if not sids:
        return {}
    conn.row_factory = sqlite3.Row
    q = ",".join("?" * len(sids))
    rows = conn.execute(
        f"""
        SELECT stock_id, stock_name, close, pct_change, volume,
               foreign_net, trust_net, dealer_net
        FROM daily_quotes WHERE date=? AND stock_id IN ({q})
        """,
        [ymd, *sids],
    ).fetchall()
    return {str(r["stock_id"]): r for r in rows}


def _verdict(pct: float, three: int, foreign: int) -> str:
    if pct < 0 and three > 0:
        return "當日虧但法人買超，資金還在進，可對照紀律再等"
    if pct < 0 and foreign > 0 and three <= 0:
        return "價跌外資買、其他法人對沖，先看外資連買會不會續"
    if pct < 0 and three < 0:
        return "價跌且法人賣超，短線等資金回來機率較低"
    if pct > 0 and three > 0:
        return "價漲法人續買"
    if pct > 0 and three < 0:
        return "價漲法人賣，像在出貨或避險"
    return "法人近乎平"


def format_flow_html(
    db_path: str = None,
    user_id: str = "",
    yyyymmdd: str = None,
) -> str:
    path = db_path or get_db_path()
    conn = sqlite3.connect(path)
    ymd = yyyymmdd or _latest_date(conn)
    if not ymd:
        conn.close()
        return "⚠️ 還沒有日 K，無法看資金移動。"

    from import_health import audit_import
    from tg_layout import kv, section, join_sections, title_line

    health = audit_import(path, ymd)
    cover = f"上市 {health['tw']}　上櫃 {health['two']}"
    if health.get("problems"):
        cover += "　⚠️ " + "；".join(health["problems"])
    else:
        cover += "　開盤日兩邊都齊"

    def line(r, col: str) -> str:
        n = int(r[col] or 0)
        pct = float(r["pct_change"] or 0)
        name = str(r["stock_name"] or "")
        sid = str(r["stock_id"])
        sign = "+" if n > 0 else ""
        return f"<code>{sid}</code> {name}　{sign}{n:,}張　{pct:+.1f}%"

    buy_f = _top(conn, ymd, "foreign_net", True)
    sell_f = _top(conn, ymd, "foreign_net", False)
    buy_t = _top(conn, ymd, "trust_net", True)
    hot = conn.execute(
        """
        SELECT stock_id, stock_name, pct_change, volume, foreign_net, trust_net, dealer_net,
               (foreign_net+trust_net+dealer_net) AS three_net
        FROM daily_quotes
        WHERE date=? AND length(stock_id)=4 AND volume>=3000 AND ABS(pct_change)>=1.5
        ORDER BY ABS(foreign_net) DESC LIMIT 6
        """,
        (ymd,),
    ).fetchall()

    hold_ids: List[str] = []
    watch_ids: List[str] = []
    holds: List[Dict[str, Any]] = []
    if user_id:
        try:
            from wayne_db import get_user_portfolio, get_user_watchlist

            holds = get_user_portfolio(path, user_id)
            hold_ids = [str(h.get("stock_code") or h.get("stock_id") or "") for h in holds]
            watch_ids = [str(w.get("stock_code") or "") for w in get_user_watchlist(path, user_id)]
        except Exception:
            hold_ids, watch_ids, holds = [], [], []

    qmap = _quotes_for(conn, ymd, [s for s in hold_ids + watch_ids if s])
    conn.close()

    ymd_s = f"{ymd[:4]}/{ymd[4:6]}/{ymd[6:]}"
    blocks = [
        title_line("資金移動", ymd_s, ""),
        section(kv("覆蓋", cover), kv("單位", "張（三大法人，不是分點）")),
    ]
    blocks.append(
        section(
            "<b>外資買超</b>",
            *[line(r, "foreign_net") for r in buy_f],
        )
    )
    blocks.append(
        section(
            "<b>外資賣超</b>",
            *[line(r, "foreign_net") for r in sell_f],
        )
    )
    blocks.append(
        section(
            "<b>投信買超</b>",
            *[line(r, "trust_net") for r in buy_t if int(r["trust_net"] or 0) > 0][:6],
        )
    )
    if hot:
        bits = []
        for r in hot:
            three = int(r["three_net"] or 0)
            bits.append(
                f"<code>{r['stock_id']}</code> {r['stock_name']}　量 {int(r['volume']):,}張　"
                f"{float(r['pct_change'] or 0):+.1f}%　法人 {three:+,}張"
            )
        blocks.append(section("<b>短線熱（量大＋波動，對照當沖／隔日沖）</b>", *bits))

    if holds:
        bits = []
        for h in holds:
            sid = str(h.get("stock_code") or "")
            q = qmap.get(sid)
            if not q:
                bits.append(f"<code>{sid}</code> 當日無報價")
                continue
            cost = float(h.get("cost_price") or 0)
            close = float(q["close"] or 0)
            pnl = ((close - cost) / cost * 100.0) if cost else 0.0
            three = int(q["foreign_net"] or 0) + int(q["trust_net"] or 0) + int(q["dealer_net"] or 0)
            bits.append(
                f"<code>{sid}</code> {q['stock_name']}　成本 {cost:g} 收 {close:g}　{pnl:+.1f}%　"
                f"法人 {three:+,}張\n　{_verdict(float(q['pct_change'] or 0), three, int(q['foreign_net'] or 0))}"
            )
        blocks.append(section("<b>你的持股 vs 當日資金</b>", *bits))
    elif user_id:
        blocks.append(section("<b>持股</b>", "尚未記買入。有持股後這裡會對照法人是否還在買。"))

    if watch_ids:
        bits = []
        for sid in watch_ids[:8]:
            q = qmap.get(sid)
            if not q:
                continue
            three = int(q["foreign_net"] or 0) + int(q["trust_net"] or 0) + int(q["dealer_net"] or 0)
            bits.append(
                f"<code>{sid}</code> {q['stock_name']}　{float(q['pct_change'] or 0):+.1f}%　法人 {three:+,}張"
            )
        if bits:
            blocks.append(section("<b>觀察清單</b>", *bits))

    blocks.append(
        "分點（每一券商據點）還沒匯入，以免把日 K／法人打崩。資金移動先看三大法人張數。"
    )
    return join_sections(*blocks)
