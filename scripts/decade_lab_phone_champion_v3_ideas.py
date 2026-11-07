# -*- coding: utf-8 -*-
"""V3 因子庫（自主循環用）：不准停在「沒辦法」。

在 V2 均衡核＋相對高點賣之上，準備下一輪可插拔因子：
- 結構：更高高／更高低連續、回踩 MA20 不破
- 量價：量能階梯放大、縮量回檔後再攻
- 時間：月線安全＋週線同向
- 大盤：feat_thrust 且非相對高風險
- 出場加強：相對高點後給 1 日確認／或 hi20 當日收弱才賣

本檔可被 champion_v3 匯入；也可 --probe 只印遮罩密度。
"""
from __future__ import annotations

from typing import Dict

import pandas as pd


def build_v3_extras(df: pd.DataFrame, feat: pd.DataFrame, bank: Dict[str, pd.Series]) -> Dict[str, pd.Series]:
    c = df["close"].astype(float)
    h = df["high"].astype(float)
    low = df["low"].astype(float)
    v = df["volume"].astype(float)
    o = df["open"].astype(float)

    hh = (h > h.shift(1)) & (h.shift(1) > h.shift(2))
    hl = (low > low.shift(1)) & (low.shift(1) > low.shift(2))
    higher_structure = hh & hl

    ma20 = feat.get("MA20")
    if ma20 is None:
        ma20 = c.rolling(20, min_periods=5).mean()
    else:
        ma20 = pd.to_numeric(ma20, errors="coerce")
    pull_ma20 = (low <= ma20 * 1.01) & (c >= ma20) & (c > o)

    vol_ma5 = v.rolling(5, min_periods=3).mean()
    vol_step_up = (v > vol_ma5) & (v.shift(1) > vol_ma5.shift(1)) & (c > o)
    shrink_then_attack = (v.shift(1) < vol_ma5.shift(1) * 0.7) & (v >= vol_ma5 * 1.5) & (c > o)

    s20 = pd.to_numeric(feat.get("ma20_time_safety"), errors="coerce")
    week = bank.get("hsiao_week", pd.Series(False, index=df.index)).fillna(False)
    time_align = week & (s20.fillna(-9) > 0)

    return {
        "V3_higher_structure": higher_structure.fillna(False),
        "V3_pull_ma20": pull_ma20.fillna(False),
        "V3_vol_step": vol_step_up.fillna(False),
        "V3_shrink_attack": shrink_then_attack.fillna(False),
        "V3_time_align": time_align.fillna(False),
        "V3_struct_vol": higher_structure.fillna(False) & (vol_step_up | shrink_then_attack).fillna(False),
        "V3_pull_week": pull_ma20.fillna(False) & week,
    }


__all__ = ["build_v3_extras"]
