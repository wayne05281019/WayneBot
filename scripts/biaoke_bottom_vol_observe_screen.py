#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""飆大量價落底觀察掃：對齊 20261126 文（2330／2383）的量價＋轉折結構。

硬邊界：
- Asia/Taipei；官方日 K；未收不當收
- 觀察／對照，不是買訊；不准發明個股 5／9（只標轉折高低，不標浪號）
- 話筒進場仍只認 leave_zero／已過閘 ma60_lower

量門檻（對齊原文「近一年級巨量／問題量」）：
- 以近 ~250 根官方量為一年窗
- 一年級＝ max(0.70×年最大量, 年窗 p92)
- 不准再用「60 日中位×3」冒充一年級（會把金融股事件量誤判）
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

TEACH_POST_ID = "190014392"
TEACH_AS_OF = "20261126"

# 對齊 2330／2383 官方柱：一年級 ≈ 0.70–0.85×年最大
YEAR_LOOKBACK = 250
YEAR_GRADE_MAX_FRAC = 0.70
YEAR_GRADE_PCTL = 0.92
MIN_DRAWDOWN_PCT = 15.0  # 相對近 120 高
MAX_DIST_TO_LOW_PCT = 15.0  # 相對近 60 低（洗盤區）
CONSEC_WINDOW = 5
SEDIMENT_LOOKBACK = 15


@dataclass
class Hit:
    stock_id: str
    stock_name: str
    market: str  # TW / TWO
    close: float
    low_60: float
    high_120: float
    dist_to_low_pct: float
    drawdown_pct: float
    vol_today: float
    vol_year_max: float
    year_grade_floor: float
    vol_ratio_year: float
    consec_year_grade: int
    style: str  # year_grade_consec | sediment | both
    score: float
    note_zh: str
    year_grade_dates: List[str]


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
    con: sqlite3.Connection, sid: str, *, lookback: int = 280
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


def year_grade_floor(vols: Sequence[float]) -> Tuple[float, float]:
    """回傳 (floor, year_max)。"""
    clean = [v for v in vols if v > 0]
    if len(clean) < 80:
        return 0.0, 0.0
    ymax = max(clean)
    vs = sorted(clean)
    pctl = vs[min(len(vs) - 1, int(len(vs) * YEAR_GRADE_PCTL))]
    return max(ymax * YEAR_GRADE_MAX_FRAC, pctl), ymax


