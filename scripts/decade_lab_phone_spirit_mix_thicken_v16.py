# -*- coding: utf-8 -*-
"""mix_v15 後：有利潤提早賣雙母體复現＋再壓 hold。

v15（n=250）：v11_nobody×profit_early_3 ≈85.5%@66d hold≈11.7（v11 hold≈14.8）；
v11_softbody×profit_early_3 ≈81.7%@79d hold≈11.9。
本輪：U112＋U250 复現；試 profit_early_2／4；仍 phone_sync=blocked。
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


def _run_uni(n_universe: int, min_turnover_k: float, mkt_raw) -> Dict[str, Any]:
    uni = select_g_universe(n=n_universe, include_twse_top100=True, min_avg_turnover_k=min_turnover_k)
    symbols = uni["stock_id"].astype(str).tolist()
    for sid in MUST_INCLUDE:
        if sid not in symbols:
            symbols.append(sid)
    trade_bucket: Dict[str, List[Dict[str, Any]]] = {}
    early_bucket: Dict[str, List[Dict[str, Any]]] = {}
    meta_n = 0
    errors: List[str] = []
    prefix = f"U{n_universe}__"

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
            v11_nobody = v11 & (~body)
            champ = w3u & _near(turn, 3) & t60 & _near(intent, 3) & risk

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

            entries = {"champ_n3": champ, "v11_softbody": v11, "v11_nobody": v11_nobody}
            for cn, entry in entries.items():
                key = f"{prefix}{cn}__SELL_hi20_or_wave_top"
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

            for ename, entry in (("v11_softbody", v11), ("v11_nobody", v11_nobody)):
                for mp in (0.02, 0.03, 0.04, 0.05):
                    key = f"{prefix}{ename}__SELL_profit_early_{int(mp*100)}"
                    trade_bucket.setdefault(key, []).extend(
                        _sim_profit_early(
                            df, entry, hl=hl, temp_label=temp, sid=sid, entry_tag=key, wave_top=wave_top, early_sell=early_sell, min_profit=mp
                        )
                    )
                    early_bucket.setdefault(key, []).extend(
                        _measure_signal_earliness(df, entry, hl, sid=sid, entry_tag=key)
                    )
                    pool = w3u if int(w3u.sum()) >= 5 else pd.Series(True, index=idx)
                    rnd = _random_matched(entry, pool, seed=seed + len(key))
                    trade_bucket.setdefault(f"random__{key}", []).extend(
                        _sim_profit_early(
                            df, rnd, hl=hl, temp_label=temp, sid=sid, entry_tag=f"random__{key}", wave_top=wave_top, early_sell=early_sell, min_profit=mp
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
                "earlier_than_baseline": bool(np.isfinite(bars) and bars > BASELINE_BARS + 0.05),
            }
        )
    return {"ranking": ranking, "n_stocks": meta_n, "errors": errors}


def run() -> Dict[str, Any]:
    t0 = time.time()
    ART.mkdir(parents=True, exist_ok=True)
    DOC.mkdir(parents=True, exist_ok=True)
    _, mkt_raw = _twii_wave_pack(entry_preset="A0_strict", score_threshold=40.0)

    # U112 = default turnover (historical lock); U250 = expanded
    parts = [
        _run_uni(150, 1_500_000.0, mkt_raw),  # historically ~112
        _run_uni(250, 400_000.0, mkt_raw),
    ]
    ranking: List[Dict[str, Any]] = []
    errors: List[str] = []
    meta = {}
    for p, label in zip(parts, ("default_turn", "expand250")):
        ranking.extend(p["ranking"])
        errors.extend(p["errors"])
        meta[label] = p["n_stocks"]

    extreme = sorted(
        [r for r in ranking if r["beats_random"] and r["win_ge80"]],
        key=lambda r: (float(r["win_rate"]), int(r["n_unique_entry_days"])),
        reverse=True,
    )
    d50 = [r for r in extreme if r["days_ge50"]]
    # baseline hold per universe from hi20 sell
    base_holds = {
        r["key"].split("__")[0]: r.get("mean_hold_days")
        for r in ranking
        if r["key"].endswith("v11_softbody__SELL_hi20_or_wave_top")
    }
    sell_rows = [
        r
        for r in ranking
        if "SELL_profit_early" in r["key"] and r.get("win_ge80") and r.get("days_ge50") and r.get("beats_random")
    ]

    def _hold_lift(r):
        pref = r["key"].split("__")[0]
        base = next((v for k, v in base_holds.items() if k == pref), None)
        # also try matching U150 vs U250 prefix
        for k, v in base_holds.items():
            if r["key"].startswith(k):
                base = v
                break
        if base is None or not np.isfinite(float(base or np.nan)):
            return 0.0
        return float(base) - float(r.get("mean_hold_days") or base)

    sell_rows = sorted(sell_rows, key=lambda r: (-_hold_lift(r), -float(r.get("win_rate") or 0)))
    # confirm both universes have profit_early_3 ge80
    confirm = {
        "U150_soft_pe3": next((r for r in sell_rows if "U150__v11_softbody__SELL_profit_early_3" in r["key"]), None),
        "U150_nobody_pe3": next((r for r in sell_rows if "U150__v11_nobody__SELL_profit_early_3" in r["key"]), None),
        "U250_soft_pe3": next((r for r in sell_rows if "U250__v11_softbody__SELL_profit_early_3" in r["key"]), None),
        "U250_nobody_pe3": next((r for r in sell_rows if "U250__v11_nobody__SELL_profit_early_3" in r["key"]), None),
    }
    conf_bits = ",".join(
        f"{k}:{(None if v is None else round(float(v.get('win_rate') or 0), 4))}" for k, v in confirm.items()
    )
    gate = (
        f"spirit_mix_thicken_v16 ge80={len(extreme)} ge80_d50={len(d50)} "
        f"profit_sell_ge80_d50={len(sell_rows)}; "
        f"best_profit_sell={sell_rows[0]['key'] if sell_rows else None} "
        f"win={sell_rows[0].get('win_rate') if sell_rows else None} "
        f"hold={sell_rows[0].get('mean_hold_days') if sell_rows else None} "
        f"hold_lift={_hold_lift(sell_rows[0]) if sell_rows else None}; "
        f"confirm_pe3={{{conf_bits}}}; "
        f"promote_lookup=NO"
    )
    out = {
        "phone_sync": PHONE_SYNC,
        "promote_to_lookup_display": False,
        "user_goal_zh": "v16：有利潤提早賣雙母體复現＋再壓 hold",
        "parent_seal": "phone_spirit_mix_thicken_v15_decision.json",
        "locked_early_buy_u112": "ei_n5&(week_n3|body_n3) ≈80.4%@50d bars≈15.86",
        "locked_early_sell_candidate": "v11_nobody|softbody × profit_early_3",
        "elapsed_s": round(time.time() - t0, 1),
        "universe_meta": meta,
        "ranking": ranking,
        "extreme_win_ge80": extreme[:20],
        "extreme_win_ge80_days50": d50[:20],
        "profit_early_sell_ge80_d50": sell_rows[:15],
        "confirm_profit_early_3": {k: v for k, v in confirm.items()},
        "gate_one_liner": gate,
        "errors_n": len(errors),
        "errors_sample": errors[:8],
    }
    text = json.dumps(out, ensure_ascii=False, indent=2, default=str)
    (ART / "phone_spirit_mix_thicken_v16_latest.json").write_text(text, encoding="utf-8")
    (DOC / "phone_spirit_mix_thicken_v16_latest.json").write_text(text, encoding="utf-8")
    print("GATE", gate, flush=True)
    print("PROFIT_SELL", json.dumps(sell_rows[:6], ensure_ascii=False, default=str)[:1400], flush=True)
    print("CONFIRM", json.dumps(confirm, ensure_ascii=False, default=str)[:1200], flush=True)
    return out


def main() -> None:
    run()


if __name__ == "__main__":
    main()
