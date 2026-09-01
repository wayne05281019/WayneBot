# -*- coding: utf-8 -*-
"""台灣加權指數深度研究：大盤 regime、趨勢、籌碼與個股信心關聯。"""
from __future__ import annotations

import sqlite3
from typing import Any, Dict, List, Optional

import pandas as pd
import requests

_SESSION = requests.Session()
_SESSION.headers.update({"User-Agent": "WayneBot/1.0"})
_INDEX_YAHOO = "%5ETWII"


def _fetch_index_daily(range_: str = "1y") -> pd.DataFrame:
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
    for ts, cl, vol in zip(stamps, q.get("close") or [], q.get("volume") or []):
        if cl is None:
            continue
        rows.append(
            {
                "date": pd.Timestamp(ts, unit="s", tz="UTC").tz_convert("Asia/Taipei").strftime("%Y%m%d"),
                "close": float(cl),
                "volume": float(vol or 0),
            }
        )
    return pd.DataFrame(rows)


def _breadth_from_db(db_path: str, as_of: str) -> Dict[str, float]:
    conn = sqlite3.connect(db_path)
    try:
        rows = conn.execute(
            """
            SELECT q.stock_id, q.close, q.volume
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
    above = 0
    total = 0
    for sid, cl, _ in rows:
        seq = by_sid.get(str(sid), [])
        if len(seq) < 20:
            continue
        ma20 = sum(seq[:20]) / 20.0
        if ma20 <= 0:
            continue
        total += 1
        if float(cl) >= ma20:
            above += 1
    pct = (above / total * 100.0) if total else 0.0
    return {"above_ma20_pct": round(pct, 1), "sample_n": total}


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
    """加權指數趨勢 + 市場廣度 + 法人合計 → regime 與操作信心。"""
    as_of = str(as_of or "").strip()
    idx = _fetch_index_daily("1y")
    if idx.empty:
        return {"ok": False, "regime": "unknown", "brief": "加權指數資料暫不可用"}
    if as_of:
        sub = idx[idx["date"] <= as_of]
        if not sub.empty:
            idx = sub
    closes = idx["close"].astype(float)
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
    breadth = _breadth_from_db(db_path, as_of or str(idx["date"].iloc[-1]))
    flow = _sector_flow_sum(db_path, as_of or str(idx["date"].iloc[-1]))
    score = 0
    if c >= ma20:
        score += 1
    if c >= ma60:
        score += 1
    if ma20 >= ma60:
        score += 1
    if slope20 > 0:
        score += 1
    if breadth.get("above_ma20_pct", 0) >= 45:
        score += 1
    if flow > 0:
        score += 1
    if score >= 5:
        regime = "bull"
        label = "多頭帶動"
    elif score <= 2:
        regime = "bear"
        label = "空方壓力"
    else:
        regime = "neutral"
        label = "區間震盪"
    confidence = round(min(100.0, max(15.0, 35.0 + score * 10.0 + chg5 * 0.8)), 1)
    return {
        "ok": True,
        "as_of": as_of or str(idx["date"].iloc[-1]),
        "close": round(c, 1),
        "ma20": round(ma20, 1),
        "ma60": round(ma60, 1),
        "chg5_pct": round(chg5, 2),
        "slope20_pct": round(slope20, 2),
        "breadth_above_ma20": breadth.get("above_ma20_pct", 0),
        "sample_n": breadth.get("sample_n", 0),
        "sector_flow_net": round(flow, 0),
        "regime": regime,
        "regime_label": label,
        "confidence": confidence,
        "score": score,
    }


def market_screening_note(snap: Dict[str, Any]) -> str:
    if not snap.get("ok"):
        return ""
    reg = snap.get("regime")
    conf = snap.get("confidence")
    if reg == "bull":
        return f"大盤多頭帶動（信心 {conf}%）：佈局桶可積極，起漲仍看個股獲利格。"
    if reg == "bear":
        return f"大盤空方壓力（信心 {conf}%）：縮小追高，起漲需量熱＋站上月線。"
    return f"大盤區間震盪（信心 {conf}%）：選股看個股結構，勿單靠大盤追高。"


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
    return "\n".join(lines)


def apply_market_filter(results: Dict[str, Any], snap: Dict[str, Any]) -> Dict[str, Any]:
    """空方時略縮當沖／隔日沖名單（大盤向下時避險）。"""
    if not snap.get("ok") or snap.get("regime") != "bear":
        return results
    out = dict(results)
    for key in ("day_trade", "overnight"):
        items = list(out.get(key) or [])
        if len(items) > 6:
            out[key] = items[:6]
    return out
