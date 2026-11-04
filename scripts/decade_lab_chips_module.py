#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""籌碼多面向模組（靜默）｜融資／廣度／成交值／期貨OI 進路徑預測。

面向：
1. 融資餘額增減（market_margin_daily）— 過熱／殺融資
2. 漲跌家數／跌停（index_breadth_daily）— 廣度背離
3. 市場成交值分位（market_tape_daily）— 量能極端
4. 台指期 OI（futures_daily TX regular）— 未平倉增減
5. 個股資券彙總（daily_margin 有才用）— 市場級融券壓力

法人金額流已在 decade_lab_inst_module；本模組不重複。
規則：只記官方數字；不准假成本；不是買訊；不上話筒。
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
if str(ROOT) not in __import__("sys").path:
    __import__("sys").path.insert(0, str(ROOT))

MARKET_DB = Path(os.environ.get("WAYNE_DB_PATH") or (ROOT / "data" / "wayne_market.db"))
OUT_DIR = ROOT / "docs" / "expert_notes" / "飆客" / "decade_lab"
TAIPEI = ZoneInfo("Asia/Taipei")

MIN_N = 20
MIN_EDGE = 0.25
MIN_SIDE_HIT = 0.55


def _now() -> str:
    return datetime.now(TAIPEI).strftime("%Y-%m-%dT%H:%M:%S")


def _ymd(raw: Any) -> str:
    t = str(raw or "").replace("-", "")[:8]
    return t if len(t) == 8 and t.isdigit() else ""


def _f(v: Any) -> Optional[float]:
    try:
        if v is None or v == "":
            return None
        if isinstance(v, str):
            v = v.replace(",", "").strip()
        n = float(v)
    except (TypeError, ValueError):
        return None
    if n != n:
        return None
    return n


def _z_maps(series: Dict[str, float], look: int = 60) -> Dict[str, float]:
    days = sorted(series)
    zs: Dict[str, float] = {}
    for i, d in enumerate(days):
        window = [series[days[j]] for j in range(max(0, i - look), i)]
        if len(window) < 20:
            continue
        mu = sum(window) / len(window)
        var = sum((x - mu) ** 2 for x in window) / len(window)
        sd = var ** 0.5
        if sd <= 1e-9:
            continue
        zs[d] = (series[d] - mu) / sd
    return zs


def _load_margin(conn: sqlite3.Connection) -> Dict[str, Dict[str, float]]:
    out: Dict[str, Dict[str, float]] = {}
    for d, prev, bal, delta in conn.execute(
        """
        SELECT date, margin_bal_prev_k, margin_bal_k, margin_delta_k
        FROM market_margin_daily ORDER BY 1
        """
    ):
        day = _ymd(d)
        if not day:
            continue
        out[day] = {
            "prev": float(prev or 0),
            "bal": float(bal or 0),
            "delta": float(delta or 0),
        }
    return out


def _load_breadth(conn: sqlite3.Connection) -> Dict[str, Dict[str, float]]:
    out: Dict[str, Dict[str, float]] = {}
    for row in conn.execute(
        """
        SELECT date, up_count, down_count, limit_up, limit_down, flat_count
        FROM index_breadth_daily ORDER BY 1
        """
    ):
        day = _ymd(row[0])
        if not day:
            continue
        up, dn = float(row[1] or 0), float(row[2] or 0)
        out[day] = {
            "up": up,
            "down": dn,
            "limit_up": float(row[3] or 0),
            "limit_down": float(row[4] or 0),
            "flat": float(row[5] or 0),
            "ud_ratio": (up / dn) if dn > 0 else (99.0 if up > 0 else 1.0),
        }
    return out


def _load_tape(conn: sqlite3.Connection) -> Dict[str, float]:
    out: Dict[str, float] = {}
    for d, amt, tril in conn.execute(
        "SELECT date, amount_ntd, amount_trillion FROM market_tape_daily ORDER BY 1"
    ):
        day = _ymd(d)
        if not day:
            continue
        a = _f(tril)
        if a is None:
            ntd = _f(amt)
            a = (ntd / 1e12) if ntd is not None else None
        if a is None:
            continue
        out[day] = float(a)
    return out


