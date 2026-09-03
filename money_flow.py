"""每日資金移動：用庫裡三大法人張數，不抓分點（分點量大，不能先打崩日 K）。

盤後資金輪動＝同一交易日、依 ISIN 產業把外資＋投信＋自營張數加總，
對照前一交易日 delta。這是佈局參考，不是分點、也不是論壇輪動故事。
"""
from __future__ import annotations

import sqlite3
from typing import Any, Dict, List, Optional, Tuple

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


def _latest_date(conn: sqlite3.Connection, db_path: str = "", now=None) -> str:
    path = db_path or ""
    if path:
        as_of, _ = resolve_flow_as_of(path, now=now)
        if as_of:
            return str(as_of).replace("-", "")
    row = conn.execute("SELECT MAX(replace(date,'-','')) FROM daily_quotes").fetchone()
    return str(row[0] or "").replace("-", "")


def resolve_flow_as_of(db_path: str, now=None) -> Tuple[str, Optional[str]]:
    """
    資金輪動基準日：盤後以 fuse 可融合日為準；庫裡當日上市＋上櫃齊才顯示當日。
    回傳 (yyyymmdd, 若落後於應顯示日則附說明 HTML)。
    """
    from config import taipei_now
    from import_health import count_markets, latest_complete_quote_date, sides_complete
    from trading_calendar import format_trading_date_zh, fuse_end_trading_date, tw_session_phase

    now = now or taipei_now()
    cap = fuse_end_trading_date(now)
    complete = latest_complete_quote_date(db_path, now=now) or ""
    lag: Optional[str] = None

    tw_cap, two_cap, total_cap = count_markets(db_path, cap)
    if sides_complete(tw_cap, two_cap) and int(total_cap or 0) > 0:
        as_of = cap
    else:
        as_of = complete or cap

    if as_of > cap:
        as_of = cap

    phase = tw_session_phase(now)
    if cap > as_of and phase in ("after", "open"):
        lag = (
            f"<i>應顯示 {format_trading_date_zh(cap)} 收盤，"
            f"目前僅有 {format_trading_date_zh(as_of)} 資料（盤後更新中或尚未寫入）。</i>"
        )

    return as_of, lag


def catch_up_quotes_to_cap(db_path: str, now=None) -> str:
    """Release／重 deploy 後庫可能只到昨天；盤後按資金時主動補到 fuse 上限。"""
    from config import taipei_now
    from import_health import clear_complete_date_cache, latest_complete_quote_date
    from trading_calendar import fuse_end_trading_date

    now = now or taipei_now()
    cap = fuse_end_trading_date(now)
    complete = latest_complete_quote_date(db_path, now=now) or ""
    if complete >= cap:
        return complete
    try:
        from main_runner import MainRunner

        clear_complete_date_cache(db_path)
        MainRunner(db_path=db_path).run_daily_increment(notify=False)
        from money_flow import recompute_sector_flow

        recompute_sector_flow(db_path, cap)
        clear_complete_date_cache(db_path)
    except Exception:
        import logging

        logging.getLogger(__name__).exception("盤後補齊失敗 cap=%s", cap)
    return latest_complete_quote_date(db_path, now=now) or complete


def _prev_quote_date(conn: sqlite3.Connection, ymd: str) -> str:
    from trading_calendar import is_trading_weekday, normalize_ymd

    ymd = normalize_ymd(ymd)
    cur = ymd
    for _ in range(12):
        row = conn.execute(
            "SELECT MAX(replace(date,'-','')) FROM daily_quotes WHERE replace(date,'-','') < ?",
            (cur,),
        ).fetchone()
        prev = normalize_ymd(row[0] if row else "")
        if not prev:
            return ""
        if is_trading_weekday(prev):
            return prev
        cur = prev
    return ""


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
        as_of, _ = resolve_flow_as_of(path)
        cap = as_of
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
            rows = []
        if not rows:
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


def _yahoo(sid, name, db_path: str = None) -> str:
    from tg_layout import html_escape

    try:
        from stock_links import html_stock_anchor

        return html_stock_anchor(sid, name, db_path)
    except Exception:
        return f"{html_escape(sid)} {html_escape(name)}".strip()


_SECTOR_SHORT = {
    "金融保險業": "金融",
    "半導體業": "半導體",
    "電子零組件業": "電子零組件",
    "電腦及週邊設備業": "電腦",
    "通信網路業": "通信",
    "光電業": "光電",
    "鋼鐵工業": "鋼鐵",
    "建材營造業": "營建",
    "生技醫療業": "生技",
    "航運業": "航運",
}


