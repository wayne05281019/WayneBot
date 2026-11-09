# -*- coding: utf-8 -*-
"""mix_v16 後：U112 上把 profit_early 抬過 ge80×50d。

v16：U250 pe2/3 稳过闸；U112 soft pe≈78.9%@51d、nobody pe≈84.8%@45d。
本輪（只跑 default U112）：soft pe 去損／软品质；nobody 软化（~body_n2／week OR）加厚日数。
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
MAX_HOLD = 60


def _bal(w: float, d: int) -> float:
    if not np.isfinite(w) or d <= 0:
        return float("-inf")
    return float(w) * min(1.0, d / 50.0)


def _sim_profit_early(df, entry_mask, *, hl, temp_label, sid, entry_tag, wave_top, early_sell, min_profit: float):
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
            px = float(c.iloc[j])
            unreal = px / entry_px - 1.0 if entry_px > 0 else 0.0
            if hl_j == "20高":
                exit_j, reason = j, "first_hi20"
                break
            if bool(wave_top.iloc[j]):
                exit_j, reason = j, "wave_rel_high"
                break
            if bool(early_sell.iloc[j]) and unreal >= min_profit:
                exit_j, reason = j, f"early_profit_{min_profit:.0%}"
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
                "hold_days": int(exit_j - entry_i),
                "net_ret": ret,
                "win": bool(np.isfinite(ret) and ret > 0),
                "exit_reason": reason,
            }
        )
        i = exit_j + 1
    return rows


def run() -> Dict[str, Any]:
    t0 = time.time()
    ART.mkdir(parents=True, exist_ok=True)
    DOC.mkdir(parents=True, exist_ok=True)
    _, mkt_raw = _twii_wave_pack(entry_preset="A0_strict", score_threshold=40.0)
    uni = select_g_universe(n=150, include_twse_top100=True, min_avg_turnover_k=1_500_000.0)
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

            ei_n5 = w3u & _near(turn, 3) & t60 & _near(intent, 5) & risk
            v11 = ei_n5 & (_near(week, 3) | _near(body, 3))
            nobody = v11 & (~body)
            # soften nobody to thicken days: not strong body recently / or week
            nobody_soft = v11 & (~_near(body, 2) | _near(week, 5))
            nobody_or_week = v11 & (~body | _near(week, 3))
            soft_q = v11 & (_near(no_fake, 3) | _near(week, 5) | ~body)

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

            entries = {
                "v11_softbody": v11,
                "v11_nobody": nobody,
                "v11_nobody_soft": nobody_soft,
                "v11_nobody_or_week": nobody_or_week,
                "v11_soft_q": soft_q,
            }
            for cn, entry in entries.items():
                # baseline hi20 sell
                key = f"{cn}__SELL_hi20_or_wave_top"
                trade_bucket.setdefault(key, []).extend(
                    _simulate_relhigh(
                        df, entry, hl=hl, temp_label=temp, sid=sid, entry_tag=key, wave_top=wave_top, mode="hi20_or_wave_top"
                    )
                )
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
                for mp in (0.02, 0.03, 0.05):
                    k2 = f"{cn}__SELL_profit_early_{int(mp*100)}"
                    trade_bucket.setdefault(k2, []).extend(
                        _sim_profit_early(
                            df, entry, hl=hl, temp_label=temp, sid=sid, entry_tag=k2, wave_top=wave_top, early_sell=early_sell, min_profit=mp
                        )
                    )
                    early_bucket.setdefault(k2, []).extend(
                        _measure_signal_earliness(df, entry, hl, sid=sid, entry_tag=k2)
                    )
                    rnd2 = _random_matched(entry, pool, seed=seed + len(k2))
                    trade_bucket.setdefault(f"random__{k2}", []).extend(
                        _sim_profit_early(
                            df, rnd2, hl=hl, temp_label=temp, sid=sid, entry_tag=f"random__{k2}", wave_top=wave_top, early_sell=early_sell, min_profit=mp
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
        holds = [float(r.get("hold_days") if r.get("hold_days") is not None else r.get("hold_bars") or np.nan) for r in raw]
        hold = float(np.nanmean(holds)) if holds else float("nan")
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
                "mean_hold_days": hold,
            }
        )

    base_hold = next((r.get("mean_hold_days") for r in ranking if r["key"] == "v11_softbody__SELL_hi20_or_wave_top"), float("nan"))
    sell_pass = [
        r
        for r in ranking
        if "SELL_profit_early" in r["key"] and r.get("win_ge80") and r.get("days_ge50") and r.get("beats_random")
    ]
    sell_pass = sorted(
        sell_pass,
        key=lambda r: (
            -(float(base_hold) - float(r.get("mean_hold_days") or base_hold) if np.isfinite(float(base_hold or np.nan)) else 0),
            -float(r.get("win_rate") or 0),
        ),
    )
    near = sorted(
        [
            r
            for r in ranking
            if "SELL_profit_early" in r["key"]
            and r.get("days_ge50")
            and float(r.get("win_rate") or 0) >= 0.78
        ],
        key=lambda r: (-float(r.get("win_rate") or 0), float(r.get("mean_hold_days") or 99)),
    )
    gate = (
        f"spirit_mix_thicken_v17 U112 n={meta_n} profit_sell_ge80_d50={len(sell_pass)}; "
        f"best={sell_pass[0]['key'] if sell_pass else None} "
        f"win={sell_pass[0].get('win_rate') if sell_pass else None} "
        f"days={sell_pass[0].get('n_unique_entry_days') if sell_pass else None} "
        f"hold={sell_pass[0].get('mean_hold_days') if sell_pass else None} "
        f"base_hold={base_hold}; "
        f"near={near[0]['key'] if near else None} near_win={near[0].get('win_rate') if near else None}; "
        f"promote_lookup=NO"
    )
    out = {
        "phone_sync": PHONE_SYNC,
        "promote_to_lookup_display": False,
        "user_goal_zh": "v17：U112 上 profit_early 过 ge80×50d",
        "parent_seal": "phone_spirit_mix_thicken_v16_decision.json",
        "elapsed_s": round(time.time() - t0, 1),
        "n_stocks": meta_n,
        "base_hold_v11_hi20": base_hold,
        "ranking": ranking,
        "profit_early_ge80_d50": sell_pass[:10],
        "near80_profit_early_d50": near[:10],
        "gate_one_liner": gate,
        "errors_n": len(errors),
        "errors_sample": errors[:8],
    }
    text = json.dumps(out, ensure_ascii=False, indent=2, default=str)
    (ART / "phone_spirit_mix_thicken_v17_latest.json").write_text(text, encoding="utf-8")
    (DOC / "phone_spirit_mix_thicken_v17_latest.json").write_text(text, encoding="utf-8")
    print("GATE", gate, flush=True)
    print("PASS", json.dumps(sell_pass[:5], ensure_ascii=False, default=str)[:1000], flush=True)
    print("NEAR", json.dumps(near[:5], ensure_ascii=False, default=str)[:1000], flush=True)
    return out


def main() -> None:
    run()


if __name__ == "__main__":
    main()
