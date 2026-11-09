# -*- coding: utf-8 -*-
"""強化進場條件 → 提高辨識率（雲端實驗室；不上話筒）。

目標：在「進場＋出場整段」架構下，加濾網讓訊號贏過「同密度隨機」，
且盡量贏 leave_zero 現況。過閘才談查股加符號。
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Tuple

import numpy as np
import pandas as pd

from scripts.decade_lab_chart_marks_stats import _build_mark_masks, _normalize_ohlc
from scripts.decade_lab_hsiao_universe import MUST_INCLUDE, load_stock_ohlcv, select_g_universe
from scripts.decade_lab_phone_trade_confront import (
    ENTRY_TAGS,
    _agg_trades,
    _build_hl_temp,
    _simulate_trades,
)

PHONE_SYNC = "blocked"
NOT_BUY_SIGNAL = True
ROOT = Path(__file__).resolve().parents[1]
ART = Path("/opt/cursor/artifacts")
DOC = ROOT / "docs" / "expert_notes" / "飆客" / "decade_lab"


def _feature_frame(df: pd.DataFrame) -> pd.DataFrame:
    cl = df["close"].astype(float)
    vo = df["volume"].astype(float)
    out = pd.DataFrame(index=df.index)
    out["close"] = cl
    out["ma20"] = cl.rolling(20, min_periods=5).mean()
    out["ma60"] = cl.rolling(60, min_periods=20).mean()
    out["v20"] = vo.rolling(20, min_periods=5).mean()
    out["vol"] = vo
    high20 = cl.rolling(20, min_periods=5).max()
    low20 = cl.rolling(20, min_periods=5).min()
    span = (high20 - low20).clip(lower=cl * 0.002)
    out["rsv"] = ((cl - low20) / span * 100.0).clip(0, 100)
    out["at_hi20"] = cl >= high20 * 0.998
    out["vol_ok"] = vo >= 0.7 * out["v20"]
    out["not_dry"] = vo >= 0.5 * out["v20"]
    out["above_ma60"] = cl >= out["ma60"] * 0.97  # 准許略低於季線 3%
    out["below_ma20"] = cl <= out["ma20"] * 1.02
    out["rsv_mid"] = (out["rsv"] >= 15.0) & (out["rsv"] <= 65.0)
    out["room_to_hi20"] = ~out["at_hi20"]
    return out


def _near_mask(base: pd.Series, other: pd.Series, window: int = 5) -> pd.Series:
    """base 當日，且前後 window 根內 other 曾出現。"""
    o = other.fillna(False).astype(bool)
    near = o.copy()
    for k in range(1, window + 1):
        near = near | o.shift(k).fillna(False) | o.shift(-k).fillna(False)
    return base.fillna(False).astype(bool) & near


FilterFn = Callable[[pd.DataFrame, Dict[str, pd.Series], pd.DataFrame], pd.Series]


def _filters() -> Dict[str, FilterFn]:
    """強化條件字典：回傳布林遮罩（與進場 AND）。"""

    def none(_df, _masks, _feat):
        return pd.Series(True, index=_df.index)

    def vol_structure(df, masks, feat):
        return feat["vol_ok"] & feat["above_ma60"] & feat["room_to_hi20"] & feat["rsv_mid"]

    def leave_with_ma60(df, masks, feat):
        # 進場日附近 5 根曾出現確認紅箭（結構辨識）
        m60 = masks.get("ma60_lower_confirmed", pd.Series(False, index=df.index)).fillna(False)
        near = m60.copy()
        for k in range(1, 6):
            near = near | m60.shift(k).fillna(False) | m60.shift(-k).fillna(False)
        return near.astype(bool) & feat["not_dry"] & feat["room_to_hi20"]

    def confluence_lz_ma60(df, masks, feat):
        lz = masks.get("leave_zero_blue_tri", pd.Series(False, index=df.index)).fillna(False)
        m60 = masks.get("ma60_lower_confirmed", pd.Series(False, index=df.index)).fillna(False)
        return _near_mask(lz, m60, 5) & feat["vol_ok"] & feat["room_to_hi20"]

    def ma60_tight_vol(df, masks, feat):
        # 確認紅箭再加：量能＋未貼死 20高＋RSV 中段
        return feat["vol_ok"] & feat["room_to_hi20"] & feat["rsv_mid"] & feat["above_ma60"]

    def strict_triple(df, masks, feat):
        # 最嚴：結構＋量＋空間＋RSV
        return (
            feat["vol_ok"]
            & feat["above_ma60"]
            & feat["room_to_hi20"]
            & feat["rsv_mid"]
            & feat["below_ma20"]  # 偏拉回而非追高
        )

    return {
        "F0_none": none,
        "F1_vol_structure": vol_structure,
        "F2_near_ma60": leave_with_ma60,
        "F3_lz_ma60_confluence": confluence_lz_ma60,
        "F4_ma60_tight_vol": ma60_tight_vol,
        "F5_strict_triple": strict_triple,
    }


def _random_matched(base: pd.Series, eligible: pd.Series, *, seed: int) -> pd.Series:
    """在 eligible 日中抽與 base 同數量的隨機日（辨識率對照）。"""
    b = base.fillna(False).astype(bool)
    elig = eligible.fillna(False).astype(bool) & ~b
    n = int(b.sum())
    idx = np.flatnonzero(elig.to_numpy())
    out = pd.Series(False, index=base.index)
    if n <= 0 or len(idx) == 0:
        return out
    rng = np.random.default_rng(seed)
    take = rng.choice(idx, size=min(n, len(idx)), replace=False)
    out.iloc[take] = True
    return out


def run_tighten(*, n_universe: int = 100) -> Dict[str, Any]:
    t0 = time.time()
    ART.mkdir(parents=True, exist_ok=True)
    DOC.mkdir(parents=True, exist_ok=True)
    uni = select_g_universe(n=n_universe, include_twse_top100=True)
    symbols = uni["stock_id"].astype(str).tolist()
    for sid in MUST_INCLUDE:
        if sid not in symbols:
            symbols.append(sid)

    filters = _filters()
    # 主測進場：leave_zero、ma60_lower；對照 random 用同密度
    bases = ("leave_zero_blue_tri", "ma60_lower_confirmed")
    bucket: Dict[str, List[Dict[str, Any]]] = {}
    meta_n = 0
    errors: List[str] = []

    for sid in symbols:
        try:
            raw = load_stock_ohlcv(sid)
            if len(raw) < 150:
                continue
            meta_n += 1
            df = _normalize_ohlc(raw)
            masks = _build_mark_masks(df)
            feat = _feature_frame(df)
            hl, temp_label = _build_hl_temp(df)
            seed = abs(hash(sid)) % (2**32)

            for base_tag in bases:
                base_m = masks.get(base_tag)
                if base_m is None:
                    continue
                base_m = base_m.fillna(False).astype(bool)
                for fname, ffn in filters.items():
                    try:
                        fmask = ffn(df, masks, feat).fillna(False).astype(bool)
                    except Exception:
                        fmask = pd.Series(False, index=df.index)
                    # F3 只對 leave_zero 有意義；套在 ma60 上改成自身＆結構
                    if fname == "F3_lz_ma60_confluence" and base_tag != "leave_zero_blue_tri":
                        fmask = filters["F4_ma60_tight_vol"](df, masks, feat).fillna(False)
                    if fname == "F2_near_ma60" and base_tag == "ma60_lower_confirmed":
                        fmask = filters["F4_ma60_tight_vol"](df, masks, feat).fillna(False)

                    entry = base_m & fmask
                    key = f"{base_tag}__{fname}"
                    tr = _simulate_trades(
                        df, entry, hl=hl, temp_label=temp_label, sid=sid, entry_tag=key
                    )
                    bucket.setdefault(key, []).extend(tr)

                    # 同密度隨機（只在濾網通過的日子抽）→ 真辨識
                    rnd = _random_matched(entry, fmask if fname != "F0_none" else pd.Series(True, index=df.index), seed=seed + len(fname))
                    rkey = f"random__{base_tag}__{fname}"
                    rtr = _simulate_trades(
                        df, rnd, hl=hl, temp_label=temp_label, sid=sid, entry_tag=rkey
                    )
                    bucket.setdefault(rkey, []).extend(rtr)
        except Exception as e:
            errors.append(f"{sid}:{type(e).__name__}:{e}")

    by_key = {k: _agg_trades(v) for k, v in bucket.items()}

    # 評分：訊號 vs 同條件隨機；以及 vs leave_zero F0
    lz0 = by_key.get("leave_zero_blue_tri__F0_none") or {}
    ranking = []
    for base_tag in bases:
        for fname in filters:
            key = f"{base_tag}__{fname}"
            rkey = f"random__{base_tag}__{fname}"
            st = by_key.get(key) or {}
            rnd = by_key.get(rkey) or {}
            days = int(st.get("n_unique_entry_days") or 0)
            ok_n = days >= 20
            beats_random = bool(
                ok_n
                and np.isfinite(st.get("expectancy", np.nan))
                and np.isfinite(rnd.get("expectancy", np.nan))
                and float(st["expectancy"]) > float(rnd["expectancy"])
                and float(st["win_rate"]) > float(rnd["win_rate"])
            )
            beats_lz0 = bool(
                ok_n
                and lz0
                and np.isfinite(lz0.get("expectancy", np.nan))
                and float(st.get("expectancy", np.nan)) > float(lz0["expectancy"])
                and float(st.get("win_rate", np.nan)) >= float(lz0["win_rate"]) - 0.005
            )
            ranking.append(
                {
                    "key": key,
                    "base": base_tag,
                    "filter": fname,
                    "n_trades": st.get("n_trades"),
                    "n_unique_entry_days": days,
                    "win_rate": st.get("win_rate"),
                    "expectancy": st.get("expectancy"),
                    "avg_hold": st.get("avg_hold"),
                    "exit_reason_counts": st.get("exit_reason_counts"),
                    "random_win_rate": rnd.get("win_rate"),
                    "random_expectancy": rnd.get("expectancy"),
                    "random_days": rnd.get("n_unique_entry_days"),
                    "beats_random": beats_random,
                    "beats_leave_zero_F0": beats_lz0,
                    "E_minus_random": (
                        float(st["expectancy"]) - float(rnd["expectancy"])
                        if ok_n
                        and np.isfinite(st.get("expectancy", np.nan))
                        and np.isfinite(rnd.get("expectancy", np.nan))
                        else float("nan")
                    ),
                    "win_minus_random": (
                        float(st["win_rate"]) - float(rnd["win_rate"])
                        if ok_n
                        and np.isfinite(st.get("win_rate", np.nan))
                        and np.isfinite(rnd.get("win_rate", np.nan))
                        else float("nan")
                    ),
                }
            )

    ranking.sort(
        key=lambda r: (
            int(r.get("beats_random") or 0),
            int(r.get("beats_leave_zero_F0") or 0),
            float(r["E_minus_random"]) if np.isfinite(r.get("E_minus_random", np.nan)) else -9,
            float(r.get("expectancy") or -9),
        ),
        reverse=True,
    )

    winners = [r for r in ranking if r.get("beats_random") and r.get("beats_leave_zero_F0")]
    promote = False  # 強化條件過「贏隨機＋贏現況」仍只 lab；真上符號另審出場
    gate = (
        f"winners={len(winners)}/{len(ranking)}; "
        f"best={ranking[0]['key'] if ranking else None} "
        f"win={ranking[0].get('win_rate') if ranking else None} "
        f"E={ranking[0].get('expectancy') if ranking else None} "
        f"vs_rand_E={ranking[0].get('E_minus_random') if ranking else None}; "
        f"promote_lookup=NO"
    )

    out = {
        "phone_sync": PHONE_SYNC,
        "not_buy_signal": NOT_BUY_SIGNAL,
        "elapsed_s": round(time.time() - t0, 1),
        "n_stocks": meta_n,
        "method_zh": "強化濾網 AND 進場；出場同 phone_trade（首碰20高／減碼／回吐8%／60日）；對照＝同濾網密度隨機",
        "leave_zero_F0": lz0,
        "ranking": ranking,
        "winners_beat_random_and_lz0": winners,
        "promote_to_lookup_display": promote,
        "gate_one_liner": gate,
        "filter_defs_zh": {
            "F0_none": "無加嚴",
            "F1_vol_structure": "量≥0.7×20日均量＋近季線＋未貼20高＋RSV15–65",
            "F2_near_ma60": "附近5根有確認紅箭＋非地量＋未貼20高",
            "F3_lz_ma60_confluence": "leave_zero 與確認紅箭5根內共振＋量能＋未貼20高",
            "F4_ma60_tight_vol": "量能＋未貼20高＋RSV中段＋近季線",
            "F5_strict_triple": "F1＋收盤未明顯高於月線（偏拉回）",
        },
        "errors_n": len(errors),
        "errors_sample": errors[:8],
        "note_zh": "辨識率＝贏同密度隨機；再比 leave_zero F0。不上話筒。",
    }
    text = json.dumps(out, ensure_ascii=False, indent=2, default=str)
    (ART / "phone_entry_tighten_latest.json").write_text(text, encoding="utf-8")
    (DOC / "phone_entry_tighten_latest.json").write_text(text, encoding="utf-8")
    print("GATE", gate, flush=True)
    print(
        "TOP",
        json.dumps(ranking[:6], ensure_ascii=False, default=str),
        flush=True,
    )
    print("WINNERS", len(winners), flush=True)
    return out


if __name__ == "__main__":
    run_tighten()
