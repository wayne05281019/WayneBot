# -*- coding: utf-8 -*-
"""mix_v25 後：結構出場壓 hold＋買側 bars 再提早。

v25：pe2 父鎖穩；pe16/ATR 更早但不 beats_random；giveback 胜率崩。
本輪賣：pe2＋收破 MA5／MA10、雙低點、max_hold 帽。
本輪買：intent/week near 窗微調衝 bars_before_hi20，保 ge80×50d。
phone_sync=blocked。
"""
from __future__ import annotations

import json
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Tuple
from zoneinfo import ZoneInfo

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
MAX_HOLD = 60
PARENT_HOLD = 13.058823529411764
PARENT_BARS = 15.86


def _bal(w: float, d: int) -> float:
    if not np.isfinite(w) or d <= 0:
        return float("-inf")
    return float(w) * min(1.0, d / 50.0)


def _sim_struct(
    df,
    entry_mask,
    *,
    hl,
    temp_label,
    sid,
    entry_tag,
    wave_top,
    early_sell,
    min_profit: float,
    ma_break: pd.Series | None = None,
    dual_lh: bool = False,
    max_hold: int = MAX_HOLD,
):
    n = len(df)
    dates = df["date"].astype(str).tolist() if "date" in df.columns else [str(i) for i in range(n)]
    o = df["open"].astype(float)
    c = df["close"].astype(float)
    h = df["high"].astype(float)
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
        prev_highs: List[float] = []
        for j in range(entry_i, min(n - 1, entry_i + max_hold) + 1):
            hl_j = str(hl.iloc[j]) if j < len(hl) else ""
            px = float(c.iloc[j])
            hi = float(h.iloc[j])
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
            if ma_break is not None and unreal >= min_profit and bool(ma_break.iloc[j]):
                exit_j, reason = j, "ma_break"
                break
            if dual_lh and unreal >= min_profit:
                prev_highs.append(hi)
                if len(prev_highs) >= 3 and prev_highs[-1] < prev_highs[-2] < prev_highs[-3]:
                    exit_j, reason = j, "dual_lower_high"
                    break
        if exit_j is None:
            exit_j, reason = min(n - 1, entry_i + max_hold), f"max_hold_{max_hold}"
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


