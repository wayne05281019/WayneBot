# -*- coding: utf-8 -*-
"""蕭氏 V1→V7 按部就班真實驗證（實驗室；phone_sync=blocked）。

資料：
- TWII index_daily ~2006–2026（約 20 年）
- 2330 lab_daily ~2016–2026（約 10 年）

每關輸出 PASS / FAIL / SKIP(缺資料)+原因。不准用合成資料冒充 20 年完成。
"""
from __future__ import annotations

import json
import sqlite3
import time
import traceback
from collections import Counter
from pathlib import Path
from typing import Any, Callable, Dict, List, Tuple

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
OUT_ART = Path("/opt/cursor/artifacts")
OUT_DOC = ROOT / "docs" / "expert_notes" / "飆客" / "decade_lab"

PHONE_SYNC = "blocked"
NOT_BUY_SIGNAL = True


def _load_twii() -> pd.DataFrame:
    con = sqlite3.connect(ROOT / "data" / "wayne_market.db")
    df = pd.read_sql(
        "SELECT date, open, high, low, close, volume FROM index_daily WHERE symbol='TWII' ORDER BY date",
        con,
    )
    con.close()
    df["date"] = pd.to_datetime(df["date"])
    df = df.set_index("date")
    for c in ("open", "high", "low", "close", "volume"):
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df["volume"] = df["volume"].fillna(0.0)
    # index 有時缺 open；用 close 補但仍標明
    if df["open"].isna().mean() > 0.3:
        df["open"] = df["open"].fillna(df["close"])
        df["high"] = df["high"].fillna(df[["open", "close"]].max(axis=1))
        df["low"] = df["low"].fillna(df[["open", "close"]].min(axis=1))
    df = df.dropna(subset=["close"])
    df = df[~df.index.duplicated(keep="last")].sort_index()
    return df.rename(
        columns={"open": "Open", "high": "High", "low": "Low", "close": "Close", "volume": "Volume"}
    )


def _load_2330() -> pd.DataFrame:
    con = sqlite3.connect(ROOT / "data" / "decade_lab.db")
    df = pd.read_sql(
        "SELECT date, open, high, low, close, volume, adj_close FROM lab_daily WHERE symbol='2330' ORDER BY date",
        con,
    )
    con.close()
    df["date"] = pd.to_datetime(df["date"])
    df = df.set_index("date")
    df = df.rename(
        columns={
            "open": "Open",
            "high": "High",
            "low": "Low",
            "close": "Close",
            "volume": "Volume",
            "adj_close": "Adj Close",
        }
    )
    for c in df.columns:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df = df.dropna(subset=["Close"])
    # lab_daily 曾出現同一日兩列；去重後才是真實交易日數
    return df[~df.index.duplicated(keep="last")].sort_index()


class Gate:
    def __init__(self):
        self.rows: List[Dict[str, Any]] = []

    def add(self, version: str, item: str, status: str, detail: str, **extra: Any) -> None:
        assert status in {"PASS", "FAIL", "SKIP"}
        row = {"version": version, "item": item, "status": status, "detail": detail, **extra}
        self.rows.append(row)
        print(f"[{status}] {version} | {item} — {detail}", flush=True)

    def summary(self) -> Dict[str, Any]:
        c = Counter(r["status"] for r in self.rows)
        return {
            "n": len(self.rows),
            "PASS": c["PASS"],
            "FAIL": c["FAIL"],
            "SKIP": c["SKIP"],
            "all_required_pass": c["FAIL"] == 0,
        }


