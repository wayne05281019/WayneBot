# -*- coding: utf-8 -*-
"""mix_v9 後：intent 主訊號＋未追高／week 併列，搶 early≥80%×50d。

v9：soft near 幾乎無差；ei_n5 仍 79.6%@53d bars≈15.9；ei_n5_week_n3 80.4%@45d。
本輪：1) intent 當日主訊號＋w3u near（較早）；2) ei_n5 未延伸／回檔／ma5 去損；
3) week_n3 OR room 加厚日數。phone_sync=blocked。
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


def _bal(w: float, d: int) -> float:
    if not np.isfinite(w) or d <= 0:
        return float("-inf")
    return float(w) * min(1.0, d / 50.0)


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

            c = df["close"].astype(float)
            h = df["high"].astype(float)
            w3u = cores["core_w3_or_ma60w3"].fillna(False)
            turn = v3["V3_macd_or_kd"].fillna(False) & v3["V3_barek_ok"].fillna(False)
            intent = spirit["INTENT_build_soft"].fillna(False)
            t60 = v4["V4_t60_safe"].fillna(False)
            risk = ~mkt["mkt_rel_high_risk"].fillna(False)
            week = v4["V4_week_stack"].fillna(False)

            hi20 = h.rolling(20, min_periods=10).max()
            room = (hi20 / c.replace(0, np.nan) - 1.0).fillna(0)
            not_ext = (room > 0.02).fillna(False)
            not_chase = (c < h.rolling(10, min_periods=5).max().shift(1)).fillna(False)
            ma5 = c.rolling(5, min_periods=3).mean()
            above_ma5 = (c > ma5).fillna(False)
            pull = (c <= h.rolling(5, min_periods=3).max() * 0.98).fillna(False)

            champ = w3u & _near(turn, 3) & t60 & _near(intent, 3) & risk
            ei_n5 = w3u & _near(turn, 3) & t60 & _near(intent, 5) & risk
            week_n3 = _near(week, 3)

            cores_entry = {
                "champ_n3": champ,
                "ei_n5": ei_n5,
                "ei_n5_week_n3": ei_n5 & week_n3,
                "ei_n5_room": ei_n5 & not_ext,
                "ei_n5_not_chase": ei_n5 & not_chase,
                "ei_n5_ma5": ei_n5 & above_ma5,
                "ei_n5_pull": ei_n5 & pull,
                "ei_n5_room_or_week": ei_n5 & (not_ext | week_n3),
                "ei_n5_week_or_nochase": ei_n5 & (week_n3 | not_chase),
                "ei_n5_week_and_room": ei_n5 & week_n3 & not_ext,
                # intent 主訊號（當日 intent）＋ w3u 近窗確認
                "intent_prim_w3u_n3": intent & _near(turn, 3) & t60 & _near(w3u, 3) & risk,
                "intent_prim_w3u_n5": intent & _near(turn, 3) & t60 & _near(w3u, 5) & risk,
                "intent_prim_w3u_n5_room": intent & _near(turn, 3) & t60 & _near(w3u, 5) & not_ext & risk,
                "intent_prim_w3u_n5_week": intent & _near(turn, 3) & t60 & _near(w3u, 5) & week_n3 & risk,
                "intent_soft_w3u_n5": _near(intent, 2) & _near(turn, 3) & t60 & _near(w3u, 5) & risk,
            }
            wave_top = (
                ev.get("LAB_W1_TOP", pd.Series(False, index=idx))
                | ev.get("LAB_W3_TOP", pd.Series(False, index=idx))
                | ev.get("LAB_SELL_W5_TOP", pd.Series(False, index=idx))
            ).fillna(False)

            for cn, entry in cores_entry.items():
                key = f"{cn}__SELL_hi20_or_wave_top"
                trades = _simulate_relhigh(
                    df, entry, hl=hl, temp_label=temp, sid=sid, entry_tag=key, wave_top=wave_top, mode="hi20_or_wave_top"
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
                trade_bucket.setdefault(rkey, []).extend(
                    _simulate_relhigh(
                        df, rnd, hl=hl, temp_label=temp, sid=sid, entry_tag=rkey, wave_top=wave_top, mode="hi20_or_wave_top"
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
                "earlier_than_baseline": bool(np.isfinite(bars) and bars > BASELINE_BARS + 0.05),
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
    near80 = sorted(
        [
            r
            for r in ranking
            if r.get("beats_random")
            and r.get("days_ge50")
            and float(r.get("win_rate") or 0) >= 0.78
            and float(r.get("mean_bars_before_hi20") or 0) > BASELINE_BARS + 0.05
        ],
        key=lambda r: (-float(r.get("win_rate") or 0), -float(r.get("mean_bars_before_hi20") or 0)),
    )
    gate = (
        f"spirit_mix_thicken_v10 ge80={len(extreme)} ge80_d50={len(d50)} earlier_d50={len(early_wins)}; "
        f"best_early_d50={d50[0]['key'] if d50 else None} "
        f"win={d50[0].get('win_rate') if d50 else None} "
        f"bars={d50[0].get('mean_bars_before_hi20') if d50 else None}; "
        f"near80_early={near80[0]['key'] if near80 else None} "
        f"near_win={near80[0].get('win_rate') if near80 else None} "
        f"near_bars={near80[0].get('mean_bars_before_hi20') if near80 else None}; "
        f"baseline_bars={BASELINE_BARS}; promote_lookup=NO"
    )
    out = {
        "phone_sync": PHONE_SYNC,
        "promote_to_lookup_display": False,
        "user_goal_zh": "v10：intent 主訊號＋未追高／week 併列搶 early ge80×50d",
        "parent_seal": "phone_spirit_mix_thicken_v9_decision.json",
        "baseline_bars_v5": BASELINE_BARS,
        "elapsed_s": round(time.time() - t0, 1),
        "n_stocks": meta_n,
        "ranking": ranking,
        "extreme_win_ge80": extreme[:20],
        "extreme_win_ge80_days50": d50[:15],
        "earlier_than_baseline_ge80_d50": early_wins[:10],
        "near80_earlier_d50": near80[:10],
        "gate_one_liner": gate,
        "errors_n": len(errors),
        "errors_sample": errors[:8],
    }
    text = json.dumps(out, ensure_ascii=False, indent=2, default=str)
    (ART / "phone_spirit_mix_thicken_v10_latest.json").write_text(text, encoding="utf-8")
    (DOC / "phone_spirit_mix_thicken_v10_latest.json").write_text(text, encoding="utf-8")
    print("GATE", gate, flush=True)
    print("TOP_EARLY_D50", json.dumps(d50[:5], ensure_ascii=False, default=str)[:1200], flush=True)
    print("EARLIER_WINS", json.dumps(early_wins[:5], ensure_ascii=False, default=str)[:800], flush=True)
    print("NEAR80_EARLY", json.dumps(near80[:5], ensure_ascii=False, default=str)[:1000], flush=True)
    return out


def main() -> None:
    run(n_universe=150)


if __name__ == "__main__":
    main()