def run() -> Dict[str, Any]:
    t0 = time.time()
    ART.mkdir(parents=True, exist_ok=True)
    DOC.mkdir(parents=True, exist_ok=True)
    _, mkt_raw = _twii_wave_pack(entry_preset="A0_strict", score_threshold=40.0)
    uni = select_g_universe(n=150, include_twse_top100=True, min_avg_turnover_k=1_500_000.0)
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
            ei_n5 = w3u & _near(turn, 3) & t60 & _near(intent, 5) & risk
            v11 = ei_n5 & (_near(week, 3) | _near(body, 3))
            nobody = v11 & (~body)
            body_only = v11 & body
            add_i3 = nobody | (body_only & _near(intent, 3))
            # buy variants
            buy_i6 = w3u & _near(turn, 3) & t60 & _near(intent, 6) & risk & (_near(week, 3) | _near(body, 3))
            buy_w4 = ei_n5 & (_near(week, 4) | _near(body, 3))
            buy_w2 = ei_n5 & (_near(week, 2) | _near(body, 2))
            buy_turn2 = w3u & _near(turn, 2) & t60 & _near(intent, 5) & risk & (_near(week, 3) | _near(body, 3))
            wave_top = (
                ev.get("LAB_W1_TOP", pd.Series(False, index=idx))
                | ev.get("LAB_W3_TOP", pd.Series(False, index=idx))
                | ev.get("LAB_SELL_W5_TOP", pd.Series(False, index=idx))
            ).fillna(False)
            h = df["high"].astype(float)
            c = df["close"].astype(float)
            hi10 = h.rolling(10, min_periods=5).max()
            exhaust = feat.get("is_exhaustion_vol")
            exhaust = exhaust.reindex(idx).fillna(False).astype(bool) if exhaust is not None else pd.Series(False, index=idx)
            early_or = exhaust | (h >= hi10.shift(1))
            ma5 = c.rolling(5, min_periods=3).mean()
            ma10 = c.rolling(10, min_periods=5).mean()
            br_ma5 = c < ma5
            br_ma10 = c < ma10

            # sell specs on add_i3
            sell_specs: List[Tuple[str, dict]] = [
                ("sell_pe2", {"early_sell": early_or, "min_profit": 0.02}),
                ("sell_pe2_ma5", {"early_sell": early_or, "min_profit": 0.02, "ma_break": br_ma5}),
                ("sell_pe2_ma10", {"early_sell": early_or, "min_profit": 0.02, "ma_break": br_ma10}),
                ("sell_pe2_lh", {"early_sell": early_or, "min_profit": 0.02, "dual_lh": True}),
                ("sell_pe2_mh40", {"early_sell": early_or, "min_profit": 0.02, "max_hold": 40}),
                ("sell_pe2_mh35", {"early_sell": early_or, "min_profit": 0.02, "max_hold": 35}),
                ("sell_pe2_mh30", {"early_sell": early_or, "min_profit": 0.02, "max_hold": 30}),
                ("sell_pe2_ma5_mh40", {"early_sell": early_or, "min_profit": 0.02, "ma_break": br_ma5, "max_hold": 40}),
                ("sell_pe18_ma5", {"early_sell": early_or, "min_profit": 0.018, "ma_break": br_ma5}),
            ]
            for cn, kw in sell_specs:
                trades = _sim_struct(df, add_i3, hl=hl, temp_label=temp, sid=sid, entry_tag=cn, wave_top=wave_top, **kw)
                trade_bucket.setdefault(cn, []).extend(trades)
                early_bucket.setdefault(cn, []).extend(_measure_signal_earliness(df, add_i3, hl, sid=sid, entry_tag=cn))
                pool = w3u if int(w3u.sum()) >= 5 else pd.Series(True, index=idx)
                rnd = _random_matched(add_i3, pool, seed=seed + len(cn))
                trade_bucket.setdefault(f"random__{cn}", []).extend(
                    _sim_struct(df, rnd, hl=hl, temp_label=temp, sid=sid, entry_tag=f"random__{cn}", wave_top=wave_top, **kw)
                )

            # buy specs: hi20 exit (earliness vs win)
            buy_specs = [
                ("buy_v11_hi20", v11),
                ("buy_i6_hi20", buy_i6),
                ("buy_w4_hi20", buy_w4),
                ("buy_w2_hi20", buy_w2),
                ("buy_turn2_hi20", buy_turn2),
                ("buy_add_i3_hi20", add_i3),
            ]
            for cn, entry in buy_specs:
                trades = _simulate_relhigh(
                    df, entry, hl=hl, temp_label=temp, sid=sid, entry_tag=cn, wave_top=wave_top, mode="hi20_or_wave_top"
                )
                trade_bucket.setdefault(cn, []).extend(trades)
                early_bucket.setdefault(cn, []).extend(_measure_signal_earliness(df, entry, hl, sid=sid, entry_tag=cn))
                pool = w3u if int(w3u.sum()) >= 5 else pd.Series(True, index=idx)
                rnd = _random_matched(entry, pool, seed=seed + 1000 + len(cn))
                trade_bucket.setdefault(f"random__{cn}", []).extend(
                    _simulate_relhigh(
                        df, rnd, hl=hl, temp_label=temp, sid=sid, entry_tag=f"random__{cn}", wave_top=wave_top, mode="hi20_or_wave_top"
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
                "earlier_sell": bool(key.startswith("sell_") and np.isfinite(hold) and hold < PARENT_HOLD - 0.05),
                "earlier_buy": bool(key.startswith("buy_") and np.isfinite(bars) and bars > PARENT_BARS + 0.2),
            }
        )

    sell_ok = [
        r
        for r in ranking
        if r["key"].startswith("sell_") and r.get("win_ge80") and r.get("days_ge50") and r.get("beats_random")
    ]
    sell_ok = sorted(sell_ok, key=lambda r: (float(r.get("mean_hold_days") or 99), -float(r.get("win_rate") or 0)))
    sell_earlier = [r for r in sell_ok if r.get("earlier_sell")]
    buy_ok = [
        r
        for r in ranking
        if r["key"].startswith("buy_") and r.get("win_ge80") and r.get("days_ge50") and r.get("beats_random")
    ]
    buy_ok = sorted(buy_ok, key=lambda r: (-float(r.get("mean_bars_before_hi20") or 0), -float(r.get("win_rate") or 0)))
    buy_earlier = [r for r in buy_ok if r.get("earlier_buy")]

    gate = (
        f"spirit_mix_thicken_v26 U112 n={meta_n} "
        f"sell_ge80_d50={len(sell_ok)} sell_earlier={len(sell_earlier)} "
        f"best_sell={sell_earlier[0]['key'] if sell_earlier else (sell_ok[0]['key'] if sell_ok else None)} "
        f"hold={sell_earlier[0].get('mean_hold_days') if sell_earlier else (sell_ok[0].get('mean_hold_days') if sell_ok else None)}; "
        f"buy_ge80_d50={len(buy_ok)} buy_earlier={len(buy_earlier)} "
        f"best_buy={buy_earlier[0]['key'] if buy_earlier else (buy_ok[0]['key'] if buy_ok else None)} "
        f"bars={buy_earlier[0].get('mean_bars_before_hi20') if buy_earlier else (buy_ok[0].get('mean_bars_before_hi20') if buy_ok else None)}; "
        f"promote_lookup=NO"
    )
    now = datetime.now(ZoneInfo("Asia/Taipei")).isoformat()
    out = {
        "phone_sync": PHONE_SYNC,
        "promote_to_lookup_display": False,
        "user_goal_zh": "v26：結構出場壓 hold＋買側 bars",
        "parent_seal": "phone_spirit_mix_thicken_v25_decision.json",
        "elapsed_s": round(time.time() - t0, 1),
        "n_stocks": meta_n,
        "ranking": ranking,
        "sell_ok": sell_ok[:12],
        "sell_earlier": sell_earlier[:8],
        "buy_ok": buy_ok[:12],
        "buy_earlier": buy_earlier[:8],
        "gate_one_liner": gate,
        "as_of_taipei": now,
        "errors_n": len(errors),
        "errors_sample": errors[:8],
    }
    text = json.dumps(out, ensure_ascii=False, indent=2, default=str)
    (ART / "phone_spirit_mix_thicken_v26_latest.json").write_text(text, encoding="utf-8")
    (DOC / "phone_spirit_mix_thicken_v26_latest.json").write_text(text, encoding="utf-8")
    print("GATE", gate, flush=True)
    print("SELL_EARLIER", json.dumps(sell_earlier[:6], ensure_ascii=False, default=str)[:1200], flush=True)
    print("BUY_EARLIER", json.dumps(buy_earlier[:6], ensure_ascii=False, default=str)[:1200], flush=True)
    print("SELL_OK", json.dumps(sell_ok[:6], ensure_ascii=False, default=str)[:1000], flush=True)
    print("BUY_OK", json.dumps(buy_ok[:6], ensure_ascii=False, default=str)[:1000], flush=True)
    return out


def main() -> None:
    run()


if __name__ == "__main__":
    main()
