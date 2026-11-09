# -*- coding: utf-8 -*-
"""精神遮罩：蕭邏輯欄＋裸K棒意＋量價＋八浪起漲區＋黃金切割貼近（實驗室）。

只用官方 OHLC／量／既有 wave／feat／bank；不上話筒；不准發明切割率。
飆大五件柱代理見 spirit_split_mix._five_proxies。
"""
from __future__ import annotations

from typing import Dict

import numpy as np
import pandas as pd

from scripts.decade_lab_phone_market_wave_sync import _barek_masks

# 定義切割率（與 fib_module／wave_fib_targets 一致；不准另發明）
RETRACE_RATIOS = (0.382, 0.5, 0.618, 0.786)
EXT_RATIOS = (1.0, 1.272, 1.618)


def _near_level(close: pd.Series, level: pd.Series, pct: float = 1.5) -> pd.Series:
    c = close.astype(float)
    lv = level.astype(float)
    ok = (c > 0) & (lv > 0) & np.isfinite(c) & np.isfinite(lv)
    return ok & ((c - lv).abs() / lv * 100.0 <= pct)


def build_spirit_masks(
    df: pd.DataFrame,
    feat: pd.DataFrame,
    *,
    wmasks: Dict[str, pd.Series] | None = None,
    bank: Dict[str, pd.Series] | None = None,
    swing_look: int = 60,
) -> Dict[str, pd.Series]:
    """回傳可插拔 bool 遮罩（index 對齊 df）。"""
    idx = df.index
    o = df["open"].astype(float)
    h = df["high"].astype(float)
    low = df["low"].astype(float)
    c = df["close"].astype(float)
    v = df["volume"].astype(float)

    bk = _barek_masks(df)
    # 量價（蕭欄優先，否則自算）
    attack = feat.get("is_attack_vol")
    if attack is None:
        vol_ma = v.rolling(20, min_periods=5).mean()
        attack = v >= (vol_ma * 1.5)
    else:
        attack = attack.reindex(idx).fillna(False).astype(bool)
    trough = feat.get("had_trough_vol_10d")
    trough = trough.reindex(idx).fillna(False).astype(bool) if trough is not None else pd.Series(False, index=idx)
    exhaust = feat.get("is_exhaustion_vol")
    exhaust = exhaust.reindex(idx).fillna(False).astype(bool) if exhaust is not None else pd.Series(False, index=idx)
    shrink = (v < v.rolling(5, min_periods=3).mean() * 0.7) & (c < o)

    # 主力意圖代理（實驗室）：建設裸K＋攻擊量；挡＝避开裸K或竭盡
    intent_build = bk["bk_constructive"].fillna(False) & attack
    intent_build_soft = bk["bk_not_avoid"].fillna(False) & (attack | trough)
    intent_block = bk["bk_avoid"].fillna(False) | exhaust

    # 八浪：起漲區（引擎）；無則退回 False
    wmasks = wmasks or {}
    w3_zone = wmasks.get("W_w3_zone", pd.Series(False, index=idx)).reindex(idx).fillna(False)
    w3_start = wmasks.get("W_w3_start", pd.Series(False, index=idx)).reindex(idx).fillna(False)
    pullbase = wmasks.get("W_pullbase", pd.Series(False, index=idx)).reindex(idx).fillna(False)

    # 黃金切割：近 lookback 波段高低的回撤位貼近
    roll_high = h.rolling(swing_look, min_periods=20).max()
    roll_low = low.rolling(swing_look, min_periods=20).min()
    span = (roll_high - roll_low).replace(0, np.nan)
    near_any = pd.Series(False, index=idx)
    near_618 = pd.Series(False, index=idx)
    near_382 = pd.Series(False, index=idx)
    for r in RETRACE_RATIOS:
        # 上升波段回撤買區：高點往下切
        lvl = roll_high - span * float(r)
        hit = _near_level(c, lvl, pct=1.5)
        near_any = near_any | hit
        if abs(r - 0.618) < 1e-9:
            near_618 = hit
        if abs(r - 0.382) < 1e-9:
            near_382 = hit

    bank = bank or {}
    V = bank.get("hsiao_V", pd.Series(False, index=idx))
    V = V.reindex(idx).fillna(False).astype(bool) if isinstance(V, pd.Series) else pd.Series(False, index=idx)

    return {
        "BK_constructive": bk["bk_constructive"].fillna(False),
        "BK_not_avoid": bk["bk_not_avoid"].fillna(False),
        "BK_avoid": bk["bk_avoid"].fillna(False),
        "VP_attack": attack.fillna(False),
        "VP_trough": trough,
        "VP_shrink_down": shrink.fillna(False),
        "VP_exhaust": exhaust,
        "INTENT_build": intent_build.fillna(False),
        "INTENT_build_soft": intent_build_soft.fillna(False),
        "INTENT_block": intent_block.fillna(False),
        "WAVE_w3_start": w3_start,
        "WAVE_w3_zone": w3_zone,
        "WAVE_pullbase": pullbase,
        "FIB_near_any": near_any.fillna(False),
        "FIB_near_618": near_618.fillna(False),
        "FIB_near_382": near_382.fillna(False),
        # 精神交叉：裸K意圖 × 量價 ×（浪起漲或切割貼近）
        "SPIRIT_core": intent_build_soft & (w3_start | w3_zone | near_618 | near_382),
        "SPIRIT_strict": intent_build & V & (w3_start | near_618),
        "SPIRIT_pull_fib": pullbase & near_any & bk["bk_not_avoid"].fillna(False),
    }


__all__ = ["RETRACE_RATIOS", "EXT_RATIOS", "build_spirit_masks"]
