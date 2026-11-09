# -*- coding: utf-8 -*-
"""均衡放大勝率：在波浪×蕭核上，用近窗／軟門／計分卡加厚獨立日（實驗室）。

目標不是灌水，而是找「勝率仍明顯高於核、且獨立日夠厚」的均衡點：
- 硬 AND（同根攻擊量）→ 勝率高但日薄（~87%@22）
- 本腳本：近窗量、Vmild、score50、計分卡≥2／≥3、母體可扩到 150
- 排序用 balanced_score = win × min(1, days/DAY_FLOOR)；另報 days≥40／50 閘

phone_sync=blocked；不上查股。
"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any, Dict, List, Tuple

import numpy as np
import pandas as pd

from scripts.decade_lab_chart_marks_stats import _build_mark_masks, _normalize_ohlc
from scripts.decade_lab_hsiao_data_preprocessor import prepare_ohlcv
from scripts.decade_lab_hsiao_quant_features import compute_hsiao_features
from scripts.decade_lab_hsiao_universe import MUST_INCLUDE, load_stock_ohlcv, select_g_universe
from scripts.decade_lab_phone_entry_tighten import _random_matched
from scripts.decade_lab_phone_extreme_hillclimb import (
    CORE_NAMES,
    KEEP_EXIT,
    _align_feat,
    _bool,
    _cores,
    _near,
    _num,
    _wave_hsiao_bank,
)
from scripts.decade_lab_phone_wave_filter import _align_wave, _wave_frame, _wave_masks
from scripts.decade_lab_phone_winrate_boost import _simulate_exits

PHONE_SYNC = "blocked"
NOT_BUY_SIGNAL = True
ROOT = Path(__file__).resolve().parents[1]
ART = Path("/opt/cursor/artifacts")
DOC = ROOT / "docs" / "expert_notes" / "飆客" / "decade_lab"

DAY_FLOOR = 50  # 均衡目標：希望獨立日靠近這條


def _balanced_score(win: float, days: int, floor: int = DAY_FLOOR) -> float:
    if not np.isfinite(win) or days <= 0:
        return float("-inf")
    return float(win) * min(1.0, float(days) / float(floor))


def _balanced_filters(feat: pd.DataFrame, bank: Dict[str, pd.Series]) -> Dict[str, pd.Series]:
    """均衡用濾網：近窗／軟門／計分卡（仍 AND 在核上）。"""
    idx = feat.index
    V = bank["hsiao_V"].reindex(idx).fillna(False)
    Vm = bank["hsiao_Vmild"].reindex(idx).fillna(False)
    S55 = bank["score55"].reindex(idx).fillna(False)
    S50 = bank["score50"].reindex(idx).fillna(False)
    macd = bank["hsiao_macd"].reindex(idx).fillna(False)
    week = bank["hsiao_week"].reindex(idx).fillna(False)
    T = bank["hsiao_T"].reindex(idx).fillna(False)
    safe = bank["wave_safe"].reindex(idx).fillna(False)
    clean = bank["hsiao_clean"].reindex(idx).fillna(False)
    not_hot = bank["hsiao_not_hot"].reindex(idx).fillna(False)

    # 近窗：訊號日前 0–2 根曾攻擊量（含當日）→ 加厚，不全砍同根
    V_near2 = _near(V, 3)  # rolling 含當日往回 3
    V_near1 = _near(V, 2)
    Vm_near2 = _near(Vm, 3)

    # 計分卡：六項各 1 分
    card = (
        V_near2.astype(int)
        + S50.astype(int)
        + macd.astype(int)
        + week.astype(int)
        + T.astype(int)
        + safe.astype(int)
    )

    return {
        "D0": pd.Series(True, index=idx),
        # 對照：硬條件
        "hard_V": V,
        "hard_S55": S55,
        "hard_VT": V & T,
        # 近窗量
        "V_near1": V_near1,
        "V_near2": V_near2,
        "Vmild": Vm,
        "Vm_near2": Vm_near2,
        # 軟分數
        "S50": S50,
        "S55": S55,
        # 均衡組合
        "Vnear2_or_S50": V_near2 | S50,
        "Vnear2_or_S55": V_near2 | S55,
        "Vmild_or_S50": Vm | S50,
        "Vnear2_and_safe": V_near2 & safe,
        "Vnear2_and_clean": V_near2 & clean & not_hot,
        "S50_and_safe": S50 & safe,
        "S50_and_macd": S50 & macd,
        "card_ge2": card >= 2,
        "card_ge3": card >= 3,
        "card_ge4": card >= 4,
        "card2_safe": (card >= 2) & safe,
        "card3_safe": (card >= 3) & safe,
        "card2_not_hot": (card >= 2) & not_hot & clean,
        "card3_Vnear_or_S50": (card >= 3) & (V_near2 | S50),
        # 厚樣本路線：只挡明显坏
        "safe_clean": safe & clean & not_hot,
        "macd_safe": macd & safe,
        "week_safe": week & safe,
    }


def run_balanced(*, n_universe: int = 100) -> Dict[str, Any]:
    t0 = time.time()
    ART.mkdir(parents=True, exist_ok=True)
    DOC.mkdir(parents=True, exist_ok=True)

    uni = select_g_universe(n=n_universe, include_twse_top100=True)
    symbols = uni["stock_id"].astype(str).tolist()
    for sid in MUST_INCLUDE:
        if sid not in symbols:
            symbols.append(sid)

    bucket: Dict[str, List[Dict[str, Any]]] = {
        "leave_zero__hi20_or_desync": [],
        "random__leave_zero__hi20_or_desync": [],
    }
    meta_n = 0
    errors: List[str] = []
    filter_names: List[str] = []

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
            filters = _balanced_filters(feat, bank)
            if not filter_names:
                filter_names = list(filters.keys())
            hl, temp_label = __import__(
                "scripts.decade_lab_phone_trade_confront", fromlist=["_build_hl_temp"]
            )._build_hl_temp(df)
            seed = abs(hash(sid)) % (2**32)

            lz = _bool(masks.get("leave_zero_blue_tri"), df.index)
            bucket["leave_zero__hi20_or_desync"].extend(
                _simulate_exits(
                    df, lz, hl=hl, temp_label=temp_label, sid=sid, entry_tag="lz", exit_mode=KEEP_EXIT
                )
            )
            bucket["random__leave_zero__hi20_or_desync"].extend(
                _simulate_exits(
                    df,
                    _random_matched(lz, pd.Series(True, index=df.index), seed=seed),
                    hl=hl,
                    temp_label=temp_label,
                    sid=sid,
                    entry_tag="rnd_lz",
                    exit_mode=KEEP_EXIT,
                )
            )

            for core_name in CORE_NAMES:
                core_m = cores[core_name].fillna(False)
                for fname, fmask in filters.items():
                    entry = core_m & fmask.reindex(df.index).fillna(False)
                    key = f"{core_name}__BAL_{fname}__{KEEP_EXIT}"
                    bucket.setdefault(key, []).extend(
                        _simulate_exits(
                            df,
                            entry,
                            hl=hl,
                            temp_label=temp_label,
                            sid=sid,
                            entry_tag=key,
                            exit_mode=KEEP_EXIT,
                        )
                    )
                    pool = cores["core_w3_or_ma60w3"].fillna(False) | cores["core_w3_start"].fillna(False)
                    if int(pool.sum()) < 5:
                        pool = pd.Series(True, index=df.index)
                    rnd_pool = pool & fmask.reindex(df.index).fillna(False) if fname != "D0" else pool
                    rnd = _random_matched(entry, rnd_pool, seed=seed + len(key))
                    bucket.setdefault(f"random__{key}", []).extend(
                        _simulate_exits(
                            df,
                            rnd,
                            hl=hl,
                            temp_label=temp_label,
                            sid=sid,
                            entry_tag=f"rnd__{key}",
                            exit_mode=KEEP_EXIT,
                        )
                    )
        except Exception as e:
            errors.append(f"{sid}:{type(e).__name__}:{e}")

    from scripts.decade_lab_phone_trade_confront import _agg_trades

    by_key = {k: _agg_trades(v) for k, v in bucket.items()}
    lz0 = by_key.get("leave_zero__hi20_or_desync") or {}

    ranking: List[Dict[str, Any]] = []
    for key, st in by_key.items():
        if key.startswith("random__") or key.startswith("leave_zero__"):
            continue
        rnd = by_key.get(f"random__{key}") or {}
        days = int(st.get("n_unique_entry_days") or 0)
        win = float(st.get("win_rate") or np.nan)
        exp = float(st.get("expectancy") or np.nan)
        ok_n = days >= 20
        beats_random = bool(
            ok_n
            and np.isfinite(exp)
            and np.isfinite(rnd.get("expectancy", np.nan))
            and exp > float(rnd["expectancy"])
            and win > float(rnd.get("win_rate") or -1)
        )
        beats_lz = bool(
            ok_n
            and lz0
            and exp > float(lz0.get("expectancy", np.nan))
            and win >= float(lz0.get("win_rate", np.nan)) - 0.005
        )
        parts = key.split("__")
        core = parts[0] if parts else ""
        base = by_key.get(f"{core}__BAL_D0__{KEEP_EXIT}") or {}
        base_win = float(base.get("win_rate") or np.nan) if base else float("nan")
        lifts_core = bool(ok_n and np.isfinite(base_win) and win > base_win + 0.005)
        bscore = _balanced_score(win, days)
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
                "beats_random": beats_random,
                "beats_leave_zero": beats_lz,
                "lifts_core_winrate": lifts_core,
                "core_base_win": base_win if np.isfinite(base_win) else None,
                "win_minus_core": (win - base_win) if ok_n and np.isfinite(base_win) else None,
                "balanced_score": bscore,
                "days_ge40": days >= 40,
                "days_ge50": days >= 50,
            }
        )

    winners = [r for r in ranking if r.get("beats_random") and r.get("beats_leave_zero")]
    lift = [r for r in winners if r.get("lifts_core_winrate")]

    def _sort_bal(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        return sorted(
            rows,
            key=lambda r: (
                float(r.get("balanced_score") or -9),
                float(r.get("win_rate") or -1),
                float(r.get("expectancy") or -9),
                int(r.get("n_unique_entry_days") or 0),
            ),
            reverse=True,
        )

    by_balanced = _sort_bal(winners)
    by_balanced_lift = _sort_bal(lift)
    by_win = sorted(
        [r for r in ranking if int(r.get("n_unique_entry_days") or 0) >= 20],
        key=lambda r: float(r.get("win_rate") or -1),
        reverse=True,
    )
    ge40 = _sort_bal([r for r in winners if r.get("days_ge40")])
    ge50 = _sort_bal([r for r in winners if r.get("days_ge50")])
    cores_d0 = [r for r in ranking if "__BAL_D0__" in r["key"]]

    best_bal = by_balanced_lift[0] if by_balanced_lift else (by_balanced[0] if by_balanced else None)
    gate = (
        f"n={n_universe}; winners={len(winners)}/{len(ranking)}; lift={len(lift)}; "
        f"best_balanced={best_bal['key'] if best_bal else None} "
        f"win={best_bal.get('win_rate') if best_bal else None} "
        f"days={best_bal.get('n_unique_entry_days') if best_bal else None} "
        f"B={best_bal.get('balanced_score') if best_bal else None}; "
        f"ge50={ge50[0]['key'] if ge50 else None}; promote_lookup=NO"
    )
    out = {
        "phone_sync": PHONE_SYNC,
        "not_buy_signal": NOT_BUY_SIGNAL,
        "method_zh": "均衡放大＝近窗量／軟門／計分卡；排序 balanced_score=win×min(1,days/50)",
        "elapsed_s": round(time.time() - t0, 1),
        "n_stocks": meta_n,
        "n_universe_request": n_universe,
        "day_floor": DAY_FLOOR,
        "filter_names": filter_names,
        "leave_zero_baseline": lz0,
        "core_baselines_D0": cores_d0,
        "ranking": ranking,
        "winners_beat_random_and_lz": winners,
        "winners_also_lift_core_winrate": lift,
        "by_balanced_score": by_balanced[:15],
        "by_balanced_score_lift_core": by_balanced_lift[:15],
        "by_winrate_n20": by_win[:15],
        "best_ge40": ge40[:8],
        "best_ge50": ge50[:8],
        "promote_to_lookup_display": False,
        "gate_one_liner": gate,
        "errors_n": len(errors),
        "errors_sample": errors[:8],
    }
    tag = f"n{n_universe}"
    text = json.dumps(out, ensure_ascii=False, indent=2, default=str)
    (ART / f"phone_balanced_enlarge_{tag}_latest.json").write_text(text, encoding="utf-8")
    (DOC / f"phone_balanced_enlarge_{tag}_latest.json").write_text(text, encoding="utf-8")
    (ART / "phone_balanced_enlarge_latest.json").write_text(text, encoding="utf-8")
    (DOC / "phone_balanced_enlarge_latest.json").write_text(text, encoding="utf-8")
    print("GATE", gate, flush=True)
    print(
        "TOP_BALANCED",
        json.dumps(by_balanced_lift[:6] or by_balanced[:6], ensure_ascii=False, default=str)[:2000],
        flush=True,
    )
    print("GE50", json.dumps(ge50[:5], ensure_ascii=False, default=str)[:1200], flush=True)
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=100)
    args = ap.parse_args()
    run_balanced(n_universe=args.n)


if __name__ == "__main__":
    main()
