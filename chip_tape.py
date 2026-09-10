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


def price_move(closes: Sequence[float], last_pct: Optional[float] = None) -> Dict[str, Any]:
    """連漲／連跌天數、區間點數與％（相對轉折前收）。

    最後一根日漲跌用官方 pct_change，不要用缺日／還原後的上一根收盤去算。
    """
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
    if last_pct is not None and c[-1] > 0:
        try:
            pct = float(last_pct)
        except (TypeError, ValueError):
            pct = None
        else:
            if pct == pct:
                denom = 1.0 + pct / 100.0
                if denom > 1e-12:
                    diffs[-1] = c[-1] - (c[-1] / denom)
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
    # 跟海選 q60r 同一套：當日量 ÷ 近 60 根均量（含今日）。
    window = vols[-60:] if len(vols) >= 60 else vols
    ma = sum(window) / max(len(window), 1)
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


def stock_tape_is_emerging(db_path: str, stock_id: str) -> bool:
    """興櫃走 emerging_quotes；不要誤讀上市櫃 daily_quotes 的撞號列。"""
    sid = str(stock_id or "").strip()
    if not sid or not db_path:
        return False
    conn = None
    try:
        conn = sqlite3.connect(db_path)
        cur = conn.cursor()
        try:
            row = cur.execute(
                "SELECT market_type FROM stock_universe WHERE stock_id=? LIMIT 1",
                (sid,),
            ).fetchone()
        except Exception:
            row = None
        mkt = str((row[0] if row else "") or "").strip().upper()
        if mkt in ("EM", "EMERGING", "興櫃"):
            return True
        try:
            n_em = int(
                (cur.execute(
                    "SELECT COUNT(*) FROM emerging_quotes WHERE stock_id=?",
                    (sid,),
                ).fetchone() or [0])[0]
                or 0
            )
        except Exception:
            n_em = 0
        try:
            n_dq = int(
                (cur.execute(
                    "SELECT COUNT(*) FROM daily_quotes WHERE stock_id=?",
                    (sid,),
                ).fetchone() or [0])[0]
                or 0
            )
        except Exception:
            n_dq = 0
        return n_em >= 5 and n_em > n_dq
    except Exception:
        return False
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass


def fmt_chip_md(date_val: Any) -> str:
    """籌碼日短標：9/9。"""
    d = str(date_val or "").replace("-", "")
    if len(d) == 8 and d.isdigit():
        return f"{int(d[4:6])}/{int(d[6:8])}"
    return d


def dates_with_market_t86(conn: sqlite3.Connection, dates: Sequence[str]) -> set:
    """哪些日期全市場已有任一檔非 0 的 T86（當日法人表已進庫）。"""
    uniq = []
    seen = set()
    for raw in dates:
        d = str(raw or "").strip()
        if not d or d in seen:
            continue
        seen.add(d)
        uniq.append(d)
    if not uniq:
        return set()
    ph = ",".join("?" * len(uniq))
    cur = conn.execute(
        f"""
        SELECT date FROM daily_quotes
         WHERE date IN ({ph})
         GROUP BY date
        HAVING SUM(
            ABS(COALESCE(foreign_net,0))+ABS(COALESCE(trust_net,0))+ABS(COALESCE(dealer_net,0))
        ) > 0
        """,
        uniq,
    )
    return {str(r[0]) for r in cur.fetchall()}


def _mark_trailing_chip_pending(rows: List[dict], ready: set) -> None:
    i = len(rows) - 1
    while i >= 0 and str(rows[i].get("date") or "") not in ready:
        rows[i]["chips_pending"] = True
        i -= 1


def load_tape_rows(
    db_path: str,
    stock_id: str,
    limit: int = 40,
    merge_live: bool = True,
    live_quote: Optional[dict] = None,
) -> List[dict]:
    sid = str(stock_id).strip()
    emerging = stock_tape_is_emerging(db_path, sid)
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    raw = []
    if emerging:
        try:
            cur.execute(
                """
                SELECT date, open, high, low, close, volume, pct_change
                FROM emerging_quotes
                WHERE stock_id=?
                ORDER BY date DESC
                LIMIT ?
                """,
                (sid, int(limit)),
            )
            raw = [(r[0], r[1], r[2], r[3], r[4], r[5], r[6], None, None, None) for r in cur.fetchall()]
        except Exception:
            raw = []
    if not raw:
        cur.execute(
            """
            SELECT date, open, high, low, close, volume, pct_change,
                   COALESCE(foreign_net, 0), COALESCE(trust_net, 0), COALESCE(dealer_net, 0)
            FROM daily_quotes
            WHERE stock_id=?
            ORDER BY date DESC
            LIMIT ?
            """,
            (sid, int(limit)),
        )
        raw = cur.fetchall()
        emerging = False
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
            "foreign_net": None if emerging else int(f or 0),
            "trust_net": None if emerging else int(t or 0),
            "dealer_net": None if emerging else int(d or 0),
            "emerging": bool(emerging),
            "chips_pending": False,
        })
    if rows and not emerging:
        try:
            ready = dates_with_market_t86(conn, [r["date"] for r in rows[-8:]])
            _mark_trailing_chip_pending(rows, ready)
        except Exception:
            pass
    try:
        conn.close()
    except Exception:
        pass
    try:
        import pandas as pd
        from live_quote import append_live_bar

        if rows and merge_live and not emerging:
            df = pd.DataFrame(rows)
            df = append_live_bar(
                df, str(stock_id).strip(), merge_live=True, live_quote=live_quote
            )
            extra = df.iloc[-1]
            if str(extra.get("date")) != str(rows[-1]["date"]):
                last = dict(rows[-1])
                last.update({
                    "date": extra["date"],
                    "open": float(extra["open"]),
                    "high": float(extra["high"]),
                    "low": float(extra["low"]),
                    "close": float(extra["close"]),
                    "volume": float(extra["volume"]),
                    "pct_change": float(extra.get("pct_change") or extra.get("change_pct") or 0),
                    # 盤中 MIS 沒有官方 T86。0 是占位不是買賣超，連買句不要吃這列。
                    "foreign_net": 0,
                    "trust_net": 0,
                    "dealer_net": 0,
                    "chips_pending": True,
                })
                rows.append(last)
            else:
                rows[-1]["open"] = float(extra["open"])
                rows[-1]["high"] = float(extra["high"])
                rows[-1]["low"] = float(extra["low"])
                rows[-1]["close"] = float(extra["close"])
                rows[-1]["volume"] = float(extra["volume"])
                rows[-1]["pct_change"] = float(extra.get("pct_change") or rows[-1]["pct_change"])
    except Exception:
        pass
    return rows


