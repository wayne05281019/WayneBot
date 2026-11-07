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


def _bank_bool(bank: Dict[str, pd.Series], key: str, index) -> pd.Series:
    s = bank.get(key)
    if s is None:
        return pd.Series(False, index=index)
    return s.reindex(index).fillna(False).astype(bool)


def build_v3_extras(
    df: pd.DataFrame,
    feat: pd.DataFrame,
    bank: Dict[str, pd.Series],
    *,
    barek: Dict[str, pd.Series] | None = None,
) -> Dict[str, pd.Series]:
    """從既有 OHLC／feat／bank／裸K 欄組可插拔遮罩（不上話筒）。"""
    idx = df.index
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
    week = _bank_bool(bank, "hsiao_week", idx)
    time_align = week & (s20.fillna(-9) > 0)

    clean = _bank_bool(bank, "hsiao_clean", idx)
    not_hot = _bank_bool(bank, "hsiao_not_hot", idx)
    macd_turn = _bank_bool(bank, "hsiao_macd_turn", idx)
    kd_ok = _bank_bool(bank, "hsiao_kd", idx)
    trough = _bank_bool(bank, "hsiao_troughV", idx)
    compress = _bank_bool(bank, "hsiao_compress", idx)
    v_ok = _bank_bool(bank, "hsiao_V", idx)

    bk = barek or {}
    barek_ok = bk.get("bk_not_avoid")
    if barek_ok is None:
        barek_ok = pd.Series(True, index=idx)
    else:
        barek_ok = barek_ok.reindex(idx).fillna(True).astype(bool)
    barek_flip = bk.get("bk_constructive")
    if barek_flip is None:
        barek_flip = pd.Series(False, index=idx)
    else:
        barek_flip = barek_flip.reindex(idx).fillna(False).astype(bool)

    return {
        "V3_higher_structure": higher_structure.fillna(False),
        "V3_pull_ma20": pull_ma20.fillna(False),
        "V3_vol_step": vol_step_up.fillna(False),
        "V3_shrink_attack": shrink_then_attack.fillna(False),
        "V3_time_align": time_align.fillna(False),
        "V3_struct_vol": higher_structure.fillna(False) & (vol_step_up | shrink_then_attack).fillna(False),
        "V3_pull_week": pull_ma20.fillna(False) & week,
        # 既有 bank／裸K（V2 試過單獨項；V3 疊在均衡核上再測）
        "V3_barek_ok": barek_ok,
        "V3_barek_constructive": barek_flip,
        "V3_clean_not_hot": clean & not_hot,
        "V3_macd_or_kd": macd_turn | kd_ok,
        "V3_trough_V": trough & v_ok,
        "V3_compress_V": compress & v_ok,
    }


__all__ = ["build_v3_extras"]
