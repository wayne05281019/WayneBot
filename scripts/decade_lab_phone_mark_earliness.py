# -*- coding: utf-8 -*-
"""查股五張圖買／賣標記「提早量」對質（實驗室；不上話筒）。

目標：密封進場候選相對 leave_zero／ma60_lower_confirmed，量
- 訊號日相對「首碰 20高」賣標提前幾根（bars_before_hi20；無 20高則看 +5d／+10d 前向）
- 命中品質：次日開進、首碰 20高出（重用 _simulate_exits）
- 報 win_rate、獨立日、mean bars_before_hi20、balanced_score

候選：core_w3_start、core_w3_or_ma60w3、bal Vnear|S55、leave_zero、ma60_lower_confirmed

phone_sync=blocked；不准改 wayne_navigator 畫記。
"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

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
from scripts.decade_lab_phone_trade_confront import MAX_HOLD, _agg_trades, _build_hl_temp
from scripts.decade_lab_phone_wave_filter import _align_wave, _wave_frame, _wave_masks
from scripts.decade_lab_phone_winrate_boost import _simulate_exits

PHONE_SYNC = "blocked"
NOT_BUY_SIGNAL = True
ROOT = Path(__file__).resolve().parents[1]
ART = Path("/opt/cursor/artifacts")
DOC = ROOT / "docs" / "expert_notes" / "飆客" / "decade_lab"
DAY_FLOOR = 50
EXIT_MODE = "hi20_only"  # 次日開進 → 首碰 20高出
FWD_HORIZONS = (5, 10)


def _bal(win: float, days: int, floor: int = DAY_FLOOR) -> float:
    if not np.isfinite(win) or days <= 0:
        return float("-inf")
    return float(win) * min(1.0, float(days) / float(floor))


def _hi20_mask(hl: pd.Series) -> pd.Series:
    return hl.astype(str).eq("20高")


def _first_hi20_after(hi20: pd.Series, signal_i: int, *, entry_i: int, max_hold: int) -> Optional[int]:
    """回傳訊號後第一根 20高 的 bar index；須晚於進場日。找不到則 None。"""
    n = len(hi20)
    end = min(n - 1, entry_i + max_hold)
    for j in range(entry_i + 1, end + 1):
        if bool(hi20.iloc[j]):
            return int(j)
    return None


def _fwd_open_to_close(df: pd.DataFrame, signal_i: int, h: int) -> float:
    """次日開 → 訊號後 h 根收（對齊進場再持 h 日的簡化前向）。"""
    n = len(df)
    entry_i = signal_i + 1
    exit_i = signal_i + h
    if entry_i >= n or exit_i >= n:
        return float("nan")
    op = float(df["open"].iloc[entry_i])
    cl = float(df["close"].iloc[exit_i])
    if not (np.isfinite(op) and np.isfinite(cl) and op > 0):
        return float("nan")
    return cl / op - 1.0


def _measure_signal_earliness(
    df: pd.DataFrame,
    entry_mask: pd.Series,
    hl: pd.Series,
    *,
    sid: str,
    entry_tag: str,
) -> List[Dict[str, Any]]:
    """每根訊號量 bars_before_hi20 與 +5d／+10d 前向（不重疊部位，對齊模擬）。"""
    hi20 = _hi20_mask(hl)
    dates = df["date"].astype(str).tolist() if "date" in df.columns else [str(i) for i in range(len(df))]
    n = len(df)
    rows: List[Dict[str, Any]] = []
    i = 0
    while i < n - 2:
        if not bool(entry_mask.iloc[i]):
            i += 1
            continue
        entry_i = i + 1
        if entry_i >= n - 1:
            break
        hi_j = _first_hi20_after(hi20, i, entry_i=entry_i, max_hold=MAX_HOLD)
        bars_before = float(hi_j - i) if hi_j is not None else float("nan")
        row: Dict[str, Any] = {
            "sid": sid,
            "entry_tag": entry_tag,
            "signal_i": int(i),
            "entry_i": int(entry_i),
            "signal_date": dates[i],
            "entry_date": dates[entry_i],
            "bars_before_hi20": bars_before,
            "hit_hi20": hi_j is not None,
            "hi20_date": dates[hi_j] if hi_j is not None else None,
        }
        for h in FWD_HORIZONS:
            row[f"fwd_ret_{h}d"] = _fwd_open_to_close(df, i, h)
        rows.append(row)
        # 對齊 _simulate_exits：出場後才接下一個訊號
        if hi_j is not None:
            i = min(n - 1, hi_j + 1) + 1  # exit at hi_j+1, then next
        else:
            i = min(n - 1, entry_i + MAX_HOLD) + 1
    return rows


def _agg_earliness(rows: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    if not rows:
        return {
            "n_signals": 0,
            "n_unique_signal_days": 0,
            "hit_hi20_rate": float("nan"),
            "mean_bars_before_hi20": float("nan"),
            "median_bars_before_hi20": float("nan"),
            "mean_fwd_ret_5d": float("nan"),
            "mean_fwd_ret_10d": float("nan"),
        }
    bars = np.asarray([float(r["bars_before_hi20"]) for r in rows], dtype=float)
    hit = bars[np.isfinite(bars)]
    days = {r["signal_date"] for r in rows}
    f5 = np.asarray([float(r.get("fwd_ret_5d", np.nan)) for r in rows], dtype=float)
    f10 = np.asarray([float(r.get("fwd_ret_10d", np.nan)) for r in rows], dtype=float)
    return {
        "n_signals": len(rows),
        "n_unique_signal_days": len(days),
        "hit_hi20_rate": float(np.mean(np.isfinite(bars))),
        "mean_bars_before_hi20": float(np.mean(hit)) if len(hit) else float("nan"),
        "median_bars_before_hi20": float(np.median(hit)) if len(hit) else float("nan"),
        "mean_fwd_ret_5d": float(np.nanmean(f5)) if np.isfinite(f5).any() else float("nan"),
        "mean_fwd_ret_10d": float(np.nanmean(f10)) if np.isfinite(f10).any() else float("nan"),
        "n_hit_hi20": int(len(hit)),
    }


def _candidate_masks(
    *,
    masks: Dict[str, pd.Series],
    cores: Dict[str, pd.Series],
    bank: Dict[str, pd.Series],
    idx,
) -> Dict[str, pd.Series]:
    V = bank["hsiao_V"].fillna(False)
    Vnear = _near(V, 3)
    S55 = bank["score55"].fillna(False)
    core_or = cores["core_w3_or_ma60w3"].fillna(False)
    return {
        "core_w3_start": cores["core_w3_start"].fillna(False),
        "core_w3_or_ma60w3": core_or,
        "bal_Vnear_or_S55": core_or & (Vnear | S55),
        "leave_zero": _bool(masks.get("leave_zero_blue_tri"), idx),
        "ma60_lower_confirmed": _bool(masks.get("ma60_lower_confirmed"), idx),
    }


def run(*, n_universe: int = 100) -> Dict[str, Any]:
    t0 = time.time()
    ART.mkdir(parents=True, exist_ok=True)
    DOC.mkdir(parents=True, exist_ok=True)

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
            masks = _build_mark_masks(df)
            cores = _cores(masks, wmasks, feat)
            bank = _wave_hsiao_bank(feat, wmasks, wave)
            hl, temp = _build_hl_temp(df)
            seed = abs(hash(sid)) % (2**32)
            cands = _candidate_masks(masks=masks, cores=cores, bank=bank, idx=df.index)
            pool = (
                cores["core_w3_or_ma60w3"].fillna(False)
                | cores["core_w3_start"].fillna(False)
                | cands["leave_zero"]
                | cands["ma60_lower_confirmed"]
            )
            if int(pool.sum()) < 5:
                pool = pd.Series(True, index=df.index)

            for key, em in cands.items():
                entry = em.fillna(False)
                trade_bucket.setdefault(key, []).extend(
                    _simulate_exits(
                        df,
                        entry,
                        hl=hl,
                        temp_label=temp,
                        sid=sid,
                        entry_tag=key,
                        exit_mode=EXIT_MODE,
                    )
                )
                early_bucket.setdefault(key, []).extend(
                    _measure_signal_earliness(df, entry, hl, sid=sid, entry_tag=key)
                )
                rnd = _random_matched(entry, pool, seed=seed + len(key))
                rkey = f"random__{key}"
                trade_bucket.setdefault(rkey, []).extend(
                    _simulate_exits(
                        df,
                        rnd,
                        hl=hl,
                        temp_label=temp,
                        sid=sid,
                        entry_tag=rkey,
                        exit_mode=EXIT_MODE,
                    )
                )
                early_bucket.setdefault(rkey, []).extend(
                    _measure_signal_earliness(df, rnd, hl, sid=sid, entry_tag=rkey)
                )
        except Exception as e:
            errors.append(f"{sid}:{type(e).__name__}:{e}")

    by_trade = {k: _agg_trades(v) for k, v in trade_bucket.items()}
    by_early = {k: _agg_earliness(v) for k, v in early_bucket.items()}

    lz0 = by_trade.get("leave_zero") or {}
    lz0_e = by_early.get("leave_zero") or {}
    ma0 = by_trade.get("ma60_lower_confirmed") or {}
    ma0_e = by_early.get("ma60_lower_confirmed") or {}

    ranking: List[Dict[str, Any]] = []
    for key in (
        "core_w3_start",
        "core_w3_or_ma60w3",
        "bal_Vnear_or_S55",
        "leave_zero",
        "ma60_lower_confirmed",
    ):
        st = by_trade.get(key) or {}
        er = by_early.get(key) or {}
        rnd = by_trade.get(f"random__{key}") or {}
        rnd_e = by_early.get(f"random__{key}") or {}
        days = int(st.get("n_unique_entry_days") or 0)
        win = float(st.get("win_rate") or np.nan)
        exp = float(st.get("expectancy") or np.nan)
        ok = days >= 20
        mean_bars = float(er.get("mean_bars_before_hi20") or np.nan)
        beats_r = bool(
            ok
            and np.isfinite(exp)
            and np.isfinite(rnd.get("expectancy", np.nan))
            and exp > float(rnd["expectancy"])
            and win > float(rnd.get("win_rate") or -1)
        )
        lz_win = float(lz0.get("win_rate") or np.nan)
        beats_lz = bool(ok and np.isfinite(win) and np.isfinite(lz_win) and win > lz_win + 0.005)
        ranking.append(
            {
                "key": key,
                "n_trades": st.get("n_trades"),
                "n_unique_entry_days": days,
                "win_rate": win,
                "expectancy": exp,
                "avg_hold": st.get("avg_hold"),
                "exit_reason_counts": st.get("exit_reason_counts"),
                "mean_bars_before_hi20": mean_bars,
                "median_bars_before_hi20": er.get("median_bars_before_hi20"),
                "hit_hi20_rate": er.get("hit_hi20_rate"),
                "mean_fwd_ret_5d": er.get("mean_fwd_ret_5d"),
                "mean_fwd_ret_10d": er.get("mean_fwd_ret_10d"),
                "n_signals": er.get("n_signals"),
                "random_win_rate": rnd.get("win_rate"),
                "random_expectancy": rnd.get("expectancy"),
                "random_mean_bars_before_hi20": rnd_e.get("mean_bars_before_hi20"),
                "beats_random": beats_r,
                "beats_leave_zero": beats_lz,
                "balanced_score": _bal(win, days) if ok else float("-inf"),
                "days_ge20": ok,
            }
        )

    winners = [r for r in ranking if r["days_ge20"] and r["beats_random"]]
    # 提早：mean bars_before_hi20 愈大＝買標相對賣標愈早
    earliest = sorted(
        [r for r in winners if np.isfinite(float(r.get("mean_bars_before_hi20") or np.nan))],
        key=lambda r: float(r["mean_bars_before_hi20"]),
        reverse=True,
    )
    by_bal = sorted(
        winners,
        key=lambda r: (float(r.get("balanced_score") or -9), float(r.get("win_rate") or -1)),
        reverse=True,
    )
    by_win = sorted(
        [r for r in ranking if r["days_ge20"]],
        key=lambda r: float(r.get("win_rate") or -1),
        reverse=True,
    )

    earliest_key = earliest[0]["key"] if earliest else None
    gate = (
        f"mark_earliness winners={len(winners)}/{len(ranking)}; "
        f"earliest_n20={earliest_key} "
        f"bars={earliest[0].get('mean_bars_before_hi20') if earliest else None} "
        f"win={earliest[0].get('win_rate') if earliest else None} "
        f"days={earliest[0].get('n_unique_entry_days') if earliest else None}; "
        f"best_bal={by_bal[0]['key'] if by_bal else None}; "
        f"phone_sync=blocked; promote_lookup=NO"
    )

    out: Dict[str, Any] = {
        "phone_sync": PHONE_SYNC,
        "not_buy_signal": NOT_BUY_SIGNAL,
        "method_zh": "買標提早量＝訊號到首碰20高根數；命中＝次日開進／首碰20高出（hi20_only）",
        "buy_lock_zh": "波浪起漲／均衡核／現況藍▲／確認紅箭",
        "sell_lock_zh": "相對高點＝首碰20高",
        "exit_mode": EXIT_MODE,
        "candidates": [
            "core_w3_start",
            "core_w3_or_ma60w3",
            "bal_Vnear_or_S55",
            "leave_zero",
            "ma60_lower_confirmed",
        ],
        "elapsed_s": round(time.time() - t0, 1),
        "n_stocks": meta_n,
        "n_universe": n_universe,
        "ranking": ranking,
        "winners_n20_beats_random": winners,
        "earliest_among_winners": earliest[:5],
        "earliest_mark_key": earliest_key,
        "by_balanced_score": by_bal[:10],
        "by_winrate_n20": by_win[:10],
        "leave_zero_baseline": {**lz0, **{f"early_{k}": v for k, v in lz0_e.items()}},
        "ma60_lower_baseline": {**ma0, **{f"early_{k}": v for k, v in ma0_e.items()}},
        "promote_to_lookup_display": False,
        "gate_one_liner": gate,
        "errors_n": len(errors),
        "errors_sample": errors[:8],
    }

    text = json.dumps(out, ensure_ascii=False, indent=2, default=str)
    (ART / "phone_mark_earliness_latest.json").write_text(text, encoding="utf-8")
    (DOC / "phone_mark_earliness_latest.json").write_text(text, encoding="utf-8")
    md = (
        "# phone_mark_earliness\n\n"
        f"- gate: `{gate}`\n"
        f"- earliest among n≥20 winners: `{earliest_key}`\n"
        f"- phone_sync: `{PHONE_SYNC}`\n"
    )
    (DOC / "phone_mark_earliness_latest.md").write_text(md, encoding="utf-8")
    (ART / "phone_mark_earliness_latest.md").write_text(md, encoding="utf-8")
    print("GATE", gate, flush=True)
    print("EARLIEST", json.dumps(earliest[:3], ensure_ascii=False, default=str)[:1200], flush=True)
    print("RANK", json.dumps(ranking, ensure_ascii=False, default=str)[:2000], flush=True)
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=100)
    args = ap.parse_args()
    run(n_universe=args.n)


if __name__ == "__main__":
    main()