def _sector_short_name(industry: str) -> str:
    ind = str(industry or "").strip()
    if ind in _SECTOR_SHORT:
        return _SECTOR_SHORT[ind]
    if ind.endswith("業") and len(ind) > 2:
        return ind[:-1]
    return ind or "產業"


def sector_theme_headline(row: Dict[str, Any]) -> str:
    """盤中／盤後最強族標題（對齊 CaryBot「金融扮演撐盤要角」）。"""
    short = _sector_short_name(str(row.get("industry") or ""))
    if str(row.get("mode") or "") == "live":
        avg = float(row.get("avg_pct") or 0)
        if avg >= 0.3:
            return f"{short}扮演撐盤要角"
        if avg >= 0.05:
            return f"{short}盤中走強"
        return f"{short}盤中偏弱"
    three = int(row.get("three_net") or 0)
    avg = float(row.get("avg_pct") or 0)
    if three > 0 and avg >= 0.2:
        return f"{short}扮演撐盤要角"
    if three > 0:
        return f"{short}法人買超居首"
    if three < 0 and avg <= -0.3:
        return f"{short}賣壓偏重"
    return f"{short}資金動向"


def _liquid_stock_meta(conn: sqlite3.Connection, *, limit: int = 360) -> Dict[str, Dict[str, Any]]:
    """近一日高成交現股母體（供盤中 MIS 掃描，不寫庫）。"""
    ind_expr = _industry_expr()
    etf = _not_etf_clause()
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        f"""
        SELECT q.stock_id, q.stock_name, {ind_expr} AS industry, q.turnover_k
        FROM daily_quotes q
        LEFT JOIN stock_universe u ON u.stock_id = q.stock_id
        WHERE replace(q.date,'-','') = (
            SELECT MAX(replace(date,'-','')) FROM daily_quotes
        )
        {etf}
          AND COALESCE(q.turnover_k, 0) >= 30000
        ORDER BY q.turnover_k DESC
        LIMIT ?
        """,
        (int(limit),),
    ).fetchall()
    out: Dict[str, Dict[str, Any]] = {}
    for r in rows:
        sid = str(r["stock_id"])
        out[sid] = {
            "stock_id": sid,
            "stock_name": str(r["stock_name"] or sid),
            "industry": str(r["industry"] or "未分類"),
            "turnover_k": float(r["turnover_k"] or 0),
        }
    return out


def compute_live_sector_rows(db_path: str, now=None) -> List[Dict[str, Any]]:
    """盤中最強族：MIS 即時均漲 × 量權重聚合（不寫庫、不用盤後法人）。"""
    from live_quote import is_live_merge_window

    if not is_live_merge_window(now):
        return []
    from midday_review import fetch_mis_batch

    conn = sqlite3.connect(db_path)
    try:
        meta = _liquid_stock_meta(conn)
    finally:
        conn.close()
    if not meta:
        return []
    live = fetch_mis_batch(list(meta.keys()), db_path)
    if not live:
        return []
    buckets: Dict[str, Dict[str, Any]] = {}
    for sid, q in live.items():
        info = meta.get(sid)
        if not info:
            continue
        px = float(q.get("close") or q.get("price") or 0)
        if px <= 0:
            continue
        pct = float(q.get("pct") or 0)
        vol = float(q.get("volume") or 0)
        if vol <= 0:
            vol = 1.0
        turn = px * vol
        ind = str(info["industry"])
        b = buckets.setdefault(
            ind,
            {
                "industry": ind,
                "mode": "live",
                "three_net": 0,
                "sample_n": 0,
                "turn_sum": 0.0,
                "pct_sum": 0.0,
                "up_n": 0,
            },
        )
        b["sample_n"] += 1
        b["turn_sum"] += turn
        b["pct_sum"] += pct * turn
        if pct > 0:
            b["up_n"] += 1
    rows: List[Dict[str, Any]] = []
    for b in buckets.values():
        if int(b["sample_n"]) < 3:
            continue
        turn_sum = float(b["turn_sum"] or 0)
        avg_pct = round(float(b["pct_sum"]) / turn_sum, 2) if turn_sum > 0 else 0.0
        rows.append(
            {
                "industry": b["industry"],
                "mode": "live",
                "three_net": 0,
                "avg_pct": avg_pct,
                "sample_n": int(b["sample_n"]),
                "up_ratio": round(int(b["up_n"]) / int(b["sample_n"]), 2),
                "_live_meta": meta,
                "_live_quotes": live,
            }
        )
    rows.sort(key=lambda x: (float(x["avg_pct"]), int(x["sample_n"])), reverse=True)
    return rows


