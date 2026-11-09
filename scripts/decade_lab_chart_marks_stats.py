# -*- coding: utf-8 -*-
"""話筒圖上「會出現的資訊／指標」統計學對質（雲端實驗室；不上話筒）。

發揮：前向報酬分布、假突破、Wilson 區間、bootstrap、對照組、多視窗、
跨股獨立交易日、年分體制、效應量（vs 隨機同日）。不准改買訊公式。
"""
from __future__ import annotations

import json
import math
import time
from collections import defaultdict
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

from scripts.decade_lab_hsiao_universe import (
    MUST_INCLUDE,
    load_stock_ohlcv,
    select_g_universe,
)

PHONE_SYNC = "blocked"
NOT_BUY_SIGNAL = True
ROOT = Path(__file__).resolve().parents[1]
ART = Path("/opt/cursor/artifacts")
DOC = ROOT / "docs" / "expert_notes" / "飆客" / "decade_lab"
HORIZONS = (1, 5, 10, 20)


def _wilson_ci(hits: int, n: int, z: float = 1.96) -> Tuple[float, float]:
    if n <= 0:
        return (float("nan"), float("nan"))
    p = hits / n
    den = 1.0 + z * z / n
    centre = (p + z * z / (2 * n)) / den
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
    return (max(0.0, centre - half), min(1.0, centre + half))


def _bootstrap_mean_ci(x: np.ndarray, n_boot: int = 400, alpha: float = 0.05) -> Tuple[float, float, float]:
    x = np.asarray(x, dtype=float)
    x = x[np.isfinite(x)]
    if len(x) == 0:
        return (float("nan"), float("nan"), float("nan"))
    rng = np.random.default_rng(42)
    means = []
    for _ in range(n_boot):
        samp = rng.choice(x, size=len(x), replace=True)
        means.append(float(np.mean(samp)))
    lo, hi = np.quantile(means, [alpha / 2, 1 - alpha / 2])
    return (float(np.mean(x)), float(lo), float(hi))


def _normalize_ohlc(df: pd.DataFrame) -> pd.DataFrame:
    """統一小寫 OHLC；補 YYYYMMDD 的 date 欄（leave_zero／止穩公式要這欄）。"""
    out = df.copy()
    if "date" not in out.columns:
        if isinstance(out.index, pd.DatetimeIndex):
            out = out.reset_index()
            # reset 後第一欄常是原 index 名（date / Date / index）
            first = out.columns[0]
            if first != "date":
                out = out.rename(columns={first: "date"})
        elif out.index.name in ("date", "Date") or str(out.index.dtype).startswith("datetime"):
            out = out.reset_index()
            if out.columns[0] != "date":
                out = out.rename(columns={out.columns[0]: "date"})
    colmap = {c.lower(): c for c in out.columns}
    rename = {}
    for need in ("open", "high", "low", "close", "volume", "date"):
        if need in colmap and colmap[need] != need:
            rename[colmap[need]] = need
        elif need.title() in out.columns:
            rename[need.title()] = need
    out = out.rename(columns=rename)
    for c in ("open", "high", "low", "close", "volume"):
        if c in out.columns:
            out[c] = pd.to_numeric(out[c], errors="coerce")
    if "date" in out.columns:
        # leave_zero／止穩認 YYYYMMDD 字串
        dts = pd.to_datetime(out["date"], errors="coerce")
        out["date"] = dts.dt.strftime("%Y%m%d")
        out = out.loc[dts.notna()].reset_index(drop=True)
    return out


def _fwd_ret(close: pd.Series, i: int, h: int) -> float:
    if i + h >= len(close):
        return float("nan")
    a = float(close.iloc[i])
    b = float(close.iloc[i + h])
    if not (np.isfinite(a) and np.isfinite(b) and a > 0):
        return float("nan")
    return b / a - 1.0


def _false_break(low: pd.Series, close: pd.Series, i: int, h: int) -> Optional[bool]:
    """後 h 日任一收盤跌破進場日低 → 假突破。"""
    if i + h >= len(close):
        return None
    entry_lo = float(low.iloc[i])
    if not np.isfinite(entry_lo):
        return None
    for j in range(1, h + 1):
        c = float(close.iloc[i + j])
        if np.isfinite(c) and c < entry_lo:
            return True
    return False


