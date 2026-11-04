#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""八浪段位 × 黃金切割率（靜默）｜波底↔波頂／波頂↔波底目標對質。

切割率被定義出來就有其意義：用官方樞紐段長量化，觀測帶只留正負容差，
不准另發明一套比例。對質過閘才進 path 幅度／目標價。

語意（八循環簡核，不冒充飆大段號）：
- 推進段結束（impulse_12345）→ 預期反向修正；目標＝前一段長的回撤切割位
  （0.382／0.5／0.618／0.75／0.786）
- 修正段結束（corrective_abc）→ 預期反向續走；目標＝參考浪延伸
  （1.0／1.272／1.618）
- 例：上升推進段見頂 → 估下一修正浪底大概落在哪一個切割價

規則：只用已收官方柱；不是買訊；不上話筒；WAVE 未對齊神經元前 phone_sync=blocked。
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

from mine_wave_rules import (  # noqa: E402
    DEFAULT_EXT_RATIOS,
    DEFAULT_RETRACE_RATIOS,
)

MARKET_DB = Path(os.environ.get("WAYNE_DB_PATH") or (ROOT / "data" / "wayne_market.db"))
OUT_DIR = ROOT / "docs" / "expert_notes" / "飆客" / "decade_lab"
TAIPEI = ZoneInfo("Asia/Taipei")

MIN_N = 20
# 觀測帶（檢測方法）：不准改切割率本身；只向量化「實際回撤比 − 定義率」的正負容差
# 價％±1.5 對波段過緊；互斥窄帶也不該用 0.55 硬閘（五率均分≈0.20）
RATIO_BAND = 0.08
TOL_PCT = 1.5
# 帶內命中相對均勻基線（2×band／深度窗≈1）抬升才算有意義
BAND_BASELINE = 2.0 * RATIO_BAND  # ≈0.16
BAND_LIFT = 0.04  # hit >= baseline+lift → 該率有用
# 最鄰近定義率：主選占比須明顯高於 1/k
NEAREST_SHARE_GATE = 0.28


def _now() -> str:
    return datetime.now(TAIPEI).strftime("%Y-%m-%dT%H:%M:%S")


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


def _within_band(actual: float, target: float, tol_pct: float = TOL_PCT) -> bool:
    """價％帶（窄）；主對質改用 _within_ratio_band。"""
    if actual <= 0 or target <= 0:
        return False
    return abs(actual - target) / target * 100.0 <= tol_pct


def _within_ratio_band(
    start_px: float,
    end_px: float,
    next_px: float,
    ratio: float,
    band: float = RATIO_BAND,
) -> bool:
    """實際回撤深度是否落在定義切割率 ±band（正負同一帶）。"""
    span = end_px - start_px
    if abs(span) <= 0:
        return False
    # 回撤深度：自 end 往 start；(end-next)/span；同向延伸則深度可 >1 或 <0
    depth = (end_px - next_px) / span
    return abs(depth - float(ratio)) <= float(band)


def retrace_targets(start_px: float, end_px: float) -> Dict[str, float]:
    """前一段 start→end 完成後，反向回撤切割價（定義率，不另發明）。"""
    span = end_px - start_px
    out: Dict[str, float] = {}
    for r in DEFAULT_RETRACE_RATIOS:
        # 自 end 往 start 回撤 r 倍段長
        out[f"{float(r):g}"] = float(end_px - span * float(r))
    return out


def extension_targets(start_px: float, end_px: float, from_px: Optional[float] = None) -> Dict[str, float]:
    """參考浪 start→end，自 from（缺＝end）同向延伸定義率。"""
    span = end_px - start_px
    base = end_px if from_px is None else float(from_px)
    out: Dict[str, float] = {}
    for r in DEFAULT_EXT_RATIOS:
        out[f"{float(r):g}"] = float(base + span * float(r))
    return out


