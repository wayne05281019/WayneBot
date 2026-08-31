"""產業說明：用官方月營收、季報、同業中位數、當日法人加總，講人話。

不是內幕、不是法人研報。高低決策卡仍是少賠的主軸；這頁只幫你看懂「這族官方數字現在長怎樣」。
"""
from __future__ import annotations

import sqlite3
from typing import Any, Dict, List, Optional

try:
    from config import get_db_path
except Exception:
    def get_db_path():
        return "data/wayne_market.db"


def _median(vals: List[float]) -> Optional[float]:
    nums = sorted(float(v) for v in vals if v is not None)
    if not nums:
        return None
    n = len(nums)
    mid = n // 2
    if n % 2:
        return nums[mid]
    return (nums[mid - 1] + nums[mid]) / 2.0


def _asof(db_path: str) -> str:
    try:
        from import_health import latest_complete_quote_date

        d = latest_complete_quote_date(db_path)
        if d:
            return str(d).replace("-", "")
    except Exception:
        pass
    conn = sqlite3.connect(db_path)
    row = conn.execute("SELECT MAX(replace(date,'-','')) FROM daily_quotes").fetchone()
    conn.close()
    return str(row[0] or "").replace("-", "")


def _universe_row(conn: sqlite3.Connection, sid: str) -> Dict[str, Any]:
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        "SELECT stock_id, stock_name, market_type, asset_type, industry FROM stock_universe WHERE stock_id=?",
        (sid,),
    ).fetchone()
    if not row:
        q = conn.execute(
            "SELECT stock_id, stock_name FROM daily_quotes WHERE stock_id=? ORDER BY date DESC LIMIT 1",
            (sid,),
        ).fetchone()
        if not q:
            return {"stock_id": sid, "stock_name": sid, "asset_type": "", "industry": ""}
        return {
            "stock_id": str(q["stock_id"]),
            "stock_name": str(q["stock_name"] or sid),
            "asset_type": "",
            "industry": "",
        }
    return {
        "stock_id": str(row["stock_id"]),
        "stock_name": str(row["stock_name"] or sid),
        "asset_type": str(row["asset_type"] or ""),
        "industry": str(row["industry"] or "").strip(),
    }


def _vs_peer(mine: Optional[float], med: Optional[float], unit: str = "pt") -> str:
    if mine is None or med is None:
        return "同業數字不夠，先看這檔自己的。"
    diff = float(mine) - float(med)
    ad = abs(diff)
    if ad < 3:
        return f"跟同業差不多（差 {diff:+.1f}{unit}）"
    if diff > 0:
        if ad >= 15:
            return f"比同業明顯較強（高 {diff:.1f}{unit}）"
        return f"比同業略強（高 {diff:.1f}{unit}）"
    if ad >= 15:
        return f"比同業明顯較弱（低 {ad:.1f}{unit}）"
    return f"比同業略弱（低 {ad:.1f}{unit}）"