def _ma_cross_up(close: pd.Series, fast: int, slow: int) -> pd.Series:
    f = close.rolling(fast).mean()
    s = close.rolling(slow).mean()
    return (f > s) & (f.shift(1) <= s.shift(1))


def _ma_cross_down(close: pd.Series, fast: int, slow: int) -> pd.Series:
    f = close.rolling(fast).mean()
    s = close.rolling(slow).mean()
    return (f < s) & (f.shift(1) >= s.shift(1))


def _build_mark_masks(df: pd.DataFrame) -> Dict[str, pd.Series]:
    """圖上／邏輯上會出現的標（因果、無前視）。"""
    from decision_card_signals import leave_zero_bar_indices
    from red_arrow_quant import (
        nav_low_arrow_first_mask,
        nav_low_ma60_lower_mask,
        nav_low_ma60_lower_tight_mask,
        nav_low_ma60_vol_mask,
    )
    from stabilize_watch import stabilize_bar_indices

    n = len(df)
    idx = df.index
    empty = pd.Series(False, index=idx)
    masks: Dict[str, pd.Series] = {}

    # 買訊相關
    lz = np.zeros(n, dtype=bool)
    try:
        for i in leave_zero_bar_indices(df):
            if 0 <= int(i) < n:
                lz[int(i)] = True
    except Exception:
        pass
    masks["leave_zero_blue_tri"] = pd.Series(lz, index=idx)  # 藍▲紅框

    try:
        masks["red_arrow_raw_first"] = nav_low_arrow_first_mask(df).reindex(idx).fillna(False)
    except Exception:
        masks["red_arrow_raw_first"] = empty.copy()
    try:
        masks["ma60_vol_proxy"] = nav_low_ma60_vol_mask(df).reindex(idx).fillna(False)
    except Exception:
        masks["ma60_vol_proxy"] = empty.copy()
    try:
        masks["ma60_lower_confirmed"] = nav_low_ma60_lower_mask(df).reindex(idx).fillna(False)
    except Exception:
        masks["ma60_lower_confirmed"] = empty.copy()
    try:
        masks["ma60_lower_tight_vnext"] = nav_low_ma60_lower_tight_mask(df).reindex(idx).fillna(False)
    except Exception:
        masks["ma60_lower_tight_vnext"] = empty.copy()

    # 止穩◆
    st = np.zeros(n, dtype=bool)
    try:
        for i in stabilize_bar_indices(df):
            if 0 <= int(i) < n:
                st[int(i)] = True
    except Exception:
        pass
    masks["stabilize_diamond"] = pd.Series(st, index=idx)

    cl = df["close"]
    masks["ma5_cross_up_ma20"] = _ma_cross_up(cl, 5, 20).fillna(False)
    masks["ma20_cross_up_ma60"] = _ma_cross_up(cl, 20, 60).fillna(False)
    masks["ma5_cross_dn_ma20"] = _ma_cross_down(cl, 5, 20).fillna(False)
    masks["ma20_cross_dn_ma60"] = _ma_cross_down(cl, 20, 60).fillna(False)

    # 量能：放量長紅／量縮
    vo = df["volume"]
    v20 = vo.rolling(20).mean()
    op = df["open"]
    masks["attack_vol_up_bar"] = ((vo >= 2.0 * v20) & (cl > op)).fillna(False)
    masks["dry_vol"] = (vo <= 0.4 * v20).fillna(False)

    # 隨機對照（同檔可交易日隨機，密度對齊 leave_zero）
    rng = np.random.default_rng(abs(hash(str(df.index[0]))) % (2**32))
    p_lz = float(masks["leave_zero_blue_tri"].mean()) if n else 0.0
    p_lz = min(max(p_lz, 0.002), 0.05)
    masks["random_matched_density"] = pd.Series(rng.random(n) < p_lz, index=idx)

    # 無箭頭對照日：非 leave_zero 且非紅箭首觸
    masks["no_buy_mark_day"] = ~(
        masks["leave_zero_blue_tri"] | masks["red_arrow_raw_first"] | masks["ma60_lower_confirmed"]
    )

    return masks


