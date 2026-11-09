# -*- coding: utf-8 -*-
"""查股標記精神：分測 → 有用再混測（含已封口高勝率法則）。

分軌（勝率不混報）：
- TRACK_HSIAO：蕭大哥邏輯（V／S55／T／週線／紅箭×W3…）
- TRACK_BAREK_VP：裸K＋量價主力意圖
- TRACK_WAVE_FIB：八浪起漲區＋黃金切割貼近
- TRACK_FIVE：飆大五件柱代理（浪／形／量／關鍵K／碎形近似）
- TRACK_CHAMP：已測過高勝率法則（V／S55／bal／turn_barek／feat×t60…）

混測 TRACK_MIX：champ 高勝率肢 × 精神有用肢（分測抬勝率者）軟 AND／OR。

鎖死：起漲買核／相對高點賣；G100 真史；n≥20；phone_sync=blocked。
不准改 leave_zero；話筒不發明 5／9。
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
    _align_feat,
    _cores,
    _near,
    _wave_hsiao_bank,
)
from scripts.decade_lab_phone_market_wave_sync import (
    _align_mkt,
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
SELL = "hi20_or_wave_top"


def _bal(w: float, d: int) -> float:
    if not np.isfinite(w) or d <= 0:
        return float("-inf")
    return float(w) * min(1.0, d / 50.0)


def _five_proxies(df: pd.DataFrame, feat: pd.DataFrame, spirit: Dict[str, pd.Series]) -> Dict[str, pd.Series]:
    """飆大五件柱代理（實驗室；非他原文標籤）。叠≥2／≥3 當交叉候選。

    對齊 biaoke_five_bt 柱判精神（假跌破／爆量後日縮站撐／關鍵K形），
    只用已收 OHLC＋feat＋spirit／wave；碎形改因果確認（無未來棒）；
    不准發明個股 5／9；不上話筒。
    """
    idx = df.index
    o = df["open"].astype(float)
    h = df["high"].astype(float)
    low = df["low"].astype(float)
    c = df["close"].astype(float)
    v = df["volume"].astype(float) if "volume" in df.columns else pd.Series(np.nan, index=idx)

    # 波浪：引擎起漲／區／回撤底（結構位，不數 5／9）
    five_wave = (
        spirit["WAVE_w3_start"]
        | spirit["WAVE_w3_zone"]
        | spirit.get("WAVE_pullbase", pd.Series(False, index=idx))
    )

    # 形態：假跌破≈刺穿近低後收回（當日或隔日因果收回）；對齊 _verdict_morph
    min20 = low.shift(1).rolling(20, min_periods=5).min()
    same_day = (low < min20) & (c > min20) & (c > o)
    pierced_y = (low.shift(1) < min20.shift(1)) & (c.shift(1) <= min20.shift(1))
    next_reclaim = pierced_y & (c > min20.shift(1)) & (c > o)
    five_morph = same_day | next_reclaim

    # 量價結構：攻擊／凹洞後紅 ＋ 爆量後日縮站撐（對齊 _verdict_vol 0.65）
    attack = spirit["VP_attack"].reindex(idx).fillna(False).astype(bool)
    five_vol = attack | (spirit["VP_trough"].reindex(idx).fillna(False) & (c > o))
    if v.notna().any():
        last_spike_vol = v.where(attack).ffill()
        last_spike_low = low.where(attack).ffill()
        pos = pd.Series(np.arange(len(idx), dtype=float), index=idx)
        last_atk_pos = pos.where(attack).ffill()
        age = pos - last_atk_pos
        post_hold = (
            (~attack)
            & last_spike_vol.notna()
            & age.notna()
            & (age >= 1)
            & (age <= 12)
            & (v < last_spike_vol * 0.65)
            & (c >= last_spike_low)
        )
        five_vol = five_vol | post_hold.fillna(False)

    # 關鍵K：蕭關鍵陽／錘子（不併裸K建設＝BK 軌；碎形語另 FIVE_fractal）
    key = feat.get("is_key_bull_candle")
    hammer = feat.get("is_hammer_shape")
    five_keyk = pd.Series(False, index=idx)
    if key is not None:
        five_keyk = five_keyk | key.reindex(idx).fillna(False).astype(bool)
    if hammer is not None:
        five_keyk = five_keyk | hammer.reindex(idx).fillna(False).astype(bool)

    # 碎形線：5-bar 高低樞紐，於中心＋2 根確認日標記（因果，無 shift 負向）
    center_h = h.shift(2)
    frac_hi = (
        (center_h >= h.shift(4))
        & (center_h >= h.shift(3))
        & (center_h >= h.shift(1))
        & (center_h >= h)
    )
    center_l = low.shift(2)
    frac_lo = (
        (center_l <= low.shift(4))
        & (center_l <= low.shift(3))
        & (center_l <= low.shift(1))
        & (center_l <= low)
    )
    five_frac = (frac_hi | frac_lo).fillna(False)

    parts = {
        "FIVE_wave": five_wave.fillna(False),
        "FIVE_morph": five_morph.fillna(False),
        "FIVE_vol": five_vol.fillna(False),
        "FIVE_keyk": five_keyk.fillna(False),
        "FIVE_fractal": five_frac,
    }
    stack = (
        parts["FIVE_wave"].astype(int)
        + parts["FIVE_morph"].astype(int)
        + parts["FIVE_vol"].astype(int)
        + parts["FIVE_keyk"].astype(int)
        + parts["FIVE_fractal"].astype(int)
    )
    parts["FIVE_cross2"] = stack >= 2
    parts["FIVE_cross3"] = stack >= 3
    return parts


def _champ_filters(
    bank: Dict[str, pd.Series],
    cores: Dict[str, pd.Series],
    spirit: Dict[str, pd.Series],
    mkt: Dict[str, pd.Series],
    df: pd.DataFrame,
) -> Dict[str, pd.Series]:
    """已封口／已見高勝率法則（分測＋混測種子）。"""
    idx = df.index
    V = bank["hsiao_V"].fillna(False)
    Vnear = _near(V, 3)
    S55 = bank["score55"].fillna(False)
    turn_barek = spirit["INTENT_build_soft"] & (
        bank.get("hsiao_macd_turn", pd.Series(False, index=idx)).reindex(idx).fillna(False)
        | bank.get("hsiao_kd", pd.Series(False, index=idx)).reindex(idx).fillna(False)
        | spirit["BK_constructive"]
    )
    # 與 v3/v4 對齊的 turn_barek
    macd_kd = bank.get("hsiao_macd_turn", pd.Series(False, index=idx))
    if isinstance(macd_kd, pd.Series):
        macd_kd = macd_kd.reindex(idx).fillna(False) | bank.get("hsiao_kd", pd.Series(False, index=idx)).reindex(idx).fillna(False)
    else:
        macd_kd = pd.Series(False, index=idx)
    turn_barek = macd_kd & spirit["BK_not_avoid"]
    feat_ok = mkt.get("mkt_feat_ok", pd.Series(True, index=df.index)).fillna(False)
    t60 = bank.get("hsiao_T60", pd.Series(False, index=idx))
    t60 = t60.reindex(idx).fillna(False) if isinstance(t60, pd.Series) else pd.Series(False, index=idx)
    time_align = spirit.get("WAVE_pullbase", pd.Series(False, index=idx))  # placeholder soft
    # 用蕭 T + week
    week = bank.get("hsiao_week", pd.Series(False, index=idx))
    week = week.reindex(idx).fillna(False) if isinstance(week, pd.Series) else pd.Series(False, index=idx)
    t60_or_time = t60 | week | spirit["FIB_near_618"]

    return {
        "CH_V": V,
        "CH_Vnear": Vnear,
        "CH_S55": S55,
        "CH_V_or_S55": Vnear | S55,
        "CH_turn_barek": turn_barek,
        "CH_feat_t60": feat_ok & t60_or_time,
        "CH_S55_barek": S55 & spirit["BK_not_avoid"],
        "CH_V_barek": V & spirit["BK_not_avoid"],
        "CH_bal_core": (Vnear | S55),  # 外層再乘 entry bal
    }


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

    # track -> key -> trades
    buckets: Dict[str, Dict[str, List[Dict[str, Any]]]] = {
        "TRACK_HSIAO": {},
        "TRACK_BAREK_VP": {},
        "TRACK_WAVE_FIB": {},
        "TRACK_FIVE": {},
        "TRACK_CHAMP": {},
        "TRACK_MIX": {},
    }
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
            ev = _stock_wave_events(raw, df)
            mkt = _align_mkt(df, mkt_raw)
            hl, temp = _build_hl_temp(df)
            seed = abs(hash(sid)) % (2**32)
            spirit = build_spirit_masks(df, feat, wmasks=wmasks, bank=bank)
            five = _five_proxies(df, feat, spirit)
            champs = _champ_filters(bank, cores, spirit, mkt, df)

            Vnear = _near(bank["hsiao_V"].fillna(False), 3)
            S55 = bank["score55"].fillna(False)
            w3 = cores["core_w3_start"].fillna(False)
            w3u = cores["core_w3_or_ma60w3"].fillna(False)
            bal = w3u & (Vnear | S55)
            wave_top = (
                ev.get("LAB_W1_TOP", pd.Series(False, index=df.index))
                | ev.get("LAB_W3_TOP", pd.Series(False, index=df.index))
                | ev.get("LAB_SELL_W5_TOP", pd.Series(False, index=df.index))
            ).fillna(False)

            # —— 分測閘 —— #
            split: Dict[str, Dict[str, pd.Series]] = {
                "TRACK_HSIAO": {
                    "H_V": bank["hsiao_V"].fillna(False),
                    "H_S55": S55,
                    "H_V_or_S55": Vnear | S55,
                    "H_T60": bank.get("hsiao_T60", pd.Series(False, index=df.index)).reindex(df.index).fillna(False)
                    if "hsiao_T60" in bank
                    else pd.Series(False, index=df.index),
                    "H_week": bank.get("hsiao_week", pd.Series(False, index=df.index)).reindex(df.index).fillna(False)
                    if "hsiao_week" in bank
                    else pd.Series(False, index=df.index),
                    "H_macd_kd": (
                        bank.get("hsiao_macd_turn", pd.Series(False, index=df.index)).reindex(df.index).fillna(False)
                        | bank.get("hsiao_kd", pd.Series(False, index=df.index)).reindex(df.index).fillna(False)
                    ),
                    "H_clean_not_hot": (
                        bank.get("hsiao_clean", pd.Series(False, index=df.index)).reindex(df.index).fillna(False)
                        & bank.get("hsiao_not_hot", pd.Series(False, index=df.index)).reindex(df.index).fillna(False)
                    ),
                },
                "TRACK_BAREK_VP": {
                    "B_constructive": spirit["BK_constructive"],
                    "B_not_avoid": spirit["BK_not_avoid"],
                    "B_intent_build": spirit["INTENT_build"],
                    "B_intent_soft": spirit["INTENT_build_soft"],
                    "B_attack": spirit["VP_attack"],
                    "B_trough_atk": spirit["VP_trough"] & spirit["VP_attack"],
                },
                "TRACK_WAVE_FIB": {
                    "W_w3_start": spirit["WAVE_w3_start"],
                    "W_w3_zone": spirit["WAVE_w3_zone"],
                    "W_pullbase": spirit["WAVE_pullbase"],
                    "F_near_any": spirit["FIB_near_any"],
                    "F_near_618": spirit["FIB_near_618"],
                    "F_near_382": spirit["FIB_near_382"],
                    "WF_pull_fib": spirit["SPIRIT_pull_fib"],
                },
                "TRACK_FIVE": {k: v for k, v in five.items()},
                "TRACK_CHAMP": champs,
            }

            entries = {"E_w3": w3, "E_w3u": w3u, "E_bal": bal}

            def _run_track(track: str, filters: Dict[str, pd.Series]) -> None:
                for en, em in entries.items():
                    for fn, fm in filters.items():
                        entry = em & fm.fillna(False) & (~mkt["mkt_rel_high_risk"].fillna(False))
                        key = f"{en}__{fn}__SELL_{SELL}"
                        buckets[track].setdefault(key, []).extend(
                            _simulate_relhigh(
                                df, entry, hl=hl, temp_label=temp, sid=sid, entry_tag=key, wave_top=wave_top, mode=SELL
                            )
                        )
                        pool = w3u | w3
                        if int(pool.sum()) < 5:
                            pool = pd.Series(True, index=df.index)
                        rnd = _random_matched(entry, pool & fm.fillna(False), seed=seed + len(key) + hash(track) % 997)
                        buckets[track].setdefault(f"random__{key}", []).extend(
                            _simulate_relhigh(
                                df, rnd, hl=hl, temp_label=temp, sid=sid, entry_tag=f"rnd__{key}", wave_top=wave_top, mode=SELL
                            )
                        )

            for tr, fl in split.items():
                _run_track(tr, fl)

            # —— 混測：高勝率 champ × 精神有用肢 —— #
            mix = {
                "MIX_champV_intent": champs["CH_V"] & spirit["INTENT_build_soft"],
                "MIX_champS55_barek": champs["CH_S55"] & spirit["BK_not_avoid"],
                "MIX_champVS55_fib618": champs["CH_V_or_S55"] & spirit["FIB_near_618"],
                "MIX_turn_fib": champs["CH_turn_barek"] & (spirit["FIB_near_any"] | spirit["WAVE_w3_zone"]),
                "MIX_feat_t60_five2": champs["CH_feat_t60"] & five["FIVE_cross2"],
                "MIX_spirit_strict": spirit["SPIRIT_strict"],
                "MIX_spirit_core": spirit["SPIRIT_core"],
                "MIX_champV_five3": champs["CH_V"] & five["FIVE_cross3"],
                "MIX_bal_intent_fib": champs["CH_bal_core"] & spirit["INTENT_build_soft"] & spirit["FIB_near_any"],
                "MIX_S55_five2_week": champs["CH_S55"]
                & five["FIVE_cross2"]
                & bank.get("hsiao_week", pd.Series(False, index=df.index)).reindex(df.index).fillna(False),
            }
            _run_track("TRACK_MIX", mix)
        except Exception as e:
            errors.append(f"{sid}:{type(e).__name__}:{e}")

    def _rank_track(track: str, bucket: Dict[str, List[Dict[str, Any]]]) -> Dict[str, Any]:
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
                }
            )
        winners = [r for r in ranking if r["beats_random"]]
        by_win = sorted(winners, key=lambda r: (float(r["win_rate"]), int(r["n_unique_entry_days"])), reverse=True)
        by_bal = sorted(winners, key=lambda r: (float(r.get("balanced_score") or -9), float(r.get("win_rate") or -1)), reverse=True)
        ge80 = [r for r in by_win if r["win_ge80"]]
        return {
            "track": track,
            "n_keys": len(ranking),
            "winners_n": len(winners),
            "ge80_n": len(ge80),
            "best_win": by_win[0] if by_win else None,
            "best_bal": by_bal[0] if by_bal else None,
            "top_win": by_win[:8],
            "top_bal": by_bal[:8],
            "ge80": ge80[:8],
            "gate_one_liner": (
                f"{track} winners={len(winners)}/{len(ranking)}; ge80={len(ge80)}; "
                f"best_win={by_win[0]['key'] if by_win else None} "
                f"win={by_win[0].get('win_rate') if by_win else None} "
                f"days={by_win[0].get('n_unique_entry_days') if by_win else None}; promote_lookup=NO"
            ),
        }

    tracks_out = {tr: _rank_track(tr, bu) for tr, bu in buckets.items()}
    # 跨軌只並列、不混勝率算總冠
    useful = []
    for tr, info in tracks_out.items():
        for r in info.get("ge80") or []:
            useful.append({"track": tr, **r})
        if not info.get("ge80") and info.get("best_win"):
            bw = info["best_win"]
            if float(bw.get("win_rate") or 0) >= 0.75 and int(bw.get("n_unique_entry_days") or 0) >= 20:
                useful.append({"track": tr, **bw, "note": "ge75_backup"})

    gate = (
        "spirit_split_mix "
        + " | ".join(f"{tr}:{tracks_out[tr]['winners_n']}w/{tracks_out[tr]['ge80_n']}ge80" for tr in tracks_out)
        + "; promote_lookup=NO"
    )
    out = {
        "phone_sync": PHONE_SYNC,
        "promote_to_lookup_display": False,
        "user_goal_zh": "查股五張圖買賣相對位置＋極高勝率",
        "spirit_zh": "蕭邏輯＋裸K量價主力意圖＋八浪＋黃金切割＋飆大五件；分測後有用再混；含已測高勝率法則",
        "elapsed_s": round(time.time() - t0, 1),
        "n_stocks": meta_n,
        "tracks": tracks_out,
        "useful_cross_list": useful[:30],
        "gate_one_liner": gate,
        "errors_n": len(errors),
        "errors_sample": errors[:8],
    }
    text = json.dumps(out, ensure_ascii=False, indent=2, default=str)
    (ART / "phone_spirit_split_mix_latest.json").write_text(text, encoding="utf-8")
    (DOC / "phone_spirit_split_mix_latest.json").write_text(text, encoding="utf-8")
    print("GATE", gate, flush=True)
    for tr, info in tracks_out.items():
        print("TRACK", info["gate_one_liner"], flush=True)
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=100)
    args = ap.parse_args()
    run(n_universe=args.n)


if __name__ == "__main__":
    main()
