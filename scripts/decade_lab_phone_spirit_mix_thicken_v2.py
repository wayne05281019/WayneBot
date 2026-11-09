# -*- coding: utf-8 -*-
"""精神有用肢加厚 v2：專攻差一日到 50 的冠軍。

mix_thicken 最厚：turn_barek_n3 ≈80%@49d；turn_fib_n5 ≈81%@48d。
本輪：近窗 4／6／9、intent∨turn 近窗、turn_fib 再軟 OR。
目標 ge80×days≥50；phone_sync=blocked。
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
from scripts.decade_lab_phone_spirit_split_mix import _five_proxies
from scripts.decade_lab_phone_trade_confront import _agg_trades, _build_hl_temp
from scripts.decade_lab_phone_wave_filter import _align_wave, _wave_frame, _wave_masks

PHONE_SYNC = "blocked"
ART = Path("/opt/cursor/artifacts")
DOC = Path(__file__).resolve().parents[1] / "docs" / "expert_notes" / "飆客" / "decade_lab"
SELL = "hi20_or_wave_top"


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
            five = _five_proxies(df, feat, spirit)
            barek = _barek_masks(df)
            ev = _stock_wave_events(raw, df)
            mkt = _align_mkt(df, mkt_raw)
            v3 = build_v3_extras(df, feat, bank, barek=barek)
            hl, temp = _build_hl_temp(df)
            seed = abs(hash(sid)) % 10_000
            idx = df.index

            w3 = cores["core_w3_start"].fillna(False)
            w3u = cores["core_w3_or_ma60w3"].fillna(False)
            V = bank["hsiao_V"].fillna(False)
            S55 = bank["score55"].fillna(False)
            bal = w3u & (_near(V, 3) | S55)
            intent = spirit["INTENT_build_soft"].fillna(False)
            turn = v3["V3_macd_or_kd"].fillna(False) & v3["V3_barek_ok"].fillna(False)
            fib = spirit.get("FIB_near_any", pd.Series(False, index=idx)).fillna(False)
            five2 = five["FIVE_cross2"].fillna(False)
            risk = ~mkt["mkt_rel_high_risk"].fillna(False)

            seeds = {
                "U_turn": turn,
                "U_intent": intent,
                "U_turn_fib": turn & fib,
                "U_intent_or_turn": intent | turn,
                "U_spirit_core": intent & (five2 | turn),
                "U_turn_or_fib": turn | fib,
                "U_turn_or_Vnear": turn | _near(V, 3),
            }
            thick: Dict[str, pd.Series] = {}
            for sn, sm in seeds.items():
                thick[sn] = sm
                for w in (3, 4, 5, 6, 9):
                    thick[f"{sn}_n{w}"] = _near(sm, w)
            # 專攻 49→50：n3∨n4 聯集近似更寬一天窗
            thick["U_turn_n3_or_n4"] = _near(turn, 3) | _near(turn, 4)
            thick["U_turn_fib_n5_or_n6"] = _near(turn & fib, 5) | _near(turn & fib, 6)
            thick["U_intent_n3_or_turn_n3"] = _near(intent, 3) | _near(turn, 3)

            wave_top = (
                ev.get("LAB_W1_TOP", pd.Series(False, index=idx))
                | ev.get("LAB_W3_TOP", pd.Series(False, index=idx))
                | ev.get("LAB_SELL_W5_TOP", pd.Series(False, index=idx))
            ).fillna(False)
            entries = {"E_w3": w3, "E_w3u": w3u, "E_bal": bal}

            for en, em in entries.items():
                for tn, tm in thick.items():
                    entry = em & tm & risk
                    key = f"{en}__{tn}__SELL_{SELL}"
                    bucket.setdefault(key, []).extend(
                        _simulate_relhigh(
                            df, entry, hl=hl, temp_label=temp, sid=sid, entry_tag=key, wave_top=wave_top, mode=SELL
                        )
                    )
                    pool = w3u | w3
                    if int(pool.sum()) < 5:
                        pool = pd.Series(True, index=idx)
                    rnd = _random_matched(entry, pool & tm, seed=seed + len(key))
                    bucket.setdefault(f"random__{key}", []).extend(
                        _simulate_relhigh(
                            df, rnd, hl=hl, temp_label=temp, sid=sid, entry_tag=f"rnd__{key}", wave_top=wave_top, mode=SELL
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
    thick30 = sorted(
        [r for r in extreme if r["days_ge30"]],
        key=lambda r: (r["n_unique_entry_days"], r["win_rate"]),
        reverse=True,
    )
    thick50 = [r for r in extreme if r["days_ge50"]]
    gate = (
        f"spirit_mix_thicken_v2 ge80={len(extreme)} ge80_d30={len(thick30)} ge80_d50={len(thick50)}; "
        f"best_win={extreme[0]['key'] if extreme else None} "
        f"win={extreme[0].get('win_rate') if extreme else None} "
        f"days={extreme[0].get('n_unique_entry_days') if extreme else None}; "
        f"best_days={thick30[0]['key'] if thick30 else None}; "
        f"best_d50={thick50[0]['key'] if thick50 else None}; promote_lookup=NO"
    )
    out = {
        "phone_sync": PHONE_SYNC,
        "promote_to_lookup_display": False,
        "user_goal_zh": "提早買／賣；衝 ge80×≥50d（破 49 天花板）",
        "parent_seal": "phone_spirit_mix_thicken_decision.json",
        "elapsed_s": round(time.time() - t0, 1),
        "n_stocks": meta_n,
        "ranking": ranking,
        "extreme_win_ge80": extreme[:25],
        "extreme_win_ge80_days30": thick30[:15],
        "extreme_win_ge80_days50": thick50[:15],
        "gate_one_liner": gate,
        "errors_n": len(errors),
        "errors_sample": errors[:8],
    }
    text = json.dumps(out, ensure_ascii=False, indent=2, default=str)
    (ART / "phone_spirit_mix_thicken_v2_latest.json").write_text(text, encoding="utf-8")
    (DOC / "phone_spirit_mix_thicken_v2_latest.json").write_text(text, encoding="utf-8")
    print("GATE", gate, flush=True)
    print("TOP_D50", json.dumps(thick50[:5], ensure_ascii=False, default=str)[:1200], flush=True)
    return out


def main() -> None:
    run(n_universe=100)


if __name__ == "__main__":
    main()