def sector_representative_stocks_live(
    db_path: str,
    industry: str,
    *,
    meta: Dict[str, Dict[str, Any]],
    live_quotes: Dict[str, Dict[str, Any]],
    ymd: str,
    limit: int = 10,
) -> List[Dict[str, Any]]:
    """盤中族內代表股：今日漲幅 + 獲利% + 量能。"""
    conn = sqlite3.connect(db_path)
    picks: List[Dict[str, Any]] = []
    try:
        for sid, q in live_quotes.items():
            info = meta.get(sid)
            if not info or str(info.get("industry")) != str(industry):
                continue
            px = float(q.get("close") or q.get("price") or 0)
            if px <= 0:
                continue
            pct = float(q.get("pct") or 0)
            vol = float(q.get("volume") or 0)
            gain = _gain_pct_cal60(conn, sid, ymd)
            score = pct * 25.0 + max(0.0, gain) + px * max(vol, 1.0) / 500000.0
            picks.append(
                {
                    "stock_id": sid,
                    "stock_name": str(q.get("name") or info.get("stock_name") or sid),
                    "pct_change": round(pct, 2),
                    "gain_pct": round(gain, 1),
                    "volume": vol,
                    "score": score,
                }
            )
    finally:
        conn.close()
    picks.sort(key=lambda x: (x["score"], x["pct_change"], x["gain_pct"]), reverse=True)
    return picks[: int(limit)]


def _gain_pct_cal60(conn: sqlite3.Connection, stock_id: str, ymd: str) -> float:
    rows = conn.execute(
        """
        SELECT date, close FROM daily_quotes
        WHERE stock_id=? AND replace(date,'-','') <= ?
        ORDER BY date
        """,
        (str(stock_id), str(ymd).replace("-", "")),
    ).fetchall()
    if len(rows) < 2:
        return 0.0
    import pandas as pd

    from decision_card_signals import profit_pct_cal60_series

    df = pd.DataFrame(rows, columns=["date", "close"])
    try:
        return float(profit_pct_cal60_series(df).iloc[-1])
    except (TypeError, ValueError, IndexError):
        return 0.0


def sector_representative_stocks(
    conn: sqlite3.Connection,
    ymd: str,
    industry: str,
    *,
    limit: int = 10,
) -> List[Dict[str, Any]]:
    """族內代表股：法人買超 + 獲利% + 成交額加權（非 Cary 熱力圖）。"""
    ymd = str(ymd or "").replace("-", "")
    ind_expr = _industry_expr()
    etf = _not_etf_clause()
    conn.row_factory = sqlite3.Row
    raw = conn.execute(
        f"""
        SELECT q.stock_id, q.stock_name, q.close, q.pct_change, q.volume, q.turnover_k,
               q.foreign_net, q.trust_net, q.dealer_net,
               (q.foreign_net+q.trust_net+q.dealer_net) AS three_net
        FROM daily_quotes q
        LEFT JOIN stock_universe u ON u.stock_id = q.stock_id
        WHERE replace(q.date,'-','')=? AND {ind_expr}=? {etf}
        """,
        (ymd, str(industry)),
    ).fetchall()
    picks: List[Dict[str, Any]] = []
    for r in raw:
        sid = str(r["stock_id"])
        three = int(r["three_net"] or 0)
        turn = float(r["turnover_k"] or 0)
        gain = _gain_pct_cal60(conn, sid, ymd)
        score = three + turn / 50000.0 + max(0.0, gain) * 50.0
        picks.append(
            {
                "stock_id": sid,
                "stock_name": str(r["stock_name"] or sid),
                "three_net": three,
                "gain_pct": round(gain, 1),
                "pct_change": float(r["pct_change"] or 0),
                "score": score,
            }
        )
    picks.sort(key=lambda x: (x["score"], x["three_net"], x["gain_pct"]), reverse=True)
    return picks[: int(limit)]


