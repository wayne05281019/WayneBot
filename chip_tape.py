# -*- coding: utf-8 -*-
"""單檔第一眼：價量連漲跌、法人連買連賣、當日 K 形態。"""
from __future__ import annotations

import sqlite3
from typing import Any, Dict, List, Optional, Sequence, Tuple


def fmt_lots(n: int) -> str:
    try:
        v = int(n)
    except (TypeError, ValueError):
        return "0張"
    if v == 0:
        return "0張"
    return f"{v:+,}張"


def fmt_lots_align(n: int, width: int = 7) -> str:
    """數字右對齊，讓「張」同一直欄（用全形空白，避免 Telegram 把半形空白吃掉）。"""
    try:
        v = int(n)
    except (TypeError, ValueError):
        v = 0
    body = "0" if v == 0 else f"{v:+,}"
    extra = width - len(body)
    pad = ""
    while extra >= 2:
        pad += "　"
        extra -= 2
    if extra == 1:
        pad += " "
    return f"{pad}{body}張"


def _sign(x: float) -> int:
    if x > 0:
        return 1
    if x < 0:
        return -1
    return 0


def _take_streak(seq: Sequence[float]) -> Tuple[int, float, int]:
    """從序列尾端取同號連續段；0 會打斷非 0 段。回傳 (天數, 累計, 方向)。"""
    if not seq:
        return 0, 0.0, 0
    s = _sign(seq[-1])
    n = 0
    acc = 0.0
    for x in reversed(seq):
        sx = _sign(x)
        if s == 0:
            if sx == 0:
                n += 1
                continue
            break
        if sx == 0 or sx != s:
            break
        n += 1
        acc += float(x)
    return n, acc, s


def chip_phrase(nets: Sequence[float]) -> str:
    """連買／連賣／連買轉連賣（本段累計張）。"""
    vals = [float(x or 0) for x in nets]
    if not vals:
        return "無資料"
    n, acc, s = _take_streak(vals)
    rest = vals[:-n] if n else vals
    pn, _pacc, ps = _take_streak(rest)

    def side(sign: int, days: int) -> str:
        if sign > 0:
            return f"連買{days}"
        if sign < 0:
            return f"連賣{days}"
        return f"平{days}日"

    if s == 0:
        if ps != 0 and pn:
            return f"{side(ps, pn)}後轉平"
        return "當日無買賣"
    cur = f"{side(s, n)}（累計 {fmt_lots(int(round(acc)))}）"
    if ps != 0 and pn and ps != s:
        return f"{side(ps, pn)}轉{side(s, n)}（本段 {fmt_lots(int(round(acc)))}）"
    return cur


def price_move(closes: Sequence[float]) -> Dict[str, Any]:
    """連漲／連跌天數、區間點數與％（相對轉折前收）。"""
    c = [float(x) for x in closes if x is not None]
    empty = {
        "days": 0,
        "sign": 0,
        "points": 0.0,
        "pct": 0.0,
        "text": "—",
        "tri": "◆",
    }
    if len(c) < 2:
        return empty
    diffs = [c[i] - c[i - 1] for i in range(1, len(c))]
    n, _acc, s = _take_streak(diffs)
    if s == 0 or n <= 0:
        return {**empty, "text": "平盤", "tri": "◆"}
    # 轉折前那根收盤 = 連動起點的前一日
    start_idx = len(c) - 1 - n
    base = c[start_idx]
    last = c[-1]
    points = last - base
    pct = (points / base * 100.0) if base else 0.0
    verb = "漲" if s > 0 else "跌"
    tri = "▲" if s > 0 else "▼"
    text = f"{tri}{n}天{verb} {points:+.2f}（{pct:+.1f}%）"
    return {
        "days": n,
        "sign": s,
        "points": round(points, 2),
        "pct": round(pct, 1),
        "text": text,
        "tri": tri,
    }


