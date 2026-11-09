# -*- coding: utf-8 -*-
"""話筒進場 × 蕭氏波浪狀態濾網（雲端實驗室；不上話筒、不發明話筒 5／9）。

問：搭配波浪能否提高辨識率（贏同密度隨機，且盡量贏 leave_zero）？
進出場仍用 phone_trade 整段；波浪只當「現在處在哪一段」的條件。
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
from scripts.decade_lab_hsiao_wave_engine import ElliottHsiaoEngine
from scripts.decade_lab_phone_entry_tighten import _feature_frame, _near_mask, _random_matched
from scripts.decade_lab_phone_trade_confront import _agg_trades, _build_hl_temp, _simulate_trades

PHONE_SYNC = "blocked"
NOT_BUY_SIGNAL = True
ROOT = Path(__file__).resolve().parents[1]
ART = Path("/opt/cursor/artifacts")
DOC = ROOT / "docs" / "expert_notes" / "飆客" / "decade_lab"

PULLBASE = {"BASE_BOTTOM", "WAVE_2_PULLBACK"}
CRASHY = {"WAVE_C_CRASH", "WAVE_A_DROP", "WAVE_B_TRAP"}
W3ISH = {"WAVE_3_MAIN"}


def _wave_frame(ohlcv_cap: pd.DataFrame) -> pd.DataFrame:
    """跑蕭氏狀態機，回傳以 date 字串為索引的狀態表。"""
    prep = prepare_ohlcv(ohlcv_cap)
    feat = compute_hsiao_features(prep)
    eng = ElliottHsiaoEngine(entry_preset="A1_score", score_threshold=50.0)
    lab = eng.run(feat, already_featured=True)
    out = pd.DataFrame(
        {
            "state_name": lab["state_name"].astype(str).values,
            "lab_signal": lab["lab_signal"].astype(str).values
            if "lab_signal" in lab.columns
            else "",
            "hsiao_score_eff": pd.to_numeric(lab.get("hsiao_score_eff"), errors="coerce").values
            if "hsiao_score_eff" in lab.columns
            else np.nan,
        },
        index=pd.to_datetime(lab.index),
    )
    out["ymd"] = out.index.strftime("%Y%m%d")
    return out.reset_index(drop=True).set_index("ymd")


def _align_wave(df: pd.DataFrame, wave: pd.DataFrame) -> pd.DataFrame:
    ymd = df["date"].astype(str).str.replace("-", "").str[:8]
    w = wave.reindex(ymd.values)
    w.index = df.index
    return w


def _wave_masks(wave: pd.DataFrame) -> Dict[str, pd.Series]:
    st = wave["state_name"].fillna("")
    sig = wave["lab_signal"].fillna("")
    score = pd.to_numeric(wave["hsiao_score_eff"], errors="coerce")
    w3_start = sig == "LAB_BUY_W3_START"
    w3_near = w3_start.copy()
    for k in range(1, 4):
        w3_near = w3_near | w3_start.shift(k).fillna(False)
    return {
        "W_pullbase": st.isin(PULLBASE),
        "W_w2": st == "WAVE_2_PULLBACK",
        "W_base": st == "BASE_BOTTOM",
        "W_not_crash": ~st.isin(CRASHY),
        "W_w3_zone": st.isin(W3ISH) | w3_near,
        "W_score50": score >= 50.0,
        "W_pullbase_score": st.isin(PULLBASE) & (score >= 50.0),
        "W_w3_start": w3_start,
    }


def run_wave_filter(*, n_universe: int = 100) -> Dict[str, Any]:
    t0 = time.time()
    ART.mkdir(parents=True, exist_ok=True)
    DOC.mkdir(parents=True, exist_ok=True)
    uni = select_g_universe(n=n_universe, include_twse_top100=True)
    symbols = uni["stock_id"].astype(str).tolist()
    for sid in MUST_INCLUDE:
        if sid not in symbols:
            symbols.append(sid)

    bases = ("leave_zero_blue_tri", "ma60_lower_confirmed")
    wave_keys = (
        "W_pullbase",
        "W_w2",
        "W_base",
        "W_not_crash",
        "W_w3_zone",
        "W_score50",
        "W_pullbase_score",
    )
    bucket: Dict[str, List[Dict[str, Any]]] = {}
    meta_n = 0
    errors: List[str] = []

    for sid in symbols:
        try:
            raw = load_stock_ohlcv(sid)
            if len(raw) < 150:
                continue
            meta_n += 1
            # Capitalized for wave engine
            ohlcv = raw.copy()
            df = _normalize_ohlc(raw)
            wave_raw = _wave_frame(ohlcv)
            wave = _align_wave(df, wave_raw)
            wmasks = _wave_masks(wave)
            masks = _build_mark_masks(df)
            feat = _feature_frame(df)
            hl, temp_label = _build_hl_temp(df)
            seed = abs(hash(sid)) % (2**32)

            # 純波浪進場（W3 起漲）— 稀有
            w3e = wmasks["W_w3_start"].fillna(False)
            key = "entry_W3_start__W0"
            bucket.setdefault(key, []).extend(
                _simulate_trades(df, w3e, hl=hl, temp_label=temp_label, sid=sid, entry_tag=key)
            )
            rnd = _random_matched(w3e, pd.Series(True, index=df.index), seed=seed)
            bucket.setdefault("random__entry_W3_start__W0", []).extend(
                _simulate_trades(df, rnd, hl=hl, temp_label=temp_label, sid=sid, entry_tag="random_w3")
            )

            for base_tag in bases:
                base_m = masks.get(base_tag)
                if base_m is None:
                    continue
                base_m = base_m.fillna(False).astype(bool)
                # F0：無波浪
                for wname in ("W0_none",) + wave_keys:
                    if wname == "W0_none":
                        fmask = pd.Series(True, index=df.index)
                    else:
                        fmask = wmasks[wname].fillna(False).astype(bool)
                    # 疊一層實用結構：未貼 20高（與先前 tighten 一致）
                    fmask = fmask & feat["room_to_hi20"].fillna(False)
                    entry = base_m & fmask
                    key = f"{base_tag}__{wname}"
                    bucket.setdefault(key, []).extend(
                        _simulate_trades(
                            df, entry, hl=hl, temp_label=temp_label, sid=sid, entry_tag=key
                        )
                    )
                    rnd = _random_matched(
                        entry,
                        fmask if wname != "W0_none" else pd.Series(True, index=df.index),
                        seed=seed + len(wname) + len(base_tag),
                    )
                    bucket.setdefault(f"random__{key}", []).extend(
                        _simulate_trades(
                            df, rnd, hl=hl, temp_label=temp_label, sid=sid, entry_tag=f"random__{key}"
                        )
                    )

                # 共振：leave/ma60 + 拉回底 + 附近確認紅箭
                m60 = masks.get("ma60_lower_confirmed", pd.Series(False, index=df.index)).fillna(False)
                near_m60 = m60.copy()
                for k in range(1, 6):
                    near_m60 = near_m60 | m60.shift(k).fillna(False) | m60.shift(-k).fillna(False)
                combo = base_m & wmasks["W_pullbase"].fillna(False) & near_m60 & feat["room_to_hi20"].fillna(False)
                # leave_zero 才加 near_m60；ma60 自身已是
                if base_tag == "ma60_lower_confirmed":
                    combo = base_m & wmasks["W_pullbase"].fillna(False) & feat["vol_ok"].fillna(False) & feat["room_to_hi20"].fillna(False)
                key = f"{base_tag}__W_pullbase_plus"
                bucket.setdefault(key, []).extend(
                    _simulate_trades(df, combo, hl=hl, temp_label=temp_label, sid=sid, entry_tag=key)
                )
                rnd = _random_matched(combo, wmasks["W_pullbase"].fillna(False) & feat["room_to_hi20"].fillna(False), seed=seed + 99)
                bucket.setdefault(f"random__{key}", []).extend(
                    _simulate_trades(df, rnd, hl=hl, temp_label=temp_label, sid=sid, entry_tag=f"random__{key}")
                )
        except Exception as e:
            errors.append(f"{sid}:{type(e).__name__}:{e}")

    by_key = {k: _agg_trades(v) for k, v in bucket.items()}
    lz0 = by_key.get("leave_zero_blue_tri__W0_none") or {}

    ranking = []
    for key, st in by_key.items():
        if key.startswith("random__"):
            continue
        rkey = f"random__{key}"
        rnd = by_key.get(rkey) or {}
        days = int(st.get("n_unique_entry_days") or 0)
        ok_n = days >= 20
        beats_random = bool(
            ok_n
            and np.isfinite(st.get("expectancy", np.nan))
            and np.isfinite(rnd.get("expectancy", np.nan))
            and float(st["expectancy"]) > float(rnd["expectancy"])
            and float(st["win_rate"]) > float(rnd["win_rate"])
        )
        beats_lz0 = bool(
            ok_n
            and lz0
            and np.isfinite(lz0.get("expectancy", np.nan))
            and float(st.get("expectancy", np.nan)) > float(lz0["expectancy"])
            and float(st.get("win_rate", np.nan)) >= float(lz0["win_rate"]) - 0.005
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
                "beats_leave_zero_F0": beats_lz0,
                "E_minus_random": (
                    float(st["expectancy"]) - float(rnd["expectancy"])
                    if ok_n
                    and np.isfinite(st.get("expectancy", np.nan))
                    and np.isfinite(rnd.get("expectancy", np.nan))
                    else float("nan")
                ),
                "win_minus_random": (
                    float(st["win_rate"]) - float(rnd["win_rate"])
                    if ok_n
                    and np.isfinite(st.get("win_rate", np.nan))
                    and np.isfinite(rnd.get("win_rate", np.nan))
                    else float("nan")
                ),
            }
        )

    ranking.sort(
        key=lambda r: (
            int(r.get("beats_random") or 0),
            int(r.get("beats_leave_zero_F0") or 0),
            float(r["E_minus_random"]) if np.isfinite(r.get("E_minus_random", np.nan)) else -9,
            float(r.get("expectancy") or -9),
        ),
        reverse=True,
    )
    winners = [r for r in ranking if r.get("beats_random") and r.get("beats_leave_zero_F0")]
    gate = (
        f"winners={len(winners)}/{len(ranking)}; "
        f"best={ranking[0]['key'] if ranking else None} "
        f"win={ranking[0].get('win_rate') if ranking else None} "
        f"E={ranking[0].get('expectancy') if ranking else None} "
        f"vs_rand_E={ranking[0].get('E_minus_random') if ranking else None}; "
        f"promote_lookup=NO"
    )
    out = {
        "phone_sync": PHONE_SYNC,
        "not_buy_signal": NOT_BUY_SIGNAL,
        "elapsed_s": round(time.time() - t0, 1),
        "n_stocks": meta_n,
        "method_zh": "話筒進場×蕭氏波浪狀態濾網；出場同 phone_trade；對照＝同波浪條件密度隨機；不畫話筒浪號",
        "leave_zero_W0": lz0,
        "ranking": ranking,
        "winners_beat_random_and_lz0": winners,
        "promote_to_lookup_display": False,
        "gate_one_liner": gate,
        "wave_filter_defs_zh": {
            "W0_none": "無波浪條件（僅未貼20高）",
            "W_pullbase": "BASE_BOTTOM 或 WAVE_2_PULLBACK",
            "W_w2": "僅 WAVE_2_PULLBACK",
            "W_base": "僅 BASE_BOTTOM",
            "W_not_crash": "排除 A/B/C 下跌陷阱段",
            "W_w3_zone": "WAVE_3_MAIN 或 W3起漲近3根",
            "W_score50": "hsiao_score_eff≥50",
            "W_pullbase_score": "拉回／築底且分數≥50",
            "W_pullbase_plus": "拉回／築底＋結構加分（leave 需近確認紅箭）",
            "entry_W3_start": "純 LAB_BUY_W3_START 進場",
        },
        "errors_n": len(errors),
        "errors_sample": errors[:10],
        "note_zh": "波浪只當實驗室濾網；不過閘不准上查股浪號／5／9。",
    }
    text = json.dumps(out, ensure_ascii=False, indent=2, default=str)
    (ART / "phone_wave_filter_latest.json").write_text(text, encoding="utf-8")
    (DOC / "phone_wave_filter_latest.json").write_text(text, encoding="utf-8")
    print("GATE", gate, flush=True)
    print("TOP", json.dumps(ranking[:8], ensure_ascii=False, default=str), flush=True)
    print("WINNERS", len(winners), flush=True)
    return out


if __name__ == "__main__":
    run_wave_filter()
