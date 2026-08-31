"""每日資金移動：用庫裡三大法人張數，不抓分點（分點量大，不能先打崩日 K）。

盤後資金輪動＝同一交易日、依 ISIN 產業把外資＋投信＋自營張數加總，
對照前一交易日 delta。這是佈局參考，不是分點、也不是論壇輪動故事。
"""
from __future__ import annotations

import sqlite3
from typing import Any, Dict, List, Tuple

try:
    from config import get_db_path
except Exception:
    def get_db_path():
        return "data/wayne_market.db"


def ensure_sector_flow_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS daily_sector_flow (
            date TEXT NOT NULL,
            industry TEXT NOT NULL,
            stock_n INTEGER DEFAULT 0,
            volume INTEGER DEFAULT 0,
            turnover_k REAL DEFAULT 0,
            foreign_net INTEGER DEFAULT 0,
            trust_net INTEGER DEFAULT 0,
            dealer_net INTEGER DEFAULT 0,
            three_net INTEGER DEFAULT 0,
            prev_three_net INTEGER DEFAULT 0,
            three_delta INTEGER DEFAULT 0,
            avg_pct REAL DEFAULT 0,
                top_buy_id TEXT DEFAULT '',
                top_buy_name TEXT DEFAULT '',
                top_buy_three INTEGER DEFAULT 0,
                top_sell_id TEXT DEFAULT '',
                top_sell_name TEXT DEFAULT '',
                top_sell_three INTEGER DEFAULT 0,
            PRIMARY KEY (date, industry)
        );
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_sector_flow_date ON daily_sector_flow(date);")
    cols = {r[1] for r in conn.execute("PRAGMA table_info(daily_sector_flow)")}
    for name, spec in (
        ("top_sell_id", "TEXT DEFAULT ''"),
        ("top_sell_name", "TEXT DEFAULT ''"),
        ("top_sell_three", "INTEGER DEFAULT 0"),
    ):
        if name not in cols:
            conn.execute(f"ALTER TABLE daily_sector_flow ADD COLUMN {name} {spec}")


def _latest_date(conn: sqlite3.Connection, db_path: str = "") -> str:
    path = db_path or ""
    if path:
        try:
            from import_health import latest_complete_quote_date

            complete = latest_complete_quote_date(path)
            if complete:
                return str(complete).replace("-", "")
        except Exception:
            pass
    row = conn.execute("SELECT MAX(replace(date,'-','')) FROM daily_quotes").fetchone()
    return str(row[0] or "").replace("-", "")


def _prev_quote_date(conn: sqlite3.Connection, ymd: str) -> str:
    ymd = str(ymd or "").replace("-", "")
    row = conn.execute(
        "SELECT MAX(replace(date,'-','')) FROM daily_quotes WHERE replace(date,'-','') < ?",
        (ymd,),
    ).fetchone()
    return str(row[0] or "").replace("-", "")


def _industry_expr() -> str:
    return """
        CASE
            WHEN TRIM(COALESCE(u.industry, '')) != '' THEN TRIM(u.industry)
            ELSE '未分類'
        END
    """


def _not_etf_clause() -> str:
    return """
        AND length(q.stock_id)=4
        AND COALESCE(u.asset_type, '') NOT LIKE 'ETF%'
        AND TRIM(COALESCE(u.industry, '')) NOT IN ('ETF', '指數投資證券', '存託憑證')
    """