def industry_snapshot(db_path: str, stock_id: str) -> Dict[str, Any]:
    path = db_path or get_db_path()
    sid = str(stock_id).strip()
    try:
        from fundamentals import ensure_fundamentals_tables

        ensure_fundamentals_tables(path)
    except Exception:
        pass
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    u = _universe_row(conn, sid)
    industry = u.get("industry") or ""
    asset = (u.get("asset_type") or "").upper()
    as_of = _asof(path)

    latest_m = conn.execute("SELECT MAX(yyyymm) FROM monthly_revenue").fetchone()[0] or ""
    latest_q = conn.execute("SELECT MAX(year), MAX(season) FROM quarterly_income").fetchone()
    q_year = int(latest_q[0] or 0)
    q_season = int(latest_q[1] or 0)

    my_m = conn.execute(
        "SELECT * FROM monthly_revenue WHERE stock_id=? ORDER BY yyyymm DESC LIMIT 1",
        (sid,),
    ).fetchone()
    my_q = conn.execute(
        "SELECT * FROM quarterly_income WHERE stock_id=? ORDER BY year DESC, season DESC LIMIT 1",
        (sid,),
    ).fetchone()

    peers_m: List[sqlite3.Row] = []
    peers_q: List[sqlite3.Row] = []
    peer_n = 0
    if industry and industry not in ("ETF", "指數投資證券"):
        peer_n = int(
            conn.execute(
                """
                SELECT COUNT(*) FROM stock_universe
                WHERE industry=? AND is_active=1 AND length(stock_id)=4
                  AND COALESCE(asset_type,'') NOT LIKE 'ETF%'
                """,
                (industry,),
            ).fetchone()[0]
            or 0
        )
        if latest_m:
            peers_m = conn.execute(
                """
                SELECT m.stock_id, m.stock_name, m.yoy_pct, m.mom_pct, m.ytd_yoy_pct, m.revenue
                FROM monthly_revenue m
                JOIN stock_universe u ON u.stock_id = m.stock_id
                WHERE m.yyyymm=? AND u.industry=? AND length(m.stock_id)=4
                  AND COALESCE(u.asset_type,'') NOT LIKE 'ETF%'
                """,
                (latest_m, industry),
            ).fetchall()
        if q_year:
            peers_q = conn.execute(
                """
                SELECT q.stock_id, q.stock_name, q.gross_margin_pct, q.eps
                FROM quarterly_income q
                JOIN stock_universe u ON u.stock_id = q.stock_id
                WHERE q.year=? AND q.season=? AND u.industry=? AND length(q.stock_id)=4
                  AND COALESCE(u.asset_type,'') NOT LIKE 'ETF%'
                """,
                (q_year, q_season, industry),
            ).fetchall()

    three = 0
    if industry and as_of:
        three = int(
            conn.execute(
                """
                SELECT COALESCE(SUM(q.foreign_net+q.trust_net+q.dealer_net),0)
                FROM daily_quotes q
                JOIN stock_universe u ON u.stock_id = q.stock_id
                WHERE replace(q.date,'-','')=? AND u.industry=? AND length(q.stock_id)=4
                  AND COALESCE(u.asset_type,'') NOT LIKE 'ETF%'
                """,
                (as_of, industry),
            ).fetchone()[0]
            or 0
        )
        ranks = conn.execute(
            """
            SELECT u.industry, SUM(q.foreign_net+q.trust_net+q.dealer_net) AS three_net
            FROM daily_quotes q
            JOIN stock_universe u ON u.stock_id = q.stock_id
            WHERE replace(q.date,'-','')=? AND length(q.stock_id)=4
              AND COALESCE(u.asset_type,'') NOT LIKE 'ETF%'
              AND TRIM(COALESCE(u.industry,'')) NOT IN ('', 'ETF', '指數投資證券', '存託憑證')
            GROUP BY u.industry
            HAVING COUNT(*) >= 2
            ORDER BY three_net DESC
            """,
            (as_of,),
        ).fetchall()
        inflow = [str(r["industry"]) for r in ranks if int(r["three_net"] or 0) > 0][:3]
        outflow = [str(r["industry"]) for r in reversed(ranks) if int(r["three_net"] or 0) < 0][:3]
        buy_streak = 0
        sell_streak = 0
        dates = [
            str(r[0])
            for r in conn.execute(
                """
                SELECT DISTINCT replace(date,'-','') AS d FROM daily_quotes
                WHERE replace(date,'-','') <= ? ORDER BY d DESC LIMIT 8
                """,
                (as_of,),
            ).fetchall()
        ]
        for i, d in enumerate(dates):
            net = int(
                conn.execute(
                    """
                    SELECT COALESCE(SUM(q.foreign_net+q.trust_net+q.dealer_net),0)
                    FROM daily_quotes q
                    JOIN stock_universe u ON u.stock_id = q.stock_id
                    WHERE replace(q.date,'-','')=? AND u.industry=? AND length(q.stock_id)=4
                      AND COALESCE(u.asset_type,'') NOT LIKE 'ETF%'
                    """,
                    (d, industry),
                ).fetchone()[0]
                or 0
            )
            if i == 0:
                if net > 0:
                    buy_streak = 1
                elif net < 0:
                    sell_streak = 1
                else:
                    break
                continue
            if buy_streak and net > 0:
                buy_streak += 1
            elif sell_streak and net < 0:
                sell_streak += 1
            else:
                break
    else:
        inflow, outflow = [], []
        buy_streak, sell_streak = 0, 0

    conn.close()

    yoy_med = _median([float(r["yoy_pct"] or 0) for r in peers_m])
    gm_med = _median([float(r["gross_margin_pct"] or 0) for r in peers_q])
    my_yoy = float(my_m["yoy_pct"]) if my_m else None
    my_gm = float(my_q["gross_margin_pct"]) if my_q else None

    stronger, weaker = [], []
    if my_m and peers_m:
        my_y = float(my_m["yoy_pct"] or 0)
        others = [r for r in peers_m if str(r["stock_id"]) != sid]
        stronger = sorted(
            [r for r in others if float(r["yoy_pct"] or 0) > my_y],
            key=lambda r: float(r["yoy_pct"] or 0),
            reverse=True,
        )[:2]
        weaker = sorted(
            [r for r in others if float(r["yoy_pct"] or 0) < my_y],
            key=lambda r: float(r["yoy_pct"] or 0),
        )[:2]

    return {
        "stock_id": sid,
        "stock_name": u.get("stock_name") or sid,
        "industry": industry,
        "asset_type": asset,
        "is_etf": asset.startswith("ETF") or industry in ("ETF", "指數投資證券"),
        "peer_n": peer_n,
        "as_of": as_of,
        "month": str(my_m["yyyymm"]) if my_m else latest_m,
        "my_yoy": my_yoy,
        "my_mom": float(my_m["mom_pct"]) if my_m else None,
        "yoy_med": yoy_med,
        "yoy_n": len(peers_m),
        "year": int(my_q["year"]) if my_q else q_year,
        "season": int(my_q["season"]) if my_q else q_season,
        "my_gm": my_gm,
        "gm_med": gm_med,
        "three_net": three,
        "buy_streak": buy_streak,
        "sell_streak": sell_streak,
        "inflow": inflow,
        "outflow": outflow,
        "stronger": [
            {"stock_id": str(r["stock_id"]), "stock_name": str(r["stock_name"] or ""), "yoy": float(r["yoy_pct"] or 0)}
            for r in stronger
        ],
        "weaker": [
            {"stock_id": str(r["stock_id"]), "stock_name": str(r["stock_name"] or ""), "yoy": float(r["yoy_pct"] or 0)}
            for r in weaker
        ],
    }


