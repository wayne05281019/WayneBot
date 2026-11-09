# -*- coding: utf-8 -*-
"""蕭氏八浪實驗室預測器 V6（不是買訊；phone_sync=blocked）。

對數費波那契目標價：target_1618 / target_2618。
"""
from __future__ import annotations

from typing import Any, Dict, Optional

import numpy as np
import pandas as pd

from scripts.decade_lab_hsiao_data_preprocessor import prepare_ohlcv
from scripts.decade_lab_hsiao_quant_features import compute_hsiao_features
from scripts.decade_lab_hsiao_wave_engine import ElliottHsiaoEngine, PHONE_SYNC

NOT_BUY_SIGNAL = True


def log_fib_targets(P0: float, P1: float, P2: float) -> Dict[str, float]:
    """幾何複利擴展第 3 波目標價。"""
    out = {
        "target_1000": float("nan"),
        "target_1618": float("nan"),
        "target_2618": float("nan"),
        "log_W1": float("nan"),
    }
    if not all(np.isfinite(x) and x > 0 for x in (P0, P1, P2)):
        return out
    log_w1 = float(np.log(P1 / P0))
    out["log_W1"] = log_w1
    out["target_1000"] = float(P2 * np.exp(1.000 * log_w1))
    out["target_1618"] = float(P2 * np.exp(1.618 * log_w1))
    out["target_2618"] = float(P2 * np.exp(2.618 * log_w1))
    return out


def run_hsiao_lab_predict(
    ohlcv: pd.DataFrame,
    *,
    already_featured: bool = False,
    preprocess: bool = True,
) -> Dict[str, Any]:
    if preprocess and not already_featured:
        ohlcv = prepare_ohlcv(ohlcv)
    feat = ohlcv if already_featured else compute_hsiao_features(ohlcv)
    engine = ElliottHsiaoEngine()
    labeled = engine.run(feat, already_featured=True)
    events = list(labeled.attrs.get("lab_events") or [])
    last = labeled.iloc[-1] if len(labeled) else None
    targets = {}
    if last is not None:
        targets = log_fib_targets(
            float(last.get("P0", np.nan)),
            float(last.get("P1", np.nan)),
            float(last.get("P2", np.nan)),
        )
    summary = {
        "n_bars": int(len(labeled)),
        "last_state": str(last["state_name"]) if last is not None else None,
        "last_lab_signal": str(last["lab_signal"]) if last is not None and last["lab_signal"] else "",
        "n_lab_events": len(events),
        "n_w3_starts": sum(1 for e in events if e.get("code") == "LAB_BUY_W3_START"),
        "n_w5_sells": sum(
            1
            for e in events
            if e.get("code")
            in {
                "LAB_SELL_W5_TOP",
                "LAB_TRUNCATED_W5_EXIT",
                "LAB_MACD_W5_DIVERGENCE_EXIT",
                "LAB_SHOOTING_STAR_EXIT",
                "LAB_ENDING_DIAGONAL_EXIT_NEXT_OPEN",
            }
        ),
        "log_fib_targets": targets,
        "not_buy_signal": True,
        "phone_sync": PHONE_SYNC,
        "buy_signal_hook": None,
        "phone_hook": None,
        "predictor_version": "hsiao_v6",
    }
    return {
        "summary": summary,
        "events": events,
        "labeled": labeled,
        "not_buy_signal": True,
        "phone_sync": PHONE_SYNC,
    }


def assert_lab_isolation(result: Dict[str, Any]) -> None:
    assert result.get("not_buy_signal") is True
    assert result.get("phone_sync") == "blocked"
    s = result.get("summary") or {}
    assert s.get("not_buy_signal") is True
    assert s.get("phone_sync") == "blocked"
    assert s.get("buy_signal_hook") is None
    assert s.get("phone_hook") is None


__all__ = [
    "run_hsiao_lab_predict",
    "assert_lab_isolation",
    "log_fib_targets",
    "NOT_BUY_SIGNAL",
    "PHONE_SYNC",
]
