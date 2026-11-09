# -*- coding: utf-8 -*-
"""量／價／時間／角度 × 波浪，疊在已過關高勝率核上（實驗室；不上話筒）。

必須保留的勝率核（上一跑 winners）：
- W3 起漲 ＋ 出場首碰20高（約76%）
- W3起漲 ∪ 紅箭×W3 ＋ 同出場（約75%）
本腳本只在其上 AND 四維條件，找出「勝率再升且仍贏隨機＋leave_zero」的變體。
"""
from __future__ import annotations

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

# 鎖定已抬勝率的出場
KEEP_EXITS = ("hi20_or_desync", "hi20_only")


def _feat_4d(ohlcv: pd.DataFrame) -> pd.DataFrame:
    prep = prepare_ohlcv(ohlcv)
    return compute_hsiao_features(prep)


def _align_feat(df: pd.DataFrame, feat: pd.DataFrame) -> pd.DataFrame:
    """把 Capitalized 特徵對到 normalize 後的 df（用 date）。"""
    f = feat.copy()
    f["ymd"] = pd.to_datetime(f.index).strftime("%Y%m%d")
    f = f.reset_index(drop=True).drop_duplicates("ymd", keep="last").set_index("ymd")
    ymd = df["date"].astype(str).str.replace("-", "").str[:8]
    out = f.reindex(ymd.values)
    out.index = df.index
    return out


def _dim_masks(feat: pd.DataFrame) -> Dict[str, pd.Series]:
    """四維獨立條件（各維可開關）。"""
    attack = feat.get("is_attack_vol")
    if attack is None:
        attack = pd.Series(False, index=feat.index)
    ratio = pd.to_numeric(feat.get("vol_attack_ratio"), errors="coerce")
    bull = feat.get("is_key_bull_candle")
    if bull is None:
        bull = pd.Series(False, index=feat.index)
    align = feat.get("bull_alignment")
    if align is None:
        align = pd.Series(False, index=feat.index)
    s20 = pd.to_numeric(feat.get("ma20_time_safety"), errors="coerce")
    a5 = pd.to_numeric(feat.get("angle_5"), errors="coerce")
    score = pd.to_numeric(feat.get("hsiao_4d_score"), errors="coerce")
    over = feat.get("is_overextended")
    if over is None:
        over = pd.Series(False, index=feat.index)

    return {
        "V_attack": attack.fillna(False).astype(bool) | ratio.fillna(0).ge(1.5),
        "P_bull": bull.fillna(False).astype(bool) | align.fillna(False).astype(bool),
        "T_safe": s20.fillna(-9) > 0.0,
        "A_up": a5.fillna(-9) >= 25.0,
        "A_steep": a5.fillna(-9) >= 35.0,
        "S55": score.fillna(0) >= 55.0,
        "S70": score.fillna(0) >= 70.0,
        "not_hot": ~over.fillna(False).astype(bool),
    }


def _core_entries(
    masks: Dict[str, pd.Series],
    wmasks: Dict[str, pd.Series],
    feat: pd.DataFrame,
) -> Dict[str, pd.Series]:
    """保留上一跑高勝率核。"""
    ma60 = masks.get("ma60_lower_confirmed", pd.Series(False, index=feat.index)).fillna(False)
    w3z = wmasks.get("W_w3_zone", pd.Series(False, index=feat.index)).fillna(False)
    w3s = wmasks.get("W_w3_start", pd.Series(False, index=feat.index)).fillna(False)
    # room: 未貼死 20高 — 用 close vs rolling 粗算（feat 可能無 room）
    cl = pd.to_numeric(feat.get("Close"), errors="coerce")
    if cl is None or cl.isna().all():
        room = pd.Series(True, index=feat.index)
    else:
        hi20 = cl.rolling(20, min_periods=5).max()
        room = ~(cl >= hi20 * 0.998)
        room = room.fillna(True)

    return {
        "core_w3_start": w3s & room,
        "core_w3_or_ma60w3": (w3s | (ma60 & w3z)) & room,
        "core_ma60_w3": ma60 & w3z & room,
    }