def _score_mask(
    df: pd.DataFrame,
    mask: pd.Series,
    *,
    sid: str,
    tag: str,
) -> List[Dict[str, Any]]:
    cl = df["close"]
    lo = df["low"]
    rows = []
    for i, hit in enumerate(mask.tolist()):
        if not hit:
            continue
        if "date" in df.columns:
            raw_d = str(df["date"].iloc[i])
            if len(raw_d) == 8 and raw_d.isdigit():
                as_of = f"{raw_d[:4]}-{raw_d[4:6]}-{raw_d[6:8]}"
            else:
                as_of = str(pd.Timestamp(raw_d).date())
        else:
            as_of = str(pd.Timestamp(df.index[i]).date())
        for h in HORIZONS:
            r = _fwd_ret(cl, i, h)
            fb = _false_break(lo, cl, i, h)
            rows.append(
                {
                    "sid": sid,
                    "tag": tag,
                    "as_of": as_of,
                    "horizon": h,
                    "ret": r,
                    "hit": (1 if (np.isfinite(r) and r > 0) else 0) if np.isfinite(r) else None,
                    "false_break": (1 if fb else 0) if fb is not None else None,
                    "pending": 0 if np.isfinite(r) else 1,
                }
            )
    return rows


def _aggregate(events: List[Dict[str, Any]]) -> Dict[str, Any]:
    by_tag: Dict[str, Dict[int, List[Dict[str, Any]]]] = defaultdict(lambda: defaultdict(list))
    for e in events:
        by_tag[e["tag"]][int(e["horizon"])].append(e)

    out: Dict[str, Any] = {}
    for tag, horizons in by_tag.items():
        tag_out = {}
        for h, rows in horizons.items():
            scored = [r for r in rows if r.get("pending") == 0 and r.get("hit") is not None]
            rets = np.array([float(r["ret"]) for r in scored if np.isfinite(r.get("ret", np.nan))])
            hits = sum(int(r["hit"]) for r in scored)
            n = len(scored)
            fb_rows = [r for r in scored if r.get("false_break") is not None]
            fb = sum(int(r["false_break"]) for r in fb_rows)
            n_fb = len(fb_rows)
            mean, blo, bhi = _bootstrap_mean_ci(rets)
            wlo, whi = _wilson_ci(hits, n)
            days = {r["as_of"] for r in scored}
            sids = {r["sid"] for r in scored}
            tag_out[f"h{h}"] = {
                "n_events": n,
                "n_unique_days": len(days),
                "n_sids": len(sids),
                "hit_rate": (hits / n) if n else float("nan"),
                "wilson_ci95": [wlo, whi],
                "avg_ret": mean,
                "bootstrap_mean_ci95": [blo, bhi],
                "median_ret": float(np.median(rets)) if len(rets) else float("nan"),
                "p25_ret": float(np.quantile(rets, 0.25)) if len(rets) else float("nan"),
                "p75_ret": float(np.quantile(rets, 0.75)) if len(rets) else float("nan"),
                "false_break_rate": (fb / n_fb) if n_fb else float("nan"),
                "n_false_break_sample": n_fb,
            }
        out[tag] = tag_out
    return out


def _effect_vs_baseline(agg: Dict[str, Any], tag: str, base: str, h: int = 5) -> Dict[str, Any]:
    a = agg.get(tag, {}).get(f"h{h}") or {}
    b = agg.get(base, {}).get(f"h{h}") or {}
    if not a or not b:
        return {"ok": False}
    return {
        "ok": True,
        "horizon": h,
        "hit_delta": float(a.get("hit_rate", np.nan) - b.get("hit_rate", np.nan))
        if np.isfinite(a.get("hit_rate", np.nan)) and np.isfinite(b.get("hit_rate", np.nan))
        else float("nan"),
        "avg_ret_delta": float(a.get("avg_ret", np.nan) - b.get("avg_ret", np.nan))
        if np.isfinite(a.get("avg_ret", np.nan)) and np.isfinite(b.get("avg_ret", np.nan))
        else float("nan"),
        "fb_delta": float(a.get("false_break_rate", np.nan) - b.get("false_break_rate", np.nan))
        if np.isfinite(a.get("false_break_rate", np.nan))
        and np.isfinite(b.get("false_break_rate", np.nan))
        else float("nan"),
        "tag_n_days": a.get("n_unique_days"),
        "base_n_days": b.get("n_unique_days"),
        "gate_n20": bool(a.get("n_unique_days", 0) >= 20),
    }