def format_industry_html(stock_id: str, db_path: str = None) -> str:
    from tg_layout import html_escape, join_sections, kv, section, title_line

    path = db_path or get_db_path()
    snap = industry_snapshot(path, stock_id)
    sid = snap["stock_id"]
    name = snap["stock_name"]
    blocks = [title_line("產業說明", sid, name)]

    if snap["is_etf"]:
        blocks.append(
            section(
                "這檔是 ETF／指數商品，沒有單一公司的產業面。",
                "看成分與「資金」頁的法人流向即可。進場仍先看高低卡，不要因為盤勢敘事追高。",
            )
        )
        return join_sections(*blocks)

    ind = snap["industry"] or "未分類（母體還沒寫到產業）"
    blocks.append(
        section(
            "<b>這檔是什麼</b>",
            kv("產業", ind),
            kv("同業", f"{snap['peer_n']} 家現股（不含 ETF）" if snap["peer_n"] else "同業名單不足"),
            "產業名來自證交所 ISIN，不是論壇分類。",
        )
    )

    month = str(snap.get("month") or "")
    mlabel = f"{month[:4]}/{month[4:]}" if len(month) >= 6 else (month or "—")
    if snap["my_yoy"] is not None:
        yoy_line = f"這檔 YoY {snap['my_yoy']:+.1f}%"
        if snap["my_mom"] is not None:
            yoy_line += f"　MoM {snap['my_mom']:+.1f}%"
        if snap["yoy_med"] is not None:
            yoy_line += f"　同業中位 YoY {snap['yoy_med']:+.1f}%（{snap['yoy_n']} 家有月報）"
        story = _vs_peer(snap["my_yoy"], snap["yoy_med"], "%")
    else:
        yoy_line = "這檔還沒有月營收列"
        story = "等公司公布、盤後寫進庫再比。"
    gm_line = "這檔還沒有季報列"
    gm_story = ""
    if snap["my_gm"] is not None:
        gm_line = f"{snap['year']}Q{snap['season']} 毛利率 {snap['my_gm']:.1f}%"
        if snap["gm_med"] is not None:
            gm_line += f"　同業中位 {snap['gm_med']:.1f}%"
        gm_story = _vs_peer(snap["my_gm"], snap["gm_med"], "pt")
    blocks.append(
        section(
            "<b>營收看同業</b>",
            kv("月營收", f"{mlabel}　{yoy_line}"),
            story,
            kv("季報", gm_line),
            gm_story,
        )
    )

    as_of = snap["as_of"]
    as_s = f"{as_of[:4]}/{as_of[4:6]}/{as_of[6:]}" if len(as_of) == 8 else (as_of or "—")
    three = int(snap["three_net"] or 0)
    sign = "+" if three > 0 else ""
    if three > 0 and snap["industry"] in (snap.get("inflow") or []):
        flow_story = "這族今天在法人買超最多的前 3 族裡。"
    elif three < 0 and snap["industry"] in (snap.get("outflow") or []):
        flow_story = "這族今天在法人賣超最多的前 3 族裡。"
    elif three > 0:
        flow_story = "這族法人合計買超，但還不是當日最熱的 3 族。"
    elif three < 0:
        flow_story = "這族法人合計賣超。"
    else:
        flow_story = "這族法人加總接近 0，或法人還沒寫進這天。"
    streak_line = "—"
    if int(snap.get("buy_streak") or 0) >= 2:
        streak_line = f"這族法人連 {int(snap['buy_streak'])} 個交易日合計買超"
    elif int(snap.get("sell_streak") or 0) >= 2:
        streak_line = f"這族法人連 {int(snap['sell_streak'])} 個交易日合計賣超"
    elif int(snap.get("buy_streak") or 0) == 1:
        streak_line = "這族今天合計買超（尚未連兩日）"
    elif int(snap.get("sell_streak") or 0) == 1:
        streak_line = "這族今天合計賣超（尚未連兩日）"
    blocks.append(
        section(
            "<b>這族資金</b>",
            kv("基準日", as_s),
            kv("法人合計", f"{sign}{three:,}張"),
            flow_story,
            streak_line,
            "張數是官方法人，不是分點。公開籌碼會落後、也會幌。",
        )
    )

    def _peer_line(rows: List[Dict[str, Any]]) -> str:
        if not rows:
            return "—"
        return "　".join(
            f"<code>{html_escape(r['stock_id'])}</code> {html_escape(r['stock_name'])} {r['yoy']:+.1f}%"
            for r in rows
        )

    if snap["stronger"] or snap["weaker"]:
        blocks.append(
            section(
                "<b>同業月營收對照</b>",
                f"較強　{_peer_line(snap['stronger'])}",
                f"較弱　{_peer_line(snap['weaker'])}",
                "YoY 特別大常常是去年基期低，只當對照，不當成一定噴。",
            )
        )

    blocks.append(
        section(
            "<b>怎麼用</b>",
            "這頁幫你用官方數字看懂這族，不是內幕、也不能替代高低卡。",
            "少賠：靠近 20 日收盤高少追；佈局才對照這頁＋資金輪動。",
            "線型看起來要噴，也先看決策卡有沒有貼月高。產業再好，追高一樣會大賠。",
        )
    )
    return join_sections(*blocks)