def compute_sector_rows(conn: sqlite3.Connection, ymd: str) -> List[Dict[str, Any]]:
    """依產業加總當日三大法人張數與價量。"""
    ymd = str(ymd or "").replace("-", "")
    if not ymd:
        return []
    prev = _prev_quote_date(conn, ymd)
    conn.row_factory = sqlite3.Row
    ind = _industry_expr()
    etf = _not_etf_clause()
    agg = conn.execute(
        f"""
        SELECT {ind} AS industry,
               COUNT(*) AS stock_n,
               SUM(q.volume) AS volume,
               SUM(q.turnover_k) AS turnover_k,
               SUM(q.foreign_net) AS foreign_net,
               SUM(q.trust_net) AS trust_net,
               SUM(q.dealer_net) AS dealer_net,
               SUM(q.foreign_net+q.trust_net+q.dealer_net) AS three_net,
               AVG(q.pct_change) AS avg_pct
        FROM daily_quotes q
        LEFT JOIN stock_universe u ON u.stock_id = q.stock_id
        WHERE replace(q.date,'-','')=? {etf}
        GROUP BY 1
        HAVING COUNT(*) >= 2
        """,
        (ymd,),
    ).fetchall()
    prev_map: Dict[str, int] = {}
    if prev:
        for r in conn.execute(
            f"""
            SELECT {ind} AS industry,
                   SUM(q.foreign_net+q.trust_net+q.dealer_net) AS three_net
            FROM daily_quotes q
            LEFT JOIN stock_universe u ON u.stock_id = q.stock_id
            WHERE replace(q.date,'-','')=? {etf}
            GROUP BY 1
            """,
            (prev,),
        ):
            prev_map[str(r["industry"])] = int(r["three_net"] or 0)
    tops = conn.execute(
        f"""
        SELECT {ind} AS industry, q.stock_id, q.stock_name,
               (q.foreign_net+q.trust_net+q.dealer_net) AS three_net
        FROM daily_quotes q
        LEFT JOIN stock_universe u ON u.stock_id = q.stock_id
        WHERE replace(q.date,'-','')=? {etf}
        """,
        (ymd,),
    ).fetchall()
    best: Dict[str, Tuple[str, str, int]] = {}
    worst: Dict[str, Tuple[str, str, int]] = {}
    for r in tops:
        industry = str(r["industry"])
        three = int(r["three_net"] or 0)
        cur = best.get(industry)
        if cur is None or three > cur[2]:
            best[industry] = (str(r["stock_id"]), str(r["stock_name"] or ""), three)
        w = worst.get(industry)
        if w is None or three < w[2]:
            worst[industry] = (str(r["stock_id"]), str(r["stock_name"] or ""), three)
    rows: List[Dict[str, Any]] = []
    for r in agg:
        industry = str(r["industry"])
        three = int(r["three_net"] or 0)
        prev_n = int(prev_map.get(industry, 0))
        buy_id, buy_name, buy_three = best.get(industry, ("", "", 0))
        sell_id, sell_name, sell_three = worst.get(industry, ("", "", 0))
        rows.append(
            {
                "date": ymd,
                "industry": industry,
                "stock_n": int(r["stock_n"] or 0),
                "volume": int(r["volume"] or 0),
                "turnover_k": float(r["turnover_k"] or 0),
                "foreign_net": int(r["foreign_net"] or 0),
                "trust_net": int(r["trust_net"] or 0),
                "dealer_net": int(r["dealer_net"] or 0),
                "three_net": three,
                "prev_three_net": prev_n,
                "three_delta": three - prev_n,
                "avg_pct": float(r["avg_pct"] or 0),
                "top_buy_id": buy_id,
                "top_buy_name": buy_name,
                "top_buy_three": int(buy_three or 0),
                "top_sell_id": sell_id,
                "top_sell_name": sell_name,
                "top_sell_three": int(sell_three or 0),
            }
        )
    rows.sort(key=lambda x: x["three_net"], reverse=True)
    return rows


