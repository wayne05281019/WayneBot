# -*- coding: utf-8 -*-
"""mix_v12 後：body_n5 bars≈16.2 搶回 ge80；v11 核上試提早賣。

v12：v11 冠軍复現；week|body_n5 bars≈16.2 win≈78.9%；bull_or win↑但 bars 略降。
本輪：1) body_n5 母體＋軟品質搶 ≥80%×50d 且 bars>15.86；
2) 鎖定 v11 進場，試 wave_top／early_rel／trail 提早賣（比 hi20 早離場）。
phone_sync=blocked。
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Dict, List

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
BASELINE_BARS = 15.27
V11_BARS = 15.857
MAX_HOLD = 60


def _bal(w: float, d: int) -> float:
    if not np.isfinite(w) or d <= 0:
        return float("-inf")
    return float(w) * min(1.0, d / 50.0)


def _sim_early_sell(df, entry_mask, *, hl, temp_label, sid, entry_tag, wave_top, early_sell, mode: str):
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
        peak = entry_px
        for j in range(entry_i, min(n - 1, entry_i + MAX_HOLD) + 1):
            px = float(c.iloc[j])
            peak = max(peak, float(df["high"].astype(float).iloc[j]))
            hl_j = str(hl.iloc[j]) if j < len(hl) else ""
            if mode in ("hi20_or_wave_top", "hi20_or_wave_or_early", "hi20_or_trail") and hl_j == "20高":
                exit_j, reason = j, "first_hi20"
                break
            if mode in ("wave_top_next", "hi20_or_wave_top", "hi20_or_wave_or_early") and bool(wave_top.iloc[j]):
                exit_j, reason = j, "wave_rel_high"
                break
            if mode == "hi20_or_wave_or_early" and bool(early_sell.iloc[j]):
                exit_j, reason = j, "early_rel_high"
                break
            if mode == "hi20_or_trail" and peak > 0 and px <= peak * 0.97 and j > entry_i + 2:
                exit_j, reason = j, "trail_3pct"
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
            t60 = v4["V4_t60_safe"].fillna(False)
            risk = ~mkt["mkt_rel_high_risk"].fillna(False)
            week = v4["V4_week_stack"].fillna(False)
            body = v4["V4_body_thrust"].fillna(False)
            no_fake = v4["V4_no_fake_break"].fillna(False)
            bull = (df["close"].astype(float) > df["open"].astype(float)).fillna(False)

            champ = w3u & _near(turn, 3) & t60 & _near(intent, 3) & risk
            ei_n5 = w3u & _near(turn, 3) & t60 & _near(intent, 5) & risk
            v11 = ei_n5 & (_near(week, 3) | _near(body, 3))
            body_n5 = ei_n5 & (_near(week, 3) | _near(body, 5))

            cores_entry = {
                "champ_n3": champ,
                "v11_softbody": v11,
                "body_n5": body_n5,
                "body_n5_nofake_n3": body_n5 & _near(no_fake, 3),
                "body_n5_bull_n2": body_n5 & _near(bull, 2),
                "body_n5_soft_or": body_n5 & (_near(no_fake, 3) | _near(bull, 2) | _near(week, 5)),
                "body_n5_and_week_n5": body_n5 & _near(week, 5),
                "body_n5_t60_strict": body_n5 & t60,  # already has t60; noop sanity
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

            # buy variants with standard sell
            for cn, entry in cores_entry.items():
                key = f"{cn}__SELL_hi20_or_wave_top"
                trades = _simulate_relhigh(
                    df, entry, hl=hl, temp_label=temp, sid=sid, entry_tag=key, wave_top=wave_top, mode="hi20_or_wave_top"
                )
                trade_bucket.setdefault(key, []).extend(trades)
                early_bucket.setdefault(key, []).extend(
                    _measure_signal_earliness(df, entry, hl, sid=sid, entry_tag=key)
                )
                pool = w3u if int(w3u.sum()) >= 5 else pd.Series(True, index=idx)
                rnd = _random_matched(entry, pool, seed=seed + len(key))
                trade_bucket.setdefault(f"random__{key}", []).extend(
                    _simulate_relhigh(
                        df, rnd, hl=hl, temp_label=temp, sid=sid, entry_tag=f"random__{key}", wave_top=wave_top, mode="hi20_or_wave_top"
                    )
                )

            # early-sell on locked v11 entry
            for mode in ("hi20_or_wave_top", "wave_top_next", "hi20_or_wave_or_early", "hi20_or_trail"):
                key = f"v11_softbody__SELL_{mode}"
                if mode == "hi20_or_wave_top":
                    continue  # already have as v11_softbody__SELL_hi20_or_wave_top
                trades = _sim_early_sell(
                    df, v11, hl=hl, temp_label=temp, sid=sid, entry_tag=key, wave_top=wave_top, early_sell=early_sell, mode=mode
                )
                trade_bucket.setdefault(key, []).extend(trades)
                early_bucket.setdefault(key, []).extend(
                    _measure_signal_earliness(df, v11, hl, sid=sid, entry_tag=key)
                )
                pool = w3u if int(w3u.sum()) >= 5 else pd.Series(True, index=idx)
                rnd = _random_matched(v11, pool, seed=seed + len(key))
                trade_bucket.setdefault(f"random__{key}", []).extend(
                    _sim_early_sell(
                        df, rnd, hl=hl, temp_label=temp, sid=sid, entry_tag=f"random__{key}", wave_top=wave_top, early_sell=early_sell, mode=mode
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
        raw = trade_bucket.get(key) or []
        hold = float(np.nanmean([float(r.get("hold_bars") or np.nan) for r in raw])) if raw else float("nan")
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
                "earlier_than_baseline": bool(np.isfinite(bars) and bars > BASELINE_BARS + 0.05),
                "earlier_than_v11": bool(np.isfinite(bars) and bars > V11_BARS + 0.05),
            }
        )

    extreme = sorted(
        [r for r in ranking if r["beats_random"] and r["win_ge80"]],
        key=lambda r: (float(r["win_rate"]), int(r["n_unique_entry_days"])),
        reverse=True,
    )
    d50 = sorted(
        [r for r in extreme if r["days_ge50"]],
        key=lambda r: (-float(r.get("mean_bars_before_hi20") or -1), -float(r["win_rate"])),
    )
    early_wins = [r for r in d50 if r.get("earlier_than_baseline")]
    beat_v11 = [r for r in early_wins if r.get("earlier_than_v11")]
    # early-sell: lower hold among ge80_d50 on v11 entry family
    sell_rows = [r for r in ranking if r["key"].startswith("v11_softbody__SELL_") and r.get("win_ge80") and r.get("days_ge50")]
    sell_rows = sorted(sell_rows, key=lambda r: (float(r.get("mean_hold_bars") or 99), -float(r.get("win_rate") or 0)))
    gate = (
        f"spirit_mix_thicken_v13 ge80={len(extreme)} ge80_d50={len(d50)} earlier_d50={len(early_wins)} "
        f"beat_v11_bars={len(beat_v11)}; "
        f"best_early_d50={d50[0]['key'] if d50 else None} "
        f"win={d50[0].get('win_rate') if d50 else None} "
        f"bars={d50[0].get('mean_bars_before_hi20') if d50 else None}; "
        f"best_early_sell={sell_rows[0]['key'] if sell_rows else None} "
        f"hold={sell_rows[0].get('mean_hold_bars') if sell_rows else None} "
        f"sell_win={sell_rows[0].get('win_rate') if sell_rows else None}; "
        f"v11_bars={V11_BARS}; promote_lookup=NO"
    )
    out = {
        "phone_sync": PHONE_SYNC,
        "promote_to_lookup_display": False,
        "user_goal_zh": "v13：body_n5 搶 ge80＋v11 核提早賣",
        "parent_seal": "phone_spirit_mix_thicken_v12_decision.json",
        "baseline_bars_v5": BASELINE_BARS,
        "v11_champ_bars": V11_BARS,
        "elapsed_s": round(time.time() - t0, 1),
        "n_stocks": meta_n,
        "ranking": ranking,
        "extreme_win_ge80": extreme[:20],
        "extreme_win_ge80_days50": d50[:15],
        "earlier_than_baseline_ge80_d50": early_wins[:10],
        "beat_v11_bars_ge80_d50": beat_v11[:10],
        "early_sell_ge80_d50": sell_rows[:10],
        "gate_one_liner": gate,
        "errors_n": len(errors),
        "errors_sample": errors[:8],
    }
    text = json.dumps(out, ensure_ascii=False, indent=2, default=str)
    (ART / "phone_spirit_mix_thicken_v13_latest.json").write_text(text, encoding="utf-8")
    (DOC / "phone_spirit_mix_thicken_v13_latest.json").write_text(text, encoding="utf-8")
    print("GATE", gate, flush=True)
    print("EARLIER", json.dumps(early_wins[:5], ensure_ascii=False, default=str)[:1000], flush=True)
    print("BEAT_V11_BARS", json.dumps(beat_v11[:5], ensure_ascii=False, default=str)[:800], flush=True)
    print("EARLY_SELL", json.dumps(sell_rows[:5], ensure_ascii=False, default=str)[:1000], flush=True)
    return out


def main() -> None:
    run(n_universe=150)


if __name__ == "__main__":
    main()