def candle_shape(open_: float, high: float, low: float, close: float) -> str:
    rng = max(float(high) - float(low), 1e-6)
    body = abs(float(close) - float(open_))
    upper = float(high) - max(float(open_), float(close))
    lower = min(float(open_), float(close)) - float(low)
    bull = float(close) >= float(open_)
    tone = "紅" if bull else "綠"
    if body / rng < 0.12 and upper > 0.28 * rng and lower > 0.28 * rng:
        return "十字線"
    if lower >= 0.45 * rng and body < 0.38 * rng:
        return f"{tone}K長下影"
    if upper >= 0.45 * rng and body < 0.38 * rng:
        return f"{tone}K長上影"
    if body / rng >= 0.62:
        return f"長{tone}實體"
    if body / rng < 0.18:
        return f"小{tone}K"
    return f"{tone}K"


def volume_tape(volumes: Sequence[float], last_chg: float) -> Dict[str, str]:
    vols = [float(x or 0) for x in volumes]
    if not vols:
        return {"ratio": "—", "pv": "—", "line": "量　—"}
    last = vols[-1]
    hist = vols[-21:-1] if len(vols) > 1 else vols
    ma = sum(hist) / max(len(hist), 1)
    ratio = last / ma if ma > 0 else 0.0
    if last_chg > 0.05 and last > ma * 1.05:
        pv = "價漲量增"
    elif last_chg > 0.05:
        pv = "價漲量縮"
    elif last_chg < -0.05 and last > ma * 1.05:
        pv = "價跌量增"
    elif last_chg < -0.05:
        pv = "價跌量縮"
    else:
        pv = "平盤量能"
    return {
        "ratio": f"{ratio:.1f}倍",
        "pv": pv,
        "line": f"{ratio:.1f}倍　{pv}",
    }


def load_tape_rows(db_path: str, stock_id: str, limit: int = 40) -> List[dict]:
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute(
        """
        SELECT date, open, high, low, close, volume, pct_change,
               COALESCE(foreign_net, 0), COALESCE(trust_net, 0), COALESCE(dealer_net, 0)
        FROM daily_quotes
        WHERE stock_id=?
        ORDER BY date DESC
        LIMIT ?
        """,
        (str(stock_id).strip(), int(limit)),
    )
    raw = cur.fetchall()
    conn.close()
    rows = []
    for date, o, h, l, c, vol, pct, f, t, d in reversed(raw):
        rows.append({
            "date": date,
            "open": float(o or 0),
            "high": float(h or 0),
            "low": float(l or 0),
            "close": float(c or 0),
            "volume": float(vol or 0),
            "pct_change": float(pct or 0),
            "foreign_net": int(f or 0),
            "trust_net": int(t or 0),
            "dealer_net": int(d or 0),
        })
    return rows


def build_tape(db_path: str, stock_id: str) -> Optional[Dict[str, Any]]:
    rows = load_tape_rows(db_path, stock_id, 40)
    if not rows:
        return None
    last = rows[-1]
    closes = [r["close"] for r in rows]
    vols = [r["volume"] for r in rows]
    f_net = [r["foreign_net"] for r in rows]
    t_net = [r["trust_net"] for r in rows]
    d_net = [r["dealer_net"] for r in rows]
    three = [a + b + c for a, b, c in zip(f_net, t_net, d_net)]
    move = price_move(closes)
    vol = volume_tape(vols, last["pct_change"])
    shape = candle_shape(last["open"], last["high"], last["low"], last["close"])
    three_today = int(three[-1])
    vol_i = int(last["volume"] or 0)
    inst_pct = round(three_today / vol_i * 100.0, 1) if vol_i else 0.0
    conflict = ""
    if move["sign"] > 0 and f_net[-1] < 0:
        conflict = "價漲外資轉賣"
    elif move["sign"] < 0 and f_net[-1] > 0:
        conflict = "價跌外資買超"
    elif move["sign"] > 0 and three_today < 0:
        conflict = "價漲法人轉賣"
    elif move["sign"] < 0 and three_today > 0:
        conflict = "價跌法人買超"
    return {
        "last": last,
        "move": move,
        "shape": shape,
        "volume": vol,
        "foreign": {"net": int(f_net[-1]), "phrase": chip_phrase(f_net)},
        "trust": {"net": int(t_net[-1]), "phrase": chip_phrase(t_net)},
        "dealer": {"net": int(d_net[-1]), "phrase": chip_phrase(d_net)},
        "three": {"net": three_today, "phrase": chip_phrase(three)},
        "inst_pct": inst_pct,
        "conflict": conflict,
    }