def last_complete_chip_nets(
    db_path: str,
    stock_id: str,
    as_of: str = "",
) -> Optional[Dict[str, Any]]:
    """最近一筆完整交易日的 T86 張數。

    不併即時列。盤後日 K 已寫進庫、全市場 T86 還沒進時，該日欄位會是 DEFAULT 0，
    不能拿這檔自己全 0 當缺資料，要用「當日全市場是否已有任一檔非 0」判斷就緒。
    """
    sid = str(stock_id or "").strip()
    if not sid or not db_path:
        return None
    if stock_tape_is_emerging(db_path, sid):
        return None
    cap = str(as_of or "").replace("-", "")[:8]
    conn = None
    row = None
    try:
        conn = sqlite3.connect(db_path)
        cur = conn.cursor()
        where = "q.stock_id=?"
        args: List[Any] = [sid]
        if len(cap) == 8 and cap.isdigit():
            where += " AND REPLACE(IFNULL(q.date,''), '-', '') <= ?"
            args.append(cap)
        cur.execute(
            f"""
            SELECT q.date,
                   COALESCE(q.foreign_net, 0),
                   COALESCE(q.trust_net, 0),
                   COALESCE(q.dealer_net, 0)
            FROM daily_quotes q
            WHERE {where}
              AND EXISTS (
                SELECT 1 FROM daily_quotes m
                 WHERE m.date = q.date
                   AND (
                    ABS(COALESCE(m.foreign_net,0))
                    + ABS(COALESCE(m.trust_net,0))
                    + ABS(COALESCE(m.dealer_net,0))
                   ) > 0
              )
            ORDER BY q.date DESC
            LIMIT 1
            """,
            args,
        )
        row = cur.fetchone()
    except Exception:
        return None
    finally:
        try:
            conn.close()
        except Exception:
            pass
    if not row:
        return None
    return {
        "quote_date": str(row[0] or ""),
        "foreign_net": int(row[1] or 0),
        "trust_net": int(row[2] or 0),
        "dealer_net": int(row[3] or 0),
    }


def build_tape(
    db_path: str,
    stock_id: str,
    merge_live: bool = True,
    live_quote: Optional[dict] = None,
) -> Optional[Dict[str, Any]]:
    rows = load_tape_rows(db_path, stock_id, 80, merge_live=merge_live, live_quote=live_quote)
    if not rows:
        return None
    last = rows[-1]
    closes = [r["close"] for r in rows]
    vols = [r["volume"] for r in rows]
    emerging = bool(last.get("emerging")) or any(r.get("foreign_net") is None for r in rows)
    move = price_move(closes, last_pct=last.get("pct_change"))
    vol = volume_tape(vols, last["pct_change"])
    shape = candle_shape(last["open"], last["high"], last["low"], last["close"])
    empty_chips = {
        "last": last,
        "move": move,
        "shape": shape,
        "volume": vol,
        "foreign": {},
        "trust": {},
        "dealer": {},
        "three": {},
        "inst_pct": None,
        "conflict": "",
        "has_chips": False,
        "emerging": bool(emerging),
        "chip_date": "",
        "chip_asof_label": "",
    }
    if emerging:
        return {**empty_chips, "emerging": True}
    chip_rows = [r for r in rows if not r.get("chips_pending")]
    if not chip_rows:
        return empty_chips
    f_net = [int(r["foreign_net"] or 0) for r in chip_rows]
    t_net = [int(r["trust_net"] or 0) for r in chip_rows]
    d_net = [int(r["dealer_net"] or 0) for r in chip_rows]
    three = [a + b + c for a, b, c in zip(f_net, t_net, d_net)]
    last_chip = chip_rows[-1]
    three_today = int(three[-1])
    vol_i = int(last_chip["volume"] or 0)
    inst_pct = round(three_today / vol_i * 100.0, 1) if vol_i else 0.0
    conflict = ""
    same_day = str(last.get("date") or "") == str(last_chip.get("date") or "")
    if same_day:
        if move["sign"] > 0 and f_net[-1] < 0:
            conflict = "價漲外資轉賣"
        elif move["sign"] < 0 and f_net[-1] > 0:
            conflict = "價跌外資買超"
        elif move["sign"] > 0 and three_today < 0:
            conflict = "價漲法人轉賣"
        elif move["sign"] < 0 and three_today > 0:
            conflict = "價跌法人買超"
    chip_date = str(last_chip.get("date") or "")
    chip_asof_label = ""
    if chip_date and str(last.get("date") or "") != chip_date:
        chip_asof_label = fmt_chip_md(chip_date)
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
        "has_chips": True,
        "emerging": False,
        "chip_date": chip_date,
        "chip_asof_label": chip_asof_label,
    }
