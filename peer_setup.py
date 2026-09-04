"""個股協助：同業價現況對照 + 庫內採樣後才留下的旗標。

兩則飆客個股文拆開後，用 wayne_market.db 流動母體、每 5 個交易日截面、
5/10/20 日前瞻報酬（相對當日流動中位數）採樣：

接入
- 爆量貼月高觀望：量比≥2 且收盤≥20日收盤高×0.98 且近60日漲≥30%。
  後10日勝率 46.7% vs 母體 49.9%，超額中位數 −0.91%。查股／佈局桶標觀望；
  當沖／隔日沖本來就是放量強勢，不拿這條去刪名單。
- 倍數回撤帶：近120日高低振幅≥100%，收盤距120日高 35–52%。只標現況
  （聯亞 7/30 約落在這帶），不是買點。淺修（<15%）後續更強，所以不把回撤當加碼。
- 同業價：官方產業、當日流動前段（最多 24 檔）的 20 日報酬排名。
  後10日超額與母體無差 → 只對照現況，不改海選排序。

不接入
- 窒息量近20日低：後10日超額比母體差。
- 波浪段數、右側口號、萬元 EPS、主題板塊（聯亞／奇鋐分屬通信網路 vs 電腦週邊，
  庫內沒有官方「光通訊」分類就不要自造）。
"""
from __future__ import annotations

import sqlite3
from typing import Any, Dict, List, Optional

SPIKE_Q60R = 2.0
SPIKE_NEAR_HI20 = 0.98
SPIKE_RET60 = 0.30
PULLBACK_RUN = 1.0
PULLBACK_DD_LO = 0.35
PULLBACK_DD_HI = 0.52
PEER_TOP_N = 24
PEER_MIN_N = 5
LIQ_VOL = 1000
LIQ_TO_K = 30000.0
LOOKBACK_DATES = 25


def _f(v, default: float = 0.0) -> float:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return default
    if x != x:  # NaN
        return default
    return x


def flags_from_ohlc_df(df, *, q60r: Optional[float] = None) -> Dict[str, Any]:
    """從單一標的日 K 算旗標。df 需有 close／high／low／volume，時間由舊到新。"""
    out: Dict[str, Any] = {
        "spike_watch": False,
        "pullback_band": False,
        "ret60": None,
        "dd120": None,
        "run120": None,
        "setup_q60r": None,
    }
    if df is None or len(df) < 20:
        return out
    close = df["close"].astype(float)
    high = df["high"].astype(float) if "high" in df.columns else close
    low = df["low"].astype(float) if "low" in df.columns else close
    vol = df["volume"].astype(float) if "volume" in df.columns else close * 0
    c0 = float(close.iloc[-1] or 0)
    if c0 <= 0:
        return out
    hi20 = float(close.iloc[-20:].max() or 0)
    vol60 = float(vol.iloc[-60:].mean() or 0) if len(vol) else 0.0
    q = _f(q60r) if q60r is not None else (float(vol.iloc[-1] / vol60) if vol60 > 0 else 0.0)
    out["setup_q60r"] = round(q, 2) if vol60 > 0 else None
    ret60 = None
    if len(close) >= 61:
        prev = float(close.iloc[-61] or 0)
        if prev > 0:
            ret60 = (c0 / prev) - 1.0
            out["ret60"] = round(ret60 * 100.0, 1)
    if q >= SPIKE_Q60R and hi20 > 0 and c0 >= hi20 * SPIKE_NEAR_HI20 and ret60 is not None and ret60 >= SPIKE_RET60:
        out["spike_watch"] = True
    n120 = min(120, len(df))
    if n120 >= 80:
        h120 = float(high.iloc[-n120:].max() or 0)
        l120 = float(low.iloc[-n120:].min() or 0)
        if h120 > 0 and l120 > 0:
            dd = (h120 - c0) / h120
            run = (h120 / l120) - 1.0
            out["dd120"] = round(dd * 100.0, 1)
            out["run120"] = round(run * 100.0, 0)
            if run >= PULLBACK_RUN and PULLBACK_DD_LO <= dd <= PULLBACK_DD_HI:
                out["pullback_band"] = True
    return out


