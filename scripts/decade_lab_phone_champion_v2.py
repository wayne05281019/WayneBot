# -*- coding: utf-8 -*-
"""自主優化 V2：鎖死起漲買／相對高點賣，疊均衡核＋大盤特徵閘＋新因子再測。

核：
- 進：W3∪紅箭×W3 × (近窗攻擊量 ∨ score55)（balanced 冠軍）
- 出：hi20_or_wave_top（相對高點賣）
- 大盤：mkt_feat_ok／feat_safe／feat_thrust（TWII 浪段引擎不夠分時用蕭特徵）
- 新因子候選：immortal近窗、hammer、非KD死叉、非過熱、MACD翻多、壓縮突破、破線翻

phone_sync=blocked。
"""
from __future__ import annotations

import argparse
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
from scripts.decade_lab_phone_entry_tighten import _random_matched
from scripts.decade_lab_phone_extreme_hillclimb import (
    _align_feat,
    _bool,
    _cores,
    _near,
    _wave_hsiao_bank,
)
from scripts.decade_lab_phone_market_wave_sync import _align_mkt, _barek_masks, _stock_wave_events, _twii_wave_pack
from scripts.decade_lab_phone_relhigh_sell import _simulate_relhigh
from scripts.decade_lab_phone_trade_confront import _agg_trades, _build_hl_temp
from scripts.decade_lab_phone_wave_filter import _align_wave, _wave_frame, _wave_masks

PHONE_SYNC = "blocked"
NOT_BUY_SIGNAL = True
ART = Path("/opt/cursor/artifacts")
DOC = Path(__file__).resolve().parents[1] / "docs" / "expert_notes" / "飆客" / "decade_lab"
SELL_MODE = "hi20_or_wave_top"
DAY_FLOOR = 50


