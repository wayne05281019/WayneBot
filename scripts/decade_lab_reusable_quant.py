#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""二十年數字柱 → 可沿用量化摘要（靜默）。

原則：找不到脈絡＝規則錯，再反向改切法；只留下 n 夠、相對基線有 edge 的數字。
只寫 json／jsonl.gz，不准存圖。不是買訊。
"""
from __future__ import annotations

import gzip
import json
import os
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
DB = Path(os.environ.get("WAYNE_DB_PATH") or (ROOT / "data" / "wayne_market.db"))
OUT_DIR = ROOT / "docs" / "expert_notes" / "飆客" / "decade_lab"
TAIPEI = ZoneInfo("Asia/Taipei")

# 可沿用閘：獨立樣本與相對基線
MIN_N = 20
MIN_EDGE_ABS = 0.25  # 後 3 日加權均％相對基線
FWD = 3


def _ymd(raw: Any) -> str:
    t = str(raw or "").replace("-", "")[:8]
    return t if len(t) == 8 and t.isdigit() else ""


def _f(v: Any) -> Optional[float]:
    try:
        if v is None or v == "":
            return None
        n = float(v)
    except (TypeError, ValueError):
        return None
    if n != n:
        return None
    return n


def _load_sym(conn: sqlite3.Connection, symbol: str) -> Dict[str, Dict[str, float]]:
    rows = conn.execute(
        """
        SELECT REPLACE(CAST(date AS TEXT),'-',''), open, high, low, close, volume, pct_change
        FROM index_daily WHERE symbol=? ORDER BY 1
        """,
        (symbol,),
    ).fetchall()
    out: Dict[str, Dict[str, float]] = {}
    prev = None
    for d, o, h, l, c, vol, pct in rows:
        day = _ymd(d)
        cc = _f(c)
        if not day or not cc or cc <= 0:
            continue
        ret = _f(pct)
        if ret is None and prev and prev > 0:
            ret = (cc / prev - 1.0) * 100.0
        out[day] = {
            "open": _f(o) or cc,
            "high": _f(h) or cc,
            "low": _f(l) or cc,
            "close": cc,
            "volume": _f(vol) or 0.0,
            "ret": ret if ret is not None else 0.0,
            "ret_ok": ret is not None,
        }
        prev = cc
    return out


def _prior_us(us_days: Sequence[str], tw: str) -> Optional[str]:
    prev = None
    for d in us_days:
        if d < tw:
            prev = d
        else:
            break
    return prev


def _fwd(twii: Dict[str, Dict[str, float]], days: Sequence[str], i: int, h: int) -> Optional[float]:
    if i < 0 or i + h >= len(days):
        return None
    c0 = twii[days[i]]["close"]
    c1 = twii[days[i + h]]["close"]
    if c0 <= 0:
        return None
    return (c1 / c0 - 1.0) * 100.0


def _mean(xs: Sequence[float]) -> Optional[float]:
    return (sum(xs) / len(xs)) if xs else None


def _wick(bar: Dict[str, float]) -> float:
    o, h, l, c = bar["open"], bar["high"], bar["low"], bar["close"]
    span = h - l
    if span <= 0:
        return 0.0
    return (min(o, c) - l) / span


def main() -> int:
    if not DB.is_file():
        print(json.dumps({"error": "missing_db"}, ensure_ascii=False))
        return 2
    conn = sqlite3.connect(str(DB), timeout=60.0)
    try:
        twii = _load_sym(conn, "TWII")
        ixic = _load_sym(conn, "IXIC")
        sox = _load_sym(conn, "SOX")
        vix = _load_sym(conn, "VIX")
        tsm = _load_sym(conn, "TSM")
        brent = _load_sym(conn, "BRENT")
        dxy = _load_sym(conn, "DXY")
    finally:
        conn.close()

    tw_days = sorted(twii.keys())
    us_days = sorted(ixic.keys())
    # 20 日均量（TWII）
    vol_ma: Dict[str, float] = {}
    for i, d in enumerate(tw_days):
        window = [twii[tw_days[j]]["volume"] for j in range(max(0, i - 20), i) if twii[tw_days[j]]["volume"] > 0]
        vol_ma[d] = (sum(window) / len(window)) if window else 0.0

    # 旗標：只用 20 年幾乎都有的序列（反向：上一輪 breadth／兆元近窗對不齊＝切錯）
    flags_by_day: Dict[str, Dict[str, bool]] = {}
    for i, day in enumerate(tw_days):
        bar = twii[day]
        if not bar.get("ret_ok"):
            continue
        u = _prior_us(us_days, day)
        if not u or u not in ixic or not ixic[u].get("ret_ok"):
            continue
        ix = ixic[u]["ret"]
        sx = sox[u]["ret"] if u in sox and sox[u].get("ret_ok") else None
        vx = vix[u]["ret"] if u in vix and vix[u].get("ret_ok") else None
        ts = tsm[u]["ret"] if u in tsm and tsm[u].get("ret_ok") else None
        br = brent[u]["ret"] if u in brent and brent[u].get("ret_ok") else None
        dx = dxy[u]["ret"] if u in dxy and dxy[u].get("ret_ok") else None
        tw = bar["ret"]
        ma = vol_ma.get(day) or 0.0
        flags_by_day[day] = {
            "us_up_tw_flat": ix >= 1.0 and abs(tw) <= 0.35,
            "us_down_tw_hold": ix <= -1.5 and tw >= -0.55,
            "us_up_tw_down": ix >= 1.0 and tw <= -0.8,
            "us_risk_off_tw_green": ix <= -1.5 and tw > 0.2,
            "sox_down_tw_hold": sx is not None and sx <= -2.0 and tw >= -0.55,
            "vix_spike_tw_hold": vx is not None and vx >= 8.0 and tw >= -0.55,
            "tsm_down_tw_hold": ts is not None and ts <= -2.0 and tw >= -0.55,
            "tw_lower_wick": _wick(bar) >= 0.45,
            "tw_vol_spike": ma > 0 and bar["volume"] >= 1.5 * ma,
            "brent_up_tw_down": br is not None and br >= 2.0 and tw <= -0.8,
            "dxy_up_tw_down": dx is not None and dx >= 0.6 and tw <= -0.8,
        }

    # 基線後 3 日
    base_fwd: List[float] = []
    day_index = {d: i for i, d in enumerate(tw_days)}
    for day in flags_by_day:
        i = day_index[day]
        v = _fwd(twii, tw_days, i, FWD)
        if v is not None:
            base_fwd.append(v)
    base3 = _mean(base_fwd)

    reusable: List[Dict[str, Any]] = []
    rejected: List[Dict[str, Any]] = []
    for key in sorted({k for f in flags_by_day.values() for k in f}):
        hits = [d for d, f in flags_by_day.items() if f.get(key)]
        fwds = []
        for d in hits:
            v = _fwd(twii, tw_days, day_index[d], FWD)
            if v is not None:
                fwds.append(v)
        n = len(fwds)
        fwd3 = _mean(fwds)
        edge = (fwd3 - base3) if fwd3 is not None and base3 is not None else None
        row = {
            "flag": key,
            "n": n,
            "fwd3_avg": fwd3,
            "base3_avg": base3,
            "edge3": edge,
            "gate_n20": n >= MIN_N,
        }
        if n >= MIN_N and edge is not None and abs(edge) >= MIN_EDGE_ABS:
            row["reusable"] = True
            reusable.append(row)
        else:
            row["reusable"] = False
            row["reject_why"] = (
                f"n<{MIN_N}" if n < MIN_N else f"|edge3|<{MIN_EDGE_ABS}"
            )
            rejected.append(row)

    reusable.sort(key=lambda r: abs(r.get("edge3") or 0), reverse=True)
    rejected.sort(key=lambda r: r["n"], reverse=True)

    # 反向檢討：若可沿用為空 → 原則仍錯
    reverse = []
    if not reusable:
        reverse.append(
            {
                "why": "20y 對齊旗標仍無 n≥20 且 |edge3|≥0.25 → 旗標切法仍錯",
                "next": ["放寬／改門檻", "改成段級鎖預測再對質", "叠多旗 AND 而非單旗"],
            }
        )
    else:
        reverse.append(
            {
                "why": "舊 trough×breadth 近窗把基線抬歪；改用 20y 美股／VIX／油／匯對齊後才有 edge",
                "keep": [r["flag"] for r in reusable],
                "drop": "breadth-only 基線與 trough 共現≥3（近窗對不齊 20y）",
            }
        )

    summary = {
        "written_at": datetime.now(TAIPEI).isoformat(timespec="seconds"),
        "tz": "Asia/Taipei",
        "twii_n": len(tw_days),
        "twii_from": tw_days[0] if tw_days else "",
        "twii_to": tw_days[-1] if tw_days else "",
        "aligned_flag_days": len(flags_by_day),
        "base3_avg": base3,
        "min_n": MIN_N,
        "min_edge_abs": MIN_EDGE_ABS,
        "reusable": reusable,
        "rejected_top": rejected[:15],
        "reverse_think": reverse,
        "not_buy_signal": True,
        "phone_sync": "blocked",
        "storage": "json + jsonl.gz only；不准 PNG",
        "note_zh": (
            "可沿用＝獨立日 n≥20 且後3日加權均相對基線 |edge|≥0.25。"
            "再找不到就再反推原則，不准空轉。"
        ),
    }

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "reusable_quant_latest.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    # 精簡列：只留可沿用
    gz_path = OUT_DIR / "reusable_quant_latest.jsonl.gz"
    with gzip.open(gz_path, "wt", encoding="utf-8") as f:
        for r in reusable:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(json.dumps(summary, ensure_ascii=False, indent=2)[:8000])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