def format_sector_theme_brief(
    db_path: str,
    ymd: str,
    top_row: Dict[str, Any],
    *,
    mode: str = "",
) -> str:
    """盤中／盤後最強族 + 族內代表股（Telegram HTML）。"""
    from tg_layout import html_metrics_tight, pct_text, qty_text, section

    live_mode = mode == "live" or str(top_row.get("mode") or "") == "live"
    if live_mode:
        if float(top_row.get("avg_pct") or 0) <= 0:
            return ""
        meta = top_row.get("_live_meta") or {}
        quotes = top_row.get("_live_quotes") or {}
        reps = sector_representative_stocks_live(
            db_path,
            str(top_row["industry"]),
            meta=meta,
            live_quotes=quotes,
            ymd=ymd,
        )
        if not reps:
            return ""
        headline = sector_theme_headline(top_row)
        n = int(top_row.get("sample_n") or 0)
        avg = float(top_row.get("avg_pct") or 0)
        lines = [
            f"<b>盤中最強族｜{headline}</b>",
            f"<i>{top_row['industry']}　均漲 {avg:+.2f}%（MIS {n} 檔）</i>",
        ]
        for i, r in enumerate(reps, start=1):
            title = _yahoo(r["stock_id"], r["stock_name"], db_path)
            lines.append(
                f"{i}. {title}\n"
                + html_metrics_tight(
                    f"獲利 {r['gain_pct']:.1f}%",
                    pct_text(r["pct_change"]),
                )
            )
        return section(*lines)

    if int(top_row.get("three_net") or 0) <= 0:
        return ""
    conn = sqlite3.connect(db_path)
    try:
        reps = sector_representative_stocks(conn, ymd, str(top_row["industry"]))
    finally:
        conn.close()
    if not reps:
        return ""
    headline = sector_theme_headline(top_row)
    three = int(top_row["three_net"])
    lines = [
        f"<b>盤後最強族｜{headline}</b>",
        f"<i>{top_row['industry']}　法人 {qty_text(three)}</i>",
    ]
    for i, r in enumerate(reps, start=1):
        title = _yahoo(r["stock_id"], r["stock_name"], db_path)
        lines.append(
            f"{i}. {title}\n"
            + html_metrics_tight(
                f"獲利 {r['gain_pct']:.1f}%",
                qty_text(int(r["three_net"])),
            )
        )
    return section(*lines)


def _sector_entry(r: Dict[str, Any], db_path: str = None) -> str:
    """一族用＝＝產業名＝＝當標題；買超／賣超那行加 ★，才跟張數列分開。"""
    from tg_layout import html_escape, html_metrics_tight, qty_text, pct_text

    three = int(r["three_net"])
    name = html_escape(r["industry"])
    lines = [
        f"＝＝{name}＝＝",
        html_metrics_tight(qty_text(three), pct_text(r["avg_pct"])),
    ]
    d = int(r.get("three_delta") or 0)
    lines.append("較前日　持平" if d == 0 else f"較前日　{html_metrics_tight(qty_text(d))}")
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
        lines.append(f"★ {tag}　{_yahoo(sid, sname, db_path)}　{html_metrics_tight(qty_text(lots))}")
    return "\n".join(lines)


def _flow_stock_lines(items: List[str]) -> List[str]:
    """族與族、檔與檔之間空一行，才不會糊成一塊。"""
    out: List[str] = []
    for i, bit in enumerate(items):
        if i:
            out.append("")
        out.append(bit)
    return out


