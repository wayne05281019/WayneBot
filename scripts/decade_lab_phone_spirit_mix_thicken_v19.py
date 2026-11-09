# -*- coding: utf-8 -*-
"""mix_v18 後：U112 混合出場——無 body 才允許有利潤提早賣。

v18：cut_pass=0；body==false 仍 84%@44d；soft pe 78.9%@51d。
本輪：進場=v11 softbody；若訊號日 body=false → pe2/3 可提早賣，
否則只 hi20|浪頂。目標整條 ge80×50d 且 hold < hi20-only。
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


def _sim_hybrid(
    df,
    entry_mask,
    *,
    hl,
    temp_label,
    sid,
    entry_tag,
    wave_top,
    early_sell,
    body_at_signal: pd.Series,
    min_profit: float,
    allow_pe_if_nobody: bool = True,
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
        nobody = not bool(body_at_signal.iloc[i])
        pe_ok = (not allow_pe_if_nobody) or nobody
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
            if pe_ok and bool(early_sell.iloc[j]) and unreal >= min_profit:
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
                "entry_nobody": bool(nobody),
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

            ei_n5 = w3u & _near(turn, 3) & t60 & _near(intent, 5) & risk
            v11 = ei_n5 & (_near(week, 3) | _near(body, 3))

            wave_top = (
                ev.get("LAB_W1_TOP", pd.Series(False, index=idx))
                | ev.get("LAB_W3_TOP", pd.Series(False, index=idx))
                | ev.get("LAB_SELL_W5_TOP", pd.Series(False, index=idx))
            ).fillna(False)
            h = df["high"].astype(float)
            hi10 = h.rolling(10, min_periods=5).max()
            exhaust = feat.get("is_exhaustion_vol")
            exhaust = exhaust.reindex(idx).fillna(False).astype(bool) if exhaust is not None else pd.Series(False, index=idx)
            early_or = exhaust | (h >= hi10.shift(1))

            # baselines
            for cn, entry, mode in (
                ("v11_hi20", v11, "hi20"),
                ("v11_pe3_all", v11, "pe3_all"),
                ("v11_hybrid_pe2", v11, "hybrid2"),
                ("v11_hybrid_pe3", v11, "hybrid3"),
                ("v11_hybrid_pe5", v11, "hybrid5"),
            ):
                key = f"{cn}"
                if mode == "hi20":
                    trades = _simulate_relhigh(
                        df, entry, hl=hl, temp_label=temp, sid=sid, entry_tag=key, wave_top=wave_top, mode="hi20_or_wave_top"
                    )
                elif mode == "pe3_all":
                    # pe always allowed: treat all signals as nobody
                    trades = _sim_hybrid(
                        df,
                        entry,
                        hl=hl,
                        temp_label=temp,
                        sid=sid,
                        entry_tag=key,
                        wave_top=wave_top,
                        early_sell=early_or,
                        body_at_signal=pd.Series(False, index=idx),
                        min_profit=0.03,
                        allow_pe_if_nobody=True,
                    )
                else:
                    mp = {"hybrid2": 0.02, "hybrid3": 0.03, "hybrid5": 0.05}[mode]
                    trades = _sim_hybrid(
                        df,
                        entry,
                        hl=hl,
                        temp_label=temp,
                        sid=sid,
                        entry_tag=key,
                        wave_top=wave_top,
                        early_sell=early_or,
                        body_at_signal=body,
                        min_profit=mp,
                        allow_pe_if_nobody=True,
                    )
                trade_bucket.setdefault(key, []).extend(trades)
                early_bucket.setdefault(key, []).extend(
                    _measure_signal_earliness(df, entry, hl, sid=sid, entry_tag=key)
                )
                pool = w3u if int(w3u.sum()) >= 5 else pd.Series(True, index=idx)
                rnd = _random_matched(entry, pool, seed=seed + len(key))
                if mode == "hi20":
                    trade_bucket.setdefault(f"random__{key}", []).extend(
                        _simulate_relhigh(
                            df, rnd, hl=hl, temp_label=temp, sid=sid, entry_tag=f"random__{key}", wave_top=wave_top, mode="hi20_or_wave_top"
                        )
                    )
                else:
                    mp = 0.03 if mode == "pe3_all" else {"hybrid2": 0.02, "hybrid3": 0.03, "hybrid5": 0.05}[mode]
                    body_rnd = pd.Series(False, index=idx) if mode == "pe3_all" else body
                    trade_bucket.setdefault(f"random__{key}", []).extend(
                        _sim_hybrid(
                            df,
                            rnd,
                            hl=hl,
                            temp_label=temp,
                            sid=sid,
                            entry_tag=f"random__{key}",
                            wave_top=wave_top,
                            early_sell=early_or,
                            body_at_signal=body_rnd,
                            min_profit=mp,
                            allow_pe_if_nobody=True,
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
        pe_exits = sum(1 for r in raw if str(r.get("exit_reason", "")).startswith("early_profit"))
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
                "n_early_profit_exits": pe_exits,
            }
        )

    base = next((r for r in ranking if r["key"] == "v11_hi20"), {})
    base_hold = float(base.get("mean_hold_days") or np.nan)
    pass_rows = [
        r
        for r in ranking
        if r.get("win_ge80") and r.get("days_ge50") and r.get("beats_random") and r["key"] != "v11_hi20"
    ]
    pass_rows = sorted(
        pass_rows,
        key=lambda r: (
            -(base_hold - float(r.get("mean_hold_days") or base_hold) if np.isfinite(base_hold) else 0),
            -float(r.get("win_rate") or 0),
        ),
    )
    gate = (
        f"spirit_mix_thicken_v19 U112 n={meta_n} hybrid_ge80_d50={len(pass_rows)}; "
        f"best={pass_rows[0]['key'] if pass_rows else None} "
        f"win={pass_rows[0].get('win_rate') if pass_rows else None} "
        f"hold={pass_rows[0].get('mean_hold_days') if pass_rows else None} "
        f"pe_exits={pass_rows[0].get('n_early_profit_exits') if pass_rows else None} "
        f"base_hold={base_hold}; promote_lookup=NO"
    )
    out = {
        "phone_sync": PHONE_SYNC,
        "promote_to_lookup_display": False,
        "user_goal_zh": "v19：U112 混合出場（nobody 才 pe）",
        "parent_seal": "phone_spirit_mix_thicken_v18_decision.json",
        "elapsed_s": round(time.time() - t0, 1),
        "n_stocks": meta_n,
        "base_hi20": base,
        "ranking": ranking,
        "hybrid_ge80_d50": pass_rows[:10],
        "gate_one_liner": gate,
        "errors_n": len(errors),
        "errors_sample": errors[:8],
    }
    text = json.dumps(out, ensure_ascii=False, indent=2, default=str)
    (ART / "phone_spirit_mix_thicken_v19_latest.json").write_text(text, encoding="utf-8")
    (DOC / "phone_spirit_mix_thicken_v19_latest.json").write_text(text, encoding="utf-8")
    print("GATE", gate, flush=True)
    print("PASS", json.dumps(pass_rows[:5], ensure_ascii=False, default=str)[:1200], flush=True)
    print("ALL", json.dumps(ranking, ensure_ascii=False, default=str)[:2000], flush=True)
    return out


def main() -> None:
    run()


if __name__ == "__main__":
    main()