def snapshot_wave_fib_targets(
    bars: Sequence[Dict[str, float]],
    pivots_all: Sequence[Dict[str, Any]],
    as_of: str,
) -> Tuple[Dict[str, Any], List[str]]:
    """as-of 收盤後：最近完成樞紐段 → 黃金切割目標價（含幅度％）。"""
    from scripts.decade_lab_wave8_dual import _phase_from_pivots, confirmed_pivots_asof

    day = _ymd(as_of)
    factors: Dict[str, Any] = {}
    missing: List[str] = []
    day_i = {b["date"]: i for i, b in enumerate(bars)}
    i = day_i.get(day)
    if i is None:
        return factors, ["wave_fib_as_of"]
    # 與 snapshot_wave_asof 同：右窗未確認的樞紐不准進（修前瞻）
    hist = confirmed_pivots_asof(pivots_all, i)
    if len(hist) < 2:
        return factors, ["wave_fib_pivots"]

    a, b = hist[-2], hist[-1]
    start_px = float(a["px"])
    end_px = float(b["px"])
    span = end_px - start_px
    if abs(span) <= 0:
        return factors, ["wave_fib_zero_span"]

    phase = _phase_from_pivots(hist)
    ph = str(phase.get("phase") or "unknown")
    leg_up = end_px > start_px
    factors["wave_fib_leg_start"] = round(start_px, 2)
    factors["wave_fib_leg_end"] = round(end_px, 2)
    factors["wave_fib_leg_span"] = round(span, 2)
    factors["wave_fib_leg_up"] = leg_up
    factors["wave_fib_phase"] = ph
    factors["wave_fib_cycle"] = phase.get("cycle")
    px = float(bars[i]["close"])

    # 推進段見頂／見底 → 估反向修正回撤位（例：升段1頂→段2底）
    rt = retrace_targets(start_px, end_px)
    for k, lvl in rt.items():
        factors[f"wave_fib_retrace_{k}"] = round(lvl, 2)
        factors[f"wave_fib_retrace_{k}_pct"] = round((lvl / px - 1.0) * 100.0, 4)

    # 修正段完 → 估同向／反向延伸（下一推進）
    ext = extension_targets(start_px, end_px)
    for k, lvl in ext.items():
        factors[f"wave_fib_ext_{k}"] = round(lvl, 2)
        factors[f"wave_fib_ext_{k}_pct"] = round((lvl / px - 1.0) * 100.0, 4)

    # 依相位挑主目標：impulse 完→回撤；ABC 完→延伸；其餘先給 0.618 回撤
    if ph.startswith("impulse"):
        # 反向修正預期
        primary_ratio = "0.618"
        primary = rt.get(primary_ratio)
        mode = "post_impulse_retrace"
        expect_down = leg_up  # 剛走完上升推進 → 估下跌回撤
    elif ph.startswith("corrective"):
        primary_ratio = "1"
        primary = ext.get(primary_ratio)
        mode = "post_corrective_ext"
        expect_down = not leg_up
    else:
        primary_ratio = "0.618"
        primary = rt.get(primary_ratio)
        mode = "leg_retrace_default"
        expect_down = leg_up

    factors["wave_fib_mode"] = mode
    factors["wave_fib_primary_ratio"] = primary_ratio
    if primary is not None:
        factors["wave_fib_primary_px"] = round(float(primary), 2)
        factors["wave_fib_primary_pct"] = round((float(primary) / px - 1.0) * 100.0, 4)
        factors["wave_fib_expect_down"] = bool(expect_down)
        # 失效：突破剛完成段的端點（推進頂／底）
        factors["wave_fib_invalidate_px"] = round(end_px, 2)
    factors["wave_fib_tol_pct"] = TOL_PCT
    factors["wave_fib_ratio_band"] = RATIO_BAND
    factors["wave_fib_defined_ratios"] = True
    return factors, missing


