# -*- coding: utf-8 -*-
"""精神有用肢加厚 v4：把 near80@67d（≈79.4%）微閘抬過 0.80×days≥50。

冠軍底：E_w3u × turn_n3 × t60 ≈79.4%@67d（差約 1 筆勝率）。
本輪：去竭盡／假突破／非陽、feat_ok、n2／n3、t60∨(S55∧no_exh) 等微調。
phone_sync=blocked；不准假資料；不准改 leave_zero。
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


def _bal(w: float, d: int) -> float:
    if not np.isfinite(w) or d <= 0:
        return float("-inf")
    return float(w) * min(1.0, d / 50.0)


def run(*, n_universe: int = 100) -> Dict[str, Any]:
    t0 = time.time()
    ART.mkdir(parents=True, exist_ok=True)
    DOC.mkdir(parents=True, exist_ok=True)
    _, mkt_raw = _twii_wave_pack(entry_preset="A0_strict", score_threshold=40.0)
    uni = select_g_universe(n=n_universe, include_twse_top100=True)
    symbols = uni["stock_id"].astype(str).tolist()
    for sid in MUST_INCLUDE:
        if sid not in symbols:
            symbols.append(sid)

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

            w3 = cores["core_w3_start"].fillna(False)
            w3u = cores["core_w3_or_ma60w3"].fillna(False)
            V = bank["hsiao_V"].fillna(False)
            S55 = bank["score55"].fillna(False)
            Vnear = _near(V, 3)
            turn = v3["V3_macd_or_kd"].fillna(False) & v3["V3_barek_ok"].fillna(False)
            intent = spirit["INTENT_build_soft"].fillna(False)
            fib = spirit.get("FIB_near_any", pd.Series(False, index=idx)).fillna(False)
            t60 = v4.get("V4_t60_safe", pd.Series(False, index=idx)).fillna(False)
            feat_ok = mkt.get("mkt_feat_ok", pd.Series(True, index=idx)).fillna(False)
            risk = ~mkt["mkt_rel_high_risk"].fillna(False)
            exhaust = feat.get("is_exhaustion_vol")
            exhaust = exhaust.reindex(idx).fillna(False).astype(bool) if exhaust is not None else pd.Series(False, index=idx)
            fake = feat.get("fake_breakout_exit")
            fake = fake.reindex(idx).fillna(False).astype(bool) if fake is not None else pd.Series(False, index=idx)
            bull = (df["close"].astype(float) > df["open"].astype(float))
            no_exh = ~exhaust
            no_fake = ~fake

            bases = {
                "turn_n2": _near(turn, 2),
                "turn_n3": _near(turn, 3),
                "turn_n4": _near(turn, 4),
                "turn_or_fib_n3": _near(turn | fib, 3),
                "intent_or_turn_n3": _near(intent | turn, 3),
            }
            micros = {
                "t60": t60,
                "t60_no_exh": t60 & no_exh,
                "t60_no_fake": t60 & no_fake,
                "t60_bull": t60 & bull,
                "t60_feat": t60 & feat_ok,
                "t60_no_exh_bull": t60 & no_exh & bull,
                "t60_or_S55_no_exh": (t60 | S55) & no_exh,
                "t60_S55": t60 & S55,
                "t60_Vnear": t60 & Vnear,
                "t60_intent": t60 & intent,
                "S55_no_exh": S55 & no_exh,
                "feat_no_exh": feat_ok & no_exh,
            }

            wave_top = (
                ev.get("LAB_W1_TOP", pd.Series(False, index=idx))
                | ev.get("LAB_W3_TOP", pd.Series(False, index=idx))
                | ev.get("LAB_SELL_W5_TOP", pd.Series(False, index=idx))
            ).fillna(False)
            entries = {"E_w3": w3, "E_w3u": w3u}
            sell_modes = ("hi20_or_wave_top", "wave_top_next")

            for en, em in entries.items():
                for bn, bm in bases.items():
                    for mn, mm in micros.items():
                        for mode in sell_modes:
                            entry = em & bm & mm & risk
                            key = f"{en}__{bn}__{mn}__SELL_{mode}"
                            bucket.setdefault(key, []).extend(
                                _simulate_relhigh(
                                    df, entry, hl=hl, temp_label=temp, sid=sid, entry_tag=key, wave_top=wave_top, mode=mode
                                )
                            )
                            pool = w3u | w3
                            if int(pool.sum()) < 5:
                                pool = pd.Series(True, index=idx)
                            rnd = _random_matched(entry, pool & bm & mm, seed=seed + len(key))
                            bucket.setdefault(f"random__{key}", []).extend(
                                _simulate_relhigh(
                                    df, rnd, hl=hl, temp_label=temp, sid=sid, entry_tag=f"rnd__{key}", wave_top=wave_top, mode=mode
                                )
                            )
        except Exception as e:
            errors.append(f"{sid}:{type(e).__name__}:{e}")

    by = {k: _agg_trades(v) for k, v in bucket.items()}
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
                "days_ge30": days >= 30,
                "days_ge40": days >= 40,
                "days_ge50": days >= 50,
            }
        )

    extreme = sorted(
        [r for r in ranking if r["beats_random"] and r["win_ge80"]],
        key=lambda r: (float(r["win_rate"]), int(r["n_unique_entry_days"])),
        reverse=True,
    )
    thick50 = sorted(
        [r for r in extreme if r["days_ge50"]],
        key=lambda r: (r["win_rate"], r["n_unique_entry_days"]),
        reverse=True,
    )
    thick30 = sorted(
        [r for r in extreme if r["days_ge30"]],
        key=lambda r: (r["n_unique_entry_days"], r["win_rate"]),
        reverse=True,
    )
    near80 = sorted(
        [r for r in ranking if r["beats_random"] and r["days_ge50"] and (r.get("win_rate") or 0) >= 0.78],
        key=lambda r: (r["win_rate"], r["n_unique_entry_days"]),
        reverse=True,
    )
    gate = (
        f"spirit_mix_thicken_v4 ge80={len(extreme)} ge80_d30={len(thick30)} ge80_d50={len(thick50)}; "
        f"best_win={extreme[0]['key'] if extreme else None} "
        f"win={extreme[0].get('win_rate') if extreme else None} "
        f"days={extreme[0].get('n_unique_entry_days') if extreme else None}; "
        f"best_d50={thick50[0]['key'] if thick50 else None}; "
        f"near80_d50={near80[0]['key'] if near80 else None}; promote_lookup=NO"
    )
    out = {
        "phone_sync": PHONE_SYNC,
        "promote_to_lookup_display": False,
        "user_goal_zh": "提早買／賣；微閘把 79.4%@67d 抬過 80%×50d",
        "parent_seal": "phone_spirit_mix_thicken_v3_decision.json",
        "elapsed_s": round(time.time() - t0, 1),
        "n_stocks": meta_n,
        "ranking": ranking,
        "extreme_win_ge80": extreme[:25],
        "extreme_win_ge80_days30": thick30[:15],
        "extreme_win_ge80_days50": thick50[:15],
        "near80_days50": near80[:15],
        "gate_one_liner": gate,
        "errors_n": len(errors),
        "errors_sample": errors[:8],
    }
    text = json.dumps(out, ensure_ascii=False, indent=2, default=str)
    (ART / "phone_spirit_mix_thicken_v4_latest.json").write_text(text, encoding="utf-8")
    (DOC / "phone_spirit_mix_thicken_v4_latest.json").write_text(text, encoding="utf-8")
    print("GATE", gate, flush=True)
    print("TOP_D50", json.dumps(thick50[:5], ensure_ascii=False, default=str)[:1200], flush=True)
    print("NEAR80_D50", json.dumps(near80[:5], ensure_ascii=False, default=str)[:1200], flush=True)
    return out


def main() -> None:
    run(n_universe=100)


if __name__ == "__main__":
    main()