def run_4d_wave(*, n_universe: int = 100) -> Dict[str, Any]:
    t0 = time.time()
    ART.mkdir(parents=True, exist_ok=True)
    DOC.mkdir(parents=True, exist_ok=True)
    uni = select_g_universe(n=n_universe, include_twse_top100=True)
    symbols = uni["stock_id"].astype(str).tolist()
    for sid in MUST_INCLUDE:
        if sid not in symbols:
            symbols.append(sid)

    # 四維搭配：單維、雙維、三維、四維齊、分數門檻
    dim_combos: List[Tuple[str, Tuple[str, ...]]] = [
        ("D0_none", ()),
        ("V", ("V_attack",)),
        ("P", ("P_bull",)),
        ("T", ("T_safe",)),
        ("A", ("A_up",)),
        ("Asteep", ("A_steep",)),
        ("VP", ("V_attack", "P_bull")),
        ("VT", ("V_attack", "T_safe")),
        ("VA", ("V_attack", "A_up")),
        ("PT", ("P_bull", "T_safe")),
        ("PA", ("P_bull", "A_up")),
        ("TA", ("T_safe", "A_up")),
        ("VPT", ("V_attack", "P_bull", "T_safe")),
        ("VPA", ("V_attack", "P_bull", "A_up")),
        ("VTA", ("V_attack", "T_safe", "A_up")),
        ("PTA", ("P_bull", "T_safe", "A_up")),
        ("VPTA", ("V_attack", "P_bull", "T_safe", "A_up")),
        ("S55", ("S55", "not_hot")),
        ("S70", ("S70", "not_hot")),
        ("VPTA_S55", ("V_attack", "P_bull", "T_safe", "A_up", "S55", "not_hot")),
    ]

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
            feat_raw = _feat_4d(raw)
            feat = _align_feat(df, feat_raw)
            dims = _dim_masks(feat)
            wave = _align_wave(df, _wave_frame(raw))
            wmasks = _wave_masks(wave)
            masks = _build_mark_masks(df)
            cores = _core_entries(masks, wmasks, feat)
            hl_temp = __import__(
                "scripts.decade_lab_phone_trade_confront", fromlist=["_build_hl_temp"]
            )._build_hl_temp(df)
            hl, temp_label = hl_temp
            seed = abs(hash(sid)) % (2**32)

            # leave_zero 基準（同出場）
            lz = masks.get("leave_zero_blue_tri", pd.Series(False, index=df.index)).fillna(False)
            bucket["leave_zero__hi20_or_desync"].extend(
                _simulate_exits(
                    df, lz, hl=hl, temp_label=temp_label, sid=sid, entry_tag="lz", exit_mode="hi20_or_desync"
                )
            )
            rnd0 = _random_matched(lz, pd.Series(True, index=df.index), seed=seed)
            bucket["random__leave_zero__hi20_or_desync"].extend(
                _simulate_exits(
                    df,
                    rnd0,
                    hl=hl,
                    temp_label=temp_label,
                    sid=sid,
                    entry_tag="rnd_lz",
                    exit_mode="hi20_or_desync",
                )
            )

            for core_name, core_m in cores.items():
                for dname, dkeys in dim_combos:
                    fmask = pd.Series(True, index=df.index)
                    for dk in dkeys:
                        fmask = fmask & dims[dk].fillna(False)
                    entry = core_m.fillna(False) & fmask
                    for exit_mode in KEEP_EXITS:
                        key = f"{core_name}__{dname}__{exit_mode}"
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
                        pool = cores["core_w3_or_ma60w3"].fillna(False) | cores["core_w3_start"].fillna(False)
                        if int(pool.sum()) < 5:
                            pool = pd.Series(True, index=df.index)
                        rnd = _random_matched(entry, pool & fmask if dkeys else pool, seed=seed + len(key))
                        bucket.setdefault(f"random__{key}", []).extend(
                            _simulate_exits(
                                df,
                                rnd,
                                hl=hl,
                                temp_label=temp_label,
                                sid=sid,
                                entry_tag=f"rnd__{key}",
                                exit_mode=exit_mode,
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
        # 相對「同核無四維」是否再抬勝率
        parts = key.split("__")
        core = parts[0] if parts else ""
        exit_mode = parts[-1] if parts else ""
        base_key = f"{core}__D0_none__{exit_mode}"
        base = by_key.get(base_key) or {}
        lifts_core_win = bool(
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
                "lifts_core_winrate": lifts_core_win,
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
    keep_cores = [r for r in ranking if "__D0_none__" in r["key"] and int(r.get("n_unique_entry_days") or 0) >= 20]
    lift_vs_core = [r for r in winners if r.get("lifts_core_winrate")]

    gate = (
        f"winners={len(winners)}/{len(ranking)}; "
        f"lift_core={len(lift_vs_core)}; "
        f"best={ranking[0]['key'] if ranking else None} "
        f"win={ranking[0].get('win_rate') if ranking else None} "
        f"E={ranking[0].get('expectancy') if ranking else None}; "
        f"promote_lookup=NO"
    )
    out = {
        "phone_sync": PHONE_SYNC,
        "not_buy_signal": NOT_BUY_SIGNAL,
        "elapsed_s": round(time.time() - t0, 1),
        "n_stocks": meta_n,
        "keep_exits": list(KEEP_EXITS),
        "leave_zero_baseline": lz0,
        "core_baselines_D0": keep_cores,
        "ranking": ranking,
        "winners_beat_random_and_lz": winners,
        "winners_also_lift_core_winrate": lift_vs_core,
        "promote_to_lookup_display": False,
        "gate_one_liner": gate,
        "dim_defs_zh": {
            "V_attack": "量：攻擊量或量比≥1.5",
            "P_bull": "價：關鍵陽線或多頭排列",
            "T_safe": "時間：月線時間安全>0",
            "A_up": "角度：5日角度≥25",
            "Asteep": "角度：≥35",
            "S55/S70": "四維總分門檻",
            "not_hot": "非過熱",
        },
        "note_zh": "高勝率核必須保留；四維只准疊加改進。不上話筒浪號。",
        "errors_n": len(errors),
        "errors_sample": errors[:8],
    }
    text = json.dumps(out, ensure_ascii=False, indent=2, default=str)
    (ART / "phone_4d_wave_boost_latest.json").write_text(text, encoding="utf-8")
    (DOC / "phone_4d_wave_boost_latest.json").write_text(text, encoding="utf-8")
    print("GATE", gate, flush=True)
    print("KEEP_CORES", json.dumps(keep_cores, ensure_ascii=False, default=str)[:1200], flush=True)
    print("LIFT", len(lift_vs_core), json.dumps(lift_vs_core[:8], ensure_ascii=False, default=str), flush=True)
    print("WINNERS_N", len(winners), flush=True)
    return out


if __name__ == "__main__":
    run_4d_wave()