def _load_tx_oi(conn: sqlite3.Connection) -> Dict[str, float]:
    out: Dict[str, float] = {}
    for d, oi in conn.execute(
        """
        SELECT REPLACE(CAST(date AS TEXT),'-',''), open_interest
        FROM futures_daily
        WHERE symbol='TX' AND session='regular'
        ORDER BY 1
        """
    ):
        day = _ymd(d)
        v = _f(oi)
        if day and v is not None and v > 0:
            out[day] = float(v)
    return out


def _load_short_agg(conn: sqlite3.Connection) -> Dict[str, Dict[str, float]]:
    """個股資券日表彙總（有才用）。"""
    out: Dict[str, Dict[str, float]] = {}
    try:
        rows = conn.execute(
            """
            SELECT REPLACE(CAST(date AS TEXT),'-',''),
                   SUM(COALESCE(margin_bal,0)), SUM(COALESCE(short_bal,0)), COUNT(*)
            FROM daily_margin
            GROUP BY 1
            HAVING COUNT(*) > 200
            """
        ).fetchall()
    except sqlite3.Error:
        return out
    for d, mb, sb, n in rows:
        day = _ymd(d)
        if not day:
            continue
        out[day] = {"margin_sum": float(mb or 0), "short_sum": float(sb or 0), "n": float(n or 0)}
    return out