def quantify_wave_fib_targets(conn: sqlite3.Connection) -> Dict[str, Any]:
    """對每個已完成樞紐段：下一相反樞紐是否落在各切割率觀測帶內。"""
    from scripts.decade_lab_wave8_dual import _load_twii, _pivots

    bars = _load_twii(conn)
    pivots = _pivots(bars)
    # 每段 i→i+1 完成後，預測 i+2（下一相反端）
    by_ratio: Dict[str, List[bool]] = {f"{float(r):g}": [] for r in DEFAULT_RETRACE_RATIOS}
    by_ext: Dict[str, List[bool]] = {f"{float(r):g}": [] for r in DEFAULT_EXT_RATIOS}
    nearest_retrace: Dict[str, int] = {f"{float(r):g}": 0 for r in DEFAULT_RETRACE_RATIOS}
    nearest_ext: Dict[str, int] = {f"{float(r):g}": 0 for r in DEFAULT_EXT_RATIOS}
    samples: List[Dict[str, Any]] = []
    n_retrace = 0
    n_ext = 0

    for k in range(len(pivots) - 2):
        a, b, c = pivots[k], pivots[k + 1], pivots[k + 2]
        # 必須交替
        if a["kind"] == b["kind"] or b["kind"] == c["kind"]:
            continue
        start_px, end_px, next_px = float(a["px"]), float(b["px"]), float(c["px"])
        if abs(end_px - start_px) <= 0:
            continue
        span = end_px - start_px
        depth = (end_px - next_px) / span if span else None
        # 回撤母體：下一端反向（深度落在 0～1.2）；延伸母體：同向續走（深度≤0）
        is_retrace_leg = depth is not None and 0.0 < depth <= 1.2
        is_ext_leg = depth is not None and depth <= 0.0
        row_hits: Dict[str, Any] = {"depth": depth, "is_retrace": is_retrace_leg, "is_ext": is_ext_leg}
        if is_retrace_leg:
            n_retrace += 1
            for key in by_ratio:
                hit = _within_ratio_band(start_px, end_px, next_px, float(key), RATIO_BAND)
                by_ratio[key].append(hit)
                row_hits[f"retrace_{key}"] = hit
            # 最鄰近定義率（主檢測）
            nearest = min(by_ratio.keys(), key=lambda rk: abs(float(depth) - float(rk)))
            nearest_retrace[nearest] += 1
            row_hits["nearest_retrace"] = nearest
        if is_ext_leg:
            n_ext += 1
            actual_ext = (next_px - end_px) / span
            for key in by_ext:
                r = float(key)
                hit = abs(actual_ext - r) <= RATIO_BAND
                by_ext[key].append(hit)
                row_hits[f"ext_{key}"] = hit
            nearest_e = min(by_ext.keys(), key=lambda rk: abs(actual_ext - float(rk)))
            nearest_ext[nearest_e] += 1
            row_hits["nearest_ext"] = nearest_e
        samples.append(
            {
                "leg_end": b.get("date"),
                "next": c.get("date"),
                "start": round(start_px, 2),
                "end": round(end_px, 2),
                "next_px": round(next_px, 2),
                "depth": round(depth, 4) if depth is not None else None,
                "leg_up": end_px > start_px,
                "hits": row_hits,
            }
        )

    def score(bucket: Dict[str, List[bool]], kind: str) -> List[Dict[str, Any]]:
        rows: List[Dict[str, Any]] = []
        for key, xs in bucket.items():
            n = len(xs)
            if n < MIN_N:
                continue
            hit = sum(1 for x in xs if x) / n
            useful = hit >= (BAND_BASELINE + BAND_LIFT)
            rows.append(
                {
                    "ratio": key,
                    "kind": kind,
                    "n": n,
                    "hit_in_band": round(hit, 4),
                    "baseline": round(BAND_BASELINE, 4),
                    "lift": round(hit - BAND_BASELINE, 4),
                    "ratio_band": RATIO_BAND,
                    "tol_pct": TOL_PCT,
                    "gate": "hard" if useful else "observe",
                    "note_zh": "切割率固定；帶內命中相對均勻基線抬升才算有用",
                }
            )
        rows.sort(key=lambda r: -float(r["hit_in_band"]))
        return rows

    def nearest_table(counts: Dict[str, int], total: int, kind: str) -> List[Dict[str, Any]]:
        rows: List[Dict[str, Any]] = []
        if total < MIN_N:
            return rows
        for key, c in counts.items():
            share = c / total
            rows.append(
                {
                    "ratio": key,
                    "kind": kind,
                    "n": c,
                    "share": round(share, 4),
                    "uniform": round(1.0 / max(1, len(counts)), 4),
                    "gate": "hard" if share >= NEAREST_SHARE_GATE else "observe",
                    "note_zh": "下一樞紐最靠近哪一個定義切割率",
                }
            )
        rows.sort(key=lambda r: -float(r["share"]))
        return rows

    retrace_scores = score(by_ratio, "retrace_next_pivot")
    ext_scores = score(by_ext, "extension_next_pivot")
    nearest_r = nearest_table(nearest_retrace, n_retrace, "nearest_retrace")
    nearest_e = nearest_table(nearest_ext, n_ext, "nearest_extension")
    # 主選：最鄰近回撤率過閘；否則帶內抬升最高；再否則觀察第一名
    primary = next((r for r in nearest_r if r["gate"] == "hard"), None)
    if primary is not None:
        primary = {
            "ratio": primary["ratio"],
            "kind": "retrace_next_pivot",
            "n": n_retrace,
            "hit_in_band": primary["share"],
            "share": primary["share"],
            "selection": "nearest_mode",
            "ratio_band": RATIO_BAND,
            "gate": "hard",
            "note_zh": "主目標＝回撤段最鄰近定義率（過均勻基線）",
        }
    if primary is None:
        primary = next((r for r in retrace_scores if r["gate"] == "hard"), None)
    if primary is None and nearest_r:
        top = nearest_r[0]
        primary = {
            "ratio": top["ratio"],
            "kind": "retrace_next_pivot",
            "n": n_retrace,
            "hit_in_band": top["share"],
            "share": top["share"],
            "selection": "nearest_mode_observe",
            "ratio_band": RATIO_BAND,
            "gate": "observe",
            "note_zh": "尚未過鄰近占比閘；仍記眾數供觀測",
        }

    out = {
        "written_at": _now(),
        "tz": "Asia/Taipei",
        "source": "wave_fib_targets",
        "note_zh": (
            "八浪樞紐段底↔頂／頂↔底 × 定義黃金切割率；"
            "觀測＝實際回撤／延伸比 − 定義率，正負帶 ±{:.2f}；過閘才進 path 幅度".format(
                RATIO_BAND
            )
        ),
        "ratio_band": RATIO_BAND,
        "tol_pct": TOL_PCT,
        "min_n": MIN_N,
        "band_baseline": BAND_BASELINE,
        "nearest_share_gate": NEAREST_SHARE_GATE,
        "n_segments": len(samples),
        "n_retrace": n_retrace,
        "n_extension": n_ext,
        "retrace": retrace_scores,
        "extension": ext_scores,
        "nearest_retrace": nearest_r,
        "nearest_extension": nearest_e,
        "primary": primary,
        "not_buy_signal": True,
        "phone_sync": "blocked",
        "WAVE_NEURONS_MATCH": False,
    }
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "wave_fib_targets_latest.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    with gzip.open(OUT_DIR / "wave_fib_targets_samples.jsonl.gz", "wt", encoding="utf-8") as f:
        for r in samples[-500:]:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    return out


def load_wave_fib_primary() -> Dict[str, Any]:
    path = OUT_DIR / "wave_fib_targets_latest.json"
    if not path.is_file():
        return {}
    try:
        blob = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    primary = blob.get("primary") or {}
    if primary.get("gate") == "hard" and primary.get("ratio"):
        return {
            "ratio": str(primary["ratio"]),
            "kind": str(primary.get("kind") or "retrace_next_pivot"),
            "hit_in_band": float(primary.get("hit_in_band") or 0),
            "tol_pct": float(blob.get("tol_pct") or TOL_PCT),
        }
    return {}


def main() -> int:
    conn = sqlite3.connect(str(MARKET_DB), timeout=60.0)
    try:
        out = quantify_wave_fib_targets(conn)
    finally:
        conn.close()
    print(json.dumps({k: out[k] for k in ("n_segments", "primary", "retrace", "extension", "phone_sync")}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