def _bal(win: float, days: int) -> float:
    if not np.isfinite(win) or days <= 0:
        return float("-inf")
    return float(win) * min(1.0, days / float(DAY_FLOOR))


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
            masks = _build_mark_masks(df)
            cores = _cores(masks, wmasks, feat)
            bank = _wave_hsiao_bank(feat, wmasks, wave)
            bk = _barek_masks(df)
            ev = _stock_wave_events(raw, df)
            mkt = _align_mkt(df, mkt_raw)
            hl, temp = _build_hl_temp(df)
            seed = abs(hash(sid)) % (2**32)

            V = bank["hsiao_V"].fillna(False)
            Vnear = _near(V, 3)
            S55 = bank["score55"].fillna(False)
            core = cores["core_w3_or_ma60w3"].fillna(False)
            bal = core & (Vnear | S55)
            wave_top = (
                ev.get("LAB_W1_TOP", pd.Series(False, index=df.index))
                | ev.get("LAB_W3_TOP", pd.Series(False, index=df.index))
                | ev.get("LAB_SELL_W5_TOP", pd.Series(False, index=df.index))
            ).fillna(False)

            immortal = _near(ev.get("LAB_IMMORTAL_GUIDE", pd.Series(False, index=df.index)), 5)
            hammer = _near(ev.get("LAB_W2_HAMMER", pd.Series(False, index=df.index)), 3) | bank.get(
                "hammer_w2", pd.Series(False, index=df.index)
            ).fillna(False)
            kd_ok = bank["hsiao_kd"].fillna(False) | (~_bool(feat.get("kd_death_cross"), df.index))
            # kd_ok above is weak; prefer not death
            not_kd_death = ~_bool(feat.get("kd_death_cross"), df.index)
            macd_turn = bank["hsiao_macd_turn"].fillna(False)
            compress = bank["hsiao_compress"].fillna(False)
            not_hot = bank["hsiao_not_hot"].fillna(False)
            clean = bank["hsiao_clean"].fillna(False)
            week = bank["hsiao_week"].fillna(False)

            extras = {
                "X0": pd.Series(True, index=df.index),
                "X_immortal": immortal,
                "X_hammer": hammer,
                "X_not_kd_death": not_kd_death,
                "X_macd_turn": macd_turn,
                "X_compress": compress,
                "X_week": week,
                "X_bk_ok": bk["bk_not_avoid"],
                "X_bk_pos": bk["bk_constructive"],
                "X_clean_hot": clean & not_hot,
                "X_hammer_or_immortal": hammer | immortal,
                "X_macd_or_compress": macd_turn | compress,
                "X_pack2": (not_kd_death.astype(int) + clean.astype(int) + not_hot.astype(int) + week.astype(int))
                >= 3,
            }
            mkt_opts = {
                "M0": pd.Series(True, index=df.index),
                "M_feat_ok": mkt.get("mkt_feat_ok", pd.Series(True, index=df.index)),
                "M_feat_safe": mkt.get("mkt_feat_safe", pd.Series(True, index=df.index)),
                "M_feat_thrust": mkt.get("mkt_feat_thrust", pd.Series(True, index=df.index)),
                "M_feat_bull": mkt.get("mkt_feat_bull", pd.Series(True, index=df.index)),
            }

            # also keep pure core baselines
            bases = {
                "B_core": core,
                "B_bal": bal,
                "B_w3": cores["core_w3_start"].fillna(False),
            }

            for bname, bmask in bases.items():
                for mname, mm in mkt_opts.items():
                    for xname, xm in extras.items():
                        if bname != "B_bal" and xname not in ("X0", "X_clean_hot", "X_bk_ok", "X_pack2"):
                            continue  # 非均衡核少掃，省時間
                        entry = bmask & mm.fillna(False) & xm.fillna(False) & (~mkt["mkt_rel_high_risk"].fillna(False))
                        key = f"{bname}__{mname}__{xname}__SELL_{SELL_MODE}"
                        bucket.setdefault(key, []).extend(
                            _simulate_relhigh(
                                df,
                                entry,
                                hl=hl,
                                temp_label=temp,
                                sid=sid,
                                entry_tag=key,
                                wave_top=wave_top,
                                mode=SELL_MODE,
                            )
                        )
                        pool = core | cores["core_w3_start"].fillna(False)
                        if int(pool.sum()) < 5:
                            pool = pd.Series(True, index=df.index)
                        rnd = _random_matched(entry, pool & mm.fillna(False) & xm.fillna(False), seed=seed + len(key))
                        bucket.setdefault(f"random__{key}", []).extend(
                            _simulate_relhigh(
                                df,
                                rnd,
                                hl=hl,
                                temp_label=temp,
                                sid=sid,
                                entry_tag=f"rnd__{key}",
                                wave_top=wave_top,
                                mode=SELL_MODE,
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
        beats_r = bool(
            ok
            and np.isfinite(exp)
            and np.isfinite(rnd.get("expectancy", np.nan))
            and exp > float(rnd["expectancy"])
            and win > float(rnd.get("win_rate") or -1)
        )
        # vs B_bal M0 X0
        base = by.get(f"B_bal__M0__X0__SELL_{SELL_MODE}") or {}
        base_win = float(base.get("win_rate") or np.nan) if base else float("nan")
        lifts = bool(ok and np.isfinite(base_win) and win > base_win + 0.005)
        ranking.append(
            {
                "key": key,
                "n_trades": st.get("n_trades"),
                "n_unique_entry_days": days,
                "win_rate": win,
                "expectancy": exp,
                "avg_hold": st.get("avg_hold"),
                "exit_reason_counts": st.get("exit_reason_counts"),
                "random_win_rate": rnd.get("win_rate"),
                "random_expectancy": rnd.get("expectancy"),
                "beats_random": beats_r,
                "lifts_bal_baseline": lifts,
                "balanced_score": _bal(win, days) if ok else float("-inf"),
                "days_ge40": days >= 40,
                "days_ge50": days >= 50,
            }
        )

    winners = [r for r in ranking if r["beats_random"]]
    lift = [r for r in winners if r["lifts_bal_baseline"]]
    by_bal = sorted(
        winners,
        key=lambda r: (float(r.get("balanced_score") or -9), float(r.get("win_rate") or -1)),
        reverse=True,
    )
    by_win = sorted(
        [r for r in ranking if int(r.get("n_unique_entry_days") or 0) >= 20],
        key=lambda r: float(r.get("win_rate") or -1),
        reverse=True,
    )
    ge50 = [r for r in by_bal if r.get("days_ge50")]
    gate = (
        f"v2 winners={len(winners)}/{len(ranking)}; lift={len(lift)}; "
        f"best_bal={by_bal[0]['key'] if by_bal else None} "
        f"win={by_bal[0].get('win_rate') if by_bal else None} "
        f"days={by_bal[0].get('n_unique_entry_days') if by_bal else None}; "
        f"ge50={ge50[0]['key'] if ge50 else None}; promote_lookup=NO"
    )
    out = {
        "phone_sync": PHONE_SYNC,
        "not_buy_signal": NOT_BUY_SIGNAL,
        "sell_lock_zh": "相對高點＝賣股票",
        "buy_lock_zh": "波浪起漲（W3∪紅箭×W3 均衡核）",
        "sell_mode": SELL_MODE,
        "elapsed_s": round(time.time() - t0, 1),
        "n_stocks": meta_n,
        "ranking": ranking,
        "winners_beat_random": winners,
        "winners_lift_bal": lift,
        "by_balanced_score": by_bal[:20],
        "by_winrate_n20": by_win[:15],
        "best_ge50": ge50[:8],
        "promote_to_lookup_display": False,
        "gate_one_liner": gate,
        "errors_n": len(errors),
        "errors_sample": errors[:8],
    }
    text = json.dumps(out, ensure_ascii=False, indent=2, default=str)
    (ART / "phone_champion_v2_latest.json").write_text(text, encoding="utf-8")
    (DOC / "phone_champion_v2_latest.json").write_text(text, encoding="utf-8")
    print("GATE", gate, flush=True)
    print("TOP_BAL", json.dumps(by_bal[:6], ensure_ascii=False, default=str)[:1800], flush=True)
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=100)
    args = ap.parse_args()
    run(n_universe=args.n)


if __name__ == "__main__":
    main()
