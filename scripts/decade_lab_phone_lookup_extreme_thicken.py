# -*- coding: utf-8 -*-
"""極高勝率加厚：從 v4 已見 ≥80% 肢出發，用近窗／軟 OR 拉長獨立日。

目標：win≥0.80 且 days 盡量 ≥30／40／50；服務查股五張圖買賣相對位置。
鎖死 bal／w3 買 × hi20_or_wave_top 賣。phone_sync=blocked。
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
from scripts.decade_lab_phone_extreme_hillclimb import (
    _align_feat,
    _cores,
    _near,
    _wave_hsiao_bank,
)
from scripts.decade_lab_phone_market_wave_sync import (
    _align_mkt,
    _barek_masks,
    _stock_wave_events,
    _twii_wave_pack,
)
from scripts.decade_lab_phone_relhigh_sell import _simulate_relhigh
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
            ev = _stock_wave_events(raw, df)
            mkt = _align_mkt(df, mkt_raw)
            hl, temp = _build_hl_temp(df)
            seed = abs(hash(sid)) % (2**32)
            bk = _barek_masks(df)
            v3 = build_v3_extras(df, feat, bank, barek=bk)
            v4 = build_v4_extras(df, feat)

            V = bank["hsiao_V"].fillna(False)
            Vnear = _near(V, 3)
            S55 = bank["score55"].fillna(False)
            w3 = cores["core_w3_start"].fillna(False)
            w3u = cores["core_w3_or_ma60w3"].fillna(False)
            bal = w3u & (Vnear | S55)
            wave_top = (
                ev.get("LAB_W1_TOP", pd.Series(False, index=df.index))
                | ev.get("LAB_W3_TOP", pd.Series(False, index=df.index))
                | ev.get("LAB_SELL_W5_TOP", pd.Series(False, index=df.index))
            ).fillna(False)
            feat_ok = mkt.get("mkt_feat_ok", pd.Series(True, index=df.index)).fillna(False)

            # 種子：v4 已見 ≥80% 肢
            turn_barek = v3["V3_macd_or_kd"].fillna(False) & v3["V3_barek_ok"].fillna(False)
            t60_or_time = v4["V4_t60_safe"].fillna(False) | v3["V3_time_align"].fillna(False)
            week_or_kd = v4["V4_week_stack"].fillna(False) | v3["V3_macd_or_kd"].fillna(False)
            seeds = {
                "S_turn_barek": turn_barek,
                "S_t60_or_time": t60_or_time,
                "S_week_or_kd": week_or_kd,
                "S_V": V,
                "S_S55": S55,
                "S_V_or_S55": Vnear | S55,
            }
            # 加厚：近窗 2/3/5；軟 OR 兩種子
            thick: Dict[str, pd.Series] = {}
            for sn, sm in seeds.items():
                thick[sn] = sm
                for w in (2, 3, 5):
                    thick[f"{sn}_n{w}"] = _near(sm, w)
            thick["T_turn_or_t60"] = turn_barek | t60_or_time
            thick["T_turn_or_week"] = turn_barek | week_or_kd
            thick["T_t60_or_week"] = t60_or_time | week_or_kd
            thick["T_turn_n3_or_Vnear"] = _near(turn_barek, 3) | Vnear
            thick["T_V_or_turn"] = V | turn_barek
            thick["T_S55_or_turn"] = S55 | turn_barek
            thick["T_pack_any2"] = (
                turn_barek.astype(int) + t60_or_time.astype(int) + week_or_kd.astype(int) + Vnear.astype(int)
            ) >= 2

            entries = {"E_w3": w3, "E_bal": bal}
            mkt_opts = {"M0": pd.Series(True, index=df.index), "M_feat_ok": feat_ok}

            for en, em in entries.items():
                for mn, mm in mkt_opts.items():
                    for tn, tm in thick.items():
                        entry = em & mm & tm & (~mkt["mkt_rel_high_risk"].fillna(False))
                        key = f"{en}__{mn}__{tn}__SELL_{SELL}"
                        bucket.setdefault(key, []).extend(
                            _simulate_relhigh(
                                df, entry, hl=hl, temp_label=temp, sid=sid, entry_tag=key, wave_top=wave_top, mode=SELL
                            )
                        )
                        pool = w3u | w3
                        if int(pool.sum()) < 5:
                            pool = pd.Series(True, index=df.index)
                        rnd = _random_matched(entry, pool & mm & tm, seed=seed + len(key))
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
                "win_ge85": bool(ok and win >= 0.85),
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
    extreme_thick = sorted(
        [r for r in extreme if r["days_ge30"]],
        key=lambda r: (float(r["win_rate"]), int(r["n_unique_entry_days"])),
        reverse=True,
    )
    by_bal = sorted(
        [r for r in ranking if r["beats_random"]],
        key=lambda r: (float(r.get("balanced_score") or -9), float(r.get("win_rate") or -1)),
        reverse=True,
    )
    gate = (
        f"extreme_thicken ge80={len(extreme)} ge80_d30={len(extreme_thick)}; "
        f"best_win={extreme[0]['key'] if extreme else None} "
        f"win={extreme[0].get('win_rate') if extreme else None} "
        f"days={extreme[0].get('n_unique_entry_days') if extreme else None}; "
        f"best_ge80_d30={extreme_thick[0]['key'] if extreme_thick else None}; promote_lookup=NO"
    )
    out = {
        "phone_sync": PHONE_SYNC,
        "promote_to_lookup_display": False,
        "user_goal_zh": "查股五張圖買賣相對位置＋極高勝率",
        "elapsed_s": round(time.time() - t0, 1),
        "n_stocks": meta_n,
        "ranking": ranking,
        "extreme_win_ge80": extreme[:25],
        "extreme_win_ge80_days30": extreme_thick[:15],
        "by_balanced_score": by_bal[:15],
        "gate_one_liner": gate,
        "errors_n": len(errors),
        "errors_sample": errors[:8],
    }
    text = json.dumps(out, ensure_ascii=False, indent=2, default=str)
    (ART / "phone_lookup_extreme_thicken_latest.json").write_text(text, encoding="utf-8")
    (DOC / "phone_lookup_extreme_thicken_latest.json").write_text(text, encoding="utf-8")
    print("GATE", gate, flush=True)
    print("TOP80", json.dumps(extreme[:5], ensure_ascii=False, default=str)[:1500], flush=True)
    return out


def main() -> None:
    run(n_universe=100)


if __name__ == "__main__":
    main()