def score_bottom_vol(bars: Sequence[Dict[str, float]]) -> Optional[Hit]:
    """量價落底觀察（對齊「近一年級巨量」，非買訊）。

    - 相對近 120 高須有明顯修正
    - 仍在近 60 低洗盤區
    - 近窗出現一年級巨量（不是 60 中位×3）
    - 連續一年級＝2383 型問題量；一年級後量縮沉澱＝2330 型
    """
    if len(bars) < 120:
        return None
    year = list(bars[-YEAR_LOOKBACK:]) if len(bars) >= YEAR_LOOKBACK else list(bars)
    win60 = list(bars[-60:])
    win120 = list(bars[-120:])
    last = bars[-1]
    vols_year = [b["volume"] for b in year]
    floor, ymax = year_grade_floor(vols_year)
    if floor <= 0 or ymax <= 0:
        return None

    low60 = min(b["low"] for b in win60 if b["low"] > 0)
    high120 = max(b["high"] for b in win120 if b["high"] > 0)
    close = last["close"]
    if close <= 0 or low60 <= 0 or high120 <= 0:
        return None
    dist = (close - low60) / low60 * 100.0
    dd = (high120 - close) / high120 * 100.0
    if dist > MAX_DIST_TO_LOW_PCT:
        return None
    if dd < MIN_DRAWDOWN_PCT:
        return None

    def is_yg(v: float) -> bool:
        return v >= floor - 1e-9

    recent5 = list(bars[-CONSEC_WINDOW:])
    yg5 = [1 if is_yg(b["volume"]) else 0 for b in recent5]
    consec = 0
    run = 0
    for f in yg5:
        if f:
            run += 1
            consec = max(consec, run)
        else:
            run = 0

    look = list(bars[-SEDIMENT_LOOKBACK:])
    yg_dates = [b["date"] for b in look if is_yg(b["volume"])]
    peak_yg = max((b["volume"] for b in look if is_yg(b["volume"])), default=0.0)

    # 沉澱：近窗有一年級，末日量明顯低於該峰但仍不是無量
    med60_vols = sorted(b["volume"] for b in win60 if b["volume"] > 0)
    med60 = med60_vols[len(med60_vols) // 2] if med60_vols else 0.0
    sediment = False
    if peak_yg > 0 and med60 > 0:
        if med60 * 0.5 <= last["volume"] < peak_yg * 0.65:
            # 一年級當日須貼近低檔（該日低點距 60 低不太遠）
            near_low_yg = False
            for b in look:
                if is_yg(b["volume"]) and b["low"] > 0:
                    d_lo = (b["low"] - low60) / low60 * 100.0
                    if d_lo <= 12.0:
                        near_low_yg = True
                        break
            sediment = near_low_yg

    style = ""
    score = 0.0
    if consec >= 2:
        style = "year_grade_consec"
        score += 45 + 10 * min(consec, 3)
    if sediment:
        style = "both" if style else "sediment"
        score += 40
    if not style:
        # 單根一年級貼低：仍可觀察，但分數較低
        if sum(yg5) >= 1 and dist <= 10.0:
            style = "year_grade_near_low"
            score += 25
        else:
            return None

    score += max(0.0, MAX_DIST_TO_LOW_PCT - dist)
    score += min(20.0, dd / 2.0)
    # 愈接近年最大愈像原文「一年級」
    score += min(15.0, (last["volume"] / ymax) * 15.0) if ymax else 0.0

    note = (
        f"距60低{dist:.1f}%；相對120高回撤{dd:.1f}%；"
        f"一年級門檻={floor:.0f}（年最大{ymax:.0f}）；"
        f"近{CONSEC_WINDOW}日一年級×{sum(yg5)}；樣式={style}"
    )
    return Hit(
        stock_id="",
        stock_name="",
        market="",
        close=close,
        low_60=low60,
        high_120=high120,
        dist_to_low_pct=round(dist, 2),
        drawdown_pct=round(dd, 2),
        vol_today=last["volume"],
        vol_year_max=ymax,
        year_grade_floor=round(floor, 1),
        vol_ratio_year=round(last["volume"] / ymax, 3) if ymax else 0.0,
        consec_year_grade=int(consec),
        style=style,
        score=round(score, 2),
        note_zh=note,
        year_grade_dates=yg_dates[-6:],
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
            "vol_rule_zh": (
                "一年級巨量＝max(0.70×近250根最大量, 年窗p92)；"
                "不用60日中位×3。連續一年級＝2383型；一年級後量縮沉澱＝2330型。"
            ),
            "universe": {
                "TW_top": len(tw),
                "TWO_top": len(two),
                "scanned_with_asof_bar": scanned,
            },
            "n_hits": len(hits),
            "hits": hits,
            "rule_zh": (
                "先抓一年級大量；浪由尾回推："
                "今日上漲→連回前幾日低點＝新開始；由該低往回試畫五波。"
                "觀察定義用，非買訊／非話筒浪認證。"
            ),
            "tail_back_method_zh": (
                "大量→由尾畫回；今日漲連近低＝新開始；由低往回看能否定義五波。"
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
                "vol_rule_zh": payload.get("vol_rule_zh"),
                "top8": [
                    f"{h['stock_id']}{h['stock_name']}@{h['style']}:"
                    f"{h['score']}/yr{h['vol_ratio_year']}"
                    for h in (payload.get("hits") or [])[:8]
                ],
            },
            ensure_ascii=False,
        )
    )
    return 0 if payload.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
