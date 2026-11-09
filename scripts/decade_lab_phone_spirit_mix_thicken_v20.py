# -*- coding: utf-8 -*-
"""mix_v19 後：中位母體 U180 桥接 U112／U250 的提早賣。

v19：U112 hybrid 仍 78.9%。U250 pe 已過；U112 未過。
本輪：turnover=800k、n=180；复現 v11×pe2/3／hybrid。
另寫 placement candidate 對照（旗標仍關）。phone_sync=blocked。
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


def _sim_pe(df, entry_mask, *, hl, temp_label, sid, entry_tag, wave_top, early_sell, min_profit: float, body=None, nobody_only: bool = False):
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
        pe_ok = True
        if nobody_only and body is not None:
            pe_ok = not bool(body.iloc[i])
        exit_j = None
        reason = "max_hold"
        for j in range(entry_i, min(n - 1, entry_i + MAX_HOLD) + 1):
            hl_j = str(hl.iloc[j]) if j < len(hl) else ""
            px = float(c.iloc[j])
            unreal = px / entry_px - 1.0 if entry_px > 0 else 0.0
            if hl_j == "20高":
                exit_j, reason = j, "first_hi20"
                break
            if bool(wave_top.iloc[j]):
                exit_j, reason = j, "wave_rel_high"
                break
            if pe_ok and bool(early_sell.iloc[j]) and unreal >= min_profit:
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


def run(*, n_universe: int = 180, min_turnover_k: float = 800_000.0) -> Dict[str, Any]:
    t0 = time.time()
    ART.mkdir(parents=True, exist_ok=True)
    DOC.mkdir(parents=True, exist_ok=True)
    _, mkt_raw = _twii_wave_pack(entry_preset="A0_strict", score_threshold=40.0)
    uni = select_g_universe(n=n_universe, include_twse_top100=True, min_avg_turnover_k=min_turnover_k)
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

            specs = [
                ("v11_hi20", v11, "hi20", 0.0, False),
                ("v11_pe2", v11, "pe", 0.02, False),
                ("v11_pe3", v11, "pe", 0.03, False),
                ("v11_hybrid_pe3", v11, "pe", 0.03, True),
                ("nobody_hi20", nobody, "hi20", 0.0, False),
                ("nobody_pe2", nobody, "pe", 0.02, False),
                ("nobody_pe3", nobody, "pe", 0.03, False),
            ]
            for cn, entry, kind, mp, hybrid in specs:
                key = f"U180__{cn}"
                if kind == "hi20":
                    trades = _simulate_relhigh(
                        df, entry, hl=hl, temp_label=temp, sid=sid, entry_tag=key, wave_top=wave_top, mode="hi20_or_wave_top"
                    )
                else:
                    trades = _sim_pe(
                        df,
                        entry,
                        hl=hl,
                        temp_label=temp,
                        sid=sid,
                        entry_tag=key,
                        wave_top=wave_top,
                        early_sell=early_or,
                        min_profit=mp,
                        body=body,
                        nobody_only=hybrid,
                    )
                trade_bucket.setdefault(key, []).extend(trades)
                early_bucket.setdefault(key, []).extend(
                    _measure_signal_earliness(df, entry, hl, sid=sid, entry_tag=key)
                )
                pool = w3u if int(w3u.sum()) >= 5 else pd.Series(True, index=idx)
                rnd = _random_matched(entry, pool, seed=seed + len(key))
                if kind == "hi20":
                    trade_bucket.setdefault(f"random__{key}", []).extend(
                        _simulate_relhigh(
                            df, rnd, hl=hl, temp_label=temp, sid=sid, entry_tag=f"random__{key}", wave_top=wave_top, mode="hi20_or_wave_top"
                        )
                    )
                else:
                    trade_bucket.setdefault(f"random__{key}", []).extend(
                        _sim_pe(
                            df,
                            rnd,
                            hl=hl,
                            temp_label=temp,
                            sid=sid,
                            entry_tag=f"random__{key}",
                            wave_top=wave_top,
                            early_sell=early_or,
                            min_profit=mp,
                            body=body,
                            nobody_only=hybrid,
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

    base = next((r for r in ranking if r["key"].endswith("v11_hi20")), {})
    base_hold = float(base.get("mean_hold_days") or np.nan)
    pe_pass = [
        r
        for r in ranking
        if r.get("win_ge80")
        and r.get("days_ge50")
        and r.get("beats_random")
        and ("pe" in r["key"] or "hybrid" in r["key"])
    ]
    pe_pass = sorted(
        pe_pass,
        key=lambda r: (
            -(base_hold - float(r.get("mean_hold_days") or base_hold) if np.isfinite(base_hold) else 0),
            -float(r.get("win_rate") or 0),
        ),
    )
    gate = (
        f"spirit_mix_thicken_v20 U180 n={meta_n} pe_ge80_d50={len(pe_pass)}; "
        f"best={pe_pass[0]['key'] if pe_pass else None} "
        f"win={pe_pass[0].get('win_rate') if pe_pass else None} "
        f"days={pe_pass[0].get('n_unique_entry_days') if pe_pass else None} "
        f"hold={pe_pass[0].get('mean_hold_days') if pe_pass else None} "
        f"base_hold={base_hold}; promote_lookup=NO"
    )

    # placement candidate map (flag still off)
    placement = {
        "phone_sync": "blocked",
        "LOOKUP_LAB_MARKS_ENABLED": False,
        "promote_to_lookup_display": False,
        "as_of_taipei": None,
        "candidates": {
            "early_buy_u112": {
                "key": "ei_n5_week_n3_softbody__SELL_hi20_or_wave_top",
                "formula": "w3u & near(turn,3) & t60 & near(intent,5) & risk & (near(week,3)|near(body,3))",
                "win_rate": 0.8039,
                "days": 50,
                "bars_before_hi20": 15.86,
                "universe": "U112",
                "glyph": "LAB_BUY_W3_START",
                "status": "locked_lab_candidate",
            },
            "early_sell_u250": {
                "key": "v11_nobody__SELL_profit_early_3",
                "formula": "entry=v11&~body; exit=hi20|wave|(exhaust|hi10 & unreal>=3%)",
                "win_rate": 0.8551,
                "days": 66,
                "hold_days": 11.68,
                "universe": "U250",
                "glyph": "REL_HIGH_SELL",
                "status": "locked_lab_candidate_u250_only",
            },
            "early_sell_u112": {
                "status": "blocked_sub80_or_days_short",
                "near_miss": "soft pe≈78.9%@51d; nobody pe≈84.8%@45d",
            },
        },
        "note_zh": "僅候選對照；LOOKUP_LAB_MARKS_ENABLED 仍 False；不准改 leave_zero",
    }

    out = {
        "phone_sync": PHONE_SYNC,
        "promote_to_lookup_display": False,
        "user_goal_zh": "v20：U180 桥接提早賣＋placement 候選對照",
        "parent_seal": "phone_spirit_mix_thicken_v19_decision.json",
        "elapsed_s": round(time.time() - t0, 1),
        "n_stocks": meta_n,
        "universe_request": {"n": n_universe, "min_turnover_k": min_turnover_k},
        "ranking": ranking,
        "pe_ge80_d50": pe_pass[:10],
        "placement_candidates": placement,
        "gate_one_liner": gate,
        "errors_n": len(errors),
        "errors_sample": errors[:8],
    }
    text = json.dumps(out, ensure_ascii=False, indent=2, default=str)
    (ART / "phone_spirit_mix_thicken_v20_latest.json").write_text(text, encoding="utf-8")
    (DOC / "phone_spirit_mix_thicken_v20_latest.json").write_text(text, encoding="utf-8")
    place_text = json.dumps(placement, ensure_ascii=False, indent=2)
    (ART / "phone_lookup_mark_placement_candidates.json").write_text(place_text, encoding="utf-8")
    (DOC / "phone_lookup_mark_placement_candidates.json").write_text(place_text, encoding="utf-8")
    print("GATE", gate, flush=True)
    print("PE_PASS", json.dumps(pe_pass[:5], ensure_ascii=False, default=str)[:1000], flush=True)
    print("N_STOCKS", meta_n, flush=True)
    return out


def main() -> None:
    run()


if __name__ == "__main__":
    main()
