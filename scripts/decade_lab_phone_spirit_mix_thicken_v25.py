# -*- coding: utf-8 -*-
"""mix_v24 後：以 add_i3_pe2 為父，續壓 hold（保 ge80×50d×beats_random）。

v24：confirm pe3；升級 pe2 hold≈13.06（pe15 更早但不 beats_random）。
本輪：pe 階梯 1.6–2.5%；early 觸發變體；簡易 ATR／收盤回吐出場。
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


def _bal(w: float, d: int) -> float:
    if not np.isfinite(w) or d <= 0:
        return float("-inf")
    return float(w) * min(1.0, d / 50.0)


def _sim_exit(
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
    giveback: float | None = None,
    atr_mult: float | None = None,
    atr: pd.Series | None = None,
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
        peak = entry_px
        exit_j = None
        reason = "max_hold"
        for j in range(entry_i, min(n - 1, entry_i + MAX_HOLD) + 1):
            hl_j = str(hl.iloc[j]) if j < len(hl) else ""
            px = float(c.iloc[j])
            hi = float(h.iloc[j])
            peak = max(peak, hi)
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
            if giveback is not None and peak > entry_px and px <= peak * (1.0 - giveback) and (peak / entry_px - 1.0) >= min_profit:
                exit_j, reason = j, f"giveback_{giveback:.0%}"
                break
            if atr_mult is not None and atr is not None:
                a = float(atr.iloc[j]) if j < len(atr) and np.isfinite(float(atr.iloc[j])) else float("nan")
                if np.isfinite(a) and a > 0 and px <= entry_px + atr_mult * a and unreal >= min_profit and j > entry_i:
                    # trail: exit when close falls atr_mult ATR below peak after profit
                    if px <= peak - atr_mult * a:
                        exit_j, reason = j, f"atr_trail_{atr_mult}"
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
            wave_top = (
                ev.get("LAB_W1_TOP", pd.Series(False, index=idx))
                | ev.get("LAB_W3_TOP", pd.Series(False, index=idx))
                | ev.get("LAB_SELL_W5_TOP", pd.Series(False, index=idx))
            ).fillna(False)
            h = df["high"].astype(float)
            c = df["close"].astype(float)
            l = df["low"].astype(float)
            hi10 = h.rolling(10, min_periods=5).max()
            exhaust = feat.get("is_exhaustion_vol")
            exhaust = exhaust.reindex(idx).fillna(False).astype(bool) if exhaust is not None else pd.Series(False, index=idx)
            early_or = exhaust | (h >= hi10.shift(1))
            early_ex = exhaust
            early_hi10 = h >= hi10.shift(1)
            prev = c.shift(1)
            tr = pd.concat([(h - l), (h - prev).abs(), (l - prev).abs()], axis=1).max(axis=1)
            atr14 = tr.rolling(14, min_periods=7).mean()

            # specs: name, kind, early_sell, min_profit, giveback, atr_mult
            specs: List[Tuple[str, str, Any, float, float | None, float | None]] = [
                ("v11_hi20", "hi20", None, 0.0, None, None),
                ("add_i3_pe2", "pe", early_or, 0.02, None, None),  # parent lock
                ("add_i3_pe18", "pe", early_or, 0.018, None, None),
                ("add_i3_pe17", "pe", early_or, 0.017, None, None),
                ("add_i3_pe16", "pe", early_or, 0.016, None, None),
                ("add_i3_pe22", "pe", early_or, 0.022, None, None),
                ("add_i3_pe25", "pe", early_or, 0.025, None, None),
                ("add_i3_pe2_ex", "pe", early_ex, 0.02, None, None),
                ("add_i3_pe2_hi10", "pe", early_hi10, 0.02, None, None),
                ("add_i3_pe18_ex", "pe", early_ex, 0.018, None, None),
                ("add_i3_pe2_gb3", "pe", early_or, 0.02, 0.03, None),
                ("add_i3_pe2_gb5", "pe", early_or, 0.02, 0.05, None),
                ("add_i3_pe18_gb3", "pe", early_or, 0.018, 0.03, None),
                ("add_i3_pe2_atr1", "pe", early_or, 0.02, None, 1.0),
                ("add_i3_pe2_atr15", "pe", early_or, 0.02, None, 1.5),
                ("add_i3_pe18_atr1", "pe", early_or, 0.018, None, 1.0),
            ]
            for cn, kind, es, mp, gb, am in specs:
                key = cn
                if kind == "hi20":
                    trades = _simulate_relhigh(
                        df, v11, hl=hl, temp_label=temp, sid=sid, entry_tag=key, wave_top=wave_top, mode="hi20_or_wave_top"
                    )
                    entry_for_early = v11
                else:
                    trades = _sim_exit(
                        df,
                        add_i3,
                        hl=hl,
                        temp_label=temp,
                        sid=sid,
                        entry_tag=key,
                        wave_top=wave_top,
                        early_sell=es,
                        min_profit=mp,
                        giveback=gb,
                        atr_mult=am,
                        atr=atr14,
                    )
                    entry_for_early = add_i3
                trade_bucket.setdefault(key, []).extend(trades)
                early_bucket.setdefault(key, []).extend(
                    _measure_signal_earliness(df, entry_for_early, hl, sid=sid, entry_tag=key)
                )
                pool = w3u if int(w3u.sum()) >= 5 else pd.Series(True, index=idx)
                rnd = _random_matched(entry_for_early, pool, seed=seed + len(key))
                rkey = f"random__{key}"
                if kind == "hi20":
                    trade_bucket.setdefault(rkey, []).extend(
                        _simulate_relhigh(
                            df, rnd, hl=hl, temp_label=temp, sid=sid, entry_tag=rkey, wave_top=wave_top, mode="hi20_or_wave_top"
                        )
                    )
                else:
                    trade_bucket.setdefault(rkey, []).extend(
                        _sim_exit(
                            df,
                            rnd,
                            hl=hl,
                            temp_label=temp,
                            sid=sid,
                            entry_tag=rkey,
                            wave_top=wave_top,
                            early_sell=es,
                            min_profit=mp,
                            giveback=gb,
                            atr_mult=am,
                            atr=atr14,
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
                "earlier_than_parent": bool(np.isfinite(hold) and hold < PARENT_HOLD - 0.05),
            }
        )

    parent = next((r for r in ranking if r["key"] == "add_i3_pe2"), None)
    pe_ok = [
        r
        for r in ranking
        if r["key"] != "v11_hi20" and r.get("win_ge80") and r.get("days_ge50") and r.get("beats_random")
    ]
    pe_ok = sorted(pe_ok, key=lambda r: (float(r.get("mean_hold_days") or 99), -float(r.get("win_rate") or 0)))
    earlier_ok = [r for r in pe_ok if r.get("earlier_than_parent")]
    gate = (
        f"spirit_mix_thicken_v25 U112 n={meta_n} parent_pe2_ok="
        f"{bool(parent and parent.get('win_ge80') and parent.get('days_ge50') and parent.get('beats_random'))} "
        f"parent_hold={parent.get('mean_hold_days') if parent else None}; "
        f"pe_ge80_d50={len(pe_ok)} earlier_than_parent={len(earlier_ok)}; "
        f"best_early={earlier_ok[0]['key'] if earlier_ok else None} "
        f"hold={earlier_ok[0].get('mean_hold_days') if earlier_ok else None} "
        f"win={earlier_ok[0].get('win_rate') if earlier_ok else None}; "
        f"promote_lookup=NO"
    )
    now = datetime.now(ZoneInfo("Asia/Taipei")).isoformat()
    out = {
        "phone_sync": PHONE_SYNC,
        "promote_to_lookup_display": False,
        "user_goal_zh": "v25：add_i3_pe2 父鎖上續壓 hold",
        "parent_seal": "phone_spirit_mix_thicken_v24_decision.json",
        "elapsed_s": round(time.time() - t0, 1),
        "n_stocks": meta_n,
        "parent_add_i3_pe2": parent,
        "ranking": ranking,
        "pe_ge80_d50": pe_ok[:15],
        "earlier_ok": earlier_ok[:10],
        "gate_one_liner": gate,
        "as_of_taipei": now,
        "errors_n": len(errors),
        "errors_sample": errors[:8],
    }
    text = json.dumps(out, ensure_ascii=False, indent=2, default=str)
    (ART / "phone_spirit_mix_thicken_v25_latest.json").write_text(text, encoding="utf-8")
    (DOC / "phone_spirit_mix_thicken_v25_latest.json").write_text(text, encoding="utf-8")
    print("GATE", gate, flush=True)
    print("PARENT", json.dumps(parent, ensure_ascii=False, default=str)[:700], flush=True)
    print("EARLIER", json.dumps(earlier_ok[:8], ensure_ascii=False, default=str)[:1400], flush=True)
    print("PASS", json.dumps(pe_ok[:8], ensure_ascii=False, default=str)[:1200], flush=True)
    return out


def main() -> None:
    run()


if __name__ == "__main__":
    main()
