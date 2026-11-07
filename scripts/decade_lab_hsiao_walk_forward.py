# -*- coding: utf-8 -*-
"""Expanding Window Walk-Forward（實驗室；不是買訊；phone_sync=blocked）。

每年 OOS 測試窗；訓練僅用該年前資料，並留 60 交易日 Embargo。
預設用邏輯回歸權重校準（無 lightgbm 依賴時退回邏輯／相關加權）。
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

PHONE_SYNC = "blocked"
NOT_BUY_SIGNAL = True
EMBARGO_DAYS = 60
FEATURE_COLS = [
    "angle_5",
    "ma20_time_safety",
    "ma60_time_safety",
    "vol_attack_ratio",
    "hsiao_4d_score",
    "rs_20d",
]


def _make_labels(df: pd.DataFrame, horizon: int = 20, thresh: float = 0.15) -> pd.Series:
    fwd = df["Close"].shift(-horizon) / df["Close"] - 1.0
    return (fwd > thresh).astype(float)


def _fit_weights(X: np.ndarray, y: np.ndarray) -> np.ndarray:
    """簡化：相關加權＋正則；無 sklearn 硬依賴。"""
    if X.size == 0 or y.size == 0 or y.sum() == 0 or y.sum() == len(y):
        return np.ones(X.shape[1]) / max(X.shape[1], 1)
    w = []
    for j in range(X.shape[1]):
        xj = X[:, j]
        if np.nanstd(xj) < 1e-12:
            w.append(0.0)
            continue
        mask = np.isfinite(xj) & np.isfinite(y)
        if mask.sum() < 10:
            w.append(0.0)
            continue
        corr = np.corrcoef(xj[mask], y[mask])[0, 1]
        w.append(0.0 if not np.isfinite(corr) else float(corr))
    w = np.array(w, dtype=float)
    # 轉成正權重
    w = np.maximum(w, 0.0)
    if w.sum() <= 0:
        w = np.ones_like(w)
    return w / w.sum()


def _predict_proba(X: np.ndarray, w: np.ndarray) -> np.ndarray:
    # 標準化列
    mu = np.nanmean(X, axis=0)
    sd = np.nanstd(X, axis=0)
    sd = np.where(sd < 1e-12, 1.0, sd)
    Z = (X - mu) / sd
    Z = np.nan_to_num(Z, nan=0.0)
    score = Z @ w
    # logistic
    return 1.0 / (1.0 + np.exp(-score))


def walk_forward_expanding(
    featured: pd.DataFrame,
    *,
    years: Optional[Sequence[int]] = None,
    embargo: int = EMBARGO_DAYS,
) -> Dict[str, Any]:
    """對單一標的特徵表做滾動盲測。需 DatetimeIndex。"""
    df = featured.copy()
    if not isinstance(df.index, pd.DatetimeIndex):
        raise ValueError("需要 DatetimeIndex")
    df = df.sort_index()
    df["label_w3_20d"] = _make_labels(df)
    # 僅在有 W2→W3 事件附近評估也可；此處全樣本校準分數
    for c in FEATURE_COLS:
        if c not in df.columns:
            df[c] = np.nan

    if years is None:
        years = list(range(2010, 2027))

    folds: List[Dict[str, Any]] = []
    oos_preds: List[pd.Series] = []

    for y in years:
        test_mask = (df.index.year == y)
        if test_mask.sum() == 0:
            continue
        test_start = df.index[test_mask][0]
        # 訓練：test_start 之前，再往前空出 embargo
        train_end_candidates = df.index[df.index < test_start]
        if len(train_end_candidates) <= embargo:
            continue
        train_end = train_end_candidates[-(embargo + 1)]
        train = df.loc[:train_end]
        test = df.loc[test_mask]
        X_train = train[FEATURE_COLS].to_numpy(dtype=float)
        y_train = train["label_w3_20d"].to_numpy(dtype=float)
        # 去掉末尾 horizon 無標籤
        valid = np.isfinite(y_train) & np.all(np.isfinite(X_train), axis=1)
        # 標籤尾端 NaN（因 shift）—— _make_labels 用 0/1，尾端 fwd nan → 轉 float 後可能 0；改用原始
        fwd = train["Close"].shift(-20) / train["Close"] - 1.0
        y_train = (fwd > 0.15).astype(float).to_numpy()
        valid = np.isfinite(fwd.to_numpy()) & np.all(np.isfinite(X_train), axis=1)
        if valid.sum() < 50:
            continue
        w = _fit_weights(X_train[valid], y_train[valid])
        X_test = test[FEATURE_COLS].to_numpy(dtype=float)
        proba = _predict_proba(X_test, w)
        pred = pd.Series(proba, index=test.index, name=f"oos_{y}")
        oos_preds.append(pred)
        # 評估：有未來標籤的測試列
        fwd_t = test["Close"].shift(-20) / test["Close"] - 1.0
        lab = (fwd_t > 0.15).astype(float)
        m = np.isfinite(fwd_t.to_numpy())
        if m.sum() == 0:
            hit = float("nan")
        else:
            hat = (proba[m] >= 0.5).astype(float)
            hit = float((hat == lab.to_numpy()[m]).mean())
        folds.append(
            {
                "year": y,
                "train_end": str(train_end.date()),
                "n_train": int(valid.sum()),
                "n_test": int(len(test)),
                "oos_accuracy": hit,
                "weights": {FEATURE_COLS[i]: float(w[i]) for i in range(len(FEATURE_COLS))},
            }
        )

    oos_all = pd.concat(oos_preds).sort_index() if oos_preds else pd.Series(dtype=float)
    accs = [f["oos_accuracy"] for f in folds if np.isfinite(f["oos_accuracy"])]
    summary = {
        "n_folds": len(folds),
        "oos_accuracy_mean": float(np.mean(accs)) if accs else float("nan"),
        "oos_accuracy_std": float(np.std(accs)) if accs else float("nan"),
        "years": [f["year"] for f in folds],
        "not_buy_signal": True,
        "phone_sync": PHONE_SYNC,
        "walk_forward_version": "hsiao_v7",
    }
    return {
        "summary": summary,
        "folds": folds,
        "oos_pred": oos_all,
        "not_buy_signal": True,
        "phone_sync": PHONE_SYNC,
    }


__all__ = ["walk_forward_expanding", "PHONE_SYNC", "NOT_BUY_SIGNAL", "FEATURE_COLS"]
