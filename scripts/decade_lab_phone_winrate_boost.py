# -*- coding: utf-8 -*-
"""圍繞已過關組合再加強勝率（雲端實驗室；不上話筒、不畫浪號）。

核心候選（上一跑 winners）：
- ma60_lower × W3 區
- 純 W3 起漲
本腳本在其上加結構／量能／共振／出場變體，目標：勝率↑且仍贏同密度隨機＋leave_zero。
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from scripts.decade_lab_chart_marks_stats import _build_mark_masks, _normalize_ohlc
from scripts.decade_lab_hsiao_universe import MUST_INCLUDE, load_stock_ohlcv, select_g_universe
from scripts.decade_lab_phone_entry_tighten import _feature_frame, _random_matched
from scripts.decade_lab_phone_trade_confront import (
    FRICTION,
    GIVEBACK,
    MAX_HOLD,
    _agg_trades,
    _build_hl_temp,
)
from scripts.decade_lab_phone_wave_filter import _align_wave, _wave_frame, _wave_masks

PHONE_SYNC = "blocked"
NOT_BUY_SIGNAL = True
ROOT = Path(__file__).resolve().parents[1]
ART = Path("/opt/cursor/artifacts")
DOC = ROOT / "docs" / "expert_notes" / "飆客" / "decade_lab"


def _simulate_exits(
    df: pd.DataFrame,
    entry_mask: pd.Series,
    *,
    hl: pd.Series,
    temp_label: pd.Series,
    sid: str,
    entry_tag: str,
    exit_mode: str = "hi20_then_giveback",
) -> List[Dict[str, Any]]:
    """出場變體：
    - hi20_then_giveback：首碰20高優先，否則回吐／60日（原版）
    - hi20_only：只等首碰20高，否則60日（不加回吐）
    - hi20_or_desync：首碰20高或如何賣直接減碼
    - giveback_only：只用回吐／60日（對照）
    """
    from sell_discipline import classify_how_to_sell

    cl = df["close"].astype(float)
    op = df["open"].astype(float)
    lo = df["low"].astype(float)
    hi = df["high"].astype(float)
    dates = df["date"].astype(str).tolist() if "date" in df.columns else [str(i) for i in range(len(df))]
    n = len(df)
    trades: List[Dict[str, Any]] = []
    i = 0
    while i < n - 2:
        if not bool(entry_mask.iloc[i]):
            i += 1
            continue
        entry_i = i + 1
        if entry_i >= n - 1:
            break
        entry_px = float(op.iloc[entry_i])
        if not (np.isfinite(entry_px) and entry_px > 0):
            i += 1
            continue
        peak = entry_px
        trough = entry_px
        exit_i = None
        exit_reason = None
        for j in range(entry_i, min(n - 1, entry_i + MAX_HOLD)):
            c = float(cl.iloc[j])
            h = float(hi.iloc[j])
            l = float(lo.iloc[j])
            if np.isfinite(h):
                peak = max(peak, h)
            if np.isfinite(l):
                trough = min(trough, l)
            hl_j = str(hl.iloc[j] or "")
            if j > entry_i:
                if exit_mode in ("hi20_then_giveback", "hi20_only", "hi20_or_desync") and hl_j == "20高":
                    exit_i = j + 1
                    exit_reason = "first_hi20"
                    break
                if exit_mode == "hi20_or_desync":
                    flags = classify_how_to_sell(hl.iloc[j], temp_label.iloc[j])
                    if str(flags.get("sell_action") or "") == "直接減碼":
                        exit_i = j + 1
                        exit_reason = "sell_desync_cut"
                        break
                if exit_mode in ("hi20_then_giveback", "giveback_only"):
                    if peak > 0 and np.isfinite(c) and c <= peak * (1.0 - GIVEBACK):
                        exit_i = j + 1
                        exit_reason = "giveback_8pct"
                        break
        if exit_i is None:
            exit_i = min(n - 1, entry_i + MAX_HOLD)
            exit_reason = "max_hold_60"
        if exit_i >= n:
            exit_i = n - 1
        if exit_reason == "max_hold_60":
            exit_px = float(cl.iloc[exit_i])
        else:
            exit_px = float(op.iloc[exit_i]) if np.isfinite(op.iloc[exit_i]) else float(cl.iloc[exit_i])
        if not (np.isfinite(exit_px) and exit_px > 0):
            i = max(i + 1, exit_i)
            continue
        gross = exit_px / entry_px - 1.0
        net = gross - FRICTION
        trades.append(
            {
                "sid": sid,
                "entry_tag": entry_tag,
                "entry_signal_date": dates[i],
                "entry_date": dates[entry_i],
                "exit_date": dates[exit_i],
                "exit_reason": exit_reason,
                "hold_days": int(exit_i - entry_i),
                "gross_ret": gross,
                "net_ret": net,
                "win": 1 if net > 0 else 0,
                "mfe": peak / entry_px - 1.0,
                "mae": trough / entry_px - 1.0,
            }
        )
        i = exit_i + 1
    return trades


def _variants() -> List[Tuple[str, str, str]]:
    """(key, entry_kind, exit_mode)"""
    kinds = [
        "ma60_w3",
        "ma60_w3_vol",
        "ma60_w3_score",
        "ma60_w3_vol_score",
        "w3_start",
        "w3_start_vol",
        "w3_start_or_ma60_w3",
        "lz_near_ma60_w3",  # leave_zero 附近紅箭且 W3 區（更稀）
    ]
    exits = ["hi20_then_giveback", "hi20_only", "hi20_or_desync"]
    out = []
    for k in kinds:
        for ex in exits:
            out.append((f"{k}__{ex}", k, ex))
    return out


def _entry_mask(
    kind: str,
    *,
    masks: Dict[str, pd.Series],
    wmasks: Dict[str, pd.Series],
    feat: pd.DataFrame,
) -> pd.Series:
    ma60 = masks.get("ma60_lower_confirmed", pd.Series(False, index=feat.index)).fillna(False)
    lz = masks.get("leave_zero_blue_tri", pd.Series(False, index=feat.index)).fillna(False)
    w3z = wmasks.get("W_w3_zone", pd.Series(False, index=feat.index)).fillna(False)
    w3s = wmasks.get("W_w3_start", pd.Series(False, index=feat.index)).fillna(False)
    score = wmasks.get("W_score50", pd.Series(False, index=feat.index)).fillna(False)
    vol = feat["vol_ok"].fillna(False)
    room = feat["room_to_hi20"].fillna(False)

    near = ma60.copy()
    for k in range(1, 6):
        near = near | ma60.shift(k).fillna(False) | ma60.shift(-k).fillna(False)

    if kind == "ma60_w3":
        return ma60 & w3z & room
    if kind == "ma60_w3_vol":
        return ma60 & w3z & vol & room
    if kind == "ma60_w3_score":
        return ma60 & w3z & score & room
    if kind == "ma60_w3_vol_score":
        return ma60 & w3z & vol & score & room
    if kind == "w3_start":
        return w3s & room
    if kind == "w3_start_vol":
        return w3s & vol & room
    if kind == "w3_start_or_ma60_w3":
        return ((w3s) | (ma60 & w3z)) & room
    if kind == "lz_near_ma60_w3":
        return lz & near & w3z & vol & room
    return pd.Series(False, index=feat.index)


def run_boost(*, n_universe: int = 100) -> Dict[str, Any]:
    t0 = time.time()
    ART.mkdir(parents=True, exist_ok=True)
    DOC.mkdir(parents=True, exist_ok=True)
    uni = select_g_universe(n=n_universe, include_twse_top100=True)
    symbols = uni["stock_id"].astype(str).tolist()
    for sid in MUST_INCLUDE:
        if sid not in symbols:
            symbols.append(sid)

    variants = _variants()
    bucket: Dict[str, List[Dict[str, Any]]] = {}
    # baseline leave_zero F0 with default exit
    bucket["leave_zero__hi20_then_giveback"] = []
    bucket["random__leave_zero__hi20_then_giveback"] = []
    meta_n = 0
    errors: List[str] = []

    for sid in symbols:
        try:
            raw = load_stock_ohlcv(sid)
            if len(raw) < 150:
                continue
            meta_n += 1
            df = _normalize_ohlc(raw)
            wave = _align_wave(df, _wave_frame(raw))
            wmasks = _wave_masks(wave)
            masks = _build_mark_masks(df)
            feat = _feature_frame(df)
            hl, temp_label = _build_hl_temp(df)
            seed = abs(hash(sid)) % (2**32)

            lz = masks.get("leave_zero_blue_tri", pd.Series(False, index=df.index)).fillna(False)
            lz_entry = lz & feat["room_to_hi20"].fillna(False)
            bucket["leave_zero__hi20_then_giveback"].extend(
                _simulate_exits(
                    df,
                    lz_entry,
                    hl=hl,
                    temp_label=temp_label,
                    sid=sid,
                    entry_tag="leave_zero",
                    exit_mode="hi20_then_giveback",
                )
            )
            rnd0 = _random_matched(lz_entry, feat["room_to_hi20"].fillna(False), seed=seed)
            bucket["random__leave_zero__hi20_then_giveback"].extend(
                _simulate_exits(
                    df,
                    rnd0,
                    hl=hl,
                    temp_label=temp_label,
                    sid=sid,
                    entry_tag="random_lz",
                    exit_mode="hi20_then_giveback",
                )
            )

            for key, kind, exit_mode in variants:
                entry = _entry_mask(kind, masks=masks, wmasks=wmasks, feat=feat)
                bucket.setdefault(key, []).extend(
                    _simulate_exits(
                        df,
                        entry,
                        hl=hl,
                        temp_label=temp_label,
                        sid=sid,
                        entry_tag=key,
                        exit_mode=exit_mode,
                    )
                )
                # 隨機對照：在「同結構母體」抽（W3區或W3起漲 ∪ room）
                if "w3_start" in kind and "ma60" not in kind:
                    pool = wmasks["W_w3_start"].fillna(False) | feat["room_to_hi20"].fillna(False)
                else:
                    pool = wmasks["W_w3_zone"].fillna(False) | wmasks["W_w3_start"].fillna(False)
                    pool = pool & feat["room_to_hi20"].fillna(False)
                if int(pool.sum()) < 5:
                    pool = feat["room_to_hi20"].fillna(False)
                rnd = _random_matched(entry, pool, seed=seed + len(key))
                bucket.setdefault(f"random__{key}", []).extend(
                    _simulate_exits(
                        df,
                        rnd,
                        hl=hl,
                        temp_label=temp_label,
                        sid=sid,
                        entry_tag=f"random__{key}",
                        exit_mode=exit_mode,
                    )
                )
        except Exception as e:
            errors.append(f"{sid}:{type(e).__name__}:{e}")

    by_key = {k: _agg_trades(v) for k, v in bucket.items()}
    lz0 = by_key.get("leave_zero__hi20_then_giveback") or {}

    ranking = []
    for key, st in by_key.items():
        if key.startswith("random__") or key.startswith("leave_zero__"):
            continue
        rnd = by_key.get(f"random__{key}") or {}
        days = int(st.get("n_unique_entry_days") or 0)
        ok_n = days >= 20
        beats_random = bool(
            ok_n
            and np.isfinite(st.get("expectancy", np.nan))
            and np.isfinite(rnd.get("expectancy", np.nan))
            and float(st["expectancy"]) > float(rnd["expectancy"])
            and float(st["win_rate"]) > float(rnd["win_rate"])
        )
        beats_lz = bool(
            ok_n
            and lz0
            and float(st.get("expectancy", np.nan)) > float(lz0.get("expectancy", np.nan))
            and float(st.get("win_rate", np.nan)) >= float(lz0.get("win_rate", np.nan)) - 0.005
        )
        ranking.append(
            {
                "key": key,
                "n_trades": st.get("n_trades"),
                "n_unique_entry_days": days,
                "win_rate": st.get("win_rate"),
                "expectancy": st.get("expectancy"),
                "avg_hold": st.get("avg_hold"),
                "exit_reason_counts": st.get("exit_reason_counts"),
                "random_win_rate": rnd.get("win_rate"),
                "random_expectancy": rnd.get("expectancy"),
                "beats_random": beats_random,
                "beats_leave_zero": beats_lz,
                "E_minus_random": (
                    float(st["expectancy"]) - float(rnd["expectancy"])
                    if ok_n
                    and np.isfinite(st.get("expectancy", np.nan))
                    and np.isfinite(rnd.get("expectancy", np.nan))
                    else float("nan")
                ),
                "win_minus_lz": (
                    float(st["win_rate"]) - float(lz0["win_rate"])
                    if ok_n and lz0 and np.isfinite(st.get("win_rate", np.nan))
                    else float("nan")
                ),
            }
        )

    ranking.sort(
        key=lambda r: (
            int(r.get("beats_random") or 0),
            int(r.get("beats_leave_zero") or 0),
            float(r.get("win_rate") or -1),
            float(r.get("expectancy") or -9),
        ),
        reverse=True,
    )
    winners = [r for r in ranking if r.get("beats_random") and r.get("beats_leave_zero")]
    # 勝率榜（n≥20）
    by_win = sorted(
        [r for r in ranking if int(r.get("n_unique_entry_days") or 0) >= 20],
        key=lambda r: (float(r.get("win_rate") or -1), float(r.get("expectancy") or -9)),
        reverse=True,
    )

    gate = (
        f"winners={len(winners)}/{len(ranking)}; "
        f"best_win={by_win[0]['key'] if by_win else None} "
        f"win={by_win[0].get('win_rate') if by_win else None} "
        f"E={by_win[0].get('expectancy') if by_win else None}; "
        f"promote_lookup=NO"
    )
    out = {
        "phone_sync": PHONE_SYNC,
        "not_buy_signal": NOT_BUY_SIGNAL,
        "elapsed_s": round(time.time() - t0, 1),
        "n_stocks": meta_n,
        "leave_zero_baseline": lz0,
        "ranking": ranking,
        "by_winrate_n20": by_win[:12],
        "winners_beat_random_and_lz": winners,
        "promote_to_lookup_display": False,
        "gate_one_liner": gate,
        "errors_n": len(errors),
        "errors_sample": errors[:8],
        "note_zh": "圍繞 W3／確認紅箭加結構與出場變體；不過閘不上查股浪號",
    }
    text = json.dumps(out, ensure_ascii=False, indent=2, default=str)
    (ART / "phone_winrate_boost_latest.json").write_text(text, encoding="utf-8")
    (DOC / "phone_winrate_boost_latest.json").write_text(text, encoding="utf-8")
    print("GATE", gate, flush=True)
    print("WINNERS", len(winners), json.dumps(winners[:5], ensure_ascii=False, default=str), flush=True)
    print("TOP_WIN", json.dumps(by_win[:6], ensure_ascii=False, default=str), flush=True)
    return out


if __name__ == "__main__":
    run_boost()
