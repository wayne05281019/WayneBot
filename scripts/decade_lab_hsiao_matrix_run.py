# -*- coding: utf-8 -*-
"""蕭氏實驗室多檔矩陣（雲端；不上話筒）。

母體＝上市近似前百大權值 ∪ 點名五檔（光聖／台光電／台燿／聯亞／群聯）。
每股只算一次特徵，A0–A3 共用；樣本不足自動降門檻／加檔／加嚴流動篩選後整包重跑。
只寫精簡 JSON。
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

from scripts.decade_lab_hsiao_backtest import run_single_backtest
from scripts.decade_lab_hsiao_data_preprocessor import prepare_ohlcv
from scripts.decade_lab_hsiao_quant_features import compute_hsiao_features
from scripts.decade_lab_hsiao_universe import (
    MUST_INCLUDE,
    load_stock_ohlcv,
    load_twii,
    select_g_universe,
)
from scripts.decade_lab_hsiao_wave_engine import ENTRY_PRESETS, ElliottHsiaoEngine

PHONE_SYNC = "blocked"
NOT_BUY_SIGNAL = True
ROOT = Path(__file__).resolve().parents[1]
ART = Path("/opt/cursor/artifacts")
DOC = ROOT / "docs" / "expert_notes" / "飆客" / "decade_lab"
PRESETS_DEFAULT = ("A0_strict", "A1_score", "A2_hammer_kd", "A3_squeeze")


def _passes_extra_filters(
    ohlcv: pd.DataFrame,
    feat: pd.DataFrame,
    *,
    avg_turnover_k: float = float("nan"),
    min_turnover_k: float = 1_500_000.0,
) -> Tuple[bool, str]:
    """跑完一看就覺得該加的篩選（實驗室自訂）。流動主看 turnover_k。"""
    if len(ohlcv) < 120:
        return False, "too_short"
    if np.isfinite(avg_turnover_k) and avg_turnover_k < min_turnover_k:
        return False, "low_turnover_k"
    tail = ohlcv.tail(60)
    if float(tail["Close"].mean()) < 12:
        return False, "penny"
    if "is_limit_down_locked" in feat.columns:
        lock_rate = float(feat["is_limit_down_locked"].fillna(False).astype(float).tail(120).mean())
        if lock_rate > 0.08:
            return False, "too_many_limit_locks"
    if "block_new_entries" in feat.columns:
        if float(feat["block_new_entries"].fillna(False).astype(float).tail(60).mean()) > 0.15:
            return False, "illiquid_anomaly_heavy"
    return True, "ok"


def _entry_days_from_labeled(labeled: pd.DataFrame) -> set:
    days = set()
    if "lab_signal" not in labeled.columns:
        return days
    m = labeled["lab_signal"].astype(str) == "LAB_BUY_W3_START"
    for ts in labeled.index[m]:
        days.add(str(pd.Timestamp(ts).date()))
    return days


def _bt_from_labeled(
    labeled: pd.DataFrame,
    *,
    symbol: str,
    allow_short: bool,
) -> Dict[str, Any]:
    """用已標註表跑簡化回測（呼叫完整 backtest 會重算特徵；這裡直接掃訊號）。"""
    # 重用完整 backtest 路徑但傳入已特徵？目前 run_single 會重算。
    # 為省時間：只統計訊號日＋用完整 backtest 僅在有訊號或點名檔時。
    return {
        "entry_days": sorted(_entry_days_from_labeled(labeled)),
        "n_w3": int((labeled["lab_signal"].astype(str) == "LAB_BUY_W3_START").sum())
        if "lab_signal" in labeled.columns
        else 0,
        "n_short": int((labeled["lab_signal"].astype(str) == "LAB_SHORT_W_C_START").sum())
        if "lab_signal" in labeled.columns
        else 0,
        "last_state": str(labeled["state_name"].iloc[-1]) if len(labeled) else None,
    }


def run_matrix(
    *,
    presets: Sequence[str] = PRESETS_DEFAULT,
    allow_short: bool = False,
    target_entry_days: int = 20,
    score_threshold: float = 55.0,
    expand_n: int = 100,
    max_expand_rounds: int = 3,
    full_backtest_on_signals: bool = True,
) -> Dict[str, Any]:
    t0 = time.time()
    ART.mkdir(parents=True, exist_ok=True)
    DOC.mkdir(parents=True, exist_ok=True)
    twii = load_twii()
    rounds: List[Dict[str, Any]] = []
    final: Dict[str, Any] = {}
    thr = float(score_threshold)
    n_target = int(expand_n)
    # 流動門檻（turnover_k）可隨輪次放寬
    min_tk = 1_500_000.0

    for rnd in range(max_expand_rounds + 1):
        uni = select_g_universe(n=n_target, include_twse_top100=True, min_avg_turnover_k=min_tk)
        must_ok = {sid: bool((uni.stock_id == sid).any()) for sid in MUST_INCLUDE}
        symbols = uni["stock_id"].astype(str).tolist()
        tk_map = {
            str(r.stock_id): float(r.avg_turnover_k)
            for r in uni.itertuples()
            if np.isfinite(getattr(r, "avg_turnover_k", np.nan))
        }
        top100_set = set(
            str(r.stock_id)
            for r in uni.itertuples()
            if bool(getattr(r, "in_twse_top100_approx", False))
        )
        keep_anyway = set(MUST_INCLUDE) | top100_set  # 點名＋近似百大權值：流動門檻不擋

        # 每股：準備＋特徵一次
        cache: Dict[str, Dict[str, Any]] = {}
        skip_counts: Dict[str, int] = {}
        for sid in symbols:
            try:
                ohlcv = load_stock_ohlcv(sid)
                if len(ohlcv) < 120:
                    skip_counts["too_short"] = skip_counts.get("too_short", 0) + 1
                    continue
                prep = prepare_ohlcv(ohlcv)
                feat = compute_hsiao_features(prep)
                # 百大／點名：只擋極端 penny／鎖死，不因歷史均 turnover 被剔除
                min_tk_sid = 0.0 if sid in keep_anyway else min_tk
                ok, reason = _passes_extra_filters(
                    ohlcv, feat, avg_turnover_k=tk_map.get(sid, float("nan")), min_turnover_k=min_tk_sid
                )
                if (not ok) and sid not in keep_anyway:
                    skip_counts[reason] = skip_counts.get(reason, 0) + 1
                    continue
                cache[sid] = {
                    "ohlcv": ohlcv,
                    "feat": feat,
                    "name": MUST_INCLUDE.get(sid)
                    or (
                        str(uni.loc[uni.stock_id == sid, "stock_name"].iloc[0])
                        if (uni.stock_id == sid).any()
                        else sid
                    ),
                    "filter_reason_if_must_fail": None if ok else reason,
                    "data_source": ohlcv.attrs.get("source"),
                    "data_years": ohlcv.attrs.get("years"),
                    "data_span": ohlcv.attrs.get("span"),
                    "data_adj_kind": ohlcv.attrs.get("adj_kind"),
                }
            except Exception as e:
                skip_counts["error"] = skip_counts.get("error", 0) + 1
                cache[sid] = {"error": f"{type(e).__name__}: {e}"}

        preset_rows = []
        all_entry_days = set()
        must_stats: Dict[str, Dict[str, Any]] = {sid: {} for sid in MUST_INCLUDE}

        for preset in presets:
            if preset not in ENTRY_PRESETS:
                continue
            entry_days = set()
            n_w3_total = 0
            active = []
            for sid, blob in cache.items():
                if "error" in blob and "feat" not in blob:
                    continue
                feat = blob["feat"]
                eng = ElliottHsiaoEngine(entry_preset=preset, score_threshold=thr)
                labeled = eng.run(feat, already_featured=True)
                info = _bt_from_labeled(labeled, symbol=sid, allow_short=allow_short)
                ed = set(info["entry_days"])
                entry_days |= ed
                all_entry_days |= ed
                n_w3_total += info["n_w3"]
                row = {
                    "stock_id": sid,
                    "name": blob.get("name"),
                    "n_w3": info["n_w3"],
                    "n_short": info["n_short"],
                    "entry_days": info["n_w3"],
                    "last_state": info["last_state"],
                }
                # 有訊號或點名 → 可選跑完整回測（含摩擦）
                if full_backtest_on_signals and (info["n_w3"] > 0 or sid in MUST_INCLUDE):
                    try:
                        bench = twii.reindex(blob["ohlcv"].index).ffill()
                        bt = run_single_backtest(
                            blob["ohlcv"],
                            symbol=sid,
                            benchmark_df=bench,
                            allow_short=allow_short,
                            entry_preset=preset,
                            score_threshold=thr,
                        )
                        row.update(
                            {
                                "n_trades": bt.summary["n_trades"],
                                "total_return": bt.summary["total_return"],
                                "max_drawdown": bt.summary["max_drawdown"],
                            }
                        )
                    except Exception as e:
                        row["bt_error"] = f"{type(e).__name__}: {e}"
                if info["n_w3"] > 0 or sid in MUST_INCLUDE:
                    active.append(row)
                if sid in MUST_INCLUDE:
                    must_stats[sid][preset] = row

            preset_rows.append(
                {
                    "preset": preset,
                    "score_threshold": thr,
                    "n_symbols_cached": len(cache),
                    "n_symbols_with_w3": sum(1 for r in active if r.get("n_w3", 0) > 0),
                    "n_w3_signals": n_w3_total,
                    "n_unique_entry_days": len(entry_days),
                    "active_stocks": active[:100],
                }
            )

        round_sum = {
            "round": rnd,
            "n_universe_listed": len(symbols),
            "n_cached_after_filter": len([1 for v in cache.values() if "feat" in v]),
            "score_threshold": thr,
            "min_turnover_k": min_tk,
            "skip_counts": skip_counts,
            "must_ok": must_ok,
            "n_unique_entry_days_all_presets": len(all_entry_days),
            "presets": preset_rows,
            "must_named_stats": {
                sid: {"name": MUST_INCLUDE[sid], **must_stats.get(sid, {})} for sid in MUST_INCLUDE
            },
        }
        rounds.append(round_sum)
        final = round_sum
        print(
            f"[round {rnd}] listed={len(symbols)} cached={round_sum['n_cached_after_filter']} "
            f"thr={thr} entry_days={len(all_entry_days)} skip={skip_counts} must={must_ok}",
            flush=True,
        )
        if len(all_entry_days) >= target_entry_days:
            break
        # 擴大策略：先降分門檻；再加檔；turnover 門檻略降
        thr = max(40.0, thr - 5.0)
        n_target = min(220, n_target + 40)
        min_tk = max(800_000.0, min_tk * 0.75)
        print(f"  expand → thr={thr} n={n_target} min_tk={min_tk:.0f}", flush=True)

    out = {
        "phone_sync": PHONE_SYNC,
        "not_buy_signal": NOT_BUY_SIGNAL,
        "elapsed_s": round(time.time() - t0, 1),
        "must_include": MUST_INCLUDE,
        "target_entry_days": target_entry_days,
        "met_target": final.get("n_unique_entry_days_all_presets", 0) >= target_entry_days,
        "extra_filters": [
            "min_bars>=120",
            "turnover_k gate (adaptive; 百大／點名不擋)",
            "avg_close>=12 (must-include／百大 exempt from turnover)",
            "limit_lock_rate<=8% (must-include／百大 exempt)",
            "illiquid_anomaly gate (must-include／百大 exempt)",
        ],
        "rounds": rounds,
        "final": final,
        "note_zh": "雲端實驗室；百大≈實收資本×收盤；五檔強制；用各檔真實最長窗；來源寫明；不上話筒",
    }
    data_honesty = {}
    for _sid in MUST_INCLUDE:
        try:
            _df = load_stock_ohlcv(_sid)
            data_honesty[_sid] = {
                "name": MUST_INCLUDE[_sid],
                "source": _df.attrs.get("source"),
                "years": _df.attrs.get("years"),
                "span": _df.attrs.get("span"),
                "adj_kind": _df.attrs.get("adj_kind"),
            }
        except Exception as e:
            data_honesty[_sid] = {"name": MUST_INCLUDE[_sid], "error": f"{type(e).__name__}: {e}"}
    out["data_honesty"] = data_honesty
    text = json.dumps(out, ensure_ascii=False, indent=2, default=str)
    (ART / "hsiao_matrix_g_latest.json").write_text(text, encoding="utf-8")
    (DOC / "hsiao_matrix_g_latest.json").write_text(text, encoding="utf-8")
    summary = {
        "met_target": out["met_target"],
        "elapsed_s": out["elapsed_s"],
        "final_entry_days": final.get("n_unique_entry_days_all_presets"),
        "n_cached": final.get("n_cached_after_filter"),
        "score_threshold": final.get("score_threshold"),
        "skip_counts": final.get("skip_counts"),
        "must_ok": final.get("must_ok"),
        "presets": [
            {
                "preset": p["preset"],
                "n_unique_entry_days": p["n_unique_entry_days"],
                "n_w3_signals": p["n_w3_signals"],
                "n_symbols_with_w3": p["n_symbols_with_w3"],
            }
            for p in final.get("presets", [])
        ],
        "must_named": {
            sid: {
                "name": MUST_INCLUDE[sid],
                **{
                    k: {"n_w3": v.get("n_w3"), "total_return": v.get("total_return"), "n_trades": v.get("n_trades")}
                    for k, v in final.get("must_named_stats", {}).get(sid, {}).items()
                    if k != "name"
                },
            }
            for sid in MUST_INCLUDE
        },
        "phone_sync": PHONE_SYNC,
    }
    (ART / "hsiao_matrix_g_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print("SUMMARY", json.dumps(summary, ensure_ascii=False), flush=True)
    return out


if __name__ == "__main__":
    run_matrix(allow_short=False, target_entry_days=20)
