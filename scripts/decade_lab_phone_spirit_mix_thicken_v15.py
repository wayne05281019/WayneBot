# -*- coding: utf-8 -*-
"""mix_v14 後：放寬母體加厚；body==false／有利潤賣搶 ge80×50d。

v14：cut_pass=0；profit_early≈78.9% hold≈13（比 v11 hold≈15.2 早離）；
body==false 去損 82%@44d。G 母體卡 112。
本輪：min_turnover 放寬＋n=250 加厚；鎖定 v11；試 body_n5&~body、
profit_early×軟品質。phone_sync=blocked。
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


def run(*, n_universe: int = 250, min_turnover_k: float = 400_000.0) -> Dict[str, Any]:
    t0 = time.time()
    ART.mkdir(parents=True, exist_ok=True)
    DOC.mkdir(parents=True, exist_ok=True)
    _, mkt_raw = _twii_wave_pack(entry_preset="A0_strict", score_threshold=40.0)
    uni = select_g_universe(
        n=n_universe,
        include_twse_top100=True,
        min_avg_turnover_k=min_turnover_k,
        min_bars=200,
    )
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
            body_n5 = ei_n5 & (_near(week, 3) | _near(body, 5))
            champ = w3u & _near(turn, 3) & t60 & _near(intent, 3) & risk
            # cut 暗示：進場當日非 body_thrust → 82%@44d；加厚用 week soft OR
            body_n5_nobody = body_n5 & (~body)
            body_n5_nobody_or_week = body_n5 & (~body | _near(week, 5))
            v11_nobody = v11 & (~body)

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

            cores_buy = {
                "champ_n3": champ,
                "v11_softbody": v11,
                "body_n5": body_n5,
                "body_n5_nobody": body_n5_nobody,
                "body_n5_nobody_or_week": body_n5_nobody_or_week,
                "v11_nobody": v11_nobody,
            }
            for cn, entry in cores_buy.items():
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

            # profit-gated early sell on v11 / v11_nobody
            for ename, entry in (("v11_softbody", v11), ("v11_nobody", v11_nobody)):
                for mp in (0.03, 0.05, 0.10):
                    key = f"{ename}__SELL_profit_early_{int(mp*100)}"
                    trades = _sim_profit_early(
                        df, entry, hl=hl, temp_label=temp, sid=sid, entry_tag=key, wave_top=wave_top, early_sell=early_sell, min_profit=mp
                    )
                    trade_bucket.setdefault(key, []).extend(trades)
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
    v11_hold = next((r.get("mean_hold_days") for r in ranking if r["key"] == "v11_softbody__SELL_hi20_or_wave_top"), float("nan"))
    sell_rows = [
        r
        for r in ranking
        if "SELL_profit_early" in r["key"] and r.get("win_ge80") and r.get("days_ge50") and r.get("beats_random")
    ]
    sell_rows = sorted(sell_rows, key=lambda r: (float(r.get("mean_hold_days") or 99), -float(r.get("win_rate") or 0)))
    gate = (
        f"spirit_mix_thicken_v15 ge80={len(extreme)} ge80_d50={len(d50)} earlier_d50={len(early_wins)} "
        f"beat_v11_bars={len(beat_v11)} n_stocks={meta_n}; "
        f"best_early_d50={d50[0]['key'] if d50 else None} "
        f"win={d50[0].get('win_rate') if d50 else None} "
        f"bars={d50[0].get('mean_bars_before_hi20') if d50 else None}; "
        f"best_profit_sell={sell_rows[0]['key'] if sell_rows else None} "
        f"hold={sell_rows[0].get('mean_hold_days') if sell_rows else None} "
        f"v11_hold={v11_hold}; promote_lookup=NO"
    )
    out = {
        "phone_sync": PHONE_SYNC,
        "promote_to_lookup_display": False,
        "user_goal_zh": "v15：放寬母體＋nobody／有利潤賣搶閘",
        "parent_seal": "phone_spirit_mix_thicken_v14_decision.json",
        "baseline_bars_v5": BASELINE_BARS,
        "v11_champ_bars": V11_BARS,
        "universe_request": {"n": n_universe, "min_turnover_k": min_turnover_k},
        "elapsed_s": round(time.time() - t0, 1),
        "n_stocks": meta_n,
        "ranking": ranking,
        "extreme_win_ge80": extreme[:20],
        "extreme_win_ge80_days50": d50[:15],
        "earlier_than_baseline_ge80_d50": early_wins[:10],
        "beat_v11_bars_ge80_d50": beat_v11[:10],
        "profit_early_sell_ge80_d50": sell_rows[:10],
        "gate_one_liner": gate,
        "errors_n": len(errors),
        "errors_sample": errors[:8],
    }
    text = json.dumps(out, ensure_ascii=False, indent=2, default=str)
    (ART / "phone_spirit_mix_thicken_v15_latest.json").write_text(text, encoding="utf-8")
    (DOC / "phone_spirit_mix_thicken_v15_latest.json").write_text(text, encoding="utf-8")
    print("GATE", gate, flush=True)
    print("EARLIER", json.dumps(early_wins[:5], ensure_ascii=False, default=str)[:1000], flush=True)
    print("PROFIT_SELL", json.dumps(sell_rows[:5], ensure_ascii=False, default=str)[:800], flush=True)
    print("N_STOCKS", meta_n, "REQ", n_universe, flush=True)
    return out


def main() -> None:
    run(n_universe=250, min_turnover_k=400_000.0)


if __name__ == "__main__":
    main()
