#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""十年回測旁路｜台積(市值龍頭)×加權 同向／背離組合。

使用者方向：台積全市场值最高，走勢與大盤必有脈絡；要進判斷因子、量化共現。
資料：decade_lab.lab_daily 2330（Yahoo 十年，標非官方）＋ index_daily TWII；
可選 market_tape_daily 成交金額兆元。

不是買訊；不准寫回話筒。
"""
from __future__ import annotations

import itertools
import json
import os
import sqlite3
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

MARKET_DB = Path(os.environ.get("WAYNE_DB_PATH") or (ROOT / "data" / "wayne_market.db"))
LAB_DB = Path(os.environ.get("DECADE_LAB_DB") or (ROOT / "data" / "decade_lab.db"))
OUT_DIR = ROOT / "docs" / "expert_notes" / "飆客" / "decade_lab"
TAIPEI = ZoneInfo("Asia/Taipei")

SAME_EPS = 0.25  # 同向但都很小時仍算 flat
UP = 0.8
DOWN = -0.8
HOLD = -0.35
LEAD = 0.6  # 台積相對加權多／少這麼多％當領先／落後
AMT_TRILLIONS = 1.3
FWD = (1, 3, 5)


def _ymd(raw: Any) -> str:
    t = str(raw or "").replace("-", "")[:8]
    return t if len(t) == 8 and t.isdigit() else ""


def _load_twii(conn: sqlite3.Connection) -> Dict[str, Dict[str, float]]:
    rows = conn.execute(
        """
        SELECT REPLACE(CAST(date AS TEXT),'-',''), close
        FROM index_daily WHERE symbol='TWII' ORDER BY 1
        """
    ).fetchall()
    out: Dict[str, Dict[str, float]] = {}
    prev = None
    for d, c in rows:
        day = _ymd(d)
        try:
            cc = float(c)
        except (TypeError, ValueError):
            continue
        if not day or cc <= 0:
            continue
        ret = None if not prev else (cc / prev - 1.0) * 100.0
        out[day] = {"close": cc, "ret": ret if ret is not None else 0.0, "ok": ret is not None}
        prev = cc
    return out


def _load_tsmc(lab: Path, market: Path) -> Dict[str, Dict[str, float]]:
    out: Dict[str, Dict[str, float]] = {}
    # prefer lab raw_quote decade
    if lab.is_file():
        conn = sqlite3.connect(str(lab), timeout=30.0)
        try:
            rows = conn.execute(
                """
                SELECT date, open, high, low, close, volume
                FROM lab_daily
                WHERE symbol='2330' AND adj_kind='raw_quote'
                ORDER BY date
                """
            ).fetchall()
        except sqlite3.Error:
            rows = []
        finally:
            conn.close()
        prev = None
        for d, o, h, l, c, v in rows:
            day = _ymd(d)
            try:
                cc = float(c)
            except (TypeError, ValueError):
                continue
            if not day or cc <= 0:
                continue
            ret = None if not prev else (cc / prev - 1.0) * 100.0
            try:
                wick = 0.0
                hh, ll, oo = float(h or cc), float(l or cc), float(o or cc)
                span = hh - ll
                if span > 0:
                    wick = (min(oo, cc) - ll) / span
            except (TypeError, ValueError):
                wick = 0.0
            out[day] = {
                "close": cc,
                "ret": ret if ret is not None else 0.0,
                "ok": ret is not None,
                "volume": float(v or 0),
                "wick": wick,
                "src": "lab_yahoo",
            }
            prev = cc
    # overlay official daily_quotes when present (same day prefer official for recent)
    if market.is_file():
        conn = sqlite3.connect(str(market), timeout=30.0)
        try:
            rows = conn.execute(
                """
                SELECT REPLACE(CAST(date AS TEXT),'-',''), open, high, low, close, volume
                FROM daily_quotes WHERE stock_id='2330' ORDER BY 1
                """
            ).fetchall()
        except sqlite3.Error:
            rows = []
        finally:
            conn.close()
        # rebuild ret with merged series: start from lab then override
        for d, o, h, l, c, v in rows:
            day = _ymd(d)
            try:
                cc = float(c)
            except (TypeError, ValueError):
                continue
            if not day or cc <= 0:
                continue
            try:
                hh, ll, oo = float(h or cc), float(l or cc), float(o or cc)
                span = hh - ll
                wick = ((min(oo, cc) - ll) / span) if span > 0 else 0.0
            except (TypeError, ValueError):
                wick = 0.0
            prev_ret = out.get(day, {}).get("ret")
            out[day] = {
                "close": cc,
                "ret": float(prev_ret or 0.0),
                "ok": True,
                "volume": float(v or 0),
                "wick": wick,
                "src": "official",
            }
        # recompute returns on sorted merged closes
        prev = None
        for day in sorted(out.keys()):
            cc = out[day]["close"]
            if prev and prev > 0:
                out[day]["ret"] = (cc / prev - 1.0) * 100.0
                out[day]["ok"] = True
            else:
                out[day]["ret"] = 0.0
                out[day]["ok"] = False
            prev = cc
    return out


def _load_tape(conn: sqlite3.Connection) -> Dict[str, float]:
    try:
        rows = conn.execute(
            "SELECT date, amount_trillion FROM market_tape_daily"
        ).fetchall()
    except sqlite3.Error:
        return {}
    out: Dict[str, float] = {}
    for d, a in rows:
        day = _ymd(d)
        try:
            out[day] = float(a)
        except (TypeError, ValueError):
            continue
    return out


def _fwd(twii: Dict[str, Dict[str, float]], days: Sequence[str], i: int, h: int) -> Optional[float]:
    if i + h >= len(days):
        return None
    c0 = twii[days[i]]["close"]
    c1 = twii[days[i + h]]["close"]
    if c0 <= 0:
        return None
    return (c1 / c0 - 1.0) * 100.0


def main() -> int:
    if not MARKET_DB.is_file():
        print(json.dumps({"error": "missing_market_db"}))
        return 2
    conn = sqlite3.connect(str(MARKET_DB), timeout=30.0)
    try:
        twii = _load_twii(conn)
        tape = _load_tape(conn)
    finally:
        conn.close()
    tsmc = _load_tsmc(LAB_DB, MARKET_DB)
    days = sorted(set(twii) & set(tsmc))
    rows = []
    combo_stats: Dict[str, Dict[str, Any]] = {}
    keys = [
        "both_up",
        "both_down",
        "tsmc_up_twii_flat",
        "tsmc_down_twii_hold",
        "twii_down_tsmc_hold",
        "tsmc_leads_up",
        "tsmc_leads_down",
        "tsmc_lower_wick",
        "amt_ge_1p3t",
        "amt_ge_1p3t_both_down",
    ]

    def bump(combo: Tuple[str, ...], fwd: Dict[str, Optional[float]]) -> None:
        k = "+".join(combo)
        st = combo_stats.setdefault(k, {"n": 0, "fwd": {str(h): [] for h in FWD}})
        st["n"] += 1
        for h in FWD:
            v = fwd.get(str(h))
            if v is not None:
                st["fwd"][str(h)].append(v)

    base_fwd = {str(h): [] for h in FWD}
    for i, day in enumerate(days):
        if day not in twii or not twii[day].get("ok") or not tsmc[day].get("ok"):
            continue
        # index in twii-only calendar for forward
        # use days list itself as calendar
        tr = float(twii[day]["ret"])
        sr = float(tsmc[day]["ret"])
        amt = tape.get(day)
        flags = {
            "both_up": tr >= UP and sr >= UP,
            "both_down": tr <= DOWN and sr <= DOWN,
            "tsmc_up_twii_flat": sr >= UP and abs(tr) <= SAME_EPS,
            "tsmc_down_twii_hold": sr <= DOWN and tr >= HOLD,
            "twii_down_tsmc_hold": tr <= DOWN and sr >= HOLD,
            "tsmc_leads_up": (sr - tr) >= LEAD and sr > 0,
            "tsmc_leads_down": (tr - sr) >= LEAD and sr < 0,  # 台積跌更多
            "tsmc_lower_wick": float(tsmc[day].get("wick") or 0) >= 0.45,
            "amt_ge_1p3t": bool(amt is not None and amt >= AMT_TRILLIONS),
            "amt_ge_1p3t_both_down": bool(
                amt is not None and amt >= AMT_TRILLIONS and tr <= DOWN and sr <= DOWN
            ),
        }
        fwd = {str(h): _fwd(twii, days, i, h) for h in FWD}
        for h in FWD:
            v = fwd.get(str(h))
            if v is not None:
                base_fwd[str(h)].append(v)
        if not any(flags.values()):
            continue
        rows.append(
            {
                "A": {"event_date": day, "seq": "tsmc_twii", "symbol": "TWII×2330"},
                "B": {
                    "flags": flags,
                    "twii_ret": tr,
                    "tsmc_ret": sr,
                    "spread_tsmc_minus_twii": sr - tr,
                    "amount_trillion": amt,
                    "tsmc_src": tsmc[day].get("src"),
                },
                "C": {"fwd_twii_pct": fwd},
                "F": {"pot": "實驗室"},
                "G": {"note": "市值龍頭對照；Yahoo十年＋官方近窗覆寫"},
            }
        )
        on = [k for k in keys if flags.get(k)]
        for r in range(1, min(3, len(on)) + 1):
            for combo in itertools.combinations(sorted(on), r):
                bump(combo, fwd)

    def mean(xs: Sequence[float]) -> Optional[float]:
        return sum(xs) / len(xs) if xs else None

    single = {}
    for k in keys:
        hit = [r for r in rows if r["B"]["flags"].get(k)]
        single[k] = {
            "n": len(hit),
            "fwd3": mean(
                [
                    float(r["C"]["fwd_twii_pct"]["3"])
                    for r in hit
                    if r["C"]["fwd_twii_pct"].get("3") is not None
                ]
            ),
            "avg_spread": mean([float(r["B"]["spread_tsmc_minus_twii"]) for r in hit]) if hit else None,
        }

    top = []
    for k, st in combo_stats.items():
        if st["n"] < 12:
            continue
        fwd_avg = {h: mean(st["fwd"][h]) for h in st["fwd"]}
        base = {h: mean(base_fwd[h]) for h in base_fwd}
        top.append(
            {
                "combo": k,
                "n": st["n"],
                "fwd3": fwd_avg.get("3"),
                "base3": base.get("3"),
                "edge3": (fwd_avg["3"] - base["3"])
                if fwd_avg.get("3") is not None and base.get("3") is not None
                else None,
            }
        )
    top.sort(key=lambda x: (x["n"], abs(x.get("edge3") or 0)), reverse=True)

    summary = {
        "written_at": datetime.now(TAIPEI).isoformat(timespec="seconds"),
        "tz": "Asia/Taipei",
        "overlap_days": len(days),
        "anomaly_or_flag_days": len(rows),
        "tsmc_n": len(tsmc),
        "tape_n": len(tape),
        "single_flags": single,
        "top_combos": top[:35],
        "base_fwd3": mean(base_fwd["3"]),
        "not_buy_signal": True,
        "phone_sync": "blocked",
        "note_zh": "台積當市值龍頭對照軸；與加權同向／背離／量能兆元共現分開計。不是買訊。",
    }
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(TAIPEI).strftime("%Y%m%d")
    jsonl = OUT_DIR / f"tsmc_twii_combos_{stamp}.jsonl"
    latest = OUT_DIR / "tsmc_twii_combos_latest.jsonl"
    with jsonl.open("w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    latest.write_text(jsonl.read_text(encoding="utf-8"), encoding="utf-8")
    (OUT_DIR / "tsmc_twii_combos_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    md = [
        "# 台積×加權 同向／背離組合（實驗室）",
        "",
        f"寫入：`{summary['written_at']}`。重疊日 n={summary['overlap_days']}；台積列 n={summary['tsmc_n']}；tape兆元日 n={summary['tape_n']}。",
        "",
        "## 單旗",
        "",
    ]
    for k, st in single.items():
        md.append(f"- `{k}` n={st['n']} 後3日加權均={st['fwd3']} 當日價差均={st['avg_spread']}")
    md += ["", "## 組合 n≥12", ""]
    for e in top[:20]:
        md.append(f"- `{e['combo']}` n={e['n']} edge3={e['edge3']} (fwd3={e['fwd3']} base={e['base3']})")
    md += ["", summary["note_zh"], "", "不是買訊。", ""]
    (OUT_DIR / "tsmc_twii_combos_latest.md").write_text("\n".join(md), encoding="utf-8")
    print(json.dumps({k: summary[k] for k in ["overlap_days", "tsmc_n", "tape_n", "single_flags", "top_combos", "base_fwd3"]}, ensure_ascii=False, indent=2)[:5000])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