def format_sector_rotation_html(
    db_path: str = None,
    yyyymmdd: str = None,
    now=None,
    lag: Optional[str] = None,
) -> str:
    from tg_layout import kv_compact, section, join_dashed, title_line

    path = db_path or get_db_path()
    conn = sqlite3.connect(path)
    resolved, resolved_lag = resolve_flow_as_of(path, now=now)
    ymd_in = None
    if yyyymmdd:
        ymd_in = str(yyyymmdd).replace("-", "")
        # 早上海選可能帶昨日 as_of；庫裡已有更新完整日時標題跟 fuse 上限
        ymd = resolved if resolved and resolved > ymd_in else ymd_in
        lag = lag if lag is not None else resolved_lag
    else:
        ymd, lag = resolved, (lag if lag is not None else resolved_lag)
    if not ymd:
        conn.close()
        return ""
    rows = compute_sector_rows(conn, ymd)
    if not rows and ymd_in and ymd != ymd_in:
        ymd = ymd_in
        rows = compute_sector_rows(conn, ymd)
    conn.close()
    if not rows:
        return ""
    top_row = rows[0]
    chip_abs = sum(abs(int(r["three_net"])) for r in rows)
    from trading_calendar import format_trading_date_zh

    ymd_s = format_trading_date_zh(ymd)
    inflow = [r for r in rows if int(r["three_net"]) > 0][:3]
    outflow = sorted([r for r in rows if int(r["three_net"]) < 0], key=lambda x: x["three_net"])[:3]
    accel = sorted(rows, key=lambda x: int(x["three_delta"]), reverse=True)
    accel = [r for r in accel if int(r["three_delta"]) > 0 and int(r["three_net"]) > 0][:3]

    blocks = [
        title_line("盤後資金輪動", ymd_s, ""),
    ]
    if lag:
        blocks.append(lag)
    blocks.append(
        section(
            kv_compact("單位", "張（產業加總三大法人，非分點）"),
            kv_compact("用途", "佈局對照：熱族＋族內代表股，不作單獨訊號"),
        ),
    )
    if chip_abs == 0:
        blocks.append("當日法人張數加總為 0，先等盤後法人寫進庫再看輪動。")
        return join_dashed(*blocks)
    theme = ""
    try:
        from live_quote import is_live_merge_window

        if is_live_merge_window(now):
            live_rows = compute_live_sector_rows(path, now=now)
            if live_rows:
                theme = format_sector_theme_brief(path, ymd, live_rows[0], mode="live")
    except Exception:
        import logging

        logging.getLogger(__name__).debug("盤中最強族略過", exc_info=True)
    if not theme and int(top_row.get("three_net") or 0) > 0:
        theme = format_sector_theme_brief(path, ymd, top_row, mode="post")
    if theme:
        blocks.append(theme)
    if inflow:
        blocks.append(
            section(
                "<b>資金流入（法人買超最多的 3 族）</b>",
                *_flow_stock_lines([_sector_entry(r, path) for r in inflow]),
            )
        )
    if outflow:
        blocks.append(
            section(
                "<b>資金流出（法人賣超最多的 3 族）</b>",
                *_flow_stock_lines([_sector_entry(r, path) for r in outflow]),
            )
        )
    if accel and {r["industry"] for r in accel} != {r["industry"] for r in inflow}:
        blocks.append(
            section("<b>較前日加碼</b>", *_flow_stock_lines([_sector_entry(r, path) for r in accel]))
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
    now=None,
) -> str:
    """盤後資金輪動＋當日三大法人排行；不含持股／觀察（各走自己的選單）。"""
    del user_id
    path = db_path or get_db_path()
    conn = sqlite3.connect(path)
    lag = None
    if yyyymmdd:
        ymd = str(yyyymmdd).replace("-", "")
    else:
        ymd, lag = resolve_flow_as_of(path, now=now)
    if not ymd:
        conn.close()
        return "⚠️ 還沒有日 K，無法看資金移動。"

    from import_health import audit_import
    from tg_layout import kv_compact, section, join_dashed, title_line, html_metrics_tight, qty_text, pct_text
    from trading_calendar import format_trading_date_zh

    health = audit_import(path, ymd)
    cover = f"上市 {health['tw']}　上櫃 {health['two']}"
    if health.get("problems"):
        cover += "　⚠️ " + "；".join(health["problems"])
    else:
        cover += "　開盤日兩邊都齊"

    def line(r, col: str, rank: int) -> str:
        n = int(r[col] or 0)
        pct = float(r["pct_change"] or 0)
        title = _yahoo(r["stock_id"], r["stock_name"], path)
        return f"{rank}. {title}\n{html_metrics_tight(qty_text(n), pct_text(pct))}"

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
    conn.close()

    ymd_s = format_trading_date_zh(ymd)
    rotation = format_sector_rotation_html(path, ymd, now=now, lag=lag)
    blocks = []
    if rotation:
        blocks.append(rotation)
    elif lag:
        blocks.append(lag)
    blocks.extend(
        [
            title_line("個股資金", ymd_s, ""),
            section(kv_compact("覆蓋", cover), kv_compact("單位", "張（三大法人，非分點）")),
        ]
    )
    blocks.append(
        section(
            "<b>外資買超</b>",
            *_flow_stock_lines([line(r, "foreign_net", i) for i, r in enumerate(buy_f, start=1)]),
        )
    )
    blocks.append(
        section(
            "<b>外資賣超</b>",
            *_flow_stock_lines([line(r, "foreign_net", i) for i, r in enumerate(sell_f, start=1)]),
        )
    )
    trust_rows = [r for r in buy_t if int(r["trust_net"] or 0) > 0][:6]
    blocks.append(
        section(
            "<b>投信買超</b>",
            *_flow_stock_lines([line(r, "trust_net", i) for i, r in enumerate(trust_rows, start=1)]),
        )
    )
    if hot:
        bits = []
        for i, r in enumerate(hot, start=1):
            three = int(r["three_net"] or 0)
            title = _yahoo(r["stock_id"], r["stock_name"], path)
            bits.append(
                f"{i}. {title}\n"
                + html_metrics_tight(
                    f"量 {qty_text(int(r['volume']), signed=False)}",
                    pct_text(r["pct_change"]),
                    f"法人 {qty_text(three)}",
                )
            )
        blocks.append(section("<b>短線熱（量大＋波動，對照當沖／隔日沖）</b>", *_flow_stock_lines(bits)))

    return join_dashed(*blocks)