def flags_from_info(info: Dict[str, Any], df=None) -> Dict[str, Any]:
    q = info.get("q60r")
    if df is not None and len(df) >= 20:
        return flags_from_ohlc_df(df, q60r=q)
    close = _f(info.get("close"))
    hi20 = _f(info.get("hi20_close"))
    qv = _f(q)
    ret60 = info.get("ret60")
    if ret60 is not None and abs(_f(ret60)) > 3:
        ret60 = _f(ret60) / 100.0
    else:
        ret60 = None if ret60 is None else _f(ret60)
    spike = bool(qv >= SPIKE_Q60R and hi20 > 0 and close >= hi20 * SPIKE_NEAR_HI20 and ret60 is not None and ret60 >= SPIKE_RET60)
    return {
        "spike_watch": spike,
        "pullback_band": bool(info.get("pullback_band")),
        "ret60": round(ret60 * 100.0, 1) if ret60 is not None else info.get("ret60"),
        "dd120": info.get("dd120"),
        "run120": info.get("run120"),
        "setup_q60r": qv if qv else None,
    }


def _as_of(db_path: str, as_of: Optional[str] = None) -> str:
    if as_of:
        return str(as_of).replace("-", "")[:8]
    try:
        from import_health import latest_complete_quote_date

        d = latest_complete_quote_date(db_path)
        if d:
            return str(d).replace("-", "")[:8]
    except Exception:
        pass
    conn = sqlite3.connect(db_path)
    row = conn.execute("SELECT MAX(replace(date,'-','')) FROM daily_quotes").fetchone()
    conn.close()
    return str(row[0] or "").replace("-", "")[:8]