def snapshot_chips_factors(conn: sqlite3.Connection, as_of: str) -> Tuple[Dict[str, Any], List[str]]:
    day = _ymd(as_of)
    factors: Dict[str, Any] = {}
    missing: List[str] = []

    # —— 融資 ——
    mrow = conn.execute(
        "SELECT margin_bal_k, margin_delta_k FROM market_margin_daily WHERE date=?",
        (day,),
    ).fetchone()
    if not mrow:
        missing.append("chips_margin")
    else:
        bal, delta = float(mrow[0] or 0), float(mrow[1] or 0)
        factors["chips_margin_bal_k"] = bal
        factors["chips_margin_delta_k"] = delta
        past = conn.execute(
            """
            SELECT margin_delta_k FROM market_margin_daily
            WHERE date < ? ORDER BY date DESC LIMIT 60
            """,
            (day,),
        ).fetchall()
        if len(past) >= 20:
            vals = [float(r[0] or 0) for r in past]
            mu = sum(vals) / len(vals)
            sd = (sum((x - mu) ** 2 for x in vals) / len(vals)) ** 0.5
            z = (delta - mu) / sd if sd > 1e-9 else 0.0
            factors["chips_margin_delta_z"] = round(z, 4)
            factors["chips_margin_z_le_m1"] = bool(z <= -1.0)
            factors["chips_margin_z_ge_p1"] = bool(z >= 1.0)
        prev = conn.execute(
            """
            SELECT margin_delta_k FROM market_margin_daily
            WHERE date < ? ORDER BY date DESC LIMIT 1
            """,
            (day,),
        ).fetchone()
        if prev:
            factors["chips_margin_kill_2d"] = bool(delta < 0 and float(prev[0] or 0) < 0)
            factors["chips_margin_add_2d"] = bool(delta > 0 and float(prev[0] or 0) > 0)

    # —— 廣度 ——
    brow = conn.execute(
        """
        SELECT up_count, down_count, limit_up, limit_down
        FROM index_breadth_daily WHERE REPLACE(CAST(date AS TEXT),'-','')=?
        """,
        (day,),
    ).fetchone()
    if not brow:
        missing.append("chips_breadth")
    else:
        up, dn, lu, ld = [float(x or 0) for x in brow]
        factors["chips_up"] = up
        factors["chips_down"] = dn
        factors["chips_limit_up"] = lu
        factors["chips_limit_down"] = ld
        ud = (up / dn) if dn > 0 else 99.0
        factors["chips_ud_ratio"] = round(ud, 4)
        factors["chips_ud_le_0_6"] = bool(ud <= 0.6)
        factors["chips_ud_ge_1_5"] = bool(ud >= 1.5)
        factors["chips_limit_down_ge_20"] = bool(ld >= 20)
        factors["chips_limit_down_ge_40"] = bool(ld >= 40)
        factors["chips_limit_up_ge_20"] = bool(lu >= 20)

    # —— 成交值分位 ——
    trow = conn.execute(
        "SELECT amount_ntd, amount_trillion FROM market_tape_daily WHERE date=?",
        (day,),
    ).fetchone()
    if not trow:
        missing.append("chips_tape")
    else:
        tril = _f(trow[1])
        if tril is None:
            ntd = _f(trow[0])
            tril = (ntd / 1e12) if ntd is not None else None
        if tril is None:
            missing.append("chips_tape")
        else:
            factors["chips_tape_tril"] = float(tril)
            hist = conn.execute(
                """
                SELECT amount_trillion, amount_ntd FROM market_tape_daily
                WHERE date < ? ORDER BY date DESC LIMIT 120
                """,
                (day,),
            ).fetchall()
            vals: List[float] = []
            for a, ntd in hist:
                v = _f(a)
                if v is None:
                    nn = _f(ntd)
                    v = (nn / 1e12) if nn is not None else None
                if v is not None:
                    vals.append(float(v))
            if len(vals) >= 40:
                vals_s = sorted(vals)

                def cut(p: float) -> float:
                    return vals_s[int((p / 100.0) * (len(vals_s) - 1))]

                factors["chips_tape_p90"] = bool(tril >= cut(90))
                factors["chips_tape_p80"] = bool(tril >= cut(80))
                factors["chips_tape_p10"] = bool(tril <= cut(10))
                factors["chips_tape_p20"] = bool(tril <= cut(20))

    # —— TX OI ——
    oi_row = conn.execute(
        """
        SELECT open_interest FROM futures_daily
        WHERE symbol='TX' AND session='regular'
          AND REPLACE(CAST(date AS TEXT),'-','')=?
        """,
        (day,),
    ).fetchone()
    if not oi_row or _f(oi_row[0]) is None:
        missing.append("chips_tx_oi")
    else:
        oi = float(oi_row[0])
        factors["chips_tx_oi"] = oi
        past_oi = conn.execute(
            """
            SELECT open_interest FROM futures_daily
            WHERE symbol='TX' AND session='regular'
              AND REPLACE(CAST(date AS TEXT),'-','') < ?
            ORDER BY date DESC LIMIT 60
            """,
            (day,),
        ).fetchall()
        vals = [float(r[0]) for r in past_oi if _f(r[0]) is not None and float(r[0]) > 0]
        if len(vals) >= 20:
            mu = sum(vals) / len(vals)
            sd = (sum((x - mu) ** 2 for x in vals) / len(vals)) ** 0.5
            z = (oi - mu) / sd if sd > 1e-9 else 0.0
            factors["chips_tx_oi_z"] = round(z, 4)
            factors["chips_tx_oi_z_ge_p1"] = bool(z >= 1.0)
            factors["chips_tx_oi_z_le_m1"] = bool(z <= -1.0)
            # 日變化
            if past_oi and _f(past_oi[0][0]) is not None:
                prev_oi = float(past_oi[0][0])
                dlt = oi - prev_oi
                factors["chips_tx_oi_delta"] = dlt
                factors["chips_tx_oi_drop"] = bool(dlt < 0)
                factors["chips_tx_oi_rise"] = bool(dlt > 0)

    # —— 融券彙總（有才） ——
    try:
        srow = conn.execute(
            """
            SELECT SUM(COALESCE(short_bal,0)), SUM(COALESCE(margin_bal,0)), COUNT(*)
            FROM daily_margin WHERE REPLACE(CAST(date AS TEXT),'-','')=?
            """,
            (day,),
        ).fetchone()
    except sqlite3.Error:
        srow = None
    if srow and int(srow[2] or 0) > 200:
        short_sum = float(srow[0] or 0)
        factors["chips_short_sum"] = short_sum
        factors["chips_margin_sum"] = float(srow[1] or 0)
        hist_s = conn.execute(
            """
            SELECT REPLACE(CAST(date AS TEXT),'-',''), SUM(COALESCE(short_bal,0))
            FROM daily_margin
            WHERE REPLACE(CAST(date AS TEXT),'-','') < ?
            GROUP BY 1 HAVING COUNT(*)>200
            ORDER BY 1 DESC LIMIT 60
            """,
            (day,),
        ).fetchall()
        vals = [float(r[1] or 0) for r in hist_s]
        if len(vals) >= 20:
            mu = sum(vals) / len(vals)
            sd = (sum((x - mu) ** 2 for x in vals) / len(vals)) ** 0.5
            z = (short_sum - mu) / sd if sd > 1e-9 else 0.0
            factors["chips_short_z"] = round(z, 4)
            factors["chips_short_z_ge_p1"] = bool(z >= 1.0)
            factors["chips_short_z_le_m1"] = bool(z <= -1.0)
    else:
        missing.append("chips_short_agg")

    return factors, missing


