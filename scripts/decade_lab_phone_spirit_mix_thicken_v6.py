# -*- coding: utf-8 -*-
"""mix_v5 冠軍再生：提早賣／提早量約束（下一版靜默對質）。

鎖死候選核：E_w3u × turn_n3 × t60 × intent_n3（v5 ≈84%@50d，U150）。
本輪試：hi20_or_wave_top vs wave_top_next vs hi20_or_wave_or_early；
並報 bars_before_hi20。phone_sync=blocked。
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd

from scripts.decade_lab_chart_marks_stats import _build_mark_masks, _normalize_ohlc
from scripts.decade_lab_hsiao_data_preprocessor import prepare_ohlcv
from scripts.decade_lab_hsiao_quant_features import compute_hsiao_features
from scripts.decade_lab_hsiao_universe import MUST_INCLUDE, load_stock_ohlcv, select_g_universe
from scripts.decade_lab_phone_champion_v3_ideas import build_v3_extras
from scripts.decade_lab_phone_champion_v4_ideas import build_v4_extras
from scripts.decade_lab_phone_entry_tighten import _random_matched
from scripts.decade_lab_phone_extreme_hillclimb import _align_feat, _cores, _near, _wave_hsiao_bank
from scripts.decade_lab_phone_mark_earliness import _agg_earliness, _measure_signal_earliness
from scripts.decade_lab_phone_market_wave_sync import (
    _align_mkt,
    _barek_masks,
    _stock_wave_events,
    _twii_wave_pack,
)
from scripts.decade_lab_phone_relhigh_sell import _simulate_relhigh
from scripts.decade_lab_phone_spirit_masks import build_spirit_masks
from scripts.decade_lab_phone_trade_confront import _agg_trades, _build_hl_temp
from scripts.decade_lab_phone_wave_filter import _align_wave, _wave_frame, _wave_masks

PHONE_SYNC = "blocked"
ART = Path("/opt/cursor/artifacts")
DOC = Path(__file__).resolve().parents[1] / "docs" / "expert_notes" / "飆客" / "decade_lab"
MAX_HOLD = 60


def _bal(w: float, d: int) -> float:
    if not np.isfinite(w) or d <= 0:
        return float("-inf")
    return float(w) * min(1.0, d / 50.0)


def _sim_early(
    df, entry_mask, *, hl, temp_label, sid, entry_tag, wave_top, early_sell, mode
):
    n = len(df)
    dates = df["date"].astype(str).tolist() if "date" in df.columns else [str(i) for i in range(n)]
    o = df["open"].astype(float)
    c = df["close"].astype(float)
    rows = []
    i = 0
    while i < n - 2:
        if not bool(entry_mask.iloc[i]):
            i += 1
            continue
        entry_i = i + 1
        if entry_i >= n - 1:
            break
        entry_px = float(o.iloc[entry_i])
        exit_j = None
        reason = "max_hold"
        for j in range(entry_i, min(n - 1, entry_i + MAX_HOLD) + 1):
            hl_j = str(hl.iloc[j]) if j < len(hl) else ""
            if mode in ("hi20_or_wave_top", "hi20_or_wave_or_early") and hl_j == "20高":
                exit_j, reason = j, "first_hi20"
                break
            if mode in ("wave_top_next", "hi20_or_wave_top", "hi20_or_wave_or_early") and bool(wave_top.iloc[j]):
                exit_j, reason = j, "wave_rel_high"
                break
            if mode == "hi20_or_wave_or_early" and bool(early_sell.iloc[j]):
                exit_j, reason = j, "early_rel_high"
                break
        if exit_j is None:
            exit_j, reason = min(n - 1, entry_i + MAX_HOLD), "max_hold_60"
        ret = float(c.iloc[exit_j]) / entry_px - 1.0 if entry_px > 0 else float("nan")
        rows.append(
            {
                "sid": sid,
                "entry_tag": entry_tag,
                "temp_label": temp_label,
                "entry_date": dates[entry_i],
                "exit_date": dates[exit_j],
                "hold_bars": int(exit_j - entry_i),
                "net_ret": ret,
                "win": bool(np.isfinite(ret) and ret > 0),
                "exit_reason": reason,
            }
        )
        i = exit_j + 1
    return rows


def run(*, n_universe: int = 150) -> Dict[str, Any]:
    t0 = time.time()
    ART.mkdir(parents=True, exist_ok=True)
    DOC.mkdir(parents=True, exist_ok=True)
    _, mkt_raw = _twii_wave_pack(entry_preset="A0_strict", score_threshold=40.0)
    uni = select_g_universe(n=n_universe, include_twse_top100=True)
    symbols = uni["stock_id"].astype(str).tolist()
    for sid in MUST_INCLUDE:
        if sid not in symbols:
            symbols.append(sid)

    trade_bucket: Dict[str, List[Dict[str, Any]]] = {}
    early_bucket: Dict[str, List[Dict[str, Any]]] = {}
    meta_n = 0
    errors: List[str] = []

    for sid in symbols:
        try:
            raw = load_stock_ohlcv(sid)
            if len(raw) < 150:
                continue
            meta_n += 1
            df = _normalize_ohlc(raw)
            feat = _align_feat(df, compute_hsiao_features(prepare_ohlcv(raw)))
            wave = _align_wave(df, _wave_frame(raw))
            wmasks = _wave_masks(wave)
            cores = _cores(_build_mark_masks(df), wmasks, feat)
            bank = _wave_hsiao_bank(feat, wmasks, wave)
            spirit = build_spirit_masks(df, feat, wmasks=wmasks, bank=bank)
            barek = _barek_masks(df)
            ev = _stock_wave_events(raw, df)
            mkt = _align_mkt(df, mkt_raw)
            v3 = build_v3_extras(df, feat, bank, barek=barek)
            v4 = build_v4_extras(df, feat)
            hl, temp = _build_hl_temp(df)
            seed = abs(hash(sid)) % 10_000
            idx = df.index

            w3u = cores["core_w3_or_ma60w3"].fillna(False)
            turn = v3["V3_macd_or_kd"].fillna(False) & v3["V3_barek_ok"].fillna(False)
            intent = spirit["INTENT_build_soft"].fillna(False)
            t60 = v4.get("V4_t60_safe", pd.Series(False, index=idx)).fillna(False)
            risk = ~mkt["mkt_rel_high_risk"].fillna(False)
            # v5 冠軍核＋並列軟化
            cores_entry = {
                "champ_intent_n3": w3u & _near(turn, 3) & t60 & _near(intent, 3) & risk,
                "champ_intent_n3_or_bull": w3u
                & _near(turn, 3)
                & t60
                & (_near(intent, 3) | (df["close"].astype(float) > df["open"].astype(float)))
                & risk,
                "champ_intent_n5": w3u & _near(turn, 3) & t60 & _near(intent, 5) & risk,
            }
            wave_top = (
                ev.get("LAB_W1_TOP", pd.Series(False, index=idx))
                | ev.get("LAB_W3_TOP", pd.Series(False, index=idx))
                | ev.get("LAB_SELL_W5_TOP", pd.Series(False, index=idx))
            ).fillna(False)
            h = df["high"].astype(float)
            hi10 = h.rolling(10, min_periods=5).max()
            exhaust = feat.get("is_exhaustion_vol")
            exhaust = exhaust.reindex(idx).fillna(False).astype(bool) if exhaust is not None else pd.Series(False, index=idx)
            early_sell = exhaust | (h >= hi10.shift(1))

            for cn, entry in cores_entry.items():
                for mode in ("hi20_or_wave_top", "wave_top_next", "hi20_or_wave_or_early"):
                    key = f"{cn}__SELL_{mode}"
                    if mode == "hi20_or_wave_or_early":
                        trades = _sim_early(
                            df, entry, hl=hl, temp_label=temp, sid=sid, entry_tag=key, wave_top=wave_top, early_sell=early_sell, mode=mode
                        )
                    else:
                        trades = _simulate_relhigh(
                            df, entry, hl=hl, temp_label=temp, sid=sid, entry_tag=key, wave_top=wave_top, mode=mode
                        )
                    trade_bucket.setdefault(key, []).extend(trades)
                    early_bucket.setdefault(key, []).extend(
                        _measure_signal_earliness(df, entry, hl, sid=sid, entry_tag=key)
                    )
                    pool = w3u
                    if int(pool.sum()) < 5:
                        pool = pd.Series(True, index=idx)
                    rnd = _random_matched(entry, pool, seed=seed + len(key))
                    rkey = f"random__{key}"
                    if mode == "hi20_or_wave_or_early":
                        trade_bucket.setdefault(rkey, []).extend(
                            _sim_early(
                                df, rnd, hl=hl, temp_label=temp, sid=sid, entry_tag=rkey, wave_top=wave_top, early_sell=early_sell, mode=mode
                            )
                        )
                    else:
                        trade_bucket.setdefault(rkey, []).extend(
                            _simulate_relhigh(
                                df, rnd, hl=hl, temp_label=temp, sid=sid, entry_tag=rkey, wave_top=wave_top, mode=mode
                            )
                        )
        except Exception as e:
            errors.append(f"{sid}:{type(e).__name__}:{e}")

    by = {k: _agg_trades(v) for k, v in trade_bucket.items()}
    by_early = {k: _agg_earliness(v) for k, v in early_bucket.items()}
    ranking = []
    for key, st in by.items():
        if key.startswith("random__"):
            continue
        rnd = by.get(f"random__{key}") or {}
        days = int(st.get("n_unique_entry_days") or 0)
        win = float(st.get("win_rate") or np.nan)
        exp = float(st.get("expectancy") or np.nan)
        ok = days >= 20
        beats = bool(
            ok
            and np.isfinite(exp)
            and np.isfinite(rnd.get("expectancy", np.nan))
            and exp > float(rnd["expectancy"])
            and win > float(rnd.get("win_rate") or -1)
        )
        early = by_early.get(key) or {}
        bars = float(early.get("mean_bars_before_hi20") or np.nan)
        raw_rows = trade_bucket.get(key) or []
        hold = float(np.nanmean([float(r.get("hold_bars") or r.get("hold_days") or np.nan) for r in raw_rows])) if raw_rows else float("nan")
        ranking.append(
            {
                "key": key,
                "n_trades": st.get("n_trades"),
                "n_unique_entry_days": days,
                "win_rate": win,
                "expectancy": exp,
                "beats_random": beats,
                "balanced_score": _bal(win, days) if ok else float("-inf"),
                "win_ge80": bool(ok and win >= 0.80),
                "days_ge50": days >= 50,
                "mean_bars_before_hi20": bars,
                "mean_hold_bars": hold,
            }
        )

    extreme = sorted(
        [r for r in ranking if r["beats_random"] and r["win_ge80"]],
        key=lambda r: (float(r["win_rate"]), int(r["n_unique_entry_days"])),
        reverse=True,
    )
    d50 = sorted([r for r in extreme if r["days_ge50"]], key=lambda r: (r["win_rate"], r.get("mean_bars_before_hi20") or 0), reverse=True)
    gate = (
        f"spirit_mix_thicken_v6 ge80={len(extreme)} ge80_d50={len(d50)}; "
        f"best_d50={d50[0]['key'] if d50 else None} "
        f"win={d50[0].get('win_rate') if d50 else None} "
        f"days={d50[0].get('n_unique_entry_days') if d50 else None} "
        f"bars={d50[0].get('mean_bars_before_hi20') if d50 else None}; promote_lookup=NO"
    )
    out = {
        "phone_sync": PHONE_SYNC,
        "promote_to_lookup_display": False,
        "user_goal_zh": "v5 冠軍再生：提早賣／提早量",
        "parent_seal": "phone_spirit_mix_thicken_v5_decision.json",
        "elapsed_s": round(time.time() - t0, 1),
        "n_stocks": meta_n,
        "ranking": ranking,
        "extreme_win_ge80": extreme[:20],
        "extreme_win_ge80_days50": d50[:15],
        "gate_one_liner": gate,
        "errors_n": len(errors),
        "errors_sample": errors[:8],
    }
    text = json.dumps(out, ensure_ascii=False, indent=2, default=str)
    (ART / "phone_spirit_mix_thicken_v6_latest.json").write_text(text, encoding="utf-8")
    (DOC / "phone_spirit_mix_thicken_v6_latest.json").write_text(text, encoding="utf-8")
    print("GATE", gate, flush=True)
    print("TOP_D50", json.dumps(d50[:5], ensure_ascii=False, default=str)[:1200], flush=True)
    return out


def main() -> None:
    run(n_universe=150)


if __name__ == "__main__":
    main()
