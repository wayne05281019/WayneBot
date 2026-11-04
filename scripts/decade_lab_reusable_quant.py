#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""二十年數字柱 → 可沿用量化摘要（多輪不同切法，靜默）。

每一輪換思考方式：單旗背離 → 雙旗 AND → 分位尾 → 領先滯後 → 急跌後 → 連兩日。
閘：獨立日 n≥20 且後3日加權均相對基線 |edge|≥0.25 才留。
目標：可沿用 ≥10 條。只寫 json／jsonl.gz，不准存圖。不是買訊。
"""
from __future__ import annotations

import gzip
import itertools
import json
import os
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
DB = Path(os.environ.get("WAYNE_DB_PATH") or (ROOT / "data" / "wayne_market.db"))
OUT_DIR = ROOT / "docs" / "expert_notes" / "飆客" / "decade_lab"
TAIPEI = ZoneInfo("Asia/Taipei")

MIN_N = 20
MIN_EDGE_ABS = 0.25
FWD = 3
TARGET_KEEP = 10


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


def _pctile(vals: Sequence[float], p: float) -> Optional[float]:
    xs = sorted(float(v) for v in vals)
    if not xs:
        return None
    if p <= 0:
        return xs[0]
    if p >= 100:
        return xs[-1]
    k = (len(xs) - 1) * (p / 100.0)
    lo = int(k)
    hi = min(lo + 1, len(xs) - 1)
    w = k - lo
    return xs[lo] * (1 - w) + xs[hi] * w


def _score_flags(
    flags_by_day: Dict[str, Dict[str, bool]],
    *,
    twii: Dict[str, Dict[str, float]],
    tw_days: Sequence[str],
    base3: float,
    lens: str,
) -> List[Dict[str, Any]]:
    day_index = {d: i for i, d in enumerate(tw_days)}
    out: List[Dict[str, Any]] = []
    keys = sorted({k for f in flags_by_day.values() for k in f})
    for key in keys:
        hits = [d for d, f in flags_by_day.items() if f.get(key)]
        fwds: List[float] = []
        for d in hits:
            v = _fwd(twii, tw_days, day_index[d], FWD)
            if v is not None:
                fwds.append(v)
        n = len(fwds)
        fwd3 = _mean(fwds)
        edge = (fwd3 - base3) if fwd3 is not None else None
        row = {
            "flag": key,
            "lens": lens,
            "n": n,
            "fwd3_avg": fwd3,
            "base3_avg": base3,
            "edge3": edge,
            "gate_n20": n >= MIN_N,
            "reusable": bool(n >= MIN_N and edge is not None and abs(edge) >= MIN_EDGE_ABS),
        }
        if not row["reusable"]:
            row["reject_why"] = f"n<{MIN_N}" if n < MIN_N else f"|edge3|<{MIN_EDGE_ABS}"
        out.append(row)
    return out


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
        nvda = _load_sym(conn, "NVDA")
        brent = _load_sym(conn, "BRENT")
        dxy = _load_sym(conn, "DXY")
        usdtwd = _load_sym(conn, "USDTWD")
    finally:
        conn.close()

    tw_days = sorted(twii.keys())
    us_days = sorted(ixic.keys())
    day_index = {d: i for i, d in enumerate(tw_days)}

    vol_ma: Dict[str, float] = {}
    for i, d in enumerate(tw_days):
        window = [
            twii[tw_days[j]]["volume"]
            for j in range(max(0, i - 20), i)
            if twii[tw_days[j]]["volume"] > 0
        ]
        vol_ma[d] = (sum(window) / len(window)) if window else 0.0

    # 對齊列（台股日 ← 前一美股日）
    rows: List[Dict[str, Any]] = []
    for i, day in enumerate(tw_days):
        bar = twii[day]
        if not bar.get("ret_ok"):
            continue
        u = _prior_us(us_days, day)
        if not u or u not in ixic or not ixic[u].get("ret_ok"):
            continue

        def rsym(m: Dict[str, Dict[str, float]]) -> Optional[float]:
            b = m.get(u)
            if not b or not b.get("ret_ok"):
                return None
            return float(b["ret"])

        tw = float(bar["ret"])
        ma = vol_ma.get(day) or 0.0
        prev_tw = None
        if i >= 1 and twii[tw_days[i - 1]].get("ret_ok"):
            prev_tw = float(twii[tw_days[i - 1]]["ret"])
        rows.append(
            {
                "day": day,
                "i": i,
                "tw": tw,
                "prev_tw": prev_tw,
                "ix": float(ixic[u]["ret"]),
                "sx": rsym(sox),
                "vx": rsym(vix),
                "ts": rsym(tsm),
                "nv": rsym(nvda),
                "br": rsym(brent),
                "dx": rsym(dxy),
                "fx": rsym(usdtwd),
                "wick": _wick(bar),
                "vol_spike": bool(ma > 0 and bar["volume"] >= 1.5 * ma),
                "u": u,
            }
        )

    base_fwd = []
    for r in rows:
        v = _fwd(twii, tw_days, r["i"], FWD)
        if v is not None:
            base_fwd.append(v)
    base3 = _mean(base_fwd) or 0.0

    # 分位切（只用對齊列的報酬）
    tw_rets = [r["tw"] for r in rows]
    ix_rets = [r["ix"] for r in rows]
    vx_rets = [r["vx"] for r in rows if r["vx"] is not None]
    p05 = _pctile(tw_rets, 5)
    p10 = _pctile(tw_rets, 10)
    p90 = _pctile(tw_rets, 90)
    ix_p10 = _pctile(ix_rets, 10)
    ix_p90 = _pctile(ix_rets, 90)
    vx_p90 = _pctile(vx_rets, 90)

    lens_rounds: List[Tuple[str, str, Callable[[], Dict[str, Dict[str, bool]]]]] = []

    def lens_diverge() -> Dict[str, Dict[str, bool]]:
        out: Dict[str, Dict[str, bool]] = {}
        for r in rows:
            out[r["day"]] = {
                "us_up_tw_flat": r["ix"] >= 1.0 and abs(r["tw"]) <= 0.35,
                "us_down_tw_hold": r["ix"] <= -1.5 and r["tw"] >= -0.55,
                "us_up_tw_down": r["ix"] >= 1.0 and r["tw"] <= -0.8,
                "us_risk_off_tw_green": r["ix"] <= -1.5 and r["tw"] > 0.2,
                "sox_down_tw_hold": r["sx"] is not None and r["sx"] <= -2.0 and r["tw"] >= -0.55,
                "vix_spike_tw_hold": r["vx"] is not None and r["vx"] >= 8.0 and r["tw"] >= -0.55,
                "tsm_down_tw_hold": r["ts"] is not None and r["ts"] <= -2.0 and r["tw"] >= -0.55,
                "tw_lower_wick": r["wick"] >= 0.45,
                "tw_vol_spike": r["vol_spike"],
                "brent_up_tw_down": r["br"] is not None and r["br"] >= 2.0 and r["tw"] <= -0.8,
                "dxy_up_tw_down": r["dx"] is not None and r["dx"] >= 0.6 and r["tw"] <= -0.8,
                "fx_up_tw_down": r["fx"] is not None and r["fx"] >= 0.4 and r["tw"] <= -0.8,
            }
        return out

    def lens_extreme() -> Dict[str, Dict[str, bool]]:
        out: Dict[str, Dict[str, bool]] = {}
        for r in rows:
            out[r["day"]] = {
                "tw_ret_le_p05": p05 is not None and r["tw"] <= p05,
                "tw_ret_le_p10": p10 is not None and r["tw"] <= p10,
                "tw_ret_ge_p90": p90 is not None and r["tw"] >= p90,
                "ix_ret_le_p10": ix_p10 is not None and r["ix"] <= ix_p10,
                "ix_ret_ge_p90": ix_p90 is not None and r["ix"] >= ix_p90,
                "vix_ret_ge_p90": vx_p90 is not None and r["vx"] is not None and r["vx"] >= vx_p90,
                "tw_crash_2pct": r["tw"] <= -2.0,
                "tw_crash_3pct": r["tw"] <= -3.0,
                "us_crash_2pct": r["ix"] <= -2.0,
            }
        return out

    def lens_leadlag() -> Dict[str, Dict[str, bool]]:
        out: Dict[str, Dict[str, bool]] = {}
        for r in rows:
            out[r["day"]] = {
                "tsm_leads_up_tw_lag": r["ts"] is not None and r["ts"] >= 1.5 and r["tw"] <= 0.3,
                "tsm_leads_down_tw_lag": r["ts"] is not None and r["ts"] <= -1.5 and r["tw"] >= -0.3,
                "sox_leads_up_tw_lag": r["sx"] is not None and r["sx"] >= 1.5 and r["tw"] <= 0.3,
                "sox_leads_down_tw_lag": r["sx"] is not None and r["sx"] <= -1.5 and r["tw"] >= -0.3,
                "nvda_down_tw_hold": r["nv"] is not None and r["nv"] <= -3.0 and r["tw"] >= -0.55,
                "nvda_up_tw_flat": r["nv"] is not None and r["nv"] >= 3.0 and abs(r["tw"]) <= 0.35,
            }
        return out

    def lens_recovery() -> Dict[str, Dict[str, bool]]:
        """急跌當日之後的『當日本身』旗標：用當日大跌定義事件日（後3日從事件日起算）。"""
        out: Dict[str, Dict[str, bool]] = {}
        for r in rows:
            out[r["day"]] = {
                "after_tw_down2_event": r["tw"] <= -2.0,
                "after_tw_down2_with_wick": r["tw"] <= -2.0 and r["wick"] >= 0.45,
                "after_tw_down2_vol_spike": r["tw"] <= -2.0 and r["vol_spike"],
                "after_tw_down2_us_also_down": r["tw"] <= -2.0 and r["ix"] <= -1.0,
                "after_tw_down2_us_up": r["tw"] <= -2.0 and r["ix"] >= 0.5,
                "after_tw_down3_event": r["tw"] <= -3.0,
            }
        return out

    def lens_streak() -> Dict[str, Dict[str, bool]]:
        out: Dict[str, Dict[str, bool]] = {}
        for r in rows:
            pt = r["prev_tw"]
            out[r["day"]] = {
                "tw_down2_streak": pt is not None and pt < 0 and r["tw"] < 0,
                "tw_down2_ge1pct": pt is not None and pt <= -1.0 and r["tw"] <= -1.0,
                "tw_up2_streak": pt is not None and pt > 0 and r["tw"] > 0,
                "tw_up_after_down": pt is not None and pt <= -1.0 and r["tw"] >= 0.5,
                "tw_down_after_up": pt is not None and pt >= 1.0 and r["tw"] <= -0.5,
            }
        return out

    def lens_combo() -> Dict[str, Dict[str, bool]]:
        """第二輪：把已強單旗做 AND（最多 2）。先用 diverge 單旗當原料。"""
        base = lens_diverge()
        seeds = [
            "us_up_tw_down",
            "us_down_tw_hold",
            "us_risk_off_tw_green",
            "tw_vol_spike",
            "dxy_up_tw_down",
            "brent_up_tw_down",
            "tw_lower_wick",
            "vix_spike_tw_hold",
        ]
        out: Dict[str, Dict[str, bool]] = {}
        for day, f in base.items():
            flags = {k: bool(f.get(k)) for k in seeds}
            # 單旗也保留（與 diverge 重疊，之後去重）
            for a, b in itertools.combinations(seeds, 2):
                flags[f"{a}+{b}"] = bool(f.get(a)) and bool(f.get(b))
            out[day] = flags
        return out

    lens_rounds = [
        ("L1_diverge", "美股×台股單旗背離／量影", lens_diverge),
        ("L2_combo", "強單旗兩兩 AND", lens_combo),
        ("L3_extreme", "報酬／VIX 分位尾與急跌", lens_extreme),
        ("L4_leadlag", "台積／費半／輝達領先滯後", lens_leadlag),
        ("L5_recovery", "急跌事件日後續", lens_recovery),
        ("L6_streak", "連兩日同向／反向", lens_streak),
    ]

    all_scored: List[Dict[str, Any]] = []
    by_lens: Dict[str, Any] = {}
    for lens_id, lens_zh, fn in lens_rounds:
        flags = fn()
        scored = _score_flags(flags, twii=twii, tw_days=tw_days, base3=base3, lens=lens_id)
        keep = [r for r in scored if r["reusable"]]
        by_lens[lens_id] = {
            "zh": lens_zh,
            "n_flags": len(scored),
            "n_keep": len(keep),
            "keep_flags": [r["flag"] for r in sorted(keep, key=lambda x: abs(x.get("edge3") or 0), reverse=True)],
        }
        all_scored.extend(scored)

    # 去重：同 flag 名留 |edge| 最大
    best: Dict[str, Dict[str, Any]] = {}
    for r in all_scored:
        if not r.get("reusable"):
            continue
        k = r["flag"]
        if k not in best or abs(r.get("edge3") or 0) > abs(best[k].get("edge3") or 0):
            best[k] = r
    reusable = sorted(best.values(), key=lambda r: abs(r.get("edge3") or 0), reverse=True)

    reverse = []
    if len(reusable) < TARGET_KEEP:
        reverse.append(
            {
                "why": f"可沿用僅 {len(reusable)} < {TARGET_KEEP} → 切法仍不夠／門檻或因子仍缺",
                "next": [
                    "補融資／TE／主動 ETF 數字長史再加透鏡",
                    "段級鎖預測＋失效位對質",
                    "改 FWD=5／改門檻重跑",
                ],
            }
        )
    else:
        reverse.append(
            {
                "why": "多透鏡輪換後達 ≥10；舊單一 trough×breadth 近窗切法廢棄",
                "keep_n": len(reusable),
                "lenses_used": [x[0] for x in lens_rounds],
            }
        )

    summary = {
        "written_at": datetime.now(TAIPEI).isoformat(timespec="seconds"),
        "tz": "Asia/Taipei",
        "twii_n": len(tw_days),
        "twii_from": tw_days[0] if tw_days else "",
        "twii_to": tw_days[-1] if tw_days else "",
        "aligned_flag_days": len(rows),
        "base3_avg": base3,
        "min_n": MIN_N,
        "min_edge_abs": MIN_EDGE_ABS,
        "target_keep": TARGET_KEEP,
        "reusable_n": len(reusable),
        "reusable": reusable,
        "by_lens": by_lens,
        "reverse_think": reverse,
        "not_buy_signal": True,
        "phone_sync": "blocked",
        "storage": "json + jsonl.gz only；不准 PNG",
        "note_zh": (
            f"多輪不同切法；可沿用閘 n≥{MIN_N} 且 |edge3|≥{MIN_EDGE_ABS}；"
            f"目標 ≥{TARGET_KEEP} 條。不是買訊。"
        ),
    }

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "reusable_quant_latest.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    with gzip.open(OUT_DIR / "reusable_quant_latest.jsonl.gz", "wt", encoding="utf-8") as f:
        for r in reusable:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    md = [
        "# 可沿用量化（多透鏡）",
        "",
        f"寫入：`{summary['written_at']}`。對齊日 n={summary['aligned_flag_days']}；基線後3日均={base3:.4f}%。",
        f"可沿用 **{len(reusable)}** 條（目標 ≥{TARGET_KEEP}）。不是買訊。",
        "",
        "## 可沿用",
        "",
    ]
    for r in reusable:
        md.append(
            f"- `{r['flag']}`（{r['lens']}）n={r['n']} fwd3={r['fwd3_avg']:.3f} edge3={r['edge3']:.3f}"
        )
    md += ["", "## 各透鏡", ""]
    for lid, info in by_lens.items():
        md.append(f"- `{lid}` {info['zh']}：keep={info['n_keep']}/{info['n_flags']}")
    md += ["", summary["note_zh"], ""]
    (OUT_DIR / "reusable_quant_latest.md").write_text("\n".join(md), encoding="utf-8")
    print(
        json.dumps(
            {
                "reusable_n": len(reusable),
                "target": TARGET_KEEP,
                "by_lens": {k: v["n_keep"] for k, v in by_lens.items()},
                "reusable": [
                    {"flag": r["flag"], "lens": r["lens"], "n": r["n"], "edge3": r["edge3"]}
                    for r in reusable
                ],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if len(reusable) >= 1 else 2


if __name__ == "__main__":
    raise SystemExit(main())