def quantify(conn: sqlite3.Connection) -> Dict[str, Any]:
    tw = {
        _ymd(d): float(c)
        for d, c in conn.execute(
            "SELECT REPLACE(CAST(date AS TEXT),'-',''), close FROM index_daily WHERE symbol='TWII'"
        )
        if _ymd(d) and c
    }
    keys = sorted(tw)
    idx = {d: i for i, d in enumerate(keys)}

    def fwd3(d: str) -> Optional[float]:
        i = idx.get(d)
        if i is None or i + 3 >= len(keys):
            return None
        return (tw[keys[i + 3]] / tw[d] - 1.0) * 100.0

    margin = _load_margin(conn)
    breadth = _load_breadth(conn)
    tape = _load_tape(conn)
    oi = _load_tx_oi(conn)
    short_agg = _load_short_agg(conn)

    m_delta = {d: v["delta"] for d, v in margin.items()}
    mz = _z_maps(m_delta)
    tape_z = _z_maps(tape)
    oi_z = _z_maps(oi)
    short_s = {d: v["short_sum"] for d, v in short_agg.items()}
    sz = _z_maps(short_s)

    # 日旗預算
    day_flags: Dict[str, Dict[str, bool]] = {}
    for d in keys:
        if fwd3(d) is None:
            continue
        f: Dict[str, bool] = {}
        if d in mz:
            f["chips_margin_z_le_m1"] = mz[d] <= -1.0
            f["chips_margin_z_ge_p1"] = mz[d] >= 1.0
        if d in margin and d in idx:
            i = idx[d]
            if i >= 1:
                prev = keys[i - 1]
                if prev in margin:
                    f["chips_margin_kill_2d"] = bool(
                        margin[d]["delta"] < 0 and margin[prev]["delta"] < 0
                    )
                    f["chips_margin_add_2d"] = bool(
                        margin[d]["delta"] > 0 and margin[prev]["delta"] > 0
                    )
        if d in breadth:
            ud = breadth[d]["ud_ratio"]
            f["chips_ud_le_0_6"] = ud <= 0.6
            f["chips_ud_ge_1_5"] = ud >= 1.5
            f["chips_limit_down_ge_20"] = breadth[d]["limit_down"] >= 20
            f["chips_limit_down_ge_40"] = breadth[d]["limit_down"] >= 40
            f["chips_limit_up_ge_20"] = breadth[d]["limit_up"] >= 20
        if d in tape and d in sorted(tape):
            # rolling pct via z as proxy + exact percentile later
            ordered_t = sorted(tape)
            if d in ordered_t:
                ti = ordered_t.index(d)
                if ti >= 120:
                    window = sorted(tape[ordered_t[j]] for j in range(ti - 120, ti))
                    if len(window) >= 40:
                        cur = tape[d]
                        f["chips_tape_p90"] = cur >= window[int(0.90 * (len(window) - 1))]
                        f["chips_tape_p80"] = cur >= window[int(0.80 * (len(window) - 1))]
                        f["chips_tape_p10"] = cur <= window[int(0.10 * (len(window) - 1))]
                        f["chips_tape_p20"] = cur <= window[int(0.20 * (len(window) - 1))]
        if d in oi_z:
            f["chips_tx_oi_z_ge_p1"] = oi_z[d] >= 1.0
            f["chips_tx_oi_z_le_m1"] = oi_z[d] <= -1.0
        if d in oi and d in idx:
            i = idx[d]
            if i >= 1 and keys[i - 1] in oi:
                dlt = oi[d] - oi[keys[i - 1]]
                f["chips_tx_oi_drop"] = dlt < 0
                f["chips_tx_oi_rise"] = dlt > 0
        if d in sz:
            f["chips_short_z_ge_p1"] = sz[d] >= 1.0
            f["chips_short_z_le_m1"] = sz[d] <= -1.0
        if f:
            day_flags[d] = f

    days = sorted(day_flags)
    base = [fwd3(d) for d in days]
    base = [x for x in base if x is not None]
    base_m = (sum(base) / len(base)) if base else 0.0
    flags: List[Dict[str, Any]] = []

    codes = [
        "chips_margin_z_le_m1",
        "chips_margin_z_ge_p1",
        "chips_margin_kill_2d",
        "chips_margin_add_2d",
        "chips_ud_le_0_6",
        "chips_ud_ge_1_5",
        "chips_limit_down_ge_20",
        "chips_limit_down_ge_40",
        "chips_limit_up_ge_20",
        "chips_tape_p90",
        "chips_tape_p80",
        "chips_tape_p10",
        "chips_tape_p20",
        "chips_tx_oi_z_ge_p1",
        "chips_tx_oi_z_le_m1",
        "chips_tx_oi_drop",
        "chips_tx_oi_rise",
        "chips_short_z_ge_p1",
        "chips_short_z_le_m1",
    ]

    def add(code: str) -> None:
        xs = [fwd3(d) for d in days if day_flags[d].get(code)]
        xs = [x for x in xs if x is not None]
        if len(xs) < MIN_N:
            return
        m = sum(xs) / len(xs)
        edge = m - base_m
        if abs(edge) < MIN_EDGE:
            return
        if edge > 0:
            hit = sum(1 for x in xs if x > 0.6) / len(xs)
            bias = "up"
        else:
            hit = sum(1 for x in xs if x < -0.6) / len(xs)
            bias = "down"
        if hit < MIN_SIDE_HIT:
            return
        flags.append(
            {
                "code": code,
                "n": len(xs),
                "mean3": round(m, 4),
                "edge3": round(edge, 4),
                "bias": bias,
                "hit_rate_side": round(hit, 4),
                "vote": round(edge, 4),
            }
        )

    for c in codes:
        add(c)

    flags.sort(key=lambda x: -abs(float(x["edge3"])))
    summary = {
        "written_at": _now(),
        "tz": "Asia/Taipei",
        "coverage": {
            "margin_n": len(margin),
            "breadth_n": len(breadth),
            "tape_n": len(tape),
            "tx_oi_n": len(oi),
            "short_agg_n": len(short_agg),
            "scored_days": len(days),
        },
        "base_mean3": round(base_m, 4),
        "flags": flags,
        "n_flags": len(flags),
        "angles_zh": [
            "融資餘額增減 z／連殺",
            "漲跌家數比／跌停簇",
            "成交值分位",
            "台指期 OI z／日變化",
            "融券餘額彙總 z（有才）",
        ],
        "gate": "n>=20 & |edge3|>=0.25 & side_hit>=0.55",
        "goal_zh": "籌碼多面向提高大盤漲勢＋幅度判斷",
        "not_buy_signal": True,
        "phone_sync": "blocked",
        "inst_separate_zh": "法人金額流見 decade_lab_inst_module",
    }
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "chips_quant_latest.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    with gzip.open(OUT_DIR / "chips_quant_flags.jsonl.gz", "wt", encoding="utf-8") as f:
        for row in flags:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    return summary


def load_chips_votes(path: Optional[Path] = None) -> Dict[str, float]:
    p = path or (OUT_DIR / "chips_quant_latest.json")
    if not p.exists():
        return {}
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    out: Dict[str, float] = {}
    for row in d.get("flags") or []:
        code = str(row.get("code") or "")
        if not code:
            continue
        out[code] = float(row.get("vote") or row.get("edge3") or 0.0)
    return out


def main() -> int:
    conn = sqlite3.connect(str(MARKET_DB), timeout=60.0)
    try:
        summary = quantify(conn)
    finally:
        conn.close()
    print(json.dumps(summary, ensure_ascii=False, indent=2)[:5000])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
