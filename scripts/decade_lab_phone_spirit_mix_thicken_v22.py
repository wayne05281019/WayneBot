# -*- coding: utf-8 -*-
"""mix_v21 後：專攻 U112 提早賣缺口（nobody days 短／soft pe 差一截）。

v21：U180+ 全面过闸；U112 仍 soft≈78.9%@51d、nobody≈84.8%@45d。
本輪槓桿：
1) 放寬 nobody（~near(body,k)／week-only／body 滯後）衝 days≥50 且 ge80
2) soft pe 出場加嚴（pe5／僅耗竭／持有≥2）+ 簡易去損切
3) U140 桥接對照
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


def _bal(w: float, d: int) -> float:
    if not np.isfinite(w) or d <= 0:
        return float("-inf")
    return float(w) * min(1.0, d / 50.0)


def _sim_pe(
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
    min_hold: int = 0,
):
    n = len(df)
    dates = df["date"].astype(str).tolist() if "date" in df.columns else [str(i) for i in range(n)]
    o = df["open"].astype(float)
    c = df["close"].astype(float)
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
        for j in range(entry_i, min(n - 1, entry_i + MAX_HOLD) + 1):
            hl_j = str(hl.iloc[j]) if j < len(hl) else ""
            px = float(c.iloc[j])
            unreal = px / entry_px - 1.0 if entry_px > 0 else 0.0
            held = j - entry_i
            if hl_j == "20高":
                exit_j, reason = j, "first_hi20"
                break
            if bool(wave_top.iloc[j]):
                exit_j, reason = j, "wave_rel_high"
                break
            if held >= min_hold and bool(early_sell.iloc[j]) and unreal >= min_profit:
                exit_j, reason = j, f"early_profit_{min_profit:.0%}"
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


def _run_uni(label: str, n: int, turnover: float, mkt_raw) -> Dict[str, Any]:
    uni = select_g_universe(n=n, include_twse_top100=True, min_avg_turnover_k=turnover)
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
            soft_n1 = v11 & (~_near(body, 1))
            soft_n2 = v11 & (~_near(body, 2))
            week_only = ei_n5 & _near(week, 3) & (~body)
            body_lag = v11 & (~body.shift(1).fillna(False).astype(bool))
            wave_top = (
                ev.get("LAB_W1_TOP", pd.Series(False, index=idx))
                | ev.get("LAB_W3_TOP", pd.Series(False, index=idx))
                | ev.get("LAB_SELL_W5_TOP", pd.Series(False, index=idx))
            ).fillna(False)
            h = df["high"].astype(float)
            hi10 = h.rolling(10, min_periods=5).max()
            exhaust = feat.get("is_exhaustion_vol")
            exhaust = exhaust.reindex(idx).fillna(False).astype(bool) if exhaust is not None else pd.Series(False, index=idx)
            early_or = exhaust | (h >= hi10.shift(1))
            early_ex = exhaust

            specs: List[Tuple[str, pd.Series, str, float, int]] = [
                ("v11_hi20", v11, "hi20", 0.0, 0),
                ("nobody_pe3", nobody, "pe", 0.03, 0),
                ("softn1_pe3", soft_n1, "pe", 0.03, 0),
                ("softn2_pe3", soft_n2, "pe", 0.03, 0),
                ("weekonly_pe3", week_only, "pe", 0.03, 0),
                ("bodylag_pe3", body_lag, "pe", 0.03, 0),
                ("v11_pe3", v11, "pe", 0.03, 0),
                ("v11_pe5", v11, "pe", 0.05, 0),
                ("v11_pe3_ex", v11, "pe_ex", 0.03, 0),
                ("v11_pe3_mh2", v11, "pe", 0.03, 2),
                ("nobody_pe2", nobody, "pe", 0.02, 0),
                ("softn1_pe2", soft_n1, "pe", 0.02, 0),
            ]
            for cn, entry, kind, mp, mh in specs:
                key = f"{label}__{cn}"
                es = early_ex if kind == "pe_ex" else early_or
                if kind == "hi20":
                    trades = _simulate_relhigh(
                        df, entry, hl=hl, temp_label=temp, sid=sid, entry_tag=key, wave_top=wave_top, mode="hi20_or_wave_top"
                    )
                else:
                    trades = _sim_pe(
                        df, entry, hl=hl, temp_label=temp, sid=sid, entry_tag=key, wave_top=wave_top, early_sell=es, min_profit=mp, min_hold=mh
                    )
                trade_bucket.setdefault(key, []).extend(trades)
                early_bucket.setdefault(key, []).extend(_measure_signal_earliness(df, entry, hl, sid=sid, entry_tag=key))
                pool = w3u if int(w3u.sum()) >= 5 else pd.Series(True, index=idx)
                rnd = _random_matched(entry, pool, seed=seed + len(key))
                rkey = f"random__{key}"
                if kind == "hi20":
                    trade_bucket.setdefault(rkey, []).extend(
                        _simulate_relhigh(
                            df, rnd, hl=hl, temp_label=temp, sid=sid, entry_tag=rkey, wave_top=wave_top, mode="hi20_or_wave_top"
                        )
                    )
                else:
                    trade_bucket.setdefault(rkey, []).extend(
                        _sim_pe(
                            df, rnd, hl=hl, temp_label=temp, sid=sid, entry_tag=rkey, wave_top=wave_top, early_sell=es, min_profit=mp, min_hold=mh
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
            }
        )
    return {"ranking": ranking, "n_stocks": meta_n, "errors": errors}


def run() -> Dict[str, Any]:
    t0 = time.time()
    ART.mkdir(parents=True, exist_ok=True)
    DOC.mkdir(parents=True, exist_ok=True)
    _, mkt_raw = _twii_wave_pack(entry_preset="A0_strict", score_threshold=40.0)
    # U112＝既有母體（n=150×1.5M 收斂）；U140＝略放寬桥接
    parts = [
        ("U112", 150, 1_500_000.0),
        ("U140", 160, 1_200_000.0),
    ]
    ranking: List[Dict[str, Any]] = []
    errors: List[str] = []
    meta = {}
    for label, n, turn in parts:
        p = _run_uni(label, n, turn, mkt_raw)
        ranking.extend(p["ranking"])
        errors.extend(p["errors"])
        meta[label] = p["n_stocks"]

    pe_ok = [
        r
        for r in ranking
        if "pe" in r["key"]
        and "hi20" not in r["key"]
        and r.get("win_ge80")
        and r.get("days_ge50")
        and r.get("beats_random")
    ]
    pe_ok = sorted(pe_ok, key=lambda r: (-float(r.get("win_rate") or 0), -int(r.get("n_unique_entry_days") or 0)))
    u112 = [r for r in pe_ok if r["key"].startswith("U112__")]
    near = sorted(
        [r for r in ranking if r["key"].startswith("U112__") and "pe" in r["key"]],
        key=lambda r: (-_bal(float(r.get("win_rate") or 0), int(r.get("n_unique_entry_days") or 0)), -float(r.get("win_rate") or 0)),
    )[:12]

    gate = (
        f"spirit_mix_thicken_v22 pe_ge80_d50={len(pe_ok)} u112_pass={len(u112)}; "
        f"best={pe_ok[0]['key'] if pe_ok else None} "
        f"win={pe_ok[0].get('win_rate') if pe_ok else None} "
        f"days={pe_ok[0].get('n_unique_entry_days') if pe_ok else None} "
        f"hold={pe_ok[0].get('mean_hold_days') if pe_ok else None}; "
        f"u112_best_near={near[0]['key'] if near else None} "
        f"near_win={near[0].get('win_rate') if near else None} "
        f"near_days={near[0].get('n_unique_entry_days') if near else None}; "
        f"promote_lookup=NO"
    )
    now = datetime.now(ZoneInfo("Asia/Taipei")).isoformat()
    out = {
        "phone_sync": PHONE_SYNC,
        "promote_to_lookup_display": False,
        "user_goal_zh": "v22：U112 提早賣放寬 nobody／加嚴 pe",
        "parent_seal": "phone_spirit_mix_thicken_v21_decision.json",
        "elapsed_s": round(time.time() - t0, 1),
        "universe_meta": meta,
        "ranking": ranking,
        "pe_ge80_d50": pe_ok[:20],
        "u112_pass": u112[:10],
        "u112_near": near,
        "gate_one_liner": gate,
        "as_of_taipei": now,
        "errors_n": len(errors),
        "errors_sample": errors[:8],
    }
    text = json.dumps(out, ensure_ascii=False, indent=2, default=str)
    (ART / "phone_spirit_mix_thicken_v22_latest.json").write_text(text, encoding="utf-8")
    (DOC / "phone_spirit_mix_thicken_v22_latest.json").write_text(text, encoding="utf-8")
    print("GATE", gate, flush=True)
    print("U112_NEAR", json.dumps(near[:6], ensure_ascii=False, default=str)[:1500], flush=True)
    print("PASS", json.dumps(pe_ok[:6], ensure_ascii=False, default=str)[:1200], flush=True)
    return out


def main() -> None:
    run()


if __name__ == "__main__":
    main()
