# -*- coding: utf-8 -*-
"""極致抬勝率——核心＝波浪理論 × 蕭大師邏輯（實驗室；不上話筒）。

【核（必須保留）】
- 波浪：ElliottHsiaoEngine 的 W3 起漲／W3 區／拉回底→轉折（不是發明話筒 5／9）
- 蕭：量攻／關鍵陽／月線時間安全／角度／四維分／週線多頭／KD 買區；
      出場對齊作者「如何賣」→ 首碰 20 高（hi20_or_desync）
- 對照核勝率約 75%–76%（先前 phone_winrate_boost）

【可自由疊】
- 波浪轉折：W2 近窗、拉回底近窗、非 B/C、分數門檻
- 蕭條件：攻擊量、非竭盡、壓縮突破、MACD 翻多、缺口突破、過熱擋
- 我的加強：elite / max_gate 多條件共振（仍要過隨機＋leave_zero）
- 下一層 nextlayer：脫離缺口／軋空／W3 延續持有／禁 X 浪／籌碼×週線×4D／缺口×月線角／
  W3 區 MACD＋乖離／仙人指路×週線 KD（僅既有 lab_signal／state／特徵欄；浪號不上話筒）

用法：
  PYTHONPATH=. python3 -u scripts/decade_lab_phone_extreme_hillclimb.py --track wave
  PYTHONPATH=. python3 -u scripts/decade_lab_phone_extreme_hillclimb.py --track hsiao
  PYTHONPATH=. python3 -u scripts/decade_lab_phone_extreme_hillclimb.py --track fusion
  PYTHONPATH=. python3 -u scripts/decade_lab_phone_extreme_hillclimb.py --track nextlayer
  PYTHONPATH=. python3 -u scripts/decade_lab_phone_extreme_hillclimb.py --track all
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
from scripts.decade_lab_phone_wave_filter import _align_wave, _wave_frame, _wave_masks
from scripts.decade_lab_phone_winrate_boost import _simulate_exits

PHONE_SYNC = "blocked"
NOT_BUY_SIGNAL = True
ROOT = Path(__file__).resolve().parents[1]
ART = Path("/opt/cursor/artifacts")
DOC = ROOT / "docs" / "expert_notes" / "飆客" / "decade_lab"

KEEP_EXIT = "hi20_or_desync"
# 波浪核：純 W3 起漲；蕭箭×W3 區併入（紅箭＝ma60_lower 確認，對齊蕭高低卡）
CORE_NAMES = ("core_w3_start", "core_w3_or_ma60w3")


def _align_feat(df: pd.DataFrame, feat: pd.DataFrame) -> pd.DataFrame:
    f = feat.copy()
    f["ymd"] = pd.to_datetime(f.index).strftime("%Y%m%d")
    f = f.reset_index(drop=True).drop_duplicates("ymd", keep="last").set_index("ymd")
    ymd = df["date"].astype(str).str.replace("-", "").str[:8]
    out = f.reindex(ymd.values)
    out.index = df.index
    return out


def _bool(s: pd.Series | None, idx, default: bool = False) -> pd.Series:
    if s is None:
        return pd.Series(default, index=idx)
    return s.reindex(idx).fillna(default).astype(bool)


def _num(s: pd.Series | None, idx) -> pd.Series:
    if s is None:
        return pd.Series(np.nan, index=idx)
    return pd.to_numeric(s.reindex(idx), errors="coerce")


def _near(mask: pd.Series, n: int = 5) -> pd.Series:
    m = mask.fillna(False).astype(bool)
    out = m.astype(float).rolling(n, min_periods=1).max().fillna(0).gt(0)
    return out


def _room_mask(feat: pd.DataFrame) -> pd.Series:
    """蕭出場看 20 高：進場時留空間，避免當日已貼死。"""
    cl = _num(feat.get("Close"), feat.index)
    if cl.isna().all():
        return pd.Series(True, index=feat.index)
    hi20 = cl.rolling(20, min_periods=5).max()
    return (cl < hi20 * 0.985).fillna(True)


def _cores(
    masks: Dict[str, pd.Series],
    wmasks: Dict[str, pd.Series],
    feat: pd.DataFrame,
) -> Dict[str, pd.Series]:
    """波浪核 × 蕭箭。"""
    ma60 = _bool(masks.get("ma60_lower_confirmed"), feat.index)  # 蕭：確認紅箭
    w3z = _bool(wmasks.get("W_w3_zone"), feat.index)
    w3s = _bool(wmasks.get("W_w3_start"), feat.index)
    room = _room_mask(feat)
    return {
        "core_w3_start": w3s & room,
        "core_w3_or_ma60w3": (w3s | (ma60 & w3z)) & room,
    }


def _wave_hsiao_bank(
    feat: pd.DataFrame,
    wmasks: Dict[str, pd.Series],
    wave: pd.DataFrame,
) -> Dict[str, pd.Series]:
    """因素庫：先波浪／蕭，再自由加強。"""
    idx = feat.index
    # —— 波浪 ——
    pull = _bool(wmasks.get("W_pullbase"), idx)
    w2 = _bool(wmasks.get("W_w2"), idx)
    base = _bool(wmasks.get("W_base"), idx) if "W_base" in wmasks else pd.Series(False, index=idx)
    not_crash = _bool(wmasks.get("W_not_crash"), idx)
    w3z = _bool(wmasks.get("W_w3_zone"), idx)
    wscore50 = _bool(wmasks.get("W_score50"), idx)
    pull_sc = _bool(wmasks.get("W_pullbase_score"), idx)
    sig = wave["lab_signal"].reindex(idx).fillna("") if "lab_signal" in wave.columns else pd.Series("", index=idx)
    st = wave["state_name"].reindex(idx).fillna("") if "state_name" in wave.columns else pd.Series("", index=idx)
    eff = _num(wave.get("hsiao_score_eff") if isinstance(wave, pd.DataFrame) else None, idx)
    if "hsiao_score_eff" in wave.columns:
        eff = pd.to_numeric(wave["hsiao_score_eff"].reindex(idx), errors="coerce")

    no_b = ~st.eq("WAVE_B_TRAP")
    no_c = ~st.isin(["WAVE_C_CRASH", "WAVE_A_DROP"])
    no_w5_end = ~st.isin(["WAVE_5_FINAL", "WAVE_5_ENDING_DIAGONAL"])
    wave_safe = not_crash & no_b & no_w5_end
    pull_near = _near(pull | w2 | base, 5)
    w2_near = _near(w2, 5)
    score50 = (eff.fillna(0) >= 50.0) | wscore50
    score55 = eff.fillna(0) >= 55.0
    score70 = eff.fillna(0) >= 70.0
    # 引擎事件（若當日有）
    hammer_w2 = sig.eq("LAB_W2_HAMMER") | _near(sig.eq("LAB_W2_HAMMER"), 3)
    chip_bonus = sig.eq("LAB_CHIP_CLEAN_BONUS") | _near(sig.eq("LAB_CHIP_CLEAN_BONUS"), 5)
    immortal = sig.isin(["LAB_IMMORTAL_GUIDE", "LAB_ADD_ON_IMMORTAL_BREAK"])
    # 下一層引擎事件（未進既有 TRACK；仍是 lab_signal／state，不發明話筒 5／9）
    breakaway = sig.eq("LAB_BREAKAWAY_GAP") | _near(sig.eq("LAB_BREAKAWAY_GAP"), 3)
    squeeze = sig.eq("LAB_SHORT_SQUEEZE_SETUP") | _near(sig.eq("LAB_SHORT_SQUEEZE_SETUP"), 5)
    ext_hold = sig.isin(["LAB_W3_EXTENSION_HOLD", "LAB_W3_SUBWAVE_HOLD"]) | _near(
        sig.isin(["LAB_W3_EXTENSION_HOLD", "LAB_W3_SUBWAVE_HOLD"]), 5
    )
    no_x = ~st.eq("WAVE_X_REBOUND")
    wash_fail = sig.isin(["LAB_WASHOUT_WATCH_CANDIDATE", "LAB_W3_FAIL_BREAK_P2", "LAB_FAKE_BREAKOUT_EXIT"])
    no_wash = ~(_near(wash_fail, 5))

    # —— 蕭四維／既有欄 ——
    attack = _bool(feat.get("is_attack_vol"), idx)
    ratio = _num(feat.get("vol_attack_ratio"), idx)
    exh = _bool(feat.get("is_exhaustion_vol"), idx)
    bull = _bool(feat.get("is_key_bull_candle"), idx)
    align = _bool(feat.get("bull_alignment"), idx)
    hammer = _bool(feat.get("is_hammer_shape"), idx)
    s20 = _num(feat.get("ma20_time_safety"), idx)
    s60 = _num(feat.get("ma60_time_safety"), idx)
    a5 = _num(feat.get("angle_5"), idx)
    a10 = _num(feat.get("angle_10"), idx)
    score4d = _num(feat.get("hsiao_4d_score"), idx)
    over = _bool(feat.get("is_overextended"), idx)
    weekly = _bool(feat.get("weekly_trend_bullish"), idx)
    w_kd_hot = _bool(feat.get("w_kd_high_passivation"), idx)
    kd_buy = _bool(feat.get("kd_pullback_buy_zone"), idx)
    kd_gold = _bool(feat.get("kd_golden_cross"), idx)
    kd_hot = _bool(feat.get("kd_high_passivation"), idx)
    kd_death = _bool(feat.get("kd_death_cross"), idx)
    compress = _bool(feat.get("had_ma_compression_5d"), idx)
    trough_vol = _bool(feat.get("had_trough_vol_10d"), idx)
    gap_br = _bool(feat.get("gap_breakaway_candidate"), idx)
    gap_ex = _bool(feat.get("gap_exhaustion_candidate"), idx)
    gap_fill = _bool(feat.get("gap_filled_within_3d"), idx)
    fake = _bool(feat.get("fake_breakout_exit"), idx)
    block = _bool(feat.get("block_new_entries"), idx)
    macd_contract = _bool(feat.get("macd_hist_contracting"), idx)
    dif = _num(feat.get("DIF"), idx)
    hist = _num(feat.get("MACD_HIST"), idx)
    bias = _num(feat.get("bias_ma20_pct"), idx)
    k = _num(feat.get("K"), idx)

    v_ok = attack | ratio.fillna(0).ge(1.5)
    v_mild = ratio.fillna(0).ge(1.2) & (~exh)
    p_ok = bull | align | hammer
    t_ok = s20.fillna(-9) > 0.0
    t60_ok = s60.fillna(-9) > 0.0
    a_ok = a5.fillna(-9) >= 25.0
    a_mid = a5.fillna(-9).between(15.0, 45.0)
    a10_ok = a10.fillna(-9) >= 20.0
    not_hot = ~over
    clean = (~exh) & (~gap_ex) & (~fake) & (~block) & (~gap_fill)
    week_ok = weekly & (~w_kd_hot)
    kd_ok = (kd_buy | kd_gold | k.fillna(50).between(25, 65)) & (~kd_hot) & (~kd_death)
    macd_ok = (dif.fillna(0) > 0) | (hist.fillna(0) > 0)
    macd_turn = (~macd_contract) & hist.fillna(0).gt(hist.shift(1).fillna(0))
    bias_ok = bias.fillna(0).between(-0.02, 0.12)
    s4d55 = score4d.fillna(0) >= 55.0
    s4d70 = score4d.fillna(0) >= 70.0
    compress_break = compress & (bull | attack)
    trough_then_attack = trough_vol & v_ok

    return {
        # 基線（核本身）
        "D0": pd.Series(True, index=idx),
        # —— 波浪轉折軌 ——
        "wave_safe": wave_safe,
        "pull_near": pull_near,
        "w2_near": w2_near,
        "pull_score": pull_sc | (pull_near & score50),
        "w3zone_only": w3z & wave_safe,
        "score50": score50,
        "score55": score55,
        "score70": score70,
        "hammer_w2": hammer_w2 | (w2_near & hammer),
        "chip_clean": chip_bonus,
        "immortal": immortal,
        "pull_wave_safe": pull_near & wave_safe,
        "w2_score": w2_near & score50 & wave_safe,
        "turn_wave": pull_near & wave_safe & score50 & no_c,
        # —— 蕭邏輯軌 ——
        "hsiao_V": v_ok,
        "hsiao_Vmild": v_mild,
        "hsiao_P": p_ok,
        "hsiao_T": t_ok,
        "hsiao_T60": t60_ok,
        "hsiao_A": a_ok,
        "hsiao_Amid": a_mid,
        "hsiao_A10": a10_ok,
        "hsiao_clean": clean,
        "hsiao_not_hot": not_hot,
        "hsiao_week": week_ok,
        "hsiao_kd": kd_ok,
        "hsiao_macd": macd_ok,
        "hsiao_macd_turn": macd_turn,
        "hsiao_bias": bias_ok,
        "hsiao_S55": s4d55,
        "hsiao_S70": s4d70,
        "hsiao_compress": compress_break,
        "hsiao_troughV": trough_then_attack,
        "hsiao_gap": gap_br,
        "hsiao_VPT": v_ok & p_ok & t_ok,
        "hsiao_VPA": v_ok & p_ok & a_ok,
        "hsiao_4dpack": s4d55 & clean & not_hot & week_ok,
        # —— 融合（波浪 × 蕭 × 我想要的）——
        "fuse_pull_V": pull_near & v_ok & wave_safe,
        "fuse_w2_V": w2_near & v_ok & wave_safe,
        "fuse_turn_hsiao": pull_near & wave_safe & clean & (macd_turn | kd_ok) & not_hot,
        "fuse_week_V": week_ok & v_ok & wave_safe,
        "fuse_week_kd_V": week_ok & kd_ok & v_ok & wave_safe,
        "fuse_struct": compress_break & v_ok & a_mid & wave_safe & not_hot,
        "fuse_score_V": score50 & v_ok & clean & wave_safe,
        "fuse_elite": week_ok & v_ok & clean & not_hot & wave_safe & (s4d55 | a_ok | score55),
        "fuse_elite_turn": week_ok & pull_near & v_ok & clean & not_hot & wave_safe & macd_ok,
        "fuse_elite_struct": week_ok & compress_break & v_ok & a_ok & clean & not_hot & wave_safe,
        "fuse_max": week_ok & kd_ok & v_ok & p_ok & t_ok & clean & not_hot & bias_ok & wave_safe & score50,
        "fuse_immortal_V": (immortal | hammer_w2) & v_ok & wave_safe & not_hot,
        # —— 下一層（波浪×蕭深組合；只疊在核上抬勝率）——
        "nx_breakaway_V": breakaway & v_ok & wave_safe & no_x & not_hot,
        "nx_squeeze_VPT": squeeze & v_ok & p_ok & t_ok & wave_safe & no_x,
        "nx_ext_hold_clean": ext_hold & clean & not_hot & t_ok & wave_safe & no_wash,
        "nx_no_x_pull_V": no_x & pull_near & v_ok & wave_safe & clean,
        "nx_chip_week_S55": chip_bonus & week_ok & s4d55 & wave_safe & not_hot & no_x,
        "nx_gap_T60_A": gap_br & t60_ok & a_ok & wave_safe & not_hot & clean,
        "nx_w3z_macd_bias": w3z & macd_turn & bias_ok & clean & wave_safe & no_x & no_wash,
        "nx_immortal_week_kd": immortal & week_ok & kd_ok & not_hot & wave_safe & no_x,
    }


TRACK_KEYS: Dict[str, Tuple[str, ...]] = {
    "baseline": ("D0",),
    "wave": (
        "wave_safe",
        "pull_near",
        "w2_near",
        "pull_score",
        "score50",
        "score55",
        "score70",
        "hammer_w2",
        "chip_clean",
        "immortal",
        "pull_wave_safe",
        "w2_score",
        "turn_wave",
    ),
    "hsiao": (
        "hsiao_V",
        "hsiao_Vmild",
        "hsiao_P",
        "hsiao_T",
        "hsiao_A",
        "hsiao_Amid",
        "hsiao_clean",
        "hsiao_not_hot",
        "hsiao_week",
        "hsiao_kd",
        "hsiao_macd",
        "hsiao_macd_turn",
        "hsiao_S55",
        "hsiao_S70",
        "hsiao_compress",
        "hsiao_troughV",
        "hsiao_gap",
        "hsiao_VPT",
        "hsiao_VPA",
        "hsiao_4dpack",
    ),
    "fusion": (
        "fuse_pull_V",
        "fuse_w2_V",
        "fuse_turn_hsiao",
        "fuse_week_V",
        "fuse_week_kd_V",
        "fuse_struct",
        "fuse_score_V",
        "fuse_elite",
        "fuse_elite_turn",
        "fuse_elite_struct",
        "fuse_max",
        "fuse_immortal_V",
    ),
    # 下一層：引擎未掃過的 wave×Hsiao 深組合（不上話筒；過閘才談）
    "nextlayer": (
        "nx_breakaway_V",
        "nx_squeeze_VPT",
        "nx_ext_hold_clean",
        "nx_no_x_pull_V",
        "nx_chip_week_S55",
        "nx_gap_T60_A",
        "nx_w3z_macd_bias",
        "nx_immortal_week_kd",
    ),
}


def _track_factor_names(track: str) -> List[str]:
    if track == "all":
        names: List[str] = ["D0"]
        for t, keys in TRACK_KEYS.items():
            if t == "baseline":
                continue
            for k in keys:
                if k not in names:
                    names.append(k)
        return names
    if track not in TRACK_KEYS:
        raise SystemExit(f"unknown track={track}; choose {list(TRACK_KEYS)+['all']}")
    out = list(TRACK_KEYS[track])
    if "D0" not in out:
        out = ["D0"] + out
    return out


def run_extreme(*, track: str = "all", n_universe: int = 100) -> Dict[str, Any]:
    t0 = time.time()
    ART.mkdir(parents=True, exist_ok=True)
    DOC.mkdir(parents=True, exist_ok=True)
    factor_names = _track_factor_names(track)

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
            factors = _wave_hsiao_bank(feat, wmasks, wave)
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
                for fname in factor_names:
                    fmask = factors[fname].reindex(df.index).fillna(False)
                    entry = core_m & fmask
                    key = f"{core_name}__{fname}__{KEEP_EXIT}"
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
                    rnd_pool = pool & fmask if fname != "D0" else pool
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
        parts = key.split("__")
        core = parts[0] if parts else ""
        base_key = f"{core}__D0__{KEEP_EXIT}"
        base = by_key.get(base_key) or {}
        lifts_core = bool(
            ok_n
            and base
            and np.isfinite(base.get("win_rate", np.nan))
            and float(st.get("win_rate", np.nan)) > float(base["win_rate"]) + 0.005
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
                "lifts_core_winrate": lifts_core,
                "core_base_win": base.get("win_rate"),
                "win_minus_core": (
                    float(st["win_rate"]) - float(base["win_rate"])
                    if ok_n and base and np.isfinite(base.get("win_rate", np.nan))
                    else float("nan")
                ),
            }
        )

    ranking.sort(
        key=lambda r: (
            int(r.get("beats_random") or 0),
            int(r.get("beats_leave_zero") or 0),
            int(r.get("lifts_core_winrate") or 0),
            float(r.get("win_rate") or -1),
            float(r.get("expectancy") or -9),
        ),
        reverse=True,
    )
    winners = [r for r in ranking if r.get("beats_random") and r.get("beats_leave_zero")]
    lift = [r for r in winners if r.get("lifts_core_winrate")]
    by_win = sorted(
        [r for r in ranking if int(r.get("n_unique_entry_days") or 0) >= 20],
        key=lambda r: float(r.get("win_rate") or -1),
        reverse=True,
    )
    cores_d0 = [r for r in ranking if "__D0__" in r["key"] and int(r.get("n_unique_entry_days") or 0) >= 20]

    gate = (
        f"track={track}; winners={len(winners)}/{len(ranking)}; lift_core={len(lift)}; "
        f"best_win={by_win[0]['key'] if by_win else None} "
        f"win={by_win[0].get('win_rate') if by_win else None} "
        f"E={by_win[0].get('expectancy') if by_win else None}; promote_lookup=NO"
    )
    out = {
        "phone_sync": PHONE_SYNC,
        "not_buy_signal": NOT_BUY_SIGNAL,
        "doctrine_zh": "核心＝波浪理論×蕭大師邏輯；其餘只准疊加抬勝率，浪號不上話筒。",
        "track": track,
        "elapsed_s": round(time.time() - t0, 1),
        "n_stocks": meta_n,
        "keep_exit": KEEP_EXIT,
        "factor_names": factor_names,
        "leave_zero_baseline": lz0,
        "core_baselines_D0": cores_d0,
        "ranking": ranking,
        "by_winrate_n20": by_win[:25],
        "winners_beat_random_and_lz": winners,
        "winners_also_lift_core_winrate": lift,
        "promote_to_lookup_display": False,
        "gate_one_liner": gate,
        "errors_n": len(errors),
        "errors_sample": errors[:8],
    }
    tag = track if track != "all" else "all"
    text = json.dumps(out, ensure_ascii=False, indent=2, default=str)
    (ART / f"phone_extreme_hillclimb_{tag}_latest.json").write_text(text, encoding="utf-8")
    (DOC / f"phone_extreme_hillclimb_{tag}_latest.json").write_text(text, encoding="utf-8")
    if track == "all":
        (ART / "phone_extreme_hillclimb_latest.json").write_text(text, encoding="utf-8")
        (DOC / "phone_extreme_hillclimb_latest.json").write_text(text, encoding="utf-8")
    print("GATE", gate, flush=True)
    print("TOP_WIN", json.dumps(by_win[:8], ensure_ascii=False, default=str)[:2000], flush=True)
    print("LIFT", len(lift), json.dumps(lift[:8], ensure_ascii=False, default=str)[:2000], flush=True)
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--track", default="all", choices=list(TRACK_KEYS) + ["all"])
    ap.add_argument("--n", type=int, default=100)
    args = ap.parse_args()
    run_extreme(track=args.track, n_universe=args.n)


if __name__ == "__main__":
    main()