def recompute_sector_flow(db_path: str = None, ymd: str = None, lookback: int = 8) -> int:
    """把最近幾個交易日的產業輪動寫進 daily_sector_flow，供佈局對照。"""
    path = db_path or get_db_path()
    conn = sqlite3.connect(path)
    ensure_sector_flow_table(conn)
    dates: List[str] = []
    if ymd:
        dates = [str(ymd).replace("-", "")]
        prev = _prev_quote_date(conn, dates[0])
        if prev:
            dates.append(prev)
    else:
        try:
            from import_health import latest_complete_quote_date

            cap = latest_complete_quote_date(path)
        except Exception:
            cap = None
        if cap:
            rows = conn.execute(
                """
                SELECT DISTINCT replace(date,'-','') AS d FROM daily_quotes
                WHERE replace(date,'-','') <= ?
                ORDER BY d DESC LIMIT ?
                """,
                (str(cap).replace("-", ""), int(lookback)),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT DISTINCT replace(date,'-','') AS d FROM daily_quotes ORDER BY d DESC LIMIT ?",
                (int(lookback),),
            ).fetchall()
        dates = [str(r[0]) for r in rows]
    written = 0
    for d in dates:
        rows = compute_sector_rows(conn, d)
        conn.execute("DELETE FROM daily_sector_flow WHERE date=?", (d,))
        for r in rows:
            conn.execute(
                """
                INSERT INTO daily_sector_flow (
                    date, industry, stock_n, volume, turnover_k,
                    foreign_net, trust_net, dealer_net, three_net,
                    prev_three_net, three_delta, avg_pct,
                    top_buy_id, top_buy_name, top_buy_three,
                    top_sell_id, top_sell_name, top_sell_three
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    r["date"], r["industry"], r["stock_n"], r["volume"], r["turnover_k"],
                    r["foreign_net"], r["trust_net"], r["dealer_net"], r["three_net"],
                    r["prev_three_net"], r["three_delta"], r["avg_pct"],
                    r["top_buy_id"], r["top_buy_name"], r["top_buy_three"],
                    r["top_sell_id"], r["top_sell_name"], r["top_sell_three"],
                ),
            )
            written += 1
    conn.commit()
    conn.close()
    return written


def sector_flow_maps(db_path: str, ymd: str) -> Dict[str, Any]:
    """海選標籤用：流入前三產業、流出前三產業。"""
    conn = sqlite3.connect(db_path)
    rows = compute_sector_rows(conn, ymd)
    conn.close()
    inflow = [r for r in rows if int(r["three_net"]) > 0][:3]
    outflow = sorted([r for r in rows if int(r["three_net"]) < 0], key=lambda x: x["three_net"])[:3]
    return {
        "inflow": {r["industry"]: i + 1 for i, r in enumerate(inflow)},
        "outflow": {r["industry"]: i + 1 for i, r in enumerate(outflow)},
        "inflow_rows": inflow,
        "outflow_rows": outflow,
    }


def annotate_items_with_sector_flow(db_path: str, ymd: str, items: List[Dict[str, Any]]) -> None:
    """海選／當沖名單標上當日產業輪動進／出，當佈局參考，不改排名公式。"""
    if not items:
        return
    annotate_screen_results(db_path, ymd, {"_": items})


def annotate_screen_results(db_path: str, ymd: str, results: Dict[str, Any]) -> None:
    """產業輪動只算一次，再批次標到所有名單。"""
    lists = [lst for lst in (results or {}).values() if isinstance(lst, list) and lst]
    if not lists:
        return
    maps = sector_flow_maps(db_path, ymd)
    ids = []
    seen = set()
    for lst in lists:
        for item in lst:
            sid = str(item.get("stock_id") or item.get("code") or "").strip()
            if sid and sid not in seen:
                seen.add(sid)
                ids.append(sid)
    industries: Dict[str, str] = {}
    conn = sqlite3.connect(db_path)
    try:
        if ids:
            qmarks = ",".join("?" * len(ids))
            for sid, ind in conn.execute(
                f"SELECT stock_id, industry FROM stock_universe WHERE stock_id IN ({qmarks})",
                ids,
            ):
                industries[str(sid)] = (str(ind or "").strip() or "未分類")
        for lst in lists:
            for item in lst:
                sid = str(item.get("stock_id") or item.get("code") or "").strip()
                if not sid:
                    continue
                ind = industries.get(sid) or industry_of(conn, sid)
                item["industry"] = ind
                if ind in maps["inflow"]:
                    item["sector_inflow"] = True
                    item["sector_flow_label"] = f"輪動進·{ind}"
                elif ind in maps["outflow"]:
                    item["sector_outflow"] = True
                    item["sector_flow_label"] = f"輪動出·{ind}"
    finally:
        conn.close()


def industry_of(conn: sqlite3.Connection, stock_id: str) -> str:
    row = conn.execute(
        "SELECT industry FROM stock_universe WHERE stock_id=?",
        (str(stock_id),),
    ).fetchone()
    ind = str(row[0] or "").strip() if row else ""
    return ind or "未分類"


def _sector_entry(r: Dict[str, Any]) -> str:
    """一族用＝＝產業名＝＝當標題；買超／賣超那行加 ▸，才跟張數列分開。"""
    from tg_layout import html_escape, html_qty_tight, html_pct_tight

    three = int(r["three_net"])
    name = html_escape(r["industry"])
    lines = [
        f"＝＝{name}＝＝",
        f"{html_qty_tight(three)}　{html_pct_tight(r['avg_pct'])}",
    ]
    d = int(r.get("three_delta") or 0)
    lines.append("較前日　持平" if d == 0 else f"較前日　{html_qty_tight(d)}")
    if three < 0:
        sid = r.get("top_sell_id") or ""
        sname = r.get("top_sell_name") or ""
        lots = int(r.get("top_sell_three") or 0)
        tag = "賣超最多"
    else:
        sid = r.get("top_buy_id") or ""
        sname = r.get("top_buy_name") or ""
        lots = int(r.get("top_buy_three") or 0)
        tag = "買超最多"
    if sid:
        lines.append(
            f"▸ {tag}　<code>{html_escape(sid)}</code> {html_escape(sname)}　{html_qty_tight(lots)}"
        )
    return "\n".join(lines)


def _flow_stock_lines(items: List[str]) -> List[str]:
    """族與族、檔與檔之間空一行，才不會糊成一塊。"""
    out: List[str] = []
    for i, bit in enumerate(items):
        if i:
            out.append("")
        out.append(bit)
    return out


def format_sector_rotation_html(db_path: str = None, yyyymmdd: str = None) -> str:
    from tg_layout import kv, section, join_dashed, title_line

    path = db_path or get_db_path()
    conn = sqlite3.connect(path)
    ymd = yyyymmdd or _latest_date(conn, path)
    if not ymd:
        conn.close()
        return ""
    rows = compute_sector_rows(conn, ymd)
    conn.close()
    if not rows:
        return ""
    chip_abs = sum(abs(int(r["three_net"])) for r in rows)
    ymd_s = f"{ymd[:4]}/{ymd[4:6]}/{ymd[6:]}"
    inflow = [r for r in rows if int(r["three_net"]) > 0][:3]
    outflow = sorted([r for r in rows if int(r["three_net"]) < 0], key=lambda x: x["three_net"])[:3]
    accel = sorted(rows, key=lambda x: int(x["three_delta"]), reverse=True)
    accel = [r for r in accel if int(r["three_delta"]) > 0 and int(r["three_net"]) > 0][:3]

    blocks = [
        title_line("盤後資金輪動", ymd_s, ""),
        section(
            kv("單位", "張（產業加總三大法人，不是分點）"),
            kv("用途", "佈局對照：熱族＋族內代表股，不單獨當訊號"),
        ),
    ]
    if chip_abs == 0:
        blocks.append("當日法人張數加總為 0，先等盤後法人寫進庫再看輪動。")
        return join_dashed(*blocks)
    if inflow:
        blocks.append(
            section("<b>資金流入（法人買超最多的 3 族）</b>", *_flow_stock_lines([_sector_entry(r) for r in inflow]))
        )
    if outflow:
        blocks.append(
            section("<b>資金流出（法人賣超最多的 3 族）</b>", *_flow_stock_lines([_sector_entry(r) for r in outflow]))
        )
    if accel and {r["industry"] for r in accel} != {r["industry"] for r in inflow}:
        blocks.append(section("<b>較前日加碼</b>", *_flow_stock_lines([_sector_entry(r) for r in accel])))
    blocks.append(
        "官方法人張數＋價量才進這張表。分點、論壇輪動故事不抓。"
        "法人也會幌，只當佈局參考因素之一，要對照股價與你的紀律。"
    )
    return join_dashed(*blocks)


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
    ymd = yyyymmdd or _latest_date(conn, path)
    if not ymd:
        conn.close()
        return "⚠️ 還沒有日 K，無法看資金移動。"

    from import_health import audit_import
    from tg_layout import kv, section, join_dashed, title_line, html_escape, html_qty_tight, html_pct_tight

    health = audit_import(path, ymd)
    cover = f"上市 {health['tw']}　上櫃 {health['two']}"
    if health.get("problems"):
        cover += "　⚠️ " + "；".join(health["problems"])
    else:
        cover += "　開盤日兩邊都齊"

    def line(r, col: str) -> str:
        n = int(r[col] or 0)
        pct = float(r["pct_change"] or 0)
        name = html_escape(str(r["stock_name"] or ""))
        sid = html_escape(str(r["stock_id"]))
        return f"<code>{sid}</code> {name}\n{html_qty_tight(n)}　{html_pct_tight(pct)}"

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
    rotation = format_sector_rotation_html(path, ymd)
    blocks = []
    if rotation:
        blocks.append(rotation)
    blocks.extend(
        [
            title_line("個股資金", ymd_s, ""),
            section(kv("覆蓋", cover), kv("單位", "張（三大法人，不是分點）")),
        ]
    )
    blocks.append(
        section(
            "<b>外資買超</b>",
            *_flow_stock_lines([line(r, "foreign_net") for r in buy_f]),
        )
    )
    blocks.append(
        section(
            "<b>外資賣超</b>",
            *_flow_stock_lines([line(r, "foreign_net") for r in sell_f]),
        )
    )
    blocks.append(
        section(
            "<b>投信買超</b>",
            *_flow_stock_lines(
                [line(r, "trust_net") for r in buy_t if int(r["trust_net"] or 0) > 0][:6]
            ),
        )
    )
    if hot:
        bits = []
        for r in hot:
            three = int(r["three_net"] or 0)
            bits.append(
                f"<code>{html_escape(r['stock_id'])}</code> {html_escape(r['stock_name'])}\n"
                f"量 {html_qty_tight(int(r['volume']), signed=False)}　{html_pct_tight(r['pct_change'])}\n"
                f"法人 {html_qty_tight(three)}"
            )
        blocks.append(section("<b>短線熱（量大＋波動，對照當沖／隔日沖）</b>", *_flow_stock_lines(bits)))

    if holds:
        bits = []
        for h in holds:
            sid = str(h.get("stock_code") or "")
            q = qmap.get(sid)
            if not q:
                bits.append(f"<code>{html_escape(sid)}</code> 當日無報價")
                continue
            cost = float(h.get("cost_price") or 0)
            close = float(q["close"] or 0)
            pnl = ((close - cost) / cost * 100.0) if cost else 0.0
            three = int(q["foreign_net"] or 0) + int(q["trust_net"] or 0) + int(q["dealer_net"] or 0)
            bits.append(
                f"<code>{html_escape(sid)}</code> {html_escape(q['stock_name'])}\n"
                f"成本 {cost:g}　收 {close:g}　{html_pct_tight(pnl)}\n"
                f"法人 {html_qty_tight(three)}\n"
                f"{_verdict(float(q['pct_change'] or 0), three, int(q['foreign_net'] or 0))}"
            )
        blocks.append(section("<b>你的持股 vs 當日資金</b>", *_flow_stock_lines(bits)))
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
                f"<code>{html_escape(sid)}</code> {html_escape(q['stock_name'])}\n"
                f"{html_pct_tight(q['pct_change'])}　法人 {html_qty_tight(three)}"
            )
        if bits:
            blocks.append(section("<b>觀察清單</b>", *_flow_stock_lines(bits)))

    blocks.append(
        "分點不抓。輪動與個股資金都用官方法人張數＋價量；這是佈局對照，不是主力 instant 動向。"
    )
    return join_dashed(*blocks)
