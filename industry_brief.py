"""產業說明：用官方月營收、季報、同業中位數、當日法人加總，講人話。

不是內幕、不是法人研報。高低決策卡仍是少賠的主軸；這頁只幫你看懂「本產業官方數字現在長怎樣」。
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
    row = conn.execute("SELECT MAX(date) FROM daily_quotes").fetchone()
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
            return {
                "stock_id": sid,
                "stock_name": sid,
                "market_type": "",
                "asset_type": "",
                "industry": "",
            }
        return {
            "stock_id": str(q["stock_id"]),
            "stock_name": str(q["stock_name"] or sid),
            "market_type": "",
            "asset_type": "",
            "industry": "",
        }
    return {
        "stock_id": str(row["stock_id"]),
        "stock_name": str(row["stock_name"] or sid),
        "market_type": str(row["market_type"] or ""),
        "asset_type": str(row["asset_type"] or ""),
        "industry": str(row["industry"] or "").strip(),
    }


COPY_CHAIN_SRC = "產業鏈來自櫃買價值鏈；「其他」不當同業。已教過的跨族仍用點名檔。"
COPY_PEER_RULE = "同業＝同一產業鏈才比；跨族檔另標他還有的鏈。"
COPY_PEER_NOTE = "小框是產業鏈／跨族標籤。有一樣才比，不是證交所半導體業全組。"
COPY_NO_CHAIN = "還沒產業鏈，不拿證交所粗分類硬比。"


def membership_label(snap: Dict[str, Any]) -> str:
    """這檔拿來比對的最細標。圖卡／HTML 同業括號同一句，跟 membership_keys 對齊。"""
    from industry_fine import _KEEP_FINEST, _KEEP_FOUNDRY_WITH

    bits: List[str] = []
    extras = [str(t).strip() for t in list(snap.get("extra_tags") or []) if str(t).strip()]
    finest = str(snap.get("fine_finest") or "").strip()
    extra_set = set(extras)
    if extras:
        if finest in _KEEP_FINEST or (
            finest == "代工" and (extra_set & _KEEP_FOUNDRY_WITH)
        ):
            if finest and finest not in bits:
                bits.append(finest)
        for t in extras:
            if t not in bits:
                bits.append(t)
        return "／".join(bits)
    from industry_fine import is_catchall_finest

    if finest and not is_catchall_finest(finest):
        bits.append(finest)
    return "／".join(bits)


def peer_scope_label(snap: Dict[str, Any]) -> str:
    lab = peer_mix_label(snap)
    mem = membership_label(snap)
    if mem and snap.get("peer_source") == "chain" and int(snap.get("peer_n") or 0):
        return f"{lab}（{mem}）"
    return lab


def stock_peer_plain_rows(stock_id: str, db_path: str = None) -> List[tuple]:
    """查股／第一眼／基本面可套用的同鏈數字。沒真數就不上，不另開證交所粗組。"""
    sid = str(stock_id or "").strip()
    if not sid:
        return []
    path = db_path or get_db_path()
    try:
        from universe import card_asset_type, is_etf_asset

        if is_etf_asset(card_asset_type(sid, path), sid):
            return []
    except Exception:
        pass
    try:
        snap = attach_fine_industry(
            industry_snapshot(path, sid), path, allow_fetch=False
        )
    except Exception:
        return []
    if snap.get("is_etf"):
        return []
    spec = industry_card_spec(snap)
    rows: List[tuple] = []
    if snap.get("peer_source") == "chain" and int(snap.get("peer_n") or 0):
        lab = str(spec.get("peer_lab") or "").strip()
        if lab and lab != "名單不足":
            rows.append(("同業", lab))
    if snap.get("my_yoy") is not None and snap.get("yoy_med") is not None:
        rows.append(("同業年增", _vs_peer(snap["my_yoy"], snap["yoy_med"], "%")))
    if snap.get("my_gm") is not None and snap.get("gm_med") is not None:
        rows.append(("同業毛利", _vs_peer(snap["my_gm"], snap["gm_med"], "pt")))
    if (
        snap.get("vol") is not None
        and snap.get("vol_med") is not None
        and float(snap["vol_med"] or 0) > 0
    ):
        ratio = float(snap["vol"]) / float(snap["vol_med"])
        rows.append(
            ("同業量比", f"{ratio:.1f}（中位 {int(round(float(snap['vol_med']))):,}張）")
        )
    bijia = snap.get("bijia") or {}
    if bijia.get("ok") and str(bijia.get("read") or "").strip():
        val = str(bijia["read"]).strip()
        flag = str(bijia.get("flag_text") or "").strip()
        if flag:
            val = f"{val}　{flag}"
        rows.append(("同鏈比價", val))
    overlay = chain_flow_overlay(snap).rstrip("。")
    if overlay:
        rows.append(("資金", overlay))
    return rows


def industry_card_spec(snap: Dict[str, Any]) -> Dict[str, Any]:
    """圖卡 PNG 與 Telegram HTML 同一套規格。不准兩邊各寫一套。"""
    from industry_fine import peer_chip_tags

    extras = [str(t) for t in list(snap.get("extra_tags") or []) if str(t).strip()]
    tags = peer_chip_tags(list(snap.get("fine_tags") or []))
    return {
        "tags": tags,
        "extras": extras,
        "chain": str(snap.get("fine_chain") or "").strip(),
        "finest": str(snap.get("fine_finest") or "").strip(),
        "membership": membership_label(snap),
        "peer_lab": peer_scope_label(snap) if snap.get("peer_n") else "名單不足",
        "copy_src": COPY_CHAIN_SRC,
        "copy_rule": COPY_PEER_RULE,
        "copy_note": COPY_PEER_NOTE,
        "copy_none": COPY_NO_CHAIN,
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


def share_flow_extra(
    *,
    flowing_in: bool = False,
    slow_in: bool = False,
    share_last: float = 0.0,
    share_up: float = 0.0,
    last_net: int = 0,
) -> str:
    """洞燭／查股／持股／產業卡同一句。流入＝佔比升，流出＝佔比退。"""
    if flowing_in or slow_in:
        return "佔比在升＝資金流入。"
    if float(share_last or 0) > 0:
        return "買超佔比還在。"
    if float(share_up or 0) < 0 or int(last_net or 0) < 0:
        return "佔比在退＝資金流出。"
    return "佔比還沒升，不算流入。"


def _chain_share_state(nets: List[int], shares: List[float]) -> Dict[str, Any]:
    vals = [int(n) for n in (nets or [])][-5:]
    sh = [float(x) for x in (shares or [])][-5:]
    last = vals[-1] if vals else 0
    rise = sum(1 for i in range(1, len(sh)) if sh[i] > sh[i - 1] + 1e-9)
    up = (sh[-1] - sh[0]) if len(sh) >= 2 else 0.0
    share_in = len(sh) >= 3 and rise >= 2 and up > 0 and sh[-1] > 0
    share_out = len(sh) >= 2 and up < -1e-9
    flowing_in = bool(share_in and not share_out) if sh else False
    extra = share_flow_extra(
        flowing_in=flowing_in,
        share_last=sh[-1] if sh else 0.0,
        share_up=up,
        last_net=last,
    )
    return {
        "share_last": sh[-1] if sh else 0.0,
        "share_up": up,
        "share_line": extra if sh else "",
        "flowing_in": flowing_in,
    }


def chain_flow_overlay(snap: Dict[str, Any]) -> str:
    """個股資金句：本鏈法人＋佔比進出。查股／持股／觀察／AI倉／產業卡同一句。"""
    if not isinstance(snap, dict) or snap.get("is_etf") or snap.get("peer_source") != "chain":
        return ""
    story, _streak = flow_story_lines(snap)
    bits: List[str] = []
    s = str(story or "").strip().rstrip("。")
    if s:
        bits.append(s)
    extra = str(snap.get("share_line") or "").strip().rstrip("。")
    if extra:
        bits.append(extra)
    if not bits:
        return ""
    return "。".join(bits) + "。"


def stock_flow_overlay(stock_id: str, db_path: str = None, ymd: str = "") -> str:
    """查股 overlay 入口。ymd 只當快取鍵備註，數字仍吃庫裡官方收。"""
    del ymd
    sid = str(stock_id or "").strip()
    if not sid:
        return ""
    path = db_path or get_db_path()
    try:
        from universe import card_asset_type, is_etf_asset

        if is_etf_asset(card_asset_type(sid, path), sid):
            return ""
    except Exception:
        pass
    try:
        snap = attach_fine_industry(
            industry_snapshot(path, sid), path, allow_fetch=False
        )
    except Exception:
        return ""
    if snap.get("is_etf"):
        return ""
    return chain_flow_overlay(snap)


def flow_story_lines(snap: Dict[str, Any]) -> List[str]:
    """法人簡述：本鏈合計。HTML／圖卡同一套。"""
    three = int(snap.get("three_net") or 0)
    chain = bool(snap.get("peer_source") == "chain")
    unit = "本鏈" if chain else "本產業"
    mem = membership_label(snap)
    if chain and mem:
        if three > 0:
            flow_story = f"{unit}（{mem}）法人合計買超。"
        elif three < 0:
            flow_story = f"{unit}（{mem}）法人合計賣超。"
        else:
            flow_story = f"{unit}（{mem}）法人加總接近 0，或法人還沒寫進這天。"
    elif three > 0:
        flow_story = f"{unit}法人合計買超。"
    elif three < 0:
        flow_story = f"{unit}法人合計賣超。"
    else:
        flow_story = "還沒產業鏈，不拿證交所粗分類硬加總。" if snap.get("peer_source") == "none" else f"{unit}法人加總接近 0，或法人還沒寫進這天。"
    streak_line = ""
    if int(snap.get("buy_streak") or 0) >= 2:
        streak_line = f"{unit}法人連 {int(snap['buy_streak'])} 個交易日合計買超"
    elif int(snap.get("sell_streak") or 0) >= 2:
        streak_line = f"{unit}法人連 {int(snap['sell_streak'])} 個交易日合計賣超"
    elif int(snap.get("buy_streak") or 0) == 1:
        streak_line = f"{unit}今天合計買超（尚未連兩日）"
    elif int(snap.get("sell_streak") or 0) == 1:
        streak_line = f"{unit}今天合計賣超（尚未連兩日）"
    return [flow_story, streak_line]


def peer_note_line(snap: Dict[str, Any]) -> str:
    if snap.get("peer_source") == "chain":
        return COPY_PEER_NOTE
    return ""


def format_month_zh(yyyymm: str) -> str:
    s = str(yyyymm or "").replace("-", "")[:6]
    if len(s) != 6 or not s.isdigit():
        return s or "—"
    return f"{int(s[:4])}年{int(s[4:6])}月"


def format_season_zh(year, season) -> str:
    try:
        y, s = int(year), int(season)
    except (TypeError, ValueError):
        return "—"
    if y <= 0 or s <= 0:
        return "—"
    return f"{y}年第{s}季"


def month_display(my_month: str, latest_month: str) -> str:
    mine = str(my_month or "").replace("-", "")[:6]
    latest = str(latest_month or "").replace("-", "")[:6]
    if not mine:
        return "—"
    label = format_month_zh(mine)
    if latest and mine < latest and len(latest) == 6:
        return f"{label}（{int(latest[4:6])}月尚未公告）"
    return label


def peer_mix_label(snap: Dict[str, Any]) -> str:
    n = int(snap.get("peer_n") or 0)
    if not n:
        return "同業名單不足"
    bits = []
    tw = int(snap.get("peer_tw") or 0)
    two = int(snap.get("peer_two") or 0)
    em = int(snap.get("peer_em") or 0)
    if tw:
        bits.append(f"上市{tw}")
    if two:
        bits.append(f"上櫃{two}")
    if em:
        bits.append(f"興櫃{em}")
    mix = "／".join(bits)
    extra = f"（{mix}，不含ETF）" if mix else "（不含ETF）"
    return f"{n}家現股{extra}"


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
    try:
        from wayne_db import listing_zh
    except Exception:
        def listing_zh(market):  # type: ignore
            return ""

    listing = listing_zh(u.get("market_type"))

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
    peer_tw = peer_two = peer_em = 0
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
        for mkt, n in conn.execute(
            """
            SELECT market_type, COUNT(*) FROM stock_universe
            WHERE industry=? AND is_active=1 AND length(stock_id)=4
              AND COALESCE(asset_type,'') NOT LIKE 'ETF%'
            GROUP BY 1
            """,
            (industry,),
        ):
            zh = listing_zh(mkt)
            if zh == "上市":
                peer_tw = int(n or 0)
            elif zh == "上櫃":
                peer_two = int(n or 0)
            elif zh == "興櫃":
                peer_em = int(n or 0)
        peer_month = str(my_m["yyyymm"]) if my_m else latest_m
        if peer_month:
            peers_m = conn.execute(
                """
                SELECT m.stock_id, m.stock_name, m.yoy_pct, m.mom_pct, m.ytd_yoy_pct, m.revenue, u.market_type
                FROM monthly_revenue m
                JOIN stock_universe u ON u.stock_id = m.stock_id
                WHERE m.yyyymm=? AND u.industry=? AND length(m.stock_id)=4
                  AND COALESCE(u.asset_type,'') NOT LIKE 'ETF%'
                """,
                (peer_month, industry),
            ).fetchall()
        peer_year = int(my_q["year"]) if my_q else q_year
        peer_season = int(my_q["season"]) if my_q else q_season
        if peer_year:
            peers_q = conn.execute(
                """
                SELECT q.stock_id, q.stock_name, q.gross_margin_pct, q.eps
                FROM quarterly_income q
                JOIN stock_universe u ON u.stock_id = q.stock_id
                WHERE q.year=? AND q.season=? AND u.industry=? AND length(q.stock_id)=4
                  AND COALESCE(u.asset_type,'') NOT LIKE 'ETF%'
                """,
                (peer_year, peer_season, industry),
            ).fetchall()

    three = 0
    if industry and as_of:
        three = int(
            conn.execute(
                """
                SELECT COALESCE(SUM(q.foreign_net+q.trust_net+q.dealer_net),0)
                FROM daily_quotes q
                JOIN stock_universe u ON u.stock_id = q.stock_id
                WHERE q.date=? AND u.industry=? AND length(q.stock_id)=4
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
            WHERE q.date=? AND length(q.stock_id)=4
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
                SELECT DISTINCT date AS d FROM daily_quotes
                WHERE date <= ? ORDER BY d DESC LIMIT 8
                """,
                (as_of,),
            ).fetchall()
        ]
        net_by: Dict[str, int] = {}
        if dates:
            qmarks = ",".join("?" * len(dates))
            for d, net in conn.execute(
                f"""
                SELECT q.date AS d,
                       COALESCE(SUM(q.foreign_net+q.trust_net+q.dealer_net),0)
                FROM daily_quotes q
                JOIN stock_universe u ON u.stock_id = q.stock_id
                WHERE q.date IN ({qmarks}) AND u.industry=? AND length(q.stock_id)=4
                  AND COALESCE(u.asset_type,'') NOT LIKE 'ETF%'
                GROUP BY 1
                """,
                (*dates, industry),
            ):
                net_by[str(d)] = int(net or 0)
        for i, d in enumerate(dates):
            net = int(net_by.get(d) or 0)
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

    vol = None
    vol_med = None
    vol_n = 0
    vol_em_n = 0
    if industry and as_of and industry not in ("ETF", "指數投資證券"):
        listed_vols = conn.execute(
            """
            SELECT q.stock_id, q.volume, u.market_type
            FROM daily_quotes q
            JOIN stock_universe u ON u.stock_id = q.stock_id
            WHERE q.date=? AND u.industry=? AND length(q.stock_id)=4
              AND COALESCE(u.asset_type,'') NOT LIKE 'ETF%'
            """,
            (as_of, industry),
        ).fetchall()
        try:
            em_vols = conn.execute(
                """
                SELECT e.stock_id, e.volume, u.market_type
                FROM emerging_quotes e
                JOIN stock_universe u ON u.stock_id = e.stock_id
                WHERE e.date=? AND u.industry=? AND length(e.stock_id)=4
                  AND COALESCE(u.asset_type,'') NOT LIKE 'ETF%'
                """,
                (as_of, industry),
            ).fetchall()
        except Exception:
            em_vols = []
        seen: Dict[str, tuple] = {}
        for r in list(listed_vols) + list(em_vols):
            seen[str(r[0])] = (float(r[1] or 0), str(r[2] or ""))
        vols = [v for v, _m in seen.values()]
        vol_n = len(vols)
        vol_em_n = sum(1 for _v, m in seen.values() if listing_zh(m) == "興櫃")
        vol_med = _median(vols)
        mine_vol = seen.get(sid)
        vol = mine_vol[0] if mine_vol else None

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
        "listing": listing,
        "is_etf": asset.startswith("ETF") or industry in ("ETF", "指數投資證券"),
        "peer_n": peer_n,
        "peer_tw": peer_tw,
        "peer_two": peer_two,
        "peer_em": peer_em,
        "as_of": as_of,
        "month": str(my_m["yyyymm"]) if my_m else latest_m,
        "latest_month": str(latest_m or ""),
        "month_label": month_display(str(my_m["yyyymm"]) if my_m else "", latest_m),
        "my_yoy": my_yoy,
        "my_mom": float(my_m["mom_pct"]) if my_m else None,
        "yoy_med": yoy_med,
        "yoy_n": len(peers_m),
        "year": int(my_q["year"]) if my_q else q_year,
        "season": int(my_q["season"]) if my_q else q_season,
        "season_label": format_season_zh(
            int(my_q["year"]) if my_q else q_year,
            int(my_q["season"]) if my_q else q_season,
        ),
        "vol": vol,
        "vol_med": vol_med,
        "vol_n": vol_n,
        "vol_em_n": vol_em_n,
        "my_gm": my_gm,
        "gm_med": gm_med,
        "three_net": three,
        "buy_streak": buy_streak,
        "sell_streak": sell_streak,
        "inflow": inflow,
        "outflow": outflow,
        "stronger": [
            {
                "stock_id": str(r["stock_id"]),
                "stock_name": str(r["stock_name"] or ""),
                "yoy": float(r["yoy_pct"] or 0),
                "listing": listing_zh(r["market_type"] if "market_type" in r.keys() else ""),
            }
            for r in stronger
        ],
        "weaker": [
            {
                "stock_id": str(r["stock_id"]),
                "stock_name": str(r["stock_name"] or ""),
                "yoy": float(r["yoy_pct"] or 0),
                "listing": listing_zh(r["market_type"] if "market_type" in r.keys() else ""),
            }
            for r in weaker
        ],
    }


def _peer_listing_counts(conn: sqlite3.Connection, ids: List[str], listing_zh) -> Dict[str, int]:
    if not ids:
        return {"n": 0, "tw": 0, "two": 0, "em": 0}
    q = ",".join("?" * len(ids))
    n = tw = two = em = 0
    for mkt, c in conn.execute(
        f"""
        SELECT market_type, COUNT(*) FROM stock_universe
        WHERE stock_id IN ({q}) AND is_active=1 AND length(stock_id)=4
          AND COALESCE(asset_type,'') NOT LIKE 'ETF%'
        GROUP BY 1
        """,
        ids,
    ):
        c = int(c or 0)
        n += c
        zh = listing_zh(mkt)
        if zh == "上市":
            tw += c
        elif zh == "上櫃":
            two += c
        elif zh == "興櫃":
            em += c
    return {"n": n, "tw": tw, "two": two, "em": em}


def _rebuild_peers_from_chain(snap: Dict[str, Any], db_path: str) -> None:
    """同業改成產業鏈細項／跨族標籤。不准再用證交所半導體業 241 家硬灌。"""
    from industry_fine import chain_peer_ids, extra_tags_for, display_tags

    sid = str(snap.get("stock_id") or "")
    peer_ids = chain_peer_ids(db_path, sid) if not snap.get("is_etf") else []
    snap["peer_ids"] = list(peer_ids)
    snap["extra_tags"] = extra_tags_for(sid)
    snap["fine_tags"] = display_tags(list(snap.get("fine_tags") or []), sid)
    snap["peer_source"] = "chain" if peer_ids else "none"
    if snap.get("is_etf"):
        return
    try:
        from wayne_db import listing_zh
    except Exception:

        def listing_zh(market):  # type: ignore
            return ""

    conn = sqlite3.connect(db_path, timeout=8.0)
    conn.row_factory = sqlite3.Row
    try:
        counts = _peer_listing_counts(conn, peer_ids, listing_zh)
        snap["peer_n"] = int(counts["n"] or 0)
        snap["peer_tw"] = int(counts["tw"] or 0)
        snap["peer_two"] = int(counts["two"] or 0)
        snap["peer_em"] = int(counts["em"] or 0)
        if not peer_ids:
            snap["yoy_med"] = None
            snap["yoy_n"] = 0
            snap["gm_med"] = None
            snap["vol_med"] = None
            snap["vol_n"] = 0
            snap["vol_em_n"] = 0
            snap["three_net"] = 0
            snap["buy_streak"] = 0
            snap["sell_streak"] = 0
            snap["share_last"] = 0.0
            snap["share_up"] = 0.0
            snap["share_line"] = ""
            snap["inflow"] = []
            snap["outflow"] = []
            snap["stronger"] = []
            snap["weaker"] = []
            return

        q = ",".join("?" * len(peer_ids))
        peer_month = str(snap.get("month") or snap.get("latest_month") or "")
        peers_m: List[sqlite3.Row] = []
        if peer_month:
            peers_m = list(
                conn.execute(
                    f"""
                    SELECT m.stock_id, m.stock_name, m.yoy_pct, m.mom_pct, u.market_type
                    FROM monthly_revenue m
                    JOIN stock_universe u ON u.stock_id = m.stock_id
                    WHERE m.yyyymm=? AND m.stock_id IN ({q}) AND length(m.stock_id)=4
                      AND COALESCE(u.asset_type,'') NOT LIKE 'ETF%'
                    """,
                    (peer_month, *peer_ids),
                )
            )
        snap["yoy_med"] = _median([float(r["yoy_pct"] or 0) for r in peers_m])
        snap["yoy_n"] = len(peers_m)

        peer_year = int(snap.get("year") or 0)
        peer_season = int(snap.get("season") or 0)
        peers_q: List[sqlite3.Row] = []
        if peer_year:
            peers_q = list(
                conn.execute(
                    f"""
                    SELECT q.stock_id, q.gross_margin_pct
                    FROM quarterly_income q
                    JOIN stock_universe u ON u.stock_id = q.stock_id
                    WHERE q.year=? AND q.season=? AND q.stock_id IN ({q})
                      AND length(q.stock_id)=4
                      AND COALESCE(u.asset_type,'') NOT LIKE 'ETF%'
                    """,
                    (peer_year, peer_season, *peer_ids),
                )
            )
        snap["gm_med"] = _median(
            [float(r["gross_margin_pct"] or 0) for r in peers_q if r["gross_margin_pct"] is not None]
        )

        as_of = str(snap.get("as_of") or "")
        vols: List[float] = []
        vol_em_n = 0
        if as_of:
            seen: Dict[str, tuple] = {}
            for r in conn.execute(
                f"""
                SELECT q.stock_id, q.volume, u.market_type
                FROM daily_quotes q
                JOIN stock_universe u ON u.stock_id = q.stock_id
                WHERE q.date=? AND q.stock_id IN ({q}) AND length(q.stock_id)=4
                  AND COALESCE(u.asset_type,'') NOT LIKE 'ETF%'
                """,
                (as_of, *peer_ids),
            ):
                seen[str(r[0])] = (float(r[1] or 0), str(r[2] or ""))
            try:
                for r in conn.execute(
                    f"""
                    SELECT e.stock_id, e.volume, u.market_type
                    FROM emerging_quotes e
                    JOIN stock_universe u ON u.stock_id = e.stock_id
                    WHERE e.date=? AND e.stock_id IN ({q}) AND length(e.stock_id)=4
                      AND COALESCE(u.asset_type,'') NOT LIKE 'ETF%'
                    """,
                    (as_of, *peer_ids),
                ):
                    seen.setdefault(str(r[0]), (float(r[1] or 0), str(r[2] or "")))
            except sqlite3.Error:
                pass
            vols = [v for v, _m in seen.values()]
            vol_em_n = sum(1 for _v, m in seen.values() if listing_zh(m) == "興櫃")
            mine_vol = seen.get(sid)
            if mine_vol:
                snap["vol"] = mine_vol[0]
        snap["vol_med"] = _median(vols) if vols else None
        snap["vol_n"] = len(vols)
        snap["vol_em_n"] = vol_em_n

        three = 0
        buy_streak = sell_streak = 0
        if as_of:
            three = int(
                conn.execute(
                    f"""
                    SELECT COALESCE(SUM(q.foreign_net+q.trust_net+q.dealer_net),0)
                    FROM daily_quotes q
                    WHERE q.date=? AND q.stock_id IN ({q}) AND length(q.stock_id)=4
                    """,
                    (as_of, *peer_ids),
                ).fetchone()[0]
                or 0
            )
            dates = [
                str(r[0])
                for r in conn.execute(
                    """
                    SELECT DISTINCT date AS d FROM daily_quotes
                    WHERE date <= ? ORDER BY d DESC LIMIT 8
                    """,
                    (as_of,),
                )
            ]
            net_by: Dict[str, int] = {}
            if dates:
                dq = ",".join("?" * len(dates))
                for d, net in conn.execute(
                    f"""
                    SELECT q.date AS d,
                           COALESCE(SUM(q.foreign_net+q.trust_net+q.dealer_net),0)
                    FROM daily_quotes q
                    WHERE q.date IN ({dq}) AND q.stock_id IN ({q})
                      AND length(q.stock_id)=4
                    GROUP BY 1
                    """,
                    (*dates, *peer_ids),
                ):
                    net_by[str(d)] = int(net or 0)
            for i, d in enumerate(dates):
                net = int(net_by.get(d) or 0)
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
            chrono = list(reversed([str(d) for d in dates if str(d)]))
            nets_ch = [int(net_by.get(d) or 0) for d in chrono]
            shares: List[float] = []
            mkt_in: Dict[str, int] = {}
            if chrono:
                dq = ",".join("?" * len(chrono))
                try:
                    for d, inn in conn.execute(
                        f"""
                        SELECT q.date,
                               COALESCE(SUM(
                                 CASE WHEN IFNULL(q.foreign_net,0)+IFNULL(q.trust_net,0)+IFNULL(q.dealer_net,0) > 0
                                      THEN IFNULL(q.foreign_net,0)+IFNULL(q.trust_net,0)+IFNULL(q.dealer_net,0)
                                      ELSE 0 END
                               ), 0)
                        FROM daily_quotes q
                        LEFT JOIN stock_universe u ON u.stock_id = q.stock_id
                        WHERE q.date IN ({dq}) AND length(q.stock_id)=4
                          AND COALESCE(u.asset_type,'') NOT LIKE 'ETF%'
                        GROUP BY 1
                        """,
                        chrono,
                    ):
                        mkt_in[str(d)] = int(inn or 0)
                except sqlite3.Error:
                    mkt_in = {}
            for d, n3 in zip(chrono, nets_ch):
                inn = int(mkt_in.get(d) or 0)
                if inn > 0 and n3 > 0:
                    shares.append(100.0 * n3 / inn)
                else:
                    shares.append(0.0)
            st = _chain_share_state(nets_ch, shares)
            snap["share_last"] = float(st.get("share_last") or 0.0)
            snap["share_up"] = float(st.get("share_up") or 0.0)
            snap["share_line"] = str(st.get("share_line") or "")
        else:
            snap["share_last"] = 0.0
            snap["share_up"] = 0.0
            snap["share_line"] = ""
        snap["three_net"] = three
        snap["buy_streak"] = buy_streak
        snap["sell_streak"] = sell_streak
        snap["inflow"] = []
        snap["outflow"] = []

        stronger: List[Dict[str, Any]] = []
        weaker: List[Dict[str, Any]] = []
        if snap.get("my_yoy") is not None and peers_m:
            my_y = float(snap["my_yoy"] or 0)
            others = [r for r in peers_m if str(r["stock_id"]) != sid]
            stronger_rows = sorted(
                [r for r in others if float(r["yoy_pct"] or 0) > my_y],
                key=lambda r: float(r["yoy_pct"] or 0),
                reverse=True,
            )[:8]
            weaker_rows = sorted(
                [r for r in others if float(r["yoy_pct"] or 0) < my_y],
                key=lambda r: float(r["yoy_pct"] or 0),
            )[:8]
            stronger = [
                {
                    "stock_id": str(r["stock_id"]),
                    "stock_name": str(r["stock_name"] or ""),
                    "yoy": float(r["yoy_pct"] or 0),
                    "listing": listing_zh(r["market_type"] if "market_type" in r.keys() else ""),
                }
                for r in stronger_rows
            ]
            weaker = [
                {
                    "stock_id": str(r["stock_id"]),
                    "stock_name": str(r["stock_name"] or ""),
                    "yoy": float(r["yoy_pct"] or 0),
                    "listing": listing_zh(r["market_type"] if "market_type" in r.keys() else ""),
                }
                for r in weaker_rows
            ]
        snap["stronger"] = stronger
        snap["weaker"] = weaker
    finally:
        conn.close()


def attach_fine_industry(
    snap: Dict[str, Any], db_path: str, *, allow_fetch: bool = False, max_fetch: int = 1
) -> Dict[str, Any]:
    """把櫃買／籌碼K產業鏈掛上這檔與對照檔。其他桶不拿來比。同業改走最細標／跨族。"""
    from industry_fine import (
        display_tags,
        extra_tags_for,
        is_catchall_finest,
        load_or_fetch_fine_industry,
    )

    sid = str(snap.get("stock_id") or "")
    fine = load_or_fetch_fine_industry(
        db_path, [sid], allow_fetch=allow_fetch, max_fetch=max_fetch
    )
    mine = fine.get(sid) or {}
    extras = extra_tags_for(sid)
    tags = display_tags(list(mine.get("tags") or []), sid)
    chain = str(mine.get("chain") or "")
    finest = str(mine.get("finest") or "")
    if is_catchall_finest(finest):
        if extras:
            chain = "／".join(extras)
            finest = extras[0]
            tags = display_tags(extras, sid)
        else:
            chain = ""
            finest = ""
            tags = extras
    snap["fine_tags"] = tags
    snap["fine_chain"] = chain
    snap["fine_finest"] = finest
    snap["extra_tags"] = extras
    _rebuild_peers_from_chain(snap, db_path)
    ids = [sid] + [
        str(row.get("stock_id") or "")
        for row in list(snap.get("stronger") or []) + list(snap.get("weaker") or [])
    ]
    ids.extend(list(snap.get("peer_ids") or [])[:80])
    fine = load_or_fetch_fine_industry(
        db_path, ids, allow_fetch=allow_fetch, max_fetch=max_fetch
    )
    snap["fine"] = fine
    for key in ("stronger", "weaker"):
        for row in snap.get(key) or []:
            rec = fine.get(str(row.get("stock_id") or "")) or {}
            psid = str(row.get("stock_id") or "")
            row["fine_tags"] = display_tags(list(rec.get("tags") or []), psid)
            row["fine_finest"] = str(rec.get("finest") or "")
            row["extra_tags"] = extra_tags_for(psid)
    return attach_price_eps_bijia(snap, db_path)


def _recent_eps_sum(conn: sqlite3.Connection, stock_id: str, *, max_n: int = 2) -> Dict[str, Any]:
    """近最多兩季 EPS 合計。官方常只有最新一期→n=1；有兩季才合計。不准自造。"""
    rows = conn.execute(
        """
        SELECT year, season, eps FROM quarterly_income
        WHERE stock_id=? ORDER BY year DESC, season DESC LIMIT ?
        """,
        (str(stock_id).strip(), int(max_n)),
    ).fetchall()
    seasons: List[str] = []
    total = 0.0
    n = 0
    for r in rows:
        try:
            eps = float(r["eps"] if isinstance(r, sqlite3.Row) else r[2] or 0)
            y = int(r["year"] if isinstance(r, sqlite3.Row) else r[0] or 0)
            s = int(r["season"] if isinstance(r, sqlite3.Row) else r[1] or 0)
        except (TypeError, ValueError, IndexError, KeyError):
            continue
        if y < 1990 or s not in (1, 2, 3, 4):
            continue
        seasons.append(f"{y}Q{s}")
        total += eps
        n += 1
    return {"eps_sum": total if n else None, "eps_n": n, "eps_seasons": seasons}


def has_positive_eps(db_path: str, stock_id: str) -> bool:
    """同鏈比價同一條：近季官方 EPS 合計 > 0 才算賺到錢。虧損／沒季報不上。"""
    sid = str(stock_id or "").strip()
    if not db_path or not sid:
        return False
    try:
        conn = sqlite3.connect(db_path, timeout=8.0)
        conn.row_factory = sqlite3.Row
        try:
            rec = _recent_eps_sum(conn, sid, max_n=2)
        finally:
            conn.close()
    except sqlite3.Error:
        return False
    try:
        n = int(rec.get("eps_n") or 0)
        total = rec.get("eps_sum")
        return n >= 1 and total is not None and float(total) > 0
    except (TypeError, ValueError):
        return False


def _latest_close(conn: sqlite3.Connection, stock_id: str) -> Dict[str, Any]:
    sid = str(stock_id).strip()
    row = conn.execute(
        "SELECT date, close FROM daily_quotes WHERE stock_id=? ORDER BY date DESC LIMIT 1",
        (sid,),
    ).fetchone()
    if row:
        close = float(row["close"] if isinstance(row, sqlite3.Row) else row[1] or 0)
        if close > 0:
            return {
                "close": close,
                "close_date": str(row["date"] if isinstance(row, sqlite3.Row) else row[0] or ""),
            }
    try:
        row = conn.execute(
            "SELECT date, avg_price FROM emerging_quotes WHERE stock_id=? ORDER BY date DESC LIMIT 1",
            (sid,),
        ).fetchone()
    except Exception:
        row = None
    if row:
        close = float(row["avg_price"] if isinstance(row, sqlite3.Row) else row[1] or 0)
        if close > 0:
            return {
                "close": close,
                "close_date": str(row["date"] if isinstance(row, sqlite3.Row) else row[0] or ""),
            }
    return {"close": None, "close_date": ""}


def attach_price_eps_bijia(snap: Dict[str, Any], db_path: str) -> Dict[str, Any]:
    """同籌碼K產業鏈：股價 vs 近季 EPS。沒鏈／沒數就不畫；不同鏈不硬綁。不是買訊。"""
    empty = {
        "ok": False,
        "chain": "",
        "eps_label": "",
        "close_date": "",
        "rows": [],
        "mine": None,
        "mult_med": None,
        "peer_n": 0,
        "read": "",
        "note": "",
    }
    snap["bijia"] = dict(empty)
    if snap.get("is_etf"):
        return snap
    chain = str(snap.get("fine_chain") or "").strip()
    sid = str(snap.get("stock_id") or "").strip()
    peer_ids = [str(x) for x in list(snap.get("peer_ids") or []) if str(x)]
    if not sid:
        snap["bijia"]["note"] = "還沒產業鏈"
        return snap
    if not chain and not peer_ids:
        snap["bijia"]["note"] = "還沒產業鏈"
        return snap
    path = db_path or get_db_path()
    try:
        from wayne_db import listing_zh
    except Exception:

        def listing_zh(market):  # type: ignore
            return ""

    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    try:
        if peer_ids:
            q = ",".join("?" * len(peer_ids))
            peers = conn.execute(
                f"""
                SELECT u.stock_id, u.stock_name, u.market_type
                FROM stock_universe u
                WHERE u.stock_id IN ({q}) AND u.is_active=1 AND length(u.stock_id)=4
                  AND COALESCE(u.asset_type,'') NOT LIKE 'ETF%'
                """,
                peer_ids,
            ).fetchall()
        else:
            peers = conn.execute(
                """
                SELECT f.stock_id, u.stock_name, u.market_type
                FROM stock_fine_industry f
                JOIN stock_universe u ON u.stock_id = f.stock_id
                WHERE f.chain=? AND u.is_active=1 AND length(f.stock_id)=4
                  AND COALESCE(u.asset_type,'') NOT LIKE 'ETF%'
                """,
                (chain,),
            ).fetchall()
    except Exception:
        conn.close()
        snap["bijia"]["note"] = "產業鏈表未就緒"
        return snap

    rows_out: List[Dict[str, Any]] = []
    close_dates: List[str] = []
    eps_ns: List[int] = []
    for r in peers:
        psid = str(r["stock_id"])
        px = _latest_close(conn, psid)
        eps = _recent_eps_sum(conn, psid, max_n=2)
        close = px.get("close")
        eps_sum = eps.get("eps_sum")
        eps_n = int(eps.get("eps_n") or 0)
        if close is None or eps_sum is None or eps_n < 1 or float(eps_sum) <= 0:
            continue
        mult = float(close) / float(eps_sum)
        if px.get("close_date"):
            close_dates.append(str(px["close_date"]))
        eps_ns.append(eps_n)
        rows_out.append(
            {
                "stock_id": psid,
                "stock_name": str(r["stock_name"] or psid),
                "listing": listing_zh(r["market_type"]),
                "close": float(close),
                "eps_sum": float(eps_sum),
                "eps_n": eps_n,
                "eps_seasons": list(eps.get("eps_seasons") or []),
                "mult": mult,
                "is_mine": psid == sid,
            }
        )
    conn.close()

    if not any(r["is_mine"] for r in rows_out):
        snap["bijia"].update({"chain": chain, "note": "缺收盤或EPS"})
        return snap
    if len(rows_out) < 2:
        snap["bijia"].update({"chain": chain, "note": "同鏈可對照不足"})
        return snap

    rows_out.sort(key=lambda x: (float(x["mult"]), float(x["close"])))
    mine = next(r for r in rows_out if r["is_mine"])
    mult_med = _median([float(r["mult"]) for r in rows_out])
    my_mult = float(mine["mult"])
    cheaper = [r for r in rows_out if not r["is_mine"] and float(r["mult"]) < my_mult]
    dearer = [r for r in rows_out if not r["is_mine"] and float(r["mult"]) > my_mult]
    low_pick = sorted(cheaper, key=lambda r: float(r["mult"]), reverse=True)[:2]
    high_pick = sorted(dearer, key=lambda r: float(r["mult"]))[:2]
    keep = list(low_pick) + [mine] + list(high_pick)
    if len(keep) < 5:
        rest = [r for r in rows_out if r["stock_id"] not in {x["stock_id"] for x in keep}]
        for r in rest:
            keep.append(r)
            if len(keep) >= 5:
                break
    keep.sort(key=lambda x: (float(x["mult"]), float(x["close"])))

    max_eps_n = max(eps_ns) if eps_ns else 1
    min_eps_n = min(eps_ns) if eps_ns else 1
    if max_eps_n >= 2 and min_eps_n >= 2:
        eps_label = "近2季EPS"
    else:
        eps_label = "近1季EPS"

    extras = [str(t) for t in list(snap.get("extra_tags") or []) if str(t)]
    chain_label = chain
    if extras:
        chain_label = f"{chain}；跨族 {'／'.join(extras)}" if chain else "跨族 " + "／".join(extras)

    if mult_med is not None and my_mult <= float(mult_med) * 0.92:
        read = f"價／EPS {my_mult:.0f}　中位 {float(mult_med):.0f}　相對便宜"
        flag = "lag"
        flag_text = "落後補漲對照"
        top = max((float(r["mult"]) for r in rows_out if not r["is_mine"]), default=0.0)
        if top >= my_mult * 1.8 and my_mult > 0:
            flag_text = "落後補漲對照　遠低同鏈高檔"
    elif mult_med is not None and my_mult >= float(mult_med) * 1.08:
        read = f"價／EPS {my_mult:.0f}　中位 {float(mult_med):.0f}　相對貴"
        flag = "dear"
        flag_text = "已偏貴"
    else:
        med_s = f"{float(mult_med):.0f}" if mult_med is not None else "—"
        read = f"價／EPS {my_mult:.0f}　中位 {med_s}"
        flag = ""
        flag_text = ""

    snap["bijia"] = {
        "ok": True,
        "chain": chain,
        "scope": chain_label,
        "eps_label": eps_label,
        "close_date": max(close_dates) if close_dates else "",
        "rows": keep,
        "mine": mine,
        "mult_med": mult_med,
        "peer_n": len(rows_out),
        "read": read,
        "flag": flag,
        "flag_text": flag_text,
        "note": "",
    }
    return snap


LISTING_SLOT_WORDS = ("上市", "上櫃", "興櫃")


def widest_stock_name(names) -> int:
    return max((len(str(n or "")) for n in names), default=0)


def pad_stock_name(name: str, widest: int) -> str:
    """股名欄以本表最長名為寬，後面預留上市／上櫃格子。"""
    raw = str(name or "")
    return raw + "　" * max(0, int(widest) - len(raw))


def pad_listing_slot(listing: str) -> str:
    raw = str(listing or "").strip()
    widest = max(len(w) for w in LISTING_SLOT_WORDS)
    return raw + "　" * max(0, widest - len(raw))


def format_bijia_cells(row: Dict[str, Any]) -> Dict[str, str]:
    """圖卡／HTML 共用欄位字串。名稱與上市／上櫃分開，預留對齊格。"""
    mark = "這檔" if row.get("is_mine") else ""
    name = str(row.get("stock_name") or "")
    listing = str(row.get("listing") or "").strip()
    eps_n = int(row.get("eps_n") or 1)
    return {
        "mark": mark,
        "sid": str(row.get("stock_id") or ""),
        "name": name,
        "listing": listing,
        "close": f"{float(row.get('close') or 0):.0f}",
        "eps": f"{float(row.get('eps_sum') or 0):.2f}" + (f"×{eps_n}" if eps_n > 1 else ""),
        "mult": f"{float(row.get('mult') or 0):.0f}",
    }


def format_industry_html(stock_id: str, db_path: str = None, *, allow_fetch: bool = False) -> str:
    from industry_fine import peer_chip_tags
    from tg_layout import (
        html_escape,
        html_pct_tight,
        html_qty_tight,
        join_sections,
        kv_compact,
        kv_html_compact,
        section,
        title_line,
    )

    path = db_path or get_db_path()
    snap = attach_fine_industry(industry_snapshot(path, stock_id), path, allow_fetch=allow_fetch)
    sid = snap["stock_id"]
    name = snap["stock_name"]
    listing = str(snap.get("listing") or "").strip()
    face = ""
    try:
        from universe import listing_industry_face

        face = listing_industry_face(sid, path)
    except Exception:
        face = ""
    title_bit = face or listing
    title_name = f"{name}　{title_bit}" if title_bit else name
    blocks = [title_line("產業說明", sid, title_name)]
    spec = industry_card_spec(snap)
    chain = spec["chain"]
    if spec["tags"] and chain not in (title_bit or ""):
        chips = "　".join(f"[{html_escape(t)}]" for t in spec["tags"])
        if chips:
            blocks[0] = blocks[0] + "　" + chips

    if snap["is_etf"]:
        from universe import etf_card_kind_label

        kind = etf_card_kind_label(snap.get("asset_type") or "", sid)
        kind_txt = f"{kind} ETF" if kind else "ETF／指數商品"
        blocks.append(
            section(
                f"這檔是{kind_txt}，沒有單一公司的產業面。",
                "進場仍先看高低卡，不要因為盤勢敘事追高。成分股之後再接官方清單，現在不畫。",
            )
        )
        return join_sections(*blocks)

    ind = snap["industry"] or "未分類（母體還沒寫到產業）"
    who_lines = [
        "<b>這檔是什麼</b>",
        kv_compact("官方產業別", ind),
    ]
    if chain:
        who_lines.append(kv_compact("產業鏈", chain))
    extras = spec["extras"]
    if extras:
        who_lines.append(kv_compact("跨族", "／".join(extras)))
    who_lines.append(kv_compact("同業", spec["peer_lab"]))
    if spec["tags"]:
        who_lines.append(spec["copy_src"])
        who_lines.append(spec["copy_rule"])
    elif snap.get("peer_source") == "none":
        who_lines.append(spec["copy_none"])
    else:
        who_lines.append("產業名來自證交所／櫃買公司基本資料產業別。")
    blocks.append(section(*who_lines))

    mlabel = str(snap.get("month_label") or "").strip()
    if not mlabel:
        month = str(snap.get("month") or "")
        mlabel = format_month_zh(month) if len(month) >= 6 else (month or "—")
    rev_rows = ["<b>營收看同業</b>", kv_compact("月營收", mlabel)]
    if snap["my_yoy"] is not None:
        rev_rows.append(kv_html_compact("這檔年增", html_pct_tight(snap["my_yoy"])))
        if snap["my_mom"] is not None:
            rev_rows.append(kv_html_compact("這檔月增", html_pct_tight(snap["my_mom"])))
        if snap["yoy_med"] is not None:
            rev_rows.append(
                kv_html_compact(
                    "同業中位年增",
                    f"{html_pct_tight(snap['yoy_med'])}（{snap['yoy_n']}家有月報）",
                )
            )
        rev_rows.append(_vs_peer(snap["my_yoy"], snap["yoy_med"], "%"))
    else:
        if listing == "興櫃":
            rev_rows.append("興櫃沒有免登入的全市場月營收彙總，沒官方列就不顯示。")
        else:
            rev_rows.append("這檔還沒有月營收列")
            latest_m = str(snap.get("latest_month") or "")
            if latest_m:
                rev_rows.append(f"市場已有{format_month_zh(latest_m)}，這檔尚未公告。")
            else:
                rev_rows.append("等公司公布、盤後寫進庫再比。")
    if snap.get("vol") is not None and snap.get("vol_med") is not None and float(snap["vol_med"] or 0) > 0:
        ratio = float(snap["vol"]) / float(snap["vol_med"])
        vol_s = f"{int(round(float(snap['vol']))):,}張　同業中位 {int(round(float(snap['vol_med']))):,}張（量比 {ratio:.1f}）"
        if int(snap.get("vol_em_n") or 0):
            vol_s += f"；含興櫃{int(snap['vol_em_n'])}家日均量"
        rev_rows.append(kv_compact("量比", vol_s))
    if snap["my_gm"] is not None:
        season_s = str(snap.get("season_label") or "").strip() or f"{snap['year']}Q{snap['season']}"
        rev_rows.append(kv_compact("季報", season_s))
        rev_rows.append(kv_compact("這檔毛利率", f"{snap['my_gm']:.1f}%"))
        if snap["gm_med"] is not None:
            rev_rows.append(kv_compact("同業中位毛利率", f"{snap['gm_med']:.1f}%"))
        rev_rows.append(_vs_peer(snap["my_gm"], snap["gm_med"], "pt"))
    else:
        rev_rows.append("這檔還沒有季報列")
    blocks.append(section(*rev_rows))

    bijia = snap.get("bijia") or {}
    if bijia.get("ok") and bijia.get("rows"):
        bj_lines = [
            "<b>同鏈比價</b>",
            kv_compact("範圍", str(bijia.get("scope") or bijia.get("chain") or "")),
            kv_compact("基準", str(bijia.get("eps_label") or "")),
        ]
        cd = str(bijia.get("close_date") or "")
        if len(cd) == 8:
            bj_lines.append(kv_compact("收盤日", f"{cd[:4]}/{cd[4:6]}/{cd[6:]}"))
        elif cd:
            bj_lines.append(kv_compact("收盤日", cd))
        nw = widest_stock_name(str(r.get("stock_name") or "") for r in bijia["rows"])
        for r in bijia["rows"]:
            c = format_bijia_cells(r)
            tag = c["mark"] or "同鏈"
            name_bit = pad_stock_name(c["name"], nw)
            list_bit = pad_listing_slot(c["listing"])
            bj_lines.append(
                f"{html_escape(tag)}　<code>{html_escape(c['sid'])}</code> "
                f"{html_escape(name_bit)}{html_escape(list_bit)}　"
                f"{html_escape(c['close'])}　"
                f"EPS {html_escape(c['eps'])}　"
                f"價/EPS <b>{html_escape(c['mult'])}</b>"
            )
        if bijia.get("read"):
            bj_lines.append(html_escape(str(bijia["read"])))
        flag = str(bijia.get("flag") or "")
        flag_text = str(bijia.get("flag_text") or "").strip()
        if flag == "lag" and flag_text:
            bj_lines.append(f"<b>◆ {html_escape(flag_text)}</b>")
        elif flag == "dear" and flag_text:
            bj_lines.append(f"<b>◇ {html_escape(flag_text)}</b>")
        blocks.append(section(*bj_lines))
    elif str(bijia.get("note") or "").strip():
        blocks.append(section("<b>同鏈比價</b>", html_escape(str(bijia["note"]))))

    as_of = snap["as_of"]
    as_s = f"{as_of[:4]}/{as_of[4:6]}/{as_of[6:]}" if len(as_of) == 8 else (as_of or "—")
    three = int(snap["three_net"] or 0)
    flow_story, streak_line = flow_story_lines(snap)
    overlay = chain_flow_overlay(snap).rstrip("。")
    blocks.append(
        section(
            "<b>本族群產業狀況簡述</b>",
            kv_compact("基準日", as_s),
            kv_html_compact("法人合計", html_qty_tight(three)),
            kv_compact("資金", overlay) if overlay else flow_story,
            streak_line or "—",
        )
    )

    def _peer_rows(title: str, rows: List[Dict[str, Any]], *, name_w: int) -> List[str]:
        if not rows:
            return [f"{title}　—"]
        out = [title]
        for r in rows:
            tags = peer_chip_tags(list(r.get("fine_tags") or []))
            if not tags:
                fine = str(r.get("fine_finest") or "").strip()
                tags = [fine] if fine else []
            tag_bit = "".join(f" [{html_escape(t)}]" for t in tags)
            name_bit = pad_stock_name(str(r.get("stock_name") or ""), name_w)
            list_bit = pad_listing_slot(str(r.get("listing") or "").strip())
            out.append(
                f"<code>{html_escape(r['stock_id'])}</code> "
                f"{html_escape(name_bit)}{html_escape(list_bit)}{tag_bit} {html_pct_tight(r['yoy'])}"
            )
        return out

    if snap["stronger"] or snap["weaker"]:
        note = peer_note_line(snap)
        all_peer = list(snap["stronger"] or []) + list(snap["weaker"] or [])
        name_w = widest_stock_name(str(r.get("stock_name") or "") for r in all_peer)
        blocks.append(
            section(
                "<b>同業月營收對照</b>",
                *_peer_rows("較強", snap["stronger"], name_w=name_w),
                *_peer_rows("較弱", snap["weaker"], name_w=name_w),
                *([note] if note else []),
            )
        )
    return join_sections(*blocks)
