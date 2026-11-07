# -*- coding: utf-8 -*-
"""蕭氏實驗室一鍵入口 V7（不是買訊；phone_sync=blocked）。

流程：preprocess → features → wave → predict → backtest（多方／多空對比）→ walk-forward
不上話筒、不改黃金買點。
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, Optional

import pandas as pd

from scripts.decade_lab_hsiao_backtest import compare_long_only_vs_long_short
from scripts.decade_lab_hsiao_data_preprocessor import prepare_ohlcv
from scripts.decade_lab_hsiao_predictor import assert_lab_isolation, run_hsiao_lab_predict
from scripts.decade_lab_hsiao_quant_features import compute_hsiao_features
from scripts.decade_lab_hsiao_walk_forward import walk_forward_expanding
from scripts.decade_lab_hsiao_wave_engine import ElliottHsiaoEngine

PHONE_SYNC = "blocked"
NOT_BUY_SIGNAL = True
OUT_DIR = Path("docs/expert_notes/飆客/decade_lab")


def run_pipeline(
    ohlcv: pd.DataFrame,
    *,
    symbol: str = "SYM",
    benchmark_df: Optional[pd.DataFrame] = None,
    do_walk_forward: bool = True,
    out_dir: Optional[Path] = None,
) -> Dict[str, Any]:
    out_dir = Path(out_dir) if out_dir else OUT_DIR
    out_dir.mkdir(parents=True, exist_ok=True)

    prep = prepare_ohlcv(ohlcv)
    feat = compute_hsiao_features(prep)
    pred = run_hsiao_lab_predict(feat, already_featured=True, preprocess=False)
    assert_lab_isolation(pred)

    cmp = compare_long_only_vs_long_short(
        ohlcv, symbol=symbol, benchmark_df=benchmark_df
    )
    wf = None
    if do_walk_forward and isinstance(feat.index, pd.DatetimeIndex) and len(feat) > 300:
        # 附 rs 欄若缺
        if "rs_20d" not in feat.columns:
            feat = feat.copy()
            feat["rs_20d"] = 0.0
        wf = walk_forward_expanding(feat)

    payload = {
        "symbol": symbol,
        "preprocessor_version": prep.attrs.get("preprocessor_version"),
        "feature_version": feat.attrs.get("feature_version"),
        "engine_version": pred["labeled"].attrs.get("engine_version"),
        "predict_summary": pred["summary"],
        "compare_report": cmp["report"],
        "walk_forward": None if wf is None else wf["summary"],
        "corp_action_n": int(prep.attrs.get("corp_action_events") and len(prep.attrs["corp_action_events"]) or prep.get("corp_action_n", pd.Series([0])).iloc[0]),
        "not_buy_signal": True,
        "phone_sync": PHONE_SYNC,
        "pipeline_version": "hsiao_v7",
    }
    out_path = out_dir / f"hsiao_pipeline_{symbol}_latest.json"
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    payload["out_path"] = str(out_path)
    return payload


def _load_csv(path: str) -> pd.DataFrame:
    df = pd.read_csv(path)
    # 嘗試解析日期
    for c in ("date", "Date", "datetime", "Datetime"):
        if c in df.columns:
            df[c] = pd.to_datetime(df[c])
            df = df.set_index(c)
            break
    return df


def main(argv: Optional[list] = None) -> int:
    p = argparse.ArgumentParser(description="Hsiao lab pipeline V7 (not buy signal)")
    p.add_argument("--csv", required=True, help="OHLCV CSV path")
    p.add_argument("--symbol", default="SYM")
    p.add_argument("--benchmark-csv", default="")
    p.add_argument("--no-walk-forward", action="store_true")
    args = p.parse_args(argv)
    ohlcv = _load_csv(args.csv)
    bench = _load_csv(args.benchmark_csv) if args.benchmark_csv else None
    out = run_pipeline(
        ohlcv,
        symbol=args.symbol,
        benchmark_df=bench,
        do_walk_forward=not args.no_walk_forward,
    )
    print(json.dumps({k: out[k] for k in out if k != "predict_summary"}, ensure_ascii=False, indent=2, default=str))
    print("phone_sync=", out["phone_sync"], "not_buy_signal=", out["not_buy_signal"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