def liquid_peer_snapshot(db_path: str, stock_id: str, as_of: Optional[str] = None) -> Dict[str, Any]:
    """官方產業、當日流動前段的 20 日報酬現況。不是預測。"""
    sid = str(stock_id).strip()
    empty: Dict[str, Any] = {
        "stock_id": sid,
        "ok": False,
        "industry": "",
        "peer_n": 0,
        "rank": None,
        "rank_of": 0,
        "ret20": None,
        "peer_med_ret20": None,
        "stronger": [],
        "weaker": [],
        "as_of": "",
    }
    path = db_path
    if not path or not sid:
        return empty
    day = _as_of(path, as_of)
    if not day:
        return empty
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    u = conn.execute(
        "SELECT stock_id, stock_name, industry, asset_type FROM stock_universe WHERE stock_id=?",
        (sid,),
    ).fetchone()
    if not u:
        conn.close()
        return empty
    industry = str(u["industry"] or "").strip()
    asset = str(u["asset_type"] or "").upper()
    empty["industry"] = industry
    empty["stock_name"] = str(u["stock_name"] or sid)
    empty["as_of"] = day
    if asset.startswith("ETF") or industry in ("", "ETF", "指數投資證券", "存託憑證"):
        conn.close()
        return empty
    dates = [
        str(r[0]).replace("-", "")[:8]
        for r in conn.execute(
            """
            SELECT DISTINCT replace(date,'-','') AS d FROM daily_quotes
            WHERE replace(date,'-','') <= ?
            ORDER BY d DESC
            LIMIT ?
            """,
            (day, LOOKBACK_DATES),
        )
    ]
    dates = [d for d in dates if d]
    dates.sort()
    if len(dates) < 21:
        conn.close()
        return empty
    qmarks = ",".join("?" * len(dates))
    rows = conn.execute(
        f"""
        SELECT replace(q.date,'-','') AS d, q.stock_id, q.stock_name, q.close, q.volume, q.turnover_k
        FROM daily_quotes q
        JOIN stock_universe u ON u.stock_id = q.stock_id
        WHERE replace(q.date,'-','') IN ({qmarks})
          AND u.industry=?
          AND length(q.stock_id)=4
          AND COALESCE(u.asset_type,'') NOT LIKE 'ETF%'
          AND q.close > 0
        """,
        (*dates, industry),
    ).fetchall()
    conn.close()
    if not rows:
        return empty
    by: Dict[str, Dict[str, Any]] = {}
    for r in rows:
        code = str(r["stock_id"])
        rec = by.setdefault(
            code,
            {"stock_id": code, "stock_name": str(r["stock_name"] or code), "closes": {}, "to": [], "vol": None, "to_last": None},
        )
        rec["closes"][str(r["d"])] = _f(r["close"])
        rec["to"].append(_f(r["turnover_k"]))
        if str(r["d"]) == day:
            rec["vol"] = _f(r["volume"])
            rec["to_last"] = _f(r["turnover_k"])
            rec["stock_name"] = str(r["stock_name"] or code)
    first = dates[-21]
    last = dates[-1]
    scored: List[Dict[str, Any]] = []
    for rec in by.values():
        c0 = rec["closes"].get(last)
        c1 = rec["closes"].get(first)
        if not c0 or not c1 or c1 <= 0:
            continue
        to20 = sum(rec["to"]) / len(rec["to"]) if rec["to"] else 0.0
        scored.append(
            {
                "stock_id": rec["stock_id"],
                "stock_name": rec["stock_name"],
                "ret20": (c0 / c1) - 1.0,
                "to20": to20,
                "vol": rec.get("vol") or 0.0,
                "to_last": rec.get("to_last") or 0.0,
                "close": c0,
            }
        )
    if not scored:
        return empty
    me = next((x for x in scored if x["stock_id"] == sid), None)
    liq = [
        x
        for x in scored
        if x["vol"] >= LIQ_VOL and x["to_last"] >= LIQ_TO_K
    ]
    liq.sort(key=lambda x: x["to20"], reverse=True)
    top = liq[:PEER_TOP_N]
    if me and me["stock_id"] not in {x["stock_id"] for x in top}:
        top.append(me)
    if len(top) < PEER_MIN_N or not me:
        return empty
    ordered = sorted(top, key=lambda x: x["ret20"], reverse=True)
    rank = next(i for i, x in enumerate(ordered, start=1) if x["stock_id"] == sid)
    rets = [x["ret20"] for x in top]
    rets_sorted = sorted(rets)
    med = rets_sorted[len(rets_sorted) // 2]
    others = [x for x in ordered if x["stock_id"] != sid]
    stronger = [x for x in others if x["ret20"] > me["ret20"]][:2]
    weaker = [x for x in reversed(others) if x["ret20"] < me["ret20"]][:2]
    return {
        "ok": True,
        "stock_id": sid,
        "stock_name": me["stock_name"],
        "industry": industry,
        "as_of": day,
        "peer_n": len(top),
        "rank": rank,
        "rank_of": len(top),
        "ret20": round(me["ret20"] * 100.0, 1),
        "peer_med_ret20": round(med * 100.0, 1),
        "stronger": [
            {"stock_id": x["stock_id"], "stock_name": x["stock_name"], "ret20": round(x["ret20"] * 100.0, 1)}
            for x in stronger
        ],
        "weaker": [
            {"stock_id": x["stock_id"], "stock_name": x["stock_name"], "ret20": round(x["ret20"] * 100.0, 1)}
            for x in weaker
        ],
    }


def attach_setup(card: Dict[str, Any], df=None, db_path: Optional[str] = None) -> Dict[str, Any]:
    if not card or card.get("error"):
        return card
    if df is not None:
        flags = flags_from_ohlc_df(df)
        card["spike_watch"] = bool(flags.get("spike_watch"))
        card["pullback_band"] = bool(flags.get("pullback_band"))
        if flags.get("setup_q60r") is not None:
            card["setup_q60r"] = flags["setup_q60r"]
        if flags.get("ret60") is not None:
            card["ret60"] = flags["ret60"]
        if flags.get("dd120") is not None:
            card["dd120"] = flags["dd120"]
        if flags.get("run120") is not None:
            card["run120"] = flags["run120"]
    if db_path:
        try:
            card["peer_tape"] = liquid_peer_snapshot(
                db_path, str(card.get("stock_id") or ""), as_of=str(card.get("latest_date") or "")
            )
        except Exception:
            card["peer_tape"] = {"ok": False}
    return card


def setup_note_lines(card: Dict[str, Any], *, include_peer: bool = True) -> List[str]:
    """查股／介紹圖用的人話。不是買訊。"""
    lines: List[str] = []
    if card.get("spike_watch"):
        q = card.get("setup_q60r") or card.get("q60r")
        r = card.get("ret60")
        bits = ["爆量貼月高觀望"]
        if q:
            bits.append(f"量比 {float(q):.2f}")
        if r is not None:
            bits.append(f"近60日 {float(r):+.1f}%")
        bits.append("後10日勝率偏低")
        lines.append("　".join(bits))
    if card.get("pullback_band"):
        dd = card.get("dd120")
        dd_s = f"{float(dd):.0f}%" if dd is not None else ""
        lines.append(f"倍數回撤帶{(' ' + dd_s) if dd_s else ''}（35–50%，不是買點）")
    tape = card.get("peer_tape") or {}
    if include_peer and tape.get("ok") and tape.get("rank") and tape.get("rank_of"):
        r20 = tape.get("ret20")
        r20_s = f"{float(r20):+.1f}%" if r20 is not None else ""
        lines.append(f"同業價 20日 {r20_s}　第 {int(tape['rank'])}/{int(tape['rank_of'])}（只對照）")
    return lines[:3]


def layout_spike_notice(item: Dict[str, Any]) -> bool:
    """佈局／起漲才標；當沖／隔日沖有進場價就不標。"""
    if not item.get("spike_watch"):
        return False
    if item.get("entry_price") is not None or item.get("buy_range") is not None:
        return False
    return True