def run_chart_marks_stats(
    *,
    n_universe: int = 120,
    max_stocks: Optional[int] = None,
) -> Dict[str, Any]:
    t0 = time.time()
    ART.mkdir(parents=True, exist_ok=True)
    DOC.mkdir(parents=True, exist_ok=True)

    # 用 turnover_k 篩流動（修 volume 單位不一致）
    import sqlite3

    con = sqlite3.connect(ROOT / "data" / "wayne_market.db")
    turn = pd.read_sql(
        """
        SELECT stock_id, AVG(turnover_k) AS avg_tk, COUNT(*) AS n
        FROM daily_quotes GROUP BY stock_id
        """,
        con,
    )
    con.close()
    uni = select_g_universe(n=n_universe, include_twse_top100=True)
    uni = uni.merge(turn, on="stock_id", how="left")
    # 額外篩選：avg turnover_k；點名檔豁免
    keep = []
    skip = defaultdict(int)
    for _, r in uni.iterrows():
        sid = str(r["stock_id"])
        if sid in MUST_INCLUDE:
            keep.append(sid)
            continue
        tk = float(r.get("avg_tk") or 0)
        if tk < 800_000:  # 約日均 8 億？若單位是千元則 8e5 千=8e8；對齊 2317~1e7
            # 實際 6442~3e6、2317~1e7：用 1.5e6 當流動下限
            pass
        if tk < 1_500_000 and sid not in MUST_INCLUDE:
            skip["low_turnover_k"] += 1
            continue
        if int(r.get("n_bars") or 0) < 200:
            skip["short_history"] += 1
            continue
        keep.append(sid)
    # 強制點名＋去重；若太少則放寬到 uni 全部強制+百大
    keep = list(dict.fromkeys(keep))
    if len(keep) < 40:
        keep = list(dict.fromkeys(list(MUST_INCLUDE.keys()) + uni["stock_id"].astype(str).tolist()))
        skip["fallback_full_universe"] = 1
    if max_stocks:
        # 保留 must，其餘截斷
        must = [s for s in keep if s in MUST_INCLUDE]
        rest = [s for s in keep if s not in MUST_INCLUDE][: max(0, max_stocks - len(must))]
        keep = must + rest

    all_events: List[Dict[str, Any]] = []
    per_sid_counts: Dict[str, Dict[str, int]] = {}
    errors: Dict[str, str] = {}

    for sid in keep:
        try:
            raw = load_stock_ohlcv(sid)
            if len(raw) < 80:
                skip["too_short_load"] += 1
                continue
            df = _normalize_ohlc(raw)
            masks = _build_mark_masks(df)
            counts = {k: int(v.sum()) for k, v in masks.items()}
            per_sid_counts[sid] = counts
            for tag, m in masks.items():
                all_events.extend(_score_mask(df, m, sid=sid, tag=tag))
        except Exception as e:
            errors[sid] = f"{type(e).__name__}: {e}"

    agg = _aggregate(all_events)
    comparisons = {
        "ma60_lower_vs_leave_zero": _effect_vs_baseline(agg, "ma60_lower_confirmed", "leave_zero_blue_tri", 5),
        "ma60_lower_vs_raw_red": _effect_vs_baseline(agg, "ma60_lower_confirmed", "red_arrow_raw_first", 5),
        "ma60_lower_vs_random": _effect_vs_baseline(agg, "ma60_lower_confirmed", "random_matched_density", 5),
        "leave_zero_vs_random": _effect_vs_baseline(agg, "leave_zero_blue_tri", "random_matched_density", 5),
        "stabilize_vs_random": _effect_vs_baseline(agg, "stabilize_diamond", "random_matched_density", 5),
        "tight_vs_ma60_lower": _effect_vs_baseline(agg, "ma60_lower_tight_vnext", "ma60_lower_confirmed", 5),
        "ma20x60_up_vs_random": _effect_vs_baseline(agg, "ma20_cross_up_ma60", "random_matched_density", 5),
    }

    # 年分體制（leave_zero / ma60_lower h5）
    regime = {}
    for tag in ("leave_zero_blue_tri", "ma60_lower_confirmed"):
        by_year = defaultdict(list)
        for e in all_events:
            if e["tag"] != tag or e.get("horizon") != 5 or e.get("pending"):
                continue
            y = str(e["as_of"])[:4]
            if e.get("hit") is not None:
                by_year[y].append(e)
        regime[tag] = {
            y: {
                "n": len(rows),
                "hit_rate": sum(int(r["hit"]) for r in rows) / len(rows) if rows else float("nan"),
                "avg_ret": float(np.mean([r["ret"] for r in rows if np.isfinite(r["ret"])])) if rows else float("nan"),
            }
            for y, rows in sorted(by_year.items())
        }

    must_focus = {}
    for sid, name in MUST_INCLUDE.items():
        must_focus[sid] = {
            "name": name,
            "mark_counts": per_sid_counts.get(sid, {}),
            "in_run": sid in per_sid_counts,
        }

    # 閘門一句（不准改買訊；只報狀態）
    lz = agg.get("leave_zero_blue_tri", {}).get("h5", {})
    m60 = agg.get("ma60_lower_confirmed", {}).get("h5", {})
    gate_line = (
        f"leave_zero h5 days={lz.get('n_unique_days')} hit={lz.get('hit_rate')}; "
        f"ma60_lower h5 days={m60.get('n_unique_days')} hit={m60.get('hit_rate')}; "
        f"promote=NO（本跑僅統計對質，不上話筒）"
    )

    out = {
        "phone_sync": PHONE_SYNC,
        "not_buy_signal": NOT_BUY_SIGNAL,
        "elapsed_s": round(time.time() - t0, 1),
        "n_stocks_scored": len(per_sid_counts),
        "n_events": len(all_events),
        "skip": dict(skip),
        "horizons": list(HORIZONS),
        "marks_tested": sorted({e["tag"] for e in all_events}),
        "aggregate": agg,
        "comparisons_h5": comparisons,
        "regime_by_year_h5": regime,
        "must_named": must_focus,
        "errors_n": len(errors),
        "errors_sample": dict(list(errors.items())[:8]),
        "gate_one_liner": gate_line,
        "stats_methods": [
            "forward_return_h1_5_10_20",
            "hit_rate_wilson_ci95",
            "bootstrap_mean_ci95",
            "false_break_vs_entry_low",
            "random_density_matched_baseline",
            "no_mark_day_baseline",
            "cross_sectional_multi_stock",
            "unique_trading_day_count",
            "year_regime_split",
            "effect_size_vs_baseline",
            "must_include_focus_counts",
        ],
        "note_zh": "圖上標／均線交叉／量能事件之統計對質；不改 leave_zero／ma60_lower 公式；不上話筒",
    }
    text = json.dumps(out, ensure_ascii=False, indent=2, default=str)
    (ART / "chart_marks_stats_latest.json").write_text(text, encoding="utf-8")
    (DOC / "chart_marks_stats_latest.json").write_text(text, encoding="utf-8")
    # 精簡摘要
    summary = {
        "gate_one_liner": gate_line,
        "n_stocks": out["n_stocks_scored"],
        "marks": out["marks_tested"],
        "comparisons_h5": comparisons,
        "must_named": must_focus,
        "leave_zero_h5": lz,
        "ma60_lower_h5": m60,
        "phone_sync": PHONE_SYNC,
        "elapsed_s": out["elapsed_s"],
    }
    (ART / "chart_marks_stats_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
    )
    print("GATE", gate_line, flush=True)
    print("SUMMARY stocks", out["n_stocks_scored"], "events", out["n_events"], flush=True)
    return out


if __name__ == "__main__":
    run_chart_marks_stats(n_universe=120)
