#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""飆大量價落底觀察掃：對齊 20261126 文（2330／2383）的量價＋波浪交叉驗證。

硬邊界：
- Asia/Taipei；官方日 K；未收不當收
- 觀察／對照，不是買訊；不准發明個股 5／9
- 話筒進場仍只認 leave_zero／已過閘 ma60_lower
"""
from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple
from zoneinfo import ZoneInfo

TAIPEI = ZoneInfo("Asia/Taipei")
ROOT = Path(__file__).resolve().parents[1]
LAB = ROOT / "docs" / "expert_notes" / "飆客" / "decade_lab"
DB_DEFAULT = ROOT / "data" / "wayne_market.db"

# 對齊原文教學（190014392）
TEACH_POST_ID = "190014392"
TEACH_AS_OF = "20261126"


@dataclass
class Hit:
    stock_id: str
    stock_name: str
    market: str  # TW / TWO
    close: float
    low_60: float
    dist_to_low_pct: float
    vol_today: float
    vol_med_60: float
    vol_ratio: float
    consec_huge: int
    style: str  # giant_consec | sediment | both
    score: float
    note_zh: str


def _num(x: Any) -> float:
    try:
        return float(x)
    except (TypeError, ValueError):
        return 0.0


def _ymd(raw: Any) -> str:
    t = str(raw or "").replace("-", "")[:8]
    return t if len(t) == 8 and t.isdigit() else ""


def latest_full_asof(con: sqlite3.Connection, *, min_rows: int = 1500) -> str:
    row = con.execute(
        """
        SELECT date, COUNT(*) AS c FROM daily_quotes
        GROUP BY date HAVING c >= ?
        ORDER BY date DESC LIMIT 1
        """,
        (int(min_rows),),
    ).fetchone()
    return _ymd(row[0]) if row else ""


def top_n_by_turnover(
    con: sqlite3.Connection,
    *,
    market: str,
    as_of: str,
    n: int = 100,
) -> List[Tuple[str, str, float]]:
    """當日成交金額前 N（排除 ETF／權證：代號長度 4 且純數字）。"""
    rows = con.execute(
        """
        SELECT stock_id, stock_name, turnover_k, volume, close
        FROM daily_quotes
        WHERE date = ? AND market = ?
        """,
        (as_of, market),
    ).fetchall()
    scored: List[Tuple[float, str, str]] = []
    for sid, name, tov, vol, close in rows:
        s = str(sid or "").strip()
        if len(s) != 4 or not s.isdigit():
            continue
        # ETF 常見 00xx；排除
        if s.startswith("00"):
            continue
        amt = _num(tov)
        if amt <= 0:
            amt = _num(vol) * _num(close)
        if amt <= 0:
            continue
        scored.append((amt, s, str(name or "").strip() or s))
    scored.sort(key=lambda t: -t[0])
    return [(s, n, a) for a, s, n in scored[: int(n)]]


def load_bars(
    con: sqlite3.Connection, sid: str, *, lookback: int = 260
) -> List[Dict[str, float]]:
    rows = con.execute(
        """
        SELECT date, open, high, low, close, volume, turnover_k
        FROM daily_quotes
        WHERE stock_id = ?
        ORDER BY date DESC
        LIMIT ?
        """,
        (sid, int(lookback)),
    ).fetchall()
    out: List[Dict[str, float]] = []
    for date, o, h, l, c, v, tov in reversed(rows):
        out.append(
            {
                "date": _ymd(date),
                "open": _num(o),
                "high": _num(h),
                "low": _num(l),
                "close": _num(c),
                "volume": _num(v),
                "turnover_k": _num(tov),
            }
        )
    return out


def score_bottom_vol(bars: Sequence[Dict[str, float]]) -> Optional[Hit]:
    """量價落底觀察（對齊教學，非買訊）。

    - 近窗接近 60 低（洗盤／回馬槍區）
    - 近 5 日出現相對 60 日中位巨量（問題量／承接）
    - 連續 2 根巨量加分（2383 型）
    - 巨量後量縮沉澱加分（2330 型籌碼沉澱）
    """
    if len(bars) < 80:
        return None
    win = list(bars[-60:])
    last = bars[-1]
    vols = [b["volume"] for b in win if b["volume"] > 0]
    if len(vols) < 30:
        return None
    vols_sorted = sorted(vols)
    med = vols_sorted[len(vols_sorted) // 2]
    if med <= 0:
        return None
    low60 = min(b["low"] for b in win if b["low"] > 0)
    close = last["close"]
    if close <= 0 or low60 <= 0:
        return None
    dist = (close - low60) / low60 * 100.0
    # 離 60 低太遠＝不像落底／回馬槍區
    if dist > 18.0:
        return None

    # 近 5 日巨量：≥ max(3×中位, 60日 90 分位)
    p90 = vols_sorted[int(len(vols_sorted) * 0.90)]
    huge_floor = max(med * 3.0, p90)
    recent = list(bars[-5:])
    huge_flags = [1 if b["volume"] >= huge_floor - 1e-9 else 0 for b in recent]
    if sum(huge_flags) < 1:
        return None

    consec = 0
    run = 0
    for f in huge_flags:
        if f:
            run += 1
            consec = max(consec, run)
        else:
            run = 0

    # 沉澱：近 10 日內曾巨量，末日量 < 該巨量×0.65 且仍 ≥ 中位（不是無量）
    sediment = False
    peak_v = 0.0
    for b in bars[-10:]:
        if b["volume"] >= huge_floor:
            peak_v = max(peak_v, b["volume"])
    if peak_v > 0 and med <= last["volume"] < peak_v * 0.65:
        sediment = True

    style = ""
    score = 0.0
    if consec >= 2:
        style = "giant_consec"
        score += 40 + 10 * min(consec, 3)
    if sediment:
        style = "both" if style else "sediment"
        score += 35
    if not style:
        style = "giant_near_low"
        score += 20

    # 愈貼低愈像洗盤區；近 5 日有長下影／收復加分
    score += max(0.0, 18.0 - dist)
    bounce = 0.0
    if len(bars) >= 3:
        lo3 = min(b["low"] for b in bars[-3:])
        if lo3 > 0:
            bounce = (close - lo3) / lo3 * 100.0
            if bounce >= 3.0:
                score += min(15.0, bounce)

    note = (
        f"距60低{dist:.1f}%；近5日巨量×{sum(huge_flags)}；"
        f"量比中位{last['volume']/med:.1f}×；樣式={style}"
    )
    return Hit(
        stock_id="",
        stock_name="",
        market="",
        close=close,
        low_60=low60,
        dist_to_low_pct=round(dist, 2),
        vol_today=last["volume"],
        vol_med_60=med,
        vol_ratio=round(last["volume"] / med, 2),
        consec_huge=int(consec),
        style=style,
        score=round(score, 2),
        note_zh=note,
    )


def screen(
    db_path: str,
    *,
    as_of: str = "",
    top_n: int = 100,
) -> Dict[str, Any]:
    con = sqlite3.connect(db_path)
    try:
        asof = _ymd(as_of) or latest_full_asof(con)
        if not asof:
            return {"ok": False, "reason": "no_full_asof", "hits": []}
        tw = top_n_by_turnover(con, market="TW", as_of=asof, n=top_n)
        two = top_n_by_turnover(con, market="TWO", as_of=asof, n=top_n)
        hits: List[Dict[str, Any]] = []
        scanned = 0
        for market, pool in (("TW", tw), ("TWO", two)):
            for sid, name, _amt in pool:
                bars = load_bars(con, sid)
                # 末日須＝asof
                if not bars or bars[-1]["date"] != asof:
                    continue
                scanned += 1
                hit = score_bottom_vol(bars)
                if not hit:
                    continue
                hit.stock_id = sid
                hit.stock_name = name
                hit.market = market
                hits.append(asdict(hit))
        hits.sort(key=lambda h: -float(h.get("score") or 0))
        return {
            "ok": True,
            "as_of": asof,
            "teach_post_id": TEACH_POST_ID,
            "teach_as_of": TEACH_AS_OF,
            "phone_sync": "blocked",
            "buy_signal": False,
            "not_buy_signal": True,
            "universe": {
                "TW_top": len(tw),
                "TWO_top": len(two),
                "scanned_with_asof_bar": scanned,
            },
            "n_hits": len(hits),
            "hits": hits,
            "rule_zh": (
                "對齊飆大 11/26：近60低＋近窗巨量（問題量／承接）；"
                "連續巨量＝2383型；巨量後量縮沉澱＝2330型。"
                "觀察用，不是買訊；不准發明個股浪號。"
            ),
            "written_at": datetime.now(TAIPEI).strftime("%Y-%m-%dT%H:%M:%S%z"),
        }
    finally:
        con.close()


def main() -> int:
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=str(DB_DEFAULT))
    ap.add_argument("--asof", default="")
    ap.add_argument("--top", type=int, default=100)
    ap.add_argument(
        "--out",
        default=str(LAB / f"biaoke_bottom_vol_observe_{TEACH_AS_OF}.json"),
    )
    args = ap.parse_args()
    payload = screen(args.db, as_of=args.asof, top_n=int(args.top))
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    latest = LAB / "biaoke_bottom_vol_observe_latest.json"
    latest.write_text(out.read_text(encoding="utf-8"), encoding="utf-8")
    print(
        json.dumps(
            {
                "ok": payload.get("ok"),
                "as_of": payload.get("as_of"),
                "n_hits": payload.get("n_hits"),
                "universe": payload.get("universe"),
                "top5": [
                    f"{h['stock_id']}{h['stock_name']}@{h['style']}:{h['score']}"
                    for h in (payload.get("hits") or [])[:5]
                ],
            },
            ensure_ascii=False,
        )
    )
    return 0 if payload.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
