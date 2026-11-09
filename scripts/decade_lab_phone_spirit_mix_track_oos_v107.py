# -*- coding: utf-8 -*-
"""spirit_mix_track_oos_v107：sealed keep 兩核 mask 建檔（供 stock_* lab 對質）。

只公開 ``_champ_masks``：early＝ei_n2_lu5／eg_bridge；fast＝lu5_vol_next。
對齊 phone_spirit_mix_dual_track_v106 封口；phone_sync=blocked；不准改 leave_zero／話筒。

本檔是 stock 靜默對質的 spirit 堆入口（先前只活在 ephemeral WAYNE_LAB_MIX_ROOT）。
不准當買訊；勝率軌與浪形軌不准混。
"""
from __future__ import annotations

from typing import Dict

import pandas as pd

from scripts.decade_lab_chart_marks_stats import _build_mark_masks
from scripts.decade_lab_hsiao_data_preprocessor import prepare_ohlcv
from scripts.decade_lab_hsiao_quant_features import compute_hsiao_features
from scripts.decade_lab_phone_champion_v3_ideas import build_v3_extras
from scripts.decade_lab_phone_champion_v4_ideas import build_v4_extras
from scripts.decade_lab_phone_extreme_hillclimb import _align_feat, _cores, _near, _wave_hsiao_bank
from scripts.decade_lab_phone_market_wave_sync import _align_mkt, _barek_masks
from scripts.decade_lab_phone_spirit_masks import build_spirit_masks
from scripts.decade_lab_phone_spirit_split_mix import _five_proxies
from scripts.decade_lab_phone_wave_filter import _align_wave, _wave_frame, _wave_masks

PHONE_SYNC = "blocked"
BUY_SIGNAL = False


def _champ_masks(df, raw, mkt_raw) -> Dict[str, pd.Series]:
    """v106 sealed keep 進場核（官方 OHLC／spirit／hsiao 可重述欄；無假成本／無浪級計分）。"""
    feat = _align_feat(df, compute_hsiao_features(prepare_ohlcv(raw)))
    wave = _align_wave(df, _wave_frame(raw))
    wmasks = _wave_masks(wave)
    cores = _cores(_build_mark_masks(df), wmasks, feat)
    bank = _wave_hsiao_bank(feat, wmasks, wave)
    spirit = build_spirit_masks(df, feat, wmasks=wmasks, bank=bank)
    five = _five_proxies(df, feat, spirit)
    five2 = five.get("FIVE_cross2")
    if five2 is None:
        five2 = pd.Series(False, index=df.index)
    f_vol = five.get("FIVE_vol")
    if f_vol is None:
        f_vol = pd.Series(False, index=df.index)
    barek = _barek_masks(df)
    mkt = _align_mkt(df, mkt_raw)
    v3 = build_v3_extras(df, feat, bank, barek=barek)
    v4 = build_v4_extras(df, feat)
    idx = df.index
    w3u = cores["core_w3_or_ma60w3"].fillna(False)
    turn = v3["V3_macd_or_kd"].fillna(False) & v3["V3_barek_ok"].fillna(False)
    intent = spirit["INTENT_build_soft"].fillna(False)
    t60 = v4["V4_t60_safe"].fillna(False)
    risk = ~mkt["mkt_rel_high_risk"].fillna(False)
    week = v4["V4_week_stack"].fillna(False)
    body = v4["V4_body_thrust"].fillna(False)
    room = v4.get("V4_room_ok", pd.Series(True, index=idx)).reindex(idx).fillna(True)
    room_soft = _near(room.fillna(False), 3)
    bk_ok = barek.get("BAREK_ok")
    if bk_ok is None:
        bk_ok = pd.Series(True, index=idx)
    bk_ok = bk_ok.fillna(True)

    def _ph(key: str) -> pd.Series:
        s = spirit.get(key)
        return s.fillna(False) if s is not None else pd.Series(False, index=idx)

    ph_wash = _ph("PHASE_wash")
    ph_absorb = _ph("PHASE_absorb")
    ph_bot = _ph("PHASE_bottom")
    ph_prep = _ph("PHASE_prep")
    ph_handoff = _ph("PHASE_handoff")
    teach_near = (
        _near(ph_wash.fillna(False), 8)
        | _near(ph_absorb.fillna(False), 8)
        | _near(ph_bot.fillna(False), 5)
        | _near(ph_prep.fillna(False), 5)
        | _near(ph_handoff.fillna(False), 10)
    )
    gate = risk & t60
    ip3 = _near(intent, 3) & bk_ok
    lu_no_five = (ip3 & teach_near & bk_ok & gate).fillna(False)
    ei_n2 = w3u & _near(turn, 3) & t60 & _near(intent, 2) & risk
    ei_n2_wb = (ei_n2 & (_near(week, 3) | _near(body, 3))).fillna(False)
    ei_n2_days = (ei_n2_wb & (room | room_soft | _near(week, 5) | _near(body, 5))).fillna(False)
    ei_n2_lu5 = (ei_n2_wb | lu_no_five).fillna(False)
    eg_bridge = (ei_n2_days | lu_no_five).fillna(False)
    fv = f_vol.fillna(False)
    _ = five2  # sealed keep 不另開 cross2 鍵；保留對齊 v107 建檔欄
    lu5_vol = (ei_n2_lu5 & _near(fv, 3)).fillna(False)
    lu5_vol_next = (lu5_vol | (ei_n2_lu5 & room_soft & _near(fv, 5))).fillna(False)
    return {
        "ei_n2_lu5": ei_n2_lu5,
        "eg_bridge": eg_bridge,
        "lu5_vol_next": lu5_vol_next,
    }
