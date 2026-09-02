# -*- coding: utf-8 -*-
"""台灣加權指數深度研究：持久化、regime、桶權重、勝率回測。"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd
import requests

_SESSION = requests.Session()
_SESSION.headers.update({"User-Agent": "WayneBot/1.0"})
_INDEX_YAHOO = "%5ETWII"
_INDEX_SYMBOL = "TWII"

# 大盤 regime → 海選桶加減分（>1 較積極、<1 較保守）
REGIME_BUCKET_MULT: Dict[str, Dict[str, float]] = {
    "bull": {
        "leave_zero": 1.15,
        "golden_buy": 1.1,
        "revenue_cross": 1.1,
        "select_01": 1.12,
        "select_02": 1.05,
        "select_03": 1.0,
        "half_year_high": 1.08,
        "day_trade": 1.1,
        "overnight": 1.05,
    },
    "neutral": {k: 1.0 for k in (
        "leave_zero", "golden_buy", "revenue_cross", "select_01", "select_02",
        "select_03", "half_year_high", "day_trade", "overnight",
    )},
    "bear": {
        "leave_zero": 0.9,
        "golden_buy": 1.05,
        "revenue_cross": 0.85,
        "select_01": 0.72,
        "select_02": 0.75,
        "select_03": 0.8,
        "half_year_high": 0.78,
        "day_trade": 0.55,
        "overnight": 0.55,
    },
}

REGIME_BUCKET_CAP: Dict[str, Dict[str, int]] = {
    "bull": {"leave_zero": 9, "select_01": 9, "half_year_high": 9},
    "neutral": {},
    "bear": {
        "leave_zero": 6,
        "select_01": 5,
        "select_02": 5,
        "select_03": 5,
        "half_year_high": 5,
        "day_trade": 4,
        "overnight": 4,
    },
}


def ensure_index_daily_table(db_path: str) -> None:
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS index_daily (
                date TEXT NOT NULL,
                symbol TEXT NOT NULL DEFAULT 'TWII',
                close REAL NOT NULL,
                volume REAL DEFAULT 0,
                pct_change REAL DEFAULT 0,
                ma20 REAL,
                ma60 REAL,
                regime TEXT,
                updated_at TEXT NOT NULL,
                PRIMARY KEY (date, symbol)
            );
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_index_daily_sym ON index_daily(symbol, date);"
        )
        conn.commit()
    finally:
        conn.close()


def _fetch_index_daily(range_: str = "2y") -> pd.DataFrame:
    url = (
        f"https://query1.finance.yahoo.com/v8/finance/chart/{_INDEX_YAHOO}"
        f"?interval=1d&range={range_}"
    )
    resp = _SESSION.get(url, timeout=20)
    resp.raise_for_status()
    result = (resp.json().get("chart") or {}).get("result") or []
    if not result:
        return pd.DataFrame()
    block = result[0]
    stamps = block.get("timestamp") or []
    q = ((block.get("indicators") or {}).get("quote") or [{}])[0]
    rows = []
    prev = None
    for ts, cl, vol in zip(stamps, q.get("close") or [], q.get("volume") or []):
        if cl is None:
            continue
        c = float(cl)
        pct = 0.0
        if prev and prev > 0:
            pct = (c - prev) / prev * 100.0
        rows.append(
            {
                "date": pd.Timestamp(ts, unit="s", tz="UTC").tz_convert("Asia/Taipei").strftime("%Y%m%d"),
                "close": c,
                "volume": float(vol or 0),
                "pct_change": round(pct, 2),
            }
        )
        prev = c
    return pd.DataFrame(rows)


def sync_index_daily(db_path: str, range_: str = "2y") -> Dict[str, Any]:
    """盤後融合：Yahoo → index_daily UPSERT。"""
    ensure_index_daily_table(db_path)
    df = _fetch_index_daily(range_)
    if df.empty:
        return {"ok": False, "rows": 0}
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    conn = sqlite3.connect(db_path)
    n = 0
    try:
        for _, row in df.iterrows():
            closes = df.loc[: row.name, "close"].astype(float)
            ma20 = float(closes.tail(20).mean()) if len(closes) >= 5 else float(row["close"])
            ma60 = float(closes.tail(60).mean()) if len(closes) >= 20 else ma20
            snap = _regime_from_closes(closes)
            conn.execute(
                """
                INSERT INTO index_daily(date, symbol, close, volume, pct_change, ma20, ma60, regime, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(date, symbol) DO UPDATE SET
                    close=excluded.close, volume=excluded.volume, pct_change=excluded.pct_change,
                    ma20=excluded.ma20, ma60=excluded.ma60, regime=excluded.regime, updated_at=excluded.updated_at
                """,
                (
                    str(row["date"]),
                    _INDEX_SYMBOL,
                    float(row["close"]),
                    float(row["volume"]),
                    float(row["pct_change"]),
                    ma20,
                    ma60,
                    snap.get("regime", "neutral"),
                    now,
                ),
            )
            n += 1
        conn.commit()
    finally:
        conn.close()
    return {"ok": True, "rows": n, "latest": str(df["date"].iloc[-1])}


def load_index_daily(db_path: str, as_of: Optional[str] = None) -> pd.DataFrame:
    ensure_index_daily_table(db_path)
    conn = sqlite3.connect(db_path)
    try:
        rows = conn.execute(
            """
            SELECT date, close, volume, pct_change, ma20, ma60, regime
            FROM index_daily WHERE symbol=? ORDER BY date
            """,
            (_INDEX_SYMBOL,),
        ).fetchall()
    finally:
        conn.close()
    if rows:
        df = pd.DataFrame(
            rows,
            columns=["date", "close", "volume", "pct_change", "ma20", "ma60", "regime"],
        )
        if as_of:
            sub = df[df["date"] <= str(as_of)]
            if not sub.empty:
                return sub.reset_index(drop=True)
        return df
    return _fetch_index_daily("1y")


def _regime_from_closes(
    closes: pd.Series,
    *,
    breadth_pct: float = 50.0,
    sector_flow: float = 0.0,
) -> Dict[str, Any]:
    if closes is None or len(closes) < 5:
        return {"regime": "unknown", "regime_label": "未知", "score": 0, "confidence": 50.0}
    c = float(closes.iloc[-1])
    ma20 = float(closes.tail(20).mean())
    ma60 = float(closes.tail(60).mean()) if len(closes) >= 60 else ma20
    chg5 = 0.0
    if len(closes) >= 6 and float(closes.iloc[-6]) > 0:
        chg5 = (c - float(closes.iloc[-6])) / float(closes.iloc[-6]) * 100.0
    slope20 = 0.0
    if len(closes) >= 25:
        m0 = float(closes.tail(20).mean())
        m1 = float(closes.iloc[-25:-5].mean())
        if m1 > 0:
            slope20 = (m0 - m1) / m1 * 100.0
    score = 0
    if c >= ma20:
        score += 1
    if c >= ma60:
        score += 1
    if ma20 >= ma60:
        score += 1
    if slope20 > 0:
        score += 1
    if breadth_pct >= 45:
        score += 1
    if sector_flow > 0:
        score += 1
    if score >= 5:
        regime, label = "bull", "多頭帶動"
    elif score <= 2:
        regime, label = "bear", "空方壓力"
    else:
        regime, label = "neutral", "區間震盪"
    confidence = round(min(100.0, max(15.0, 35.0 + score * 10.0 + chg5 * 0.8)), 1)
    return {
        "regime": regime,
        "regime_label": label,
        "score": score,
        "confidence": confidence,
        "close": round(c, 1),
        "ma20": round(ma20, 1),
        "ma60": round(ma60, 1),
        "chg5_pct": round(chg5, 2),
        "slope20_pct": round(slope20, 2),
    }


def _breadth_from_db(db_path: str, as_of: str) -> Dict[str, float]:
    conn = sqlite3.connect(db_path)
    try:
        rows = conn.execute(
            """
            SELECT q.stock_id, q.close
            FROM daily_quotes q
            JOIN stock_universe u ON u.stock_id = q.stock_id
            WHERE q.date = ? AND u.is_active = 1 AND LENGTH(q.stock_id) = 4
            """,
            (as_of,),
        ).fetchall()
        hist = conn.execute(
            """
            SELECT stock_id, close FROM daily_quotes
            WHERE date <= ? AND stock_id IN (
                SELECT stock_id FROM stock_universe WHERE is_active = 1 AND LENGTH(stock_id) = 4
            )
            ORDER BY stock_id, date DESC
            """,
            (as_of,),
        ).fetchall()
    finally:
        conn.close()
    if not rows:
        return {"above_ma20_pct": 0.0, "sample_n": 0}
    by_sid: Dict[str, List[float]] = {}
    for sid, cl in hist:
        lst = by_sid.setdefault(str(sid), [])
        if len(lst) < 25:
            lst.append(float(cl or 0))
    above = total = 0
    for sid, cl in rows:
        seq = by_sid.get(str(sid), [])
        if len(seq) < 20:
            continue
        ma20 = sum(seq[:20]) / 20.0
        if ma20 <= 0:
            continue
        total += 1
        if float(cl) >= ma20:
            above += 1
    return {"above_ma20_pct": round((above / total * 100.0) if total else 0.0, 1), "sample_n": total}


def _sector_flow_sum(db_path: str, as_of: str) -> float:
    conn = sqlite3.connect(db_path)
    try:
        has = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='daily_sector_flow'"
        ).fetchone()
        if not has:
            return 0.0
        row = conn.execute(
            "SELECT SUM(foreign_net + trust_net + dealer_net) FROM daily_sector_flow WHERE date = ?",
            (as_of,),
        ).fetchone()
    finally:
        conn.close()
    try:
        return float(row[0] or 0)
    except (TypeError, ValueError):
        return 0.0


def analyze_taiwan_market(db_path: str, as_of: Optional[str] = None) -> Dict[str, Any]:
    as_of = str(as_of or "").strip()
    idx = load_index_daily(db_path, as_of or None)
    if idx.empty:
        return {"ok": False, "regime": "unknown", "brief": "加權指數資料暫不可用"}
    ref_date = as_of or str(idx["date"].iloc[-1])
    breadth = _breadth_from_db(db_path, ref_date)
    flow = _sector_flow_sum(db_path, ref_date)
    core = _regime_from_closes(
        idx["close"].astype(float),
        breadth_pct=breadth.get("above_ma20_pct", 0),
        sector_flow=flow,
    )
    bt = backtest_bucket_win_rate_by_regime(db_path, limit_days=60)
    return {
        "ok": True,
        "as_of": ref_date,
        "close": core.get("close", 0),
        "ma20": core.get("ma20", 0),
        "ma60": core.get("ma60", 0),
        "chg5_pct": core.get("chg5_pct", 0),
        "slope20_pct": core.get("slope20_pct", 0),
        "breadth_above_ma20": breadth.get("above_ma20_pct", 0),
        "sample_n": breadth.get("sample_n", 0),
        "sector_flow_net": round(flow, 0),
        "regime": core.get("regime", "neutral"),
        "regime_label": core.get("regime_label", "區間震盪"),
        "confidence": core.get("confidence", 50),
        "score": core.get("score", 0),
        "backtest": bt,
    }


def backtest_bucket_win_rate_by_regime(db_path: str, limit_days: int = 60) -> List[Dict[str, Any]]:
    """海選隔日勝率 × 當日大盤 regime（需 index_daily + screen_picks）。"""
    ensure_index_daily_table(db_path)
    conn = sqlite3.connect(db_path)
    try:
        has_picks = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='screen_picks'"
        ).fetchone()
        if not has_picks:
            return []
        rows = conn.execute(
            """
            SELECT p.bucket, i.regime, p.next_pct
            FROM screen_picks p
            JOIN index_daily i ON i.date = p.as_of AND i.symbol = ?
            WHERE p.next_pct IS NOT NULL
            ORDER BY p.as_of DESC
            LIMIT ?
            """,
            (_INDEX_SYMBOL, limit_days * 40),
        ).fetchall()
    finally:
        conn.close()
    if not rows:
        return []
    agg: Dict[Tuple[str, str], List[float]] = {}
    for bucket, regime, pct in rows:
        if not regime or regime == "unknown":
            continue
        agg.setdefault((str(bucket), str(regime)), []).append(float(pct))
    out = []
    for (bucket, regime), pcts in sorted(agg.items()):
        n = len(pcts)
        if n < 3:
            continue
        avg = sum(pcts) / n
        hit = sum(1 for p in pcts if p > 0) / n
        out.append(
            {
                "bucket": bucket,
                "regime": regime,
                "n": n,
                "avg_next_pct": round(avg, 2),
                "hit_rate": round(hit, 2),
            }
        )
    return out


def _item_sort_score(key: str, item: Dict[str, Any]) -> float:
    if key == "leave_zero":
        return float(item.get("q60r") or 0) * 2 + (20 - min(int(item.get("vol_rank_120") or 99), 20))
    if key == "golden_buy":
        return -float(item.get("bias_monthly") or 0)
    return float(item.get("q60r") or 0) + float(item.get("pct_change") or item.get("pct") or 0) * 0.1


def latest_regime(db_path: str) -> str:
    ensure_index_daily_table(db_path)
    conn = sqlite3.connect(db_path)
    try:
        row = conn.execute(
            "SELECT regime FROM index_daily WHERE symbol=? ORDER BY date DESC LIMIT 1",
            (_INDEX_SYMBOL,),
        ).fetchone()
    finally:
        conn.close()
    if row and row[0]:
        return str(row[0])
    return "neutral"


def sync_regime_ai_weights(db_path: str, as_of: Optional[str] = None) -> Dict[str, float]:
    """盤後／海選後：復盤 base 權重 × 大盤 regime → bucket_w_*。"""
    from screen_review import adapt_bucket_weights

    snap = analyze_taiwan_market(db_path, as_of)
    regime = snap.get("regime") if snap.get("ok") else latest_regime(db_path)
    return adapt_bucket_weights(db_path, regime=regime)


def apply_market_weights(results: Dict[str, Any], snap: Dict[str, Any]) -> Dict[str, Any]:
    """依大盤 regime 調整桶內排序與上限。"""
    if not snap.get("ok"):
        return results
    regime = str(snap.get("regime") or "neutral")
    mults = REGIME_BUCKET_MULT.get(regime, REGIME_BUCKET_MULT["neutral"])
    caps = REGIME_BUCKET_CAP.get(regime, {})
    out = dict(results)
    out["_mkt_regime"] = regime
    out["_mkt_confidence"] = snap.get("confidence")
    for key, items in list(out.items()):
        if not isinstance(items, list) or key.startswith("_"):
            continue
        if not items:
            continue
        m = float(mults.get(key, 1.0))
        scored = sorted(
            ((float(_item_sort_score(key, it)) * m, it) for it in items),
            key=lambda x: x[0],
            reverse=True,
        )
        trimmed = [it for _, it in scored]
        cap = caps.get(key)
        if cap and len(trimmed) > cap:
            trimmed = trimmed[:cap]
        out[key] = trimmed
    return out


def market_screening_note(snap: Dict[str, Any]) -> str:
    if not snap.get("ok"):
        return ""
    reg = snap.get("regime")
    conf = snap.get("confidence")
    if reg == "bull":
        return f"大盤多頭帶動（信心 {conf}%）：佈局桶加權偏多，起漲仍看獲利格。"
    if reg == "bear":
        return f"大盤空方壓力（信心 {conf}%）：突破桶縮水，起漲需量熱＋站上月線。"
    return f"大盤區間震盪（信心 {conf}%）：中性權重，選股看個股結構。"


def format_taiwan_market_brief_html(db_path: str, as_of: Optional[str] = None) -> str:
    snap = analyze_taiwan_market(db_path, as_of)
    if not snap.get("ok"):
        return ""
    lines = [
        "<b>📊 台灣加權指數研究</b>",
        f"收盤 <b>{snap['close']}</b>　MA20 {snap['ma20']}　MA60 {snap['ma60']}",
        f"5日 {snap['chg5_pct']:+.2f}%　20日斜率 {snap['slope20_pct']:+.2f}%",
        f"站上月線廣度 {snap['breadth_above_ma20']:.1f}%（{snap['sample_n']} 檔）",
        f"產業法人合計 {snap['sector_flow_net']:+,.0f} 張",
        f"Regime：<b>{snap['regime_label']}</b>（信心 {snap['confidence']}%）",
        market_screening_note(snap),
    ]
    bt = snap.get("backtest") or []
    cur = snap.get("regime")
    hits = [b for b in bt if b.get("regime") == cur and b.get("n", 0) >= 5]
    if hits:
        bits = [f"{b['bucket']} 隔日{b['avg_next_pct']:+.1f}%（勝{b['hit_rate']:.0%}）" for b in hits[:3]]
        lines.append("同 regime 海選復盤：" + "　".join(bits))
    return "\n".join(lines)


# 向後相容
apply_market_filter = apply_market_weights
