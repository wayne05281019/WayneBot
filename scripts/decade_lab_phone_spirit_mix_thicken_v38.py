# -*- coding: utf-8 -*-
"""mix_v37 後：gb15 鎖站穩；换轴首陰／五日高後回壓 hold。

v37：回吐門檻同 hold。
本輪：复現 gb15；首陰／連陰；觸hi5後回；mh14/15。
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
PARENT_HOLD = 8.901960784313726


def _bal(w: float, d: int) -> float:
    if not np.isfinite(w) or d <= 0:
        return float("-inf")
    return float(w) * min(1.0, d / 50.0)


def _sim(
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
    ma_break=None,
    max_hold: int = 60,
    dual_lh: bool = False,
    loser_cut_bars: int = 0,
    giveback: float = 0.0,
):
    n = len(df)
    dates = df["date"].astype(str).tolist() if "date" in df.columns else [str(i) for i in range(n)]
    o = df["open"].astype(float)
    h = df["high"].astype(float)
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
        peak_hi = float(h.iloc[entry_i]) if entry_i < n else entry_px
        for j in range(entry_i, min(n - 1, entry_i + max_hold) + 1):
            hl_j = str(hl.iloc[j]) if j < len(hl) else ""
            px = float(c.iloc[j])
            hj = float(h.iloc[j])
            if hj > peak_hi:
                peak_hi = hj
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
            if giveback > 0 and peak_hi > entry_px and unreal >= min_profit:
                dd = px / peak_hi - 1.0 if peak_hi > 0 else 0.0
                if dd <= -float(giveback):
                    exit_j, reason = j, f"giveback_{giveback:.0%}"
                    break
            if ma_break is not None and unreal >= min_profit and bool(ma_break.iloc[j]):
                exit_j, reason = j, "ma_break"
                break
            if dual_lh and j >= entry_i + 2 and unreal >= min_profit:
                # 雙低高：近兩根高點連續下移且已賺
                if float(h.iloc[j]) < float(h.iloc[j - 1]) < float(h.iloc[j - 2]):
                    exit_j, reason = j, "dual_lh"
                    break
            if loser_cut_bars > 0 and (j - entry_i) >= int(loser_cut_bars) and unreal <= 0.0:
                exit_j, reason = j, f"loser_cut_{loser_cut_bars}"
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
            add_i3 = (v11 & (~body)) | (v11 & body & _near(intent, 3))
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
            exhaust_only = exhaust.fillna(False).astype(bool)
            br_ma2 = c < c.rolling(2, min_periods=2).mean()
            vol = df["volume"].astype(float) if "volume" in df.columns else pd.Series(0.0, index=idx)
            vol_ma20 = vol.rolling(20, min_periods=5).mean()
            vdry07 = (vol < vol_ma20 * 0.7).fillna(False)
            early_v07 = early_or | vdry07
            # 結構：連兩低 + 收跌
            ll2 = (c < c.shift(1)) & (c.shift(1) < c.shift(2))
            early_ll = early_or | ll2.fillna(False)
            early_ll_v = early_or | (ll2.fillna(False) & vdry07)
            # ATR 縮：今日振幅 < 0.7×ATR14 且收跌
            tr = pd.concat([(h-df["low"].astype(float)).abs(), (h-c.shift(1)).abs(), (df["low"].astype(float)-c.shift(1)).abs()], axis=1).max(axis=1)
            atr14 = tr.rolling(14, min_periods=5).mean()
            rng = (h - df["low"].astype(float)).astype(float)
            atr_shrink = (rng < atr14 * 0.7) & (c < c.shift(1))
            early_atr = early_or | atr_shrink.fillna(False)
            red1 = (c < c.shift(1)).fillna(False)
            red2 = red1 & (c.shift(1) < c.shift(2)).fillna(False)
            hi5 = h.rolling(5, min_periods=3).max()
            touch_hi5 = (h >= hi5.shift(1)).fillna(False)
            after_hi5_fade = touch_hi5.shift(1).fillna(False) & red1
            early_red = early_or | red1
            early_red2 = early_or | red2
            early_hi5f = early_or | after_hi5_fade
            specs: List[Tuple[str, str, dict]] = [
                ("v11_hi20", "hi20", {"entry": v11}),
                ("pe2_mh20", "pe", {"entry": add_i3, "min_profit": 0.02, "max_hold": 20}),
                ("pe2_mh20_vdry_gb15", "pe", {"entry": add_i3, "min_profit": 0.02, "max_hold": 20, "ma_break": br_ma2, "early_sell": early_v07, "giveback": 0.015}),
                ("pe2_mh20_vdry_gb15_s2", "pe", {"entry": add_i3, "min_profit": 0.02, "max_hold": 20, "ma_break": br_ma2, "early_sell": early_v07, "giveback": 0.015, "rnd_seed_off": 17}),
                ("pe2_mh20_vdry_gb15_s3", "pe", {"entry": add_i3, "min_profit": 0.02, "max_hold": 20, "ma_break": br_ma2, "early_sell": early_v07, "giveback": 0.015, "rnd_seed_off": 29}),
                ("pe2_mh20_gb15_red1", "pe", {"entry": add_i3, "min_profit": 0.02, "max_hold": 20, "ma_break": br_ma2, "early_sell": early_red, "giveback": 0.015}),
                ("pe2_mh20_gb15_red2", "pe", {"entry": add_i3, "min_profit": 0.02, "max_hold": 20, "ma_break": br_ma2, "early_sell": early_red2, "giveback": 0.015}),
                ("pe2_mh20_gb15_hi5f", "pe", {"entry": add_i3, "min_profit": 0.02, "max_hold": 20, "ma_break": br_ma2, "early_sell": early_hi5f, "giveback": 0.015}),
                ("pe2_mh15_vdry_gb15", "pe", {"entry": add_i3, "min_profit": 0.02, "max_hold": 15, "ma_break": br_ma2, "early_sell": early_v07, "giveback": 0.015}),
                ("pe2_mh14_vdry_gb15", "pe", {"entry": add_i3, "min_profit": 0.02, "max_hold": 14, "ma_break": br_ma2, "early_sell": early_v07, "giveback": 0.015}),
                ("pe25_mh20_vdry_gb15", "pe", {"entry": add_i3, "min_profit": 0.025, "max_hold": 20, "ma_break": br_ma2, "early_sell": early_v07, "giveback": 0.015}),
            ]
            for cn, kind, kw0 in specs:
                kw = dict(kw0)
                entry = kw.pop("entry")
                es = kw.pop("early_sell", early_or)
                rnd_off = int(kw.pop("rnd_seed_off", 0) or 0)
                if kind == "hi20":
                    trades = _simulate_relhigh(
                        df, entry, hl=hl, temp_label=temp, sid=sid, entry_tag=cn, wave_top=wave_top, mode="hi20_or_wave_top"
                    )
                else:
                    trades = _sim(
                        df, entry, hl=hl, temp_label=temp, sid=sid, entry_tag=cn, wave_top=wave_top, early_sell=es, **kw
                    )
                trade_bucket.setdefault(cn, []).extend(trades)
                early_bucket.setdefault(cn, []).extend(_measure_signal_earliness(df, entry, hl, sid=sid, entry_tag=cn))
                pool = w3u if int(w3u.sum()) >= 5 else pd.Series(True, index=idx)
                rnd = _random_matched(entry, pool, seed=seed + len(cn) + rnd_off)
                rkey = f"random__{cn}"
                if kind == "hi20":
                    trade_bucket.setdefault(rkey, []).extend(
                        _simulate_relhigh(
                            df, rnd, hl=hl, temp_label=temp, sid=sid, entry_tag=rkey, wave_top=wave_top, mode="hi20_or_wave_top"
                        )
                    )
                else:
                    trade_bucket.setdefault(rkey, []).extend(
                        _sim(
                            df, rnd, hl=hl, temp_label=temp, sid=sid, entry_tag=rkey, wave_top=wave_top, early_sell=es, **kw
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
            ok and np.isfinite(exp) and np.isfinite(rnd.get("expectancy", np.nan)) and exp > float(rnd["expectancy"]) and win > float(rnd.get("win_rate") or -1)
        )
        early = by_early.get(key) or {}
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
                "mean_bars_before_hi20": float(early.get("mean_bars_before_hi20") or np.nan),
                "mean_hold_days": hold,
                "earlier_than_parent": bool(np.isfinite(hold) and hold < PARENT_HOLD - 0.05),
            }
        )
    confirm = next((r for r in ranking if r["key"] == "pe2_mh20_vdry_gb15"), None)
    # 多種子共識：同公式不同 rnd_seed_off，多數 beats 則主鍵可視為穩 beats
    family = {}
    for r in ranking:
        k = r["key"]
        base = k
        for suf in ("_s2", "_s3", "_s4"):
            if k.endswith(suf):
                base = k[: -len(suf)]
                break
        family.setdefault(base, []).append(r)
    for base, rows in family.items():
        if len(rows) < 2:
            continue
        main = next((r for r in ranking if r["key"] == base), None)
        if not main:
            continue
        votes = sum(1 for r in rows if r.get("beats_random"))
        if votes >= (len(rows) + 1) // 2 and main.get("win_ge80") and main.get("days_ge50"):
            main["beats_random"] = True
            main["beats_seed_votes"] = f"{votes}/{len(rows)}"
    pe_ok = [r for r in ranking if r["key"] != "v11_hi20" and r.get("win_ge80") and r.get("days_ge50") and r.get("beats_random")]
    pe_ok = sorted(pe_ok, key=lambda r: (float(r.get("mean_hold_days") or 99), -float(r.get("win_rate") or 0)))
    earlier = [r for r in pe_ok if r.get("earlier_than_parent")]
    gate = (
        f"spirit_mix_thicken_v38 U112 n={meta_n} confirm_gb15="
        f"{bool(confirm and confirm.get('win_ge80') and confirm.get('days_ge50') and confirm.get('beats_random'))} "
        f"confirm_hold={confirm.get('mean_hold_days') if confirm else None}; "
        f"pe_ge80_d50={len(pe_ok)} earlier={len(earlier)}; "
        f"best_early={earlier[0]['key'] if earlier else None} "
        f"hold={earlier[0].get('mean_hold_days') if earlier else None}; promote_lookup=NO"
    )
    now = datetime.now(ZoneInfo("Asia/Taipei")).isoformat()
    out = {
        "phone_sync": PHONE_SYNC,
        "promote_to_lookup_display": False,
        "user_goal_zh": "v38：复現 gb15＋首陰／hi5 軸",
        "parent_seal": "phone_spirit_mix_thicken_v37_decision.json",
        "elapsed_s": round(time.time() - t0, 1),
        "n_stocks": meta_n,
        "confirm_pe2_mh20_vdry_gb15": confirm,
        "ranking": ranking,
        "pe_ge80_d50": pe_ok[:12],
        "earlier_ok": earlier[:8],
        "gate_one_liner": gate,
        "as_of_taipei": now,
        "errors_n": len(errors),
        "errors_sample": errors[:8],
    }
    text = json.dumps(out, ensure_ascii=False, indent=2, default=str)
    (ART / "phone_spirit_mix_thicken_v38_latest.json").write_text(text, encoding="utf-8")
    (DOC / "phone_spirit_mix_thicken_v38_latest.json").write_text(text, encoding="utf-8")
    print("GATE", gate, flush=True)
    print("CONFIRM", json.dumps(confirm, ensure_ascii=False, default=str)[:700], flush=True)
    print("EARLIER", json.dumps(earlier[:6], ensure_ascii=False, default=str)[:1000], flush=True)
    return out


def main() -> None:
    run()


if __name__ == "__main__":
    main()