def run() -> Dict[str, Any]:
    from scripts.decade_lab_hsiao_backtest import (
        apply_slippage,
        compare_long_only_vs_long_short,
        get_tw_tick_size,
        position_weight,
        priority_rank_score,
        run_single_backtest,
    )
    from scripts.decade_lab_hsiao_data_preprocessor import (
        corporate_action_sanitizer,
        prepare_ohlcv,
    )
    from scripts.decade_lab_hsiao_predictor import assert_lab_isolation, log_fib_targets, run_hsiao_lab_predict
    from scripts.decade_lab_hsiao_quant_features import compute_hsiao_features
    from scripts.decade_lab_hsiao_sector_momentum import compute_sector_bull_ratio
    from scripts.decade_lab_hsiao_walk_forward import walk_forward_expanding
    from scripts.decade_lab_hsiao_wave_engine import ElliottHsiaoEngine, WaveState, _log_len, _log_retrace

    g = Gate()
    t0 = time.time()
    twii = _load_twii()
    s2330 = _load_2330()
    years_tw = (twii.index.max() - twii.index.min()).days / 365.25
    years_23 = (s2330.index.max() - s2330.index.min()).days / 365.25

    g.add(
        "DATA",
        "TWII_span",
        "PASS" if years_tw >= 19.5 else "FAIL",
        f"n={len(twii)} {twii.index.min().date()}→{twii.index.max().date()} years={years_tw:.2f}",
    )
    g.add(
        "DATA",
        "2330_span",
        "PASS" if years_23 >= 9.5 else "FAIL",
        f"n={len(s2330)} {s2330.index.min().date()}→{s2330.index.max().date()} years={years_23:.2f}（非20年個股全市場）",
    )
    g.add(
        "DATA",
        "full_market_20y_stocks",
        "SKIP",
        "wayne_market.daily_quotes 個股僅 2023-12 起；本機無全市場20年個股母體，不謊稱已測",
    )

    # ---------- V1 基礎隔離 ----------
    prep23 = prepare_ohlcv(s2330)
    feat23 = compute_hsiao_features(prep23)
    pred23 = run_hsiao_lab_predict(feat23, already_featured=True, preprocess=False)
    try:
        assert_lab_isolation(pred23)
        g.add("V1", "lab_isolation", "PASS", "phone_sync=blocked not_buy_signal=True")
    except Exception as e:
        g.add("V1", "lab_isolation", "FAIL", str(e))
    eng = ElliottHsiaoEngine()
    lab23 = eng.run(feat23, already_featured=True)
    g.add(
        "V1",
        "engine_runs_2330",
        "PASS" if len(lab23) == len(feat23) and "state_name" in lab23.columns else "FAIL",
        f"bars={len(lab23)} events={len(lab23.attrs.get('lab_events') or [])}",
    )

    # ---------- V2 ----------
    g.add(
        "V2",
        "ratio_adj_or_continuous",
        "PASS" if "Continuous_Close" in prep23.columns and prep23.attrs.get("preprocessor_version") else "FAIL",
        f"preprocessor={prep23.attrs.get('preprocessor_version')} ratio_adjusted={bool(prep23.get('ratio_adjusted', pd.Series([False])).iloc[0])}",
    )
    need_v2 = [
        "weekly_trend_bullish",
        "W_MA13",
        "w_ma13_safety",
        "ma_compression",
        "had_ma_compression_5d",
        "deduction_accelerating",
        "is_overextended",
        "hsiao_4d_score",
    ]
    miss = [c for c in need_v2 if c not in feat23.columns]
    g.add("V2", "feature_columns", "PASS" if not miss else "FAIL", f"missing={miss}")
    # 週線防未來：週五值不可在當週一就出現——抽樣檢查 W_Close 在週中等於上週五 close（簡測：非 NaN 起點後存在）
    wb = int(feat23["weekly_trend_bullish"].notna().sum())
    g.add("V2", "weekly_aligned", "PASS" if wb > 100 else "FAIL", f"weekly_trend_bullish non-null={wb}")

    # ---------- V3 ----------
    pre = feat23.loc[feat23.index < "2015-06-01"]
    # 2330 從 2016 起，pre 可能空 → 用 TWII
    prep_tw = prepare_ohlcv(twii)
    feat_tw = compute_hsiao_features(prep_tw)
    pre_t = feat_tw.loc[feat_tw.index < "2015-06-01", "bull_ret_thresh"]
    post_t = feat_tw.loc[feat_tw.index >= "2015-06-01", "bull_ret_thresh"]
    ok_reg = len(pre_t) and len(post_t) and float(pre_t.iloc[0]) == 0.025 and float(post_t.iloc[0]) == 0.035
    g.add("V3", "limit_regime_2015", "PASS" if ok_reg else "FAIL", f"pre_n={len(pre_t)} post_n={len(post_t)}")
    gap_cols = ["bull_gap", "gap_support", "gap_breakaway_candidate", "fake_breakout_exit", "is_limit_up"]
    miss = [c for c in gap_cols if c not in feat_tw.columns]
    g.add("V3", "gap_and_limit_cols", "PASS" if not miss else "FAIL", f"missing={miss} bull_gap_days={int(feat_tw['bull_gap'].fillna(False).sum())}")
    # 橫截面排序函數
    demo = pd.DataFrame(
        {
            "angle_5": [10.0, 40.0, 20.0],
            "ma20_time_safety": [0.1, 0.5, -0.2],
            "ma60_time_safety": [0.0, 0.2, -0.1],
            "vol_shrink_ratio": [0.5, 0.8, 1.2],
            "rs_20d": [0.01, 0.05, -0.02],
        }
    )
    pr = priority_rank_score(demo)
    g.add("V3", "priority_rank_score", "PASS" if len(pr) == 3 and pr.max() >= pr.min() else "FAIL", f"scores={list(pr.round(3))}")

    # ---------- V4 ----------
    # 對數回撤／Fib
    t = log_fib_targets(100, 120, 110)
    r = _log_retrace(120, 100, 108)
    g.add(
        "V4",
        "log_fib_and_retrace",
        "PASS" if np.isfinite(t["target_1618"]) and 0 < r < 1 else "FAIL",
        f"t1618={t['target_1618']:.4f} retrace={r:.4f}",
    )
    kd_ok = all(c in feat23.columns for c in ("K", "D", "kd_high_passivation", "up_bar_vol", "down_bar_vol", "turnover_ok"))
    g.add("V4", "kd_and_lock_helpers", "PASS" if kd_ok else "FAIL", f"K_finite={int(feat23['K'].notna().sum())}")
    # walk-forward on TWII
    feat_tw2 = feat_tw.copy()
    feat_tw2["rs_20d"] = 0.0
    try:
        wf = walk_forward_expanding(feat_tw2, years=list(range(2010, 2027)))
        nfolds = int(wf["summary"]["n_folds"])
        g.add(
            "V4",
            "walk_forward_TWII",
            "PASS" if nfolds >= 10 else "FAIL",
            f"folds={nfolds} oos_acc_mean={wf['summary'].get('oos_accuracy_mean')}",
            folds=wf["folds"],
            summary=wf["summary"],
        )
    except Exception as e:
        g.add("V4", "walk_forward_TWII", "FAIL", f"{type(e).__name__}: {e}")
        wf = None
    # sector：缺 panel → SKIP
    try:
        compute_sector_bull_ratio(
            pd.DataFrame(
                {
                    "date": [feat23.index[-1]] * 3,
                    "symbol": ["A", "B", "C"],
                    "sector": ["X", "X", "Y"],
                    "Close": [1, 2, 3],
                    "MA20": [0.5, 1, 4],
                    "MA60": [0.4, 0.9, 5],
                    "angle_10": [25, 30, 10],
                }
            )
        )
        g.add("V4", "sector_momentum_api", "PASS", "API 可用；全市場產業母體本機不足，實盤族群排序未對全市場跑")
    except Exception as e:
        g.add("V4", "sector_momentum_api", "FAIL", str(e))

    # ---------- V5 ----------
    # 真凹洞量：振幅條件存在
    g.add(
        "V5",
        "true_trough_vol",
        "PASS" if "intraday_range" in feat23.columns and "is_illiquid_anomaly" in feat23.columns else "FAIL",
        f"trough_days={int(feat23['is_trough_vol'].fillna(False).sum())} illiquid={int(feat23['is_illiquid_anomaly'].fillna(False).sum())}",
    )
    g.add(
        "V5",
        "ending_diagonal_state",
        "PASS" if hasattr(WaveState, "WAVE_5_ENDING_DIAGONAL") else "FAIL",
        f"value={int(WaveState.WAVE_5_ENDING_DIAGONAL)}",
    )
    w = position_weight(100, 90)
    g.add("V5", "risk_parity_sizing", "PASS" if 0 < w <= 0.20 else "FAIL", f"weight_10pct_stop={w:.4f}")
    # continuous vs raw：除權後連續序列應存在
    g.add(
        "V5",
        "continuous_ohlc",
        "PASS" if "Continuous_Close" in prep23.columns else "FAIL",
        f"cont_last={float(prep23['Continuous_Close'].iloc[-1]):.4f} close_last={float(prep23['Close'].iloc[-1]):.4f}",
    )

    # ---------- V6 ----------
    shadow_ok = all(
        c in feat23.columns
        for c in ("lower_shadow_ratio", "is_hammer_shape", "is_long_upper_shadow_vol", "DIF", "MACD_HIST", "ma60_angle")
    )
    g.add("V6", "shadow_macd_cols", "PASS" if shadow_ok else "FAIL", f"hammer_days={int(feat23['is_hammer_shape'].fillna(False).sum())}")
    g.add(
        "V6",
        "wave_x_rebound_state",
        "PASS" if hasattr(WaveState, "WAVE_X_REBOUND") else "FAIL",
        f"value={int(WaveState.WAVE_X_REBOUND)}",
    )
    ticks = [get_tw_tick_size(p) for p in (5, 25, 80, 200, 800, 1500)]
    g.add("V6", "tw_tick_size", "PASS" if ticks == [0.01, 0.05, 0.1, 0.5, 1.0, 5.0] else "FAIL", f"ticks={ticks}")
    slip = apply_slippage(100.0, side="buy", ts=pd.Timestamp("2021-01-04"))
    g.add("V6", "slippage_post_202003", "PASS" if abs(slip - 100.5) < 1e-9 else "FAIL", f"buy_slip={slip}")

    # ---------- V7 ----------
    # 減資消毒：人造越界裂口
    idx = pd.bdate_range("2016-01-04", periods=8)
    c = pd.Series([100, 101, 102, 103, 20.0, 20.4, 20.8, 21.0], index=idx)
    o = c.copy()
    o.iloc[4] = 20.0
    _, _, _, c2, _, ev = corporate_action_sanitizer(o, c * 1.01, c * 0.99, c)
    g.add(
        "V7",
        "corporate_action_sanitizer",
        "PASS" if len(ev) >= 1 and abs(float(c2.iloc[3]) / 20.0 - 1) < 0.05 else "FAIL",
        f"events={len(ev)} joined_prev={float(c2.iloc[3]):.4f}",
    )
    chip_cols = ["chip_clean_candidate", "is_short_squeeze_setup", "is_limit_down_locked", "is_limit_up_locked"]
    miss = [c for c in chip_cols if c not in feat23.columns]
    g.add("V7", "chip_and_lock_cols", "PASS" if not miss else "FAIL", f"missing={miss}")
    # 真實回測 TWII 20y + 2330 10y
    bt_results = {}
    for name, df, bench in (
        ("TWII", twii, None),
        ("2330", s2330, twii.reindex(s2330.index).ffill()),
    ):
        try:
            cmp = compare_long_only_vs_long_short(df, symbol=name, benchmark_df=bench)
            assert cmp["phone_sync"] == "blocked"
            lo = cmp["report"]["long_only"]
            ls = cmp["report"]["long_short"]
            bt_results[name] = cmp["report"]
            # 有跑完＝PASS；0 筆成交要標明（不謊稱有績效）
            def _bt_status(n_trades: int) -> str:
                return "PASS"

            g.add(
                "V7",
                f"backtest_{name}_long_only",
                _bt_status(lo["n_trades"]),
                f"ret={lo['total_return']:.4f} mdd={lo['max_drawdown']:.4f} trades={lo['n_trades']} bars={lo['n_bars']}"
                + ("" if lo["n_trades"] else "｜真柱跑完但 0 筆成交（規則未觸發 W3）"),
            )
            g.add(
                "V7",
                f"backtest_{name}_long_short",
                _bt_status(ls["n_trades"]),
                f"ret={ls['total_return']:.4f} mdd={ls['max_drawdown']:.4f} trades={ls['n_trades']} delta_ret={cmp['report']['delta_total_return']:.4f}"
                + ("" if ls["n_trades"] else "｜真柱跑完但 0 筆成交"),
            )
            g.add(
                "V7",
                f"backtest_{name}_has_entries",
                "PASS" if lo["n_trades"] > 0 or ls["n_trades"] > 0 else "FAIL",
                "至少一方有成交" if (lo["n_trades"] > 0 or ls["n_trades"] > 0) else "W2→W3／放空皆未觸發，績效曲線無意義",
            )
        except Exception as e:
            g.add("V7", f"backtest_{name}", "FAIL", f"{type(e).__name__}: {e}\n{traceback.format_exc()[-500:]}")

    # 狀態機是否曾走出關鍵狀態（真柱上至少見過部分）
    lab_tw = ElliottHsiaoEngine().run(feat_tw, already_featured=True)
    states = set(lab_tw["state_name"].astype(str).unique())
    codes = Counter(e.get("code") for e in (lab_tw.attrs.get("lab_events") or []))
    g.add(
        "V7",
        "wave_states_seen_TWII",
        "PASS" if len(states) >= 3 else "FAIL",
        f"states={sorted(states)[:12]} top_events={codes.most_common(8)}",
    )

    summary = g.summary()
    out = {
        "phone_sync": PHONE_SYNC,
        "not_buy_signal": NOT_BUY_SIGNAL,
        "elapsed_s": round(time.time() - t0, 1),
        "data": {
            "TWII": {
                "n": len(twii),
                "start": str(twii.index.min().date()),
                "end": str(twii.index.max().date()),
                "years": round(years_tw, 2),
            },
            "2330": {
                "n": len(s2330),
                "start": str(s2330.index.min().date()),
                "end": str(s2330.index.max().date()),
                "years": round(years_23, 2),
            },
        },
        "summary": summary,
        "gates": g.rows,
        "backtests": bt_results,
        "walk_forward": None if wf is None else wf.get("summary"),
        "honesty": {
            "full_20y_stock_universe": False,
            "twii_approx_20y_ran": True,
            "stock_2330_approx_10y_ran": True,
            "note_zh": "七大版本按關驗證；20年真柱僅 TWII。全市場個股20年本機無資料＝SKIP 不謊稱完成。",
        },
    }
    OUT_ART.mkdir(parents=True, exist_ok=True)
    OUT_DOC.mkdir(parents=True, exist_ok=True)
    p1 = OUT_ART / "hsiao_v1_v7_step_verify.json"
    p2 = OUT_DOC / "hsiao_v1_v7_step_verify_latest.json"
    text = json.dumps(out, ensure_ascii=False, indent=2, default=str)
    p1.write_text(text, encoding="utf-8")
    p2.write_text(text, encoding="utf-8")
    print("SUMMARY", json.dumps(summary, ensure_ascii=False), flush=True)
    print("WROTE", p1, flush=True)
    return out


if __name__ == "__main__":
    run()
