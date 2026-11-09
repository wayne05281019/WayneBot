# -*- coding: utf-8 -*-
"""因果八浪狀態機 V5 定版（實驗室；不是買訊；phone_sync=blocked）。

V2：延長浪防賣飛、二四交替、週線／過熱濾網
V3：缺口／假突破／失敗第5／B浪穿頭
V4：對數波段、鎖碼比、KD鈍化、破底翻觀察池標記
V5：終結楔形 Ending Diagonal、處置股擋買（讀 block_new_entries）
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import IntEnum
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from scripts.decade_lab_hsiao_quant_features import compute_hsiao_features

PHONE_SYNC = "blocked"
NOT_BUY_SIGNAL = True


class WaveState(IntEnum):
    BASE_BOTTOM = 0
    WAVE_1_UP = 1
    WAVE_2_PULLBACK = 2
    WAVE_3_MAIN = 3
    WAVE_4_CONSOL = 4
    WAVE_5_FINAL = 5
    WAVE_A_DROP = 6
    WAVE_B_TRAP = 7
    WAVE_C_CRASH = 8
    WAVE_5_ENDING_DIAGONAL = 9
    WAVE_X_REBOUND = 10  # V6：複合修正 X 浪，禁止 W2→W3


STATE_NAME = {s: s.name for s in WaveState}


@dataclass
class SwingCandidate:
    t_idx: int = -1
    price: float = float("nan")
    v_ma5: float = float("nan")
    angle10: float = float("nan")


def _log_retrace(p1: float, p0: float, low: float) -> float:
    if not all(np.isfinite(x) and x > 0 for x in (p1, p0, low)):
        return float("nan")
    den = np.log(p1) - np.log(p0)
    if abs(den) < 1e-12:
        return float("nan")
    return float((np.log(p1) - np.log(low)) / den)


def _log_len(a: float, b: float) -> float:
    if not (np.isfinite(a) and np.isfinite(b) and a > 0 and b > 0):
        return float("nan")
    return float(np.log(a / b))


# 實驗室進場预设（不上話筒）
# A4_index_soft：大盤指數 decade 窗專用；放寬量能／週線硬閘，仍 phone_sync=blocked
ENTRY_PRESETS = ("A0_strict", "A1_score", "A2_hammer_kd", "A3_squeeze", "A4_index_soft")


@dataclass
class ElliottHsiaoEngine:
    """entry_preset 僅實驗室；預設 A0_strict。phone_sync 永遠 blocked。"""

    entry_preset: str = "A0_strict"
    score_threshold: float = 55.0
    state: WaveState = WaveState.BASE_BOTTOM
    cand_high: SwingCandidate = field(default_factory=SwingCandidate)
    cand_low: SwingCandidate = field(default_factory=SwingCandidate)
    P0: float = float("nan")
    t_P0: int = -1
    P1: float = float("nan")
    t_P1: int = -1
    V1_peak: float = float("nan")
    A1_peak: float = float("nan")
    P2: float = float("nan")
    t_P2: int = -1
    P3: float = float("nan")
    t_P3: int = -1
    V3_peak: float = float("nan")
    A3_peak: float = float("nan")
    P4: float = float("nan")
    t_P4: int = -1
    P5: float = float("nan")
    PA: float = float("nan")
    PB: float = float("nan")
    stop_loss: float = float("nan")
    len_w3: float = float("nan")
    log_W1: float = float("nan")
    log_W3: float = float("nan")
    log_W5: float = float("nan")
    had_trough_since_p1: bool = False
    w2_depth: float = float("nan")
    w2_days: int = 0
    gap_iron_support: float = float("nan")
    score_boost: float = 0.0
    w3_reduce_flag: bool = False
    has_impulse_momentum: bool = False
    sum_vol_w1_up: float = 0.0
    sum_vol_w2_down: float = 0.0
    # 楔形下軌：P2→P4 直線
    diag_slope: float = float("nan")
    diag_intercept: float = float("nan")
    # V6 MACD 峰值
    dif_w3_peak: float = float("nan")
    hist_w3_peak: float = float("nan")
    # V6 錘子／仙人指路
    hammer_high: float = float("nan")
    hammer_t: int = -1
    immortal_add_trigger: float = float("nan")
    immortal_add_expire_t: int = -1
    shooting_star_low: float = float("nan")
    x_rebound_lock: bool = False
    # V7 籌碼／放空
    chip_clean_boost: float = 0.0
    short_squeeze: bool = False
    w3_target_mult: float = 1.618
    vol_ma5_a_peak: float = float("nan")  # A 浪下跌段最大 VOL_MA5
    short_stop: float = float("nan")
    in_short: bool = False
    lab_events: List[Dict[str, Any]] = field(default_factory=list)

    def reset_structure(self) -> None:
        self.state = WaveState.BASE_BOTTOM
        self.P0 = self.P1 = self.P2 = self.P3 = self.P4 = self.P5 = float("nan")
        self.PA = self.PB = float("nan")
        self.t_P0 = self.t_P1 = self.t_P2 = self.t_P3 = self.t_P4 = -1
        self.V1_peak = self.A1_peak = self.V3_peak = self.A3_peak = float("nan")
        self.stop_loss = self.len_w3 = float("nan")
        self.log_W1 = self.log_W3 = self.log_W5 = float("nan")
        self.had_trough_since_p1 = False
        self.w2_depth = float("nan")
        self.w2_days = 0
        self.gap_iron_support = float("nan")
        self.score_boost = 0.0
        self.w3_reduce_flag = False
        self.has_impulse_momentum = False
        self.sum_vol_w1_up = 0.0
        self.sum_vol_w2_down = 0.0
        self.diag_slope = self.diag_intercept = float("nan")
        self.dif_w3_peak = self.hist_w3_peak = float("nan")
        self.hammer_high = float("nan")
        self.hammer_t = -1
        self.immortal_add_trigger = float("nan")
        self.immortal_add_expire_t = -1
        self.shooting_star_low = float("nan")
        self.chip_clean_boost = 0.0
        self.short_squeeze = False
        self.w3_target_mult = 1.618
        self.vol_ma5_a_peak = float("nan")
        self.short_stop = float("nan")
        self.in_short = False
        # x_rebound_lock 不在每輪結構重置時清掉，由季線扣抵解除

    def _update_candidates(self, t: int, row: pd.Series) -> None:
        hi = float(row["High"])
        lo = float(row["Low"])
        v5 = float(row["VOL_MA5"]) if np.isfinite(row["VOL_MA5"]) else float("nan")
        a10 = float(row["angle_10"]) if np.isfinite(row.get("angle_10", np.nan)) else float("nan")
        if not np.isfinite(self.cand_high.price) or hi >= self.cand_high.price:
            self.cand_high = SwingCandidate(t, hi, v5, a10)
        if not np.isfinite(self.cand_low.price) or lo <= self.cand_low.price:
            self.cand_low = SwingCandidate(t, lo, v5, a10)

    def _confirm_swing_high(self, t: int, row: pd.Series) -> bool:
        if self.cand_high.t_idx < 0 or not np.isfinite(self.cand_high.price):
            return False
        atr = float(row["ATR_14"]) if np.isfinite(row["ATR_14"]) else float("nan")
        close = float(row["Close"])
        ma10 = float(row["MA10"]) if np.isfinite(row["MA10"]) else float("nan")
        p_high = self.cand_high.price
        dt = t - self.cand_high.t_idx
        cond_a = np.isfinite(atr) and atr > 0 and close <= p_high - 1.5 * atr and dt >= 3
        pull = (p_high - close) / p_high if p_high > 0 else 0.0
        cond_b = np.isfinite(ma10) and close < ma10 and pull > 0.045
        return bool(cond_a or cond_b)

    def _confirm_swing_low(self, t: int, row: pd.Series) -> bool:
        if self.cand_low.t_idx < 0 or not np.isfinite(self.cand_low.price):
            return False
        atr = float(row["ATR_14"]) if np.isfinite(row["ATR_14"]) else float("nan")
        close = float(row["Close"])
        p_low = self.cand_low.price
        dt = t - self.cand_low.t_idx
        cond_a = np.isfinite(atr) and atr > 0 and close >= p_low + 1.5 * atr and dt >= 3
        cond_b = bool(row.get("is_key_bull_candle")) and bool(row.get("is_attack_vol"))
        return bool(cond_a or cond_b)

    def _emit(self, t: int, code: str, **extra: Any) -> None:
        self.lab_events.append({"t": t, "code": code, **extra})

    def _w3_extension_hold(self, row: pd.Series, close: float, ma20: float, ma20_safe: float) -> bool:
        if not (np.isfinite(ma20) and close >= ma20):
            return False
        if not (np.isfinite(ma20_safe) and ma20_safe > 0.2):
            return False
        if bool(row.get("is_exhaustion_vol")):
            return False
        return True

    def _apply_breakaway_gap(self, t: int, row: pd.Series, ok: bool) -> None:
        if not ok or not bool(row.get("gap_breakaway_candidate")):
            return
        gs = float(row.get("gap_support", np.nan))
        if np.isfinite(gs):
            self.gap_iron_support = gs
            self.stop_loss = gs if not np.isfinite(self.stop_loss) else max(self.stop_loss, gs)
        self.score_boost = max(self.score_boost, 15.0)
        self._emit(t, "LAB_BREAKAWAY_GAP", gap_support=gs)

    def _diag_line_at(self, t: int) -> float:
        if not (np.isfinite(self.diag_slope) and np.isfinite(self.diag_intercept)):
            return float("nan")
        return float(self.diag_slope * t + self.diag_intercept)

    def _set_diag_from_p2_p4(self) -> None:
        if self.t_P2 < 0 or self.t_P4 < 0:
            return
        if self.t_P4 == self.t_P2:
            return
        if not (np.isfinite(self.P2) and np.isfinite(self.P4)):
            return
        self.diag_slope = (self.P4 - self.P2) / float(self.t_P4 - self.t_P2)
        self.diag_intercept = self.P2 - self.diag_slope * self.t_P2

    def _iron_rule3_ok(self) -> Optional[bool]:
        """log_W3 不得同時小於 log_W1 與 log_W5。資料不足回 None。"""
        if not all(np.isfinite(x) for x in (self.log_W1, self.log_W3, self.log_W5)):
            return None
        return not (self.log_W3 < self.log_W1 and self.log_W3 < self.log_W5)

    def _snap(self, signal: str, position_hint: str, base_score: float) -> Dict[str, Any]:
        lock = self.sum_vol_w2_down / (self.sum_vol_w1_up + 1e-8)
        lock_bonus = 10.0 if lock <= 0.45 and self.sum_vol_w1_up > 0 else 0.0
        eff = min(
            100.0,
            base_score
            + float(self.score_boost or 0.0)
            + lock_bonus
            + float(self.chip_clean_boost or 0.0),
        )
        return {
            "state": int(self.state),
            "state_name": STATE_NAME[self.state],
            "lab_signal": signal,
            "position_hint": position_hint,
            "hard_stop_price": float(self.stop_loss) if np.isfinite(self.stop_loss) else float("nan"),
            "gap_iron_support": float(self.gap_iron_support)
            if np.isfinite(self.gap_iron_support)
            else float("nan"),
            "w2_depth": float(self.w2_depth) if np.isfinite(self.w2_depth) else float("nan"),
            "w2_days": int(self.w2_days),
            "w2_lock_ratio": float(lock),
            "log_W1": self.log_W1,
            "log_W3": self.log_W3,
            "log_W5": self.log_W5,
            "iron_rule3_ok": self._iron_rule3_ok(),
            "has_impulse_momentum": bool(self.has_impulse_momentum),
            "hsiao_score_eff": eff,
            "P0": self.P0,
            "P1": self.P1,
            "P2": self.P2,
            "P3": self.P3,
            "P4": self.P4,
            "P5": self.P5,
            "diag_support": float("nan"),
            "x_rebound_lock": bool(self.x_rebound_lock),
            "immortal_add_trigger": float(self.immortal_add_trigger)
            if np.isfinite(self.immortal_add_trigger)
            else float("nan"),
            "shooting_star_low": float(self.shooting_star_low)
            if np.isfinite(self.shooting_star_low)
            else float("nan"),
            "short_squeeze": bool(self.short_squeeze),
            "w3_target_mult": float(self.w3_target_mult),
            "short_stop": float(self.short_stop) if np.isfinite(self.short_stop) else float("nan"),
            "chip_clean_boost": float(self.chip_clean_boost),
            "not_buy_signal": True,
            "phone_sync": PHONE_SYNC,
        }

    def step(self, t: int, row: pd.Series) -> Dict[str, Any]:
        self._update_candidates(t, row)
        signal = ""
        position_hint = "flat"
        close = float(row["Close"])
        atr = float(row["ATR_14"]) if np.isfinite(row["ATR_14"]) else float("nan")
        ma5 = float(row["MA5"]) if np.isfinite(row["MA5"]) else float("nan")
        ma10 = float(row["MA10"]) if np.isfinite(row["MA10"]) else float("nan")
        ma20 = float(row["MA20"]) if np.isfinite(row["MA20"]) else float("nan")
        ma60 = float(row["MA60"]) if np.isfinite(row["MA60"]) else float("nan")
        angle5 = float(row["angle_5"]) if np.isfinite(row.get("angle_5", np.nan)) else float("nan")
        angle10 = float(row["angle_10"]) if np.isfinite(row.get("angle_10", np.nan)) else float("nan")
        ma20_safe = float(row["ma20_time_safety"]) if np.isfinite(row.get("ma20_time_safety", np.nan)) else float("nan")
        ma60_safe = float(row["ma60_time_safety"]) if np.isfinite(row.get("ma60_time_safety", np.nan)) else float("nan")
        vol_ma5 = float(row["VOL_MA5"]) if np.isfinite(row["VOL_MA5"]) else float("nan")
        attack = float(row["vol_attack_ratio"]) if np.isfinite(row.get("vol_attack_ratio", np.nan)) else float("nan")
        weekly_bull = bool(row.get("weekly_trend_bullish"))
        overext = bool(row.get("is_overextended"))
        base_score = float(row["hsiao_4d_score"]) if np.isfinite(row.get("hsiao_4d_score", np.nan)) else 0.0
        k_val = float(row["K"]) if np.isfinite(row.get("K", np.nan)) else float("nan")
        block_entry = bool(row.get("block_new_entries"))
        turnover_ok = bool(row.get("turnover_ok", True))
        up_vol = float(row.get("up_bar_vol", 0.0) or 0.0)
        down_vol = float(row.get("down_bar_vol", 0.0) or 0.0)

        # 鎖碼累積
        if self.state == WaveState.WAVE_1_UP:
            self.sum_vol_w1_up += up_vol
        elif self.state == WaveState.WAVE_2_PULLBACK:
            self.sum_vol_w2_down += down_vol

        # KD 鈍化 → 推動浪基因
        if self.state in (WaveState.WAVE_1_UP, WaveState.WAVE_3_MAIN) and bool(
            row.get("kd_high_passivation")
        ):
            self.has_impulse_momentum = True

        # 假突破／竭盡缺口
        if self.state in (WaveState.WAVE_3_MAIN, WaveState.WAVE_4_CONSOL, WaveState.WAVE_5_FINAL, WaveState.WAVE_5_ENDING_DIAGONAL):
            if bool(row.get("fake_breakout_exit")):
                signal = "LAB_FAKE_BREAKOUT_EXIT"
                position_hint = "exit"
                self._emit(t, signal)
            if self.state in (WaveState.WAVE_3_MAIN, WaveState.WAVE_5_FINAL, WaveState.WAVE_5_ENDING_DIAGONAL):
                if bool(row.get("gap_exhaustion_candidate")) or bool(row.get("gap_filled_within_3d")):
                    signal = "LAB_EXHAUSTION_GAP_EXIT"
                    position_hint = "exit"
                    self.P5 = self.cand_high.price if np.isfinite(self.cand_high.price) else close
                    self.state = WaveState.WAVE_A_DROP
                    self._emit(t, signal)
                    return self._snap(signal, position_hint, base_score)

        # V6：複合修正 X 浪鎖定解除
        ma60_ang = float(row["ma60_angle"]) if np.isfinite(row.get("ma60_angle", np.nan)) else float("nan")
        if self.x_rebound_lock and np.isfinite(ma60_safe) and ma60_safe >= -0.2:
            self.x_rebound_lock = False
            self._emit(t, "LAB_X_REBOUND_UNLOCK")

        if self.state == WaveState.BASE_BOTTOM:
            if block_entry:
                return self._snap(signal, position_hint, base_score)
            # V6：季線重壓 → 鎖成 X 浪反彈，禁止後續 W2→W3
            heavy_cap = (np.isfinite(ma60_safe) and ma60_safe < -0.8) and (
                np.isfinite(ma60_ang) and ma60_ang < -25.0
            )
            ignite = (
                (close > ma60 if np.isfinite(ma60) else False) or bool(row.get("bull_alignment"))
            ) and bool(row.get("is_key_bull_candle")) and bool(row.get("is_attack_vol"))
            if (
                ignite
                and np.isfinite(angle5)
                and angle5 >= 35.0
                and np.isfinite(ma20_safe)
                and ma20_safe > 0
                and turnover_ok
                and self._confirm_swing_low(t, row)
            ):
                self.P0 = self.cand_low.price
                self.t_P0 = self.cand_low.t_idx
                self.sum_vol_w1_up = up_vol
                self.cand_high = SwingCandidate(t, float(row["High"]), vol_ma5, angle10)
                if heavy_cap:
                    self.x_rebound_lock = True
                    self.state = WaveState.WAVE_X_REBOUND
                    self._emit(t, "LAB_X_REBOUND_LOCK", ma60_safe=ma60_safe, ma60_angle=ma60_ang)
                else:
                    self.state = WaveState.WAVE_1_UP
                    self._apply_breakaway_gap(t, row, True)
                    self._emit(t, "LAB_W1_START", P0=self.P0)

        elif self.state == WaveState.WAVE_X_REBOUND:
            # 只追蹤反彈，嚴禁買訊；解鎖後回到 BASE 等待真底
            position_hint = "flat"
            if not self.x_rebound_lock:
                self.reset_structure()
                self._emit(t, "LAB_X_REBOUND_TO_BASE")
            elif np.isfinite(self.P0) and close < self.P0:
                self.reset_structure()
                self.x_rebound_lock = True  # 仍鎖，直到季線扣抵改善
                self._emit(t, "LAB_X_REBOUND_FAIL")

        elif self.state == WaveState.WAVE_1_UP:
            self._apply_breakaway_gap(t, row, True)
            if self._confirm_swing_high(t, row):
                p1 = self.cand_high.price
                if np.isfinite(self.P0) and p1 > self.P0 * 1.06:
                    self.P1 = p1
                    self.t_P1 = self.cand_high.t_idx
                    self.log_W1 = _log_len(self.P1, self.P0)
                    self.V1_peak = self.cand_high.v_ma5
                    self.A1_peak = self.cand_high.angle10
                    self.state = WaveState.WAVE_2_PULLBACK
                    self.had_trough_since_p1 = False
                    self.sum_vol_w2_down = 0.0
                    self.cand_low = SwingCandidate(t, float(row["Low"]), vol_ma5, angle10)
                    self._emit(t, "LAB_W1_TOP", P1=self.P1, log_W1=self.log_W1)

        elif self.state == WaveState.WAVE_2_PULLBACK:
            if self.x_rebound_lock:
                # 嚴禁 W2→W3
                return self._snap("LAB_X_REBOUND_NO_BUY", "flat", base_score)
            if bool(row.get("had_trough_vol_10d")) or bool(row.get("is_trough_vol")):
                self.had_trough_since_p1 = True
            # V6：W2 破底錘子 — 記高點，隔日越過即右側確認
            if (
                bool(row.get("is_hammer_shape"))
                and np.isfinite(ma20_safe)
                and ma20_safe > 0
                and np.isfinite(self.cand_low.price)
                and float(row["Low"]) <= self.cand_low.price * 1.001
            ):
                self.hammer_high = float(row["High"])
                self.hammer_t = t
                self._emit(t, "LAB_W2_HAMMER", hammer_high=self.hammer_high)
            if np.isfinite(self.P0) and close < self.P0:
                self.reset_structure()
                self._emit(t, "LAB_W2_FAIL_BREAK_P0")
            else:
                cur_low = self.cand_low.price if np.isfinite(self.cand_low.price) else close
                retrace = _log_retrace(self.P1, self.P0, cur_low)
                days_w2 = t - self.t_P1 if self.t_P1 >= 0 else 0
                # A4：指數 decade 防 W2 淺回卡死（曾見近千根不進 W3）
                if self.entry_preset == "A4_index_soft" and days_w2 >= 60:
                    shallow = (not np.isfinite(retrace)) or retrace < 0.20
                    if shallow and np.isfinite(self.P1) and close > self.P1:
                        # 淺回後再創高＝W1 延伸，重標 P1，繼續等真 W2
                        self.P1 = float(row["High"]) if np.isfinite(row.get("High", np.nan)) else close
                        self.t_P1 = t
                        self.log_W1 = _log_len(self.P1, self.P0)
                        self.had_trough_since_p1 = False
                        self.sum_vol_w2_down = 0.0
                        self.cand_low = SwingCandidate(t, float(row["Low"]), vol_ma5, angle10)
                        self._emit(t, "LAB_W1_EXTEND_SHALLOW_W2", P1=self.P1, days_w2=days_w2)
                        return self._snap("LAB_W1_EXTEND_SHALLOW_W2", "flat", base_score)
                    if shallow and days_w2 >= 120:
                        self.reset_structure()
                        self._emit(t, "LAB_W2_TIMEOUT_SHALLOW", days_w2=days_w2, retrace=retrace)
                        return self._snap("LAB_W2_TIMEOUT_SHALLOW", "flat", base_score)
                prior_high5 = float(row.get("prior_high_5", np.nan))
                if not np.isfinite(prior_high5):
                    prior_high5 = self.P1
                turn = bool(row.get("is_key_bull_candle")) or close > prior_high5
                hammer_confirm = (
                    self.hammer_t >= 0
                    and t > self.hammer_t
                    and np.isfinite(self.hammer_high)
                    and close > self.hammer_high
                )
                kd_buy = (
                    self.has_impulse_momentum
                    and bool(row.get("kd_pullback_buy_zone"))
                    and np.isfinite(ma20_safe)
                    and ma20_safe > 0
                )
                vol_ok = self.had_trough_since_p1 and (
                    (np.isfinite(attack) and attack >= 1.8) or bool(row.get("is_attack_vol"))
                )
                price_ok = (
                    np.isfinite(retrace)
                    and 0.30 <= retrace <= 0.786
                    and np.isfinite(ma60)
                    and close > ma60
                )
                time_ok = (
                    np.isfinite(ma20_safe)
                    and ma20_safe >= 0
                    and np.isfinite(ma60_safe)
                    and ma60_safe >= 0
                )
                ang_ok = (np.isfinite(angle5) and angle5 >= 40.0 and turn) or kd_buy or hammer_confirm
                squeeze = bool(row.get("is_short_squeeze_setup"))
                # A3：軋空時允許正乖離 < 20% 仍進；其餘预设過熱即擋
                if self.entry_preset == "A3_squeeze" and squeeze:
                    bias_pct = (
                        float(row["bias_ma20_pct"])
                        if np.isfinite(row.get("bias_ma20_pct", np.nan))
                        else float("nan")
                    )
                    overext_block = overext and (not np.isfinite(bias_pct) or bias_pct >= 0.20)
                else:
                    overext_block = overext
                mtf_ok = weekly_bull and (not overext_block) and (not block_entry) and turnover_ok
                lock = self.sum_vol_w2_down / (self.sum_vol_w1_up + 1e-8)
                if lock <= 0.45 and self.sum_vol_w1_up > 0:
                    self.score_boost = max(self.score_boost, 8.0)
                # V7：籌碼清洗＋法人承接
                if bool(row.get("chip_clean_candidate")):
                    self.chip_clean_boost = 15.0
                    self._emit(t, "LAB_CHIP_CLEAN_BONUS")
                eff_score = min(
                    100.0,
                    base_score + float(self.score_boost or 0.0) + float(self.chip_clean_boost or 0.0),
                )
                swing_ok = self._confirm_swing_low(t, row) or kd_buy or hammer_confirm
                preset = self.entry_preset if self.entry_preset in ENTRY_PRESETS else "A0_strict"
                if preset == "A0_strict":
                    enter = (
                        price_ok
                        and (vol_ok or kd_buy or hammer_confirm)
                        and time_ok
                        and ang_ok
                        and mtf_ok
                        and swing_ok
                    )
                elif preset == "A1_score":
                    soft = (vol_ok or kd_buy or hammer_confirm or eff_score >= self.score_threshold)
                    # 硬濾：週線／不過熱／結構回撤／時間安全墊（月線）
                    hard = (
                        mtf_ok
                        and price_ok
                        and np.isfinite(ma20_safe)
                        and ma20_safe >= 0
                        and swing_ok
                    )
                    enter = hard and soft and eff_score >= self.score_threshold
                elif preset == "A2_hammer_kd":
                    hard = mtf_ok and price_ok and np.isfinite(ma20_safe) and ma20_safe >= 0
                    enter = hard and (
                        hammer_confirm
                        or kd_buy
                        or (eff_score >= self.score_threshold and swing_ok)
                    )
                elif preset == "A3_squeeze":
                    hard = mtf_ok and price_ok and np.isfinite(ma20_safe) and ma20_safe >= 0 and swing_ok
                    soft = vol_ok or kd_buy or hammer_confirm or eff_score >= self.score_threshold
                    if squeeze:
                        enter = hard and soft
                    else:
                        enter = hard and soft and eff_score >= self.score_threshold
                else:  # A4_index_soft — 指數 decade 對質用，不准上話筒
                    vol_soft = self.had_trough_since_p1 and (
                        (np.isfinite(attack) and attack >= 1.2) or bool(row.get("is_attack_vol"))
                    )
                    ang_soft = (np.isfinite(angle5) and angle5 >= 25.0 and turn) or kd_buy or hammer_confirm
                    above_ma = (np.isfinite(ma60) and close > ma60) or (
                        np.isfinite(ma20) and close > ma20
                    )
                    price_soft = (
                        np.isfinite(retrace) and 0.15 <= retrace <= 0.886 and above_ma
                    )
                    weekly_soft = weekly_bull or (
                        above_ma
                        and np.isfinite(ma60_safe)
                        and ma60_safe >= -0.25
                    )
                    mtf_soft = weekly_soft and (not overext_block) and (not block_entry) and turnover_ok
                    structure_turn = swing_ok or turn or kd_buy or hammer_confirm
                    hard = (
                        mtf_soft
                        and price_soft
                        and np.isfinite(ma20_safe)
                        and ma20_safe >= -0.5
                        and structure_turn
                    )
                    soft = vol_soft or kd_buy or hammer_confirm or ang_soft or (
                        eff_score >= max(45.0, float(self.score_threshold) - 10.0)
                    )
                    enter = hard and soft
                if enter:
                    self._apply_breakaway_gap(t, row, True)
                    self.P2 = self.cand_low.price
                    self.t_P2 = self.cand_low.t_idx
                    self.w2_depth = float(retrace) if np.isfinite(retrace) else float("nan")
                    self.w2_days = int(days_w2)
                    hard = min(float(row["Low"]), self.P2)
                    if np.isfinite(self.gap_iron_support):
                        hard = max(hard, self.gap_iron_support)
                    self.stop_loss = hard
                    self.state = WaveState.WAVE_3_MAIN
                    self.V3_peak = vol_ma5
                    self.A3_peak = angle10 if np.isfinite(angle10) else float("nan")
                    self.dif_w3_peak = float(row["DIF"]) if np.isfinite(row.get("DIF", np.nan)) else float("nan")
                    self.hist_w3_peak = (
                        float(row["MACD_HIST"]) if np.isfinite(row.get("MACD_HIST", np.nan)) else float("nan")
                    )
                    # V7：軋空 → 目標 2.618、放寬過熱
                    if bool(row.get("is_short_squeeze_setup")):
                        self.short_squeeze = True
                        self.w3_target_mult = 2.618
                        self._emit(t, "LAB_SHORT_SQUEEZE_SETUP")
                    else:
                        self.short_squeeze = False
                        self.w3_target_mult = 1.618
                    self.cand_high = SwingCandidate(t, float(row["High"]), vol_ma5, angle10)
                    signal = "LAB_BUY_W3_START"
                    position_hint = "long"
                    self._emit(
                        t,
                        signal,
                        P2=self.P2,
                        stop=self.stop_loss,
                        w2_depth=self.w2_depth,
                        w2_lock_ratio=lock,
                        kd_buy=kd_buy,
                        hammer_confirm=hammer_confirm,
                        w3_target_mult=self.w3_target_mult,
                    )

        elif self.state == WaveState.WAVE_3_MAIN:
            position_hint = "reduce_1_3" if self.w3_reduce_flag else "long"
            if np.isfinite(vol_ma5) and (not np.isfinite(self.V3_peak) or vol_ma5 > self.V3_peak):
                self.V3_peak = vol_ma5
            if np.isfinite(angle10) and (not np.isfinite(self.A3_peak) or angle10 > self.A3_peak):
                self.A3_peak = angle10
            dif = float(row["DIF"]) if np.isfinite(row.get("DIF", np.nan)) else float("nan")
            hist = float(row["MACD_HIST"]) if np.isfinite(row.get("MACD_HIST", np.nan)) else float("nan")
            if np.isfinite(dif) and (not np.isfinite(self.dif_w3_peak) or dif > self.dif_w3_peak):
                self.dif_w3_peak = dif
            if np.isfinite(hist) and (not np.isfinite(self.hist_w3_peak) or hist > self.hist_w3_peak):
                self.hist_w3_peak = hist
            # V6：仙人指路 — 剛破 P1 初段爆量長上影
            bias = float(row["bias_ma20_pct"]) if np.isfinite(row.get("bias_ma20_pct", np.nan)) else float("nan")
            just_broke_p1 = np.isfinite(self.P1) and close > self.P1 and float(row["Low"]) <= self.P1 * 1.02
            if (
                bool(row.get("is_long_upper_shadow_vol"))
                and just_broke_p1
                and np.isfinite(ma20_safe)
                and ma20_safe > 0.5
                and np.isfinite(bias)
                and bias < 0.08
            ):
                self.immortal_add_trigger = float(row["High"])
                self.immortal_add_expire_t = t + 3
                self._emit(t, "LAB_IMMORTAL_GUIDE", trigger=self.immortal_add_trigger)
            if (
                np.isfinite(self.immortal_add_trigger)
                and t <= self.immortal_add_expire_t
                and float(row["High"]) > self.immortal_add_trigger
            ):
                signal = "LAB_ADD_ON_IMMORTAL_BREAK"
                position_hint = "add_40pct"
                self._emit(t, signal)
                self.immortal_add_trigger = float("nan")
            if np.isfinite(self.gap_iron_support) and close < self.gap_iron_support:
                signal = "LAB_GAP_SUPPORT_BREAK_EXIT"
                position_hint = "exit"
                self.state = WaveState.WAVE_A_DROP
                self._emit(t, signal)
            elif np.isfinite(self.P2) and close < self.P2 and (
                not np.isfinite(self.P1) or self.cand_high.price <= self.P1
            ):
                # 標記洗盤觀察（回測讀事件）
                self._emit(t, "LAB_WASHOUT_WATCH_CANDIDATE", reason="break_P2")
                self.reset_structure()
                position_hint = "exit"
                self._emit(t, "LAB_W3_FAIL_BREAK_P2")
            else:
                pulling = np.isfinite(ma10) and close < ma10
                if pulling and self._w3_extension_hold(row, close, ma20, ma20_safe):
                    self.w3_reduce_flag = True
                    position_hint = "reduce_1_3"
                    self._emit(t, "LAB_W3_SUBWAVE_HOLD")
                else:
                    # 對數：W3 長度目標相對 log_W1（軋空用更高倍數才認頂）
                    stretch = 0.618 if not self.short_squeeze else 1.0
                    ext_need = (
                        self.P2 * np.exp(stretch * self.log_W1)
                        if np.isfinite(self.P2) and np.isfinite(self.log_W1)
                        else float("nan")
                    )
                    if (
                        np.isfinite(ext_need)
                        and self.cand_high.price > ext_need
                        and self._confirm_swing_high(t, row)
                    ):
                        if self._w3_extension_hold(row, close, ma20, ma20_safe) and not bool(
                            row.get("is_exhaustion_vol")
                        ):
                            self.w3_reduce_flag = True
                            position_hint = "reduce_1_3"
                            self._emit(t, "LAB_W3_EXTENSION_HOLD")
                        else:
                            self.P3 = self.cand_high.price
                            self.t_P3 = self.cand_high.t_idx
                            self.log_W3 = _log_len(self.P3, self.P2)
                            self.state = WaveState.WAVE_4_CONSOL
                            self.w3_reduce_flag = False
                            self.cand_low = SwingCandidate(t, float(row["Low"]), vol_ma5, angle10)
                            self._emit(t, "LAB_W3_TOP", P3=self.P3, log_W3=self.log_W3)

        elif self.state == WaveState.WAVE_4_CONSOL:
            position_hint = "long"
            if (
                np.isfinite(self.P1)
                and np.isfinite(atr)
                and atr > 0
                and close < self.P1 - 0.5 * atr
                and np.isfinite(ma60)
                and close < ma60
            ):
                self.state = WaveState.WAVE_A_DROP
                position_hint = "exit"
                self._emit(t, "LAB_W4_OVERLAP_FAIL")
            else:
                days_w4 = t - self.t_P3 if self.t_P3 >= 0 else 0
                retrace4 = _log_retrace(self.P3, self.P2, self.cand_low.price if np.isfinite(self.cand_low.price) else close)
                alt_deep_w2 = np.isfinite(self.w2_depth) and self.w2_depth >= 0.55
                if alt_deep_w2:
                    retrace_ok = np.isfinite(retrace4) and 0.15 <= retrace4 <= 0.382
                    time_ok4 = days_w4 >= max(1, int(self.w2_days * 1.2))
                else:
                    retrace_ok = True
                    time_ok4 = True
                kd_buy = (
                    self.has_impulse_momentum
                    and bool(row.get("kd_pullback_buy_zone"))
                    and np.isfinite(ma20_safe)
                    and ma20_safe > 0
                )
                bounce = (
                    (
                        (bool(row.get("had_trough_vol_10d")) or bool(row.get("is_trough_vol")))
                        and bool(row.get("is_key_bull_candle"))
                        and bool(row.get("is_attack_vol"))
                    )
                    or kd_buy
                ) and np.isfinite(ma20) and close > ma20 and np.isfinite(self.P1) and close > self.P1 * 0.98 and retrace_ok and time_ok4
                if bounce and (self._confirm_swing_low(t, row) or kd_buy):
                    self.P4 = self.cand_low.price
                    self.t_P4 = self.cand_low.t_idx
                    self._set_diag_from_p2_p4()
                    self.state = WaveState.WAVE_5_FINAL
                    self.cand_high = SwingCandidate(t, float(row["High"]), vol_ma5, angle10)
                    self._emit(t, "LAB_W5_START", P4=self.P4, kd_buy=kd_buy)

        elif self.state == WaveState.WAVE_5_FINAL:
            position_hint = "long"
            bias = float(row["bias_ma20_pct"]) if np.isfinite(row.get("bias_ma20_pct", np.nan)) else float("nan")
            # V6：高檔避雷針
            if bool(row.get("is_long_upper_shadow_vol")) and (
                (np.isfinite(bias) and bias > 0.15) or True
            ):
                self.shooting_star_low = float(row["Low"])
                self._emit(t, "LAB_SHOOTING_STAR", low=self.shooting_star_low)
            if np.isfinite(self.shooting_star_low) and close < self.shooting_star_low:
                signal = "LAB_SHOOTING_STAR_EXIT"
                position_hint = "exit"
                self.P5 = self.cand_high.price if np.isfinite(self.cand_high.price) else close
                self.log_W5 = _log_len(self.P5, self.P4) if np.isfinite(self.P4) else float("nan")
                self.state = WaveState.WAVE_A_DROP
                self._emit(t, signal)
            # V6：MACD 雙重頂背離
            dif = float(row["DIF"]) if np.isfinite(row.get("DIF", np.nan)) else float("nan")
            hist = float(row["MACD_HIST"]) if np.isfinite(row.get("MACD_HIST", np.nan)) else float("nan")
            price_new_high = np.isfinite(self.P3) and float(row["High"]) >= self.P3
            macd_div = (
                price_new_high
                and np.isfinite(dif)
                and np.isfinite(self.dif_w3_peak)
                and dif < self.dif_w3_peak * 0.85
                and np.isfinite(hist)
                and np.isfinite(self.hist_w3_peak)
                and hist < self.hist_w3_peak * 0.80
                and bool(row.get("macd_hist_contracting"))
            )
            if macd_div and ((np.isfinite(ma5) and close < ma5) or bool(row.get("is_exhaustion_vol"))):
                signal = "LAB_MACD_W5_DIVERGENCE_EXIT"
                position_hint = "exit"
                self.P5 = self.cand_high.price if np.isfinite(self.cand_high.price) else close
                self.log_W5 = _log_len(self.P5, self.P4) if np.isfinite(self.P4) else float("nan")
                self.state = WaveState.WAVE_A_DROP
                self._emit(t, signal, dif=dif, hist=hist)
            # V5：終結楔形
            diag = self._diag_line_at(t)
            broke_p3 = np.isfinite(self.P3) and close < self.P3
            above_diag = (not np.isfinite(diag)) or close >= diag
            mild_new_high = np.isfinite(self.P3) and float(row["High"]) > self.P3 * 1.001
            if broke_p3 and above_diag and mild_new_high and np.isfinite(diag):
                self.state = WaveState.WAVE_5_ENDING_DIAGONAL
                self._emit(t, "LAB_W5_ENDING_DIAGONAL")
            elif position_hint != "exit":
                near_zone = np.isfinite(self.P3) and float(row["High"]) >= self.P3 * 0.95
                div_vol = (
                    near_zone
                    and np.isfinite(vol_ma5)
                    and np.isfinite(self.V3_peak)
                    and vol_ma5 < 0.80 * self.V3_peak
                )
                div_ang = (
                    near_zone
                    and np.isfinite(angle10)
                    and np.isfinite(self.A3_peak)
                    and angle10 < self.A3_peak - 10.0
                )
                break_ma20 = np.isfinite(ma20) and close < ma20
                break_p4 = np.isfinite(self.P4) and close < self.P4
                never_past = np.isfinite(self.P3) and self.cand_high.price < self.P3
                if near_zone and (div_vol or div_ang or macd_div) and (break_ma20 or break_p4) and never_past:
                    self.P5 = self.cand_high.price if np.isfinite(self.cand_high.price) else close
                    self.log_W5 = _log_len(self.P5, self.P4)
                    self.state = WaveState.WAVE_A_DROP
                    signal = "LAB_TRUNCATED_W5_EXIT"
                    position_hint = "exit"
                    self._emit(t, signal, iron_rule3=self._iron_rule3_ok())
                else:
                    near_p3 = np.isfinite(self.P3) and float(row["High"]) >= self.P3 * 0.98
                    div_n = sum(
                        [
                            near_p3
                            and np.isfinite(vol_ma5)
                            and np.isfinite(self.V3_peak)
                            and vol_ma5 < 0.85 * self.V3_peak,
                            near_p3
                            and np.isfinite(angle10)
                            and np.isfinite(self.A3_peak)
                            and angle10 < self.A3_peak - 10.0,
                            np.isfinite(ma20_safe) and ma20_safe < 0,
                            macd_div,
                        ]
                    )
                    if div_n >= 2 and ((np.isfinite(ma5) and close < ma5) or bool(row.get("is_exhaustion_vol"))):
                        self.P5 = self.cand_high.price if np.isfinite(self.cand_high.price) else close
                        self.log_W5 = _log_len(self.P5, self.P4)
                        self.state = WaveState.WAVE_A_DROP
                        signal = "LAB_SELL_W5_TOP"
                        position_hint = "exit"
                        self._emit(t, signal, iron_rule3=self._iron_rule3_ok())

        elif self.state == WaveState.WAVE_5_ENDING_DIAGONAL:
            position_hint = "long"
            diag = self._diag_line_at(t)
            # 防守收緊：MA5 與楔形下軌
            stop_candidates = [x for x in (ma5, diag) if np.isfinite(x)]
            if stop_candidates:
                tight = max(stop_candidates)  # 更高的那條＝更緊（對多頭）
                # 實際用較緊：多頭防守取較高支撐中的較嚴格 → 跌破任一即出，用 min 當聯合下緣
                tight = min(stop_candidates)
                self.stop_loss = tight
            if np.isfinite(ma5) and close < ma5:
                signal = "LAB_ENDING_DIAGONAL_EXIT_NEXT_OPEN"
                position_hint = "exit_next_open"
                self.P5 = self.cand_high.price if np.isfinite(self.cand_high.price) else close
                self.log_W5 = _log_len(self.P5, self.P4) if np.isfinite(self.P4) else float("nan")
                self.state = WaveState.WAVE_A_DROP
                self._emit(t, signal, stop=self.stop_loss)

        elif self.state == WaveState.WAVE_A_DROP:
            position_hint = "flat"
            # 追蹤 A 浪最大 5 日均量（供 B 浪量價背離）
            if np.isfinite(vol_ma5) and (
                not np.isfinite(self.vol_ma5_a_peak) or vol_ma5 > self.vol_ma5_a_peak
            ):
                self.vol_ma5_a_peak = vol_ma5
            if self._confirm_swing_low(t, row):
                self.PA = self.cand_low.price
                self.state = WaveState.WAVE_B_TRAP
                self.cand_high = SwingCandidate(t, float(row["High"]), vol_ma5, angle10)
                self._emit(t, "LAB_WA_BOTTOM", PA=self.PA)

        elif self.state == WaveState.WAVE_B_TRAP:
            signal = "LAB_NO_BUY_B_WAVE_TRAP"
            position_hint = "flat"
            pierced = np.isfinite(self.P5) and float(row["High"]) > self.P5
            weak_vol = np.isfinite(self.V3_peak) and np.isfinite(vol_ma5) and vol_ma5 < self.V3_peak * 0.65
            time_press = np.isfinite(ma60_safe) and ma60_safe < 0
            if pierced and (weak_vol or time_press):
                self._emit(t, "LAB_B_EXPANDED_FLAT_TRAP", weak_vol=weak_vol, time_press=time_press)
            failed_passivation = (not bool(row.get("kd_high_passivation"))) and bool(
                row.get("kd_death_cross")
            ) and np.isfinite(k_val) and k_val > 80
            # 記 PB
            if np.isfinite(self.cand_high.price):
                if (not np.isfinite(self.PB)) or self.cand_high.price > self.PB:
                    self.PB = self.cand_high.price
            # V7：C 浪放空對稱引擎
            under_ma60 = np.isfinite(ma60) and close < ma60
            dual_cap = (
                np.isfinite(ma20_safe)
                and ma20_safe <= -0.4
                and np.isfinite(ma60_safe)
                and ma60_safe <= -0.4
            )
            b_vol_div = (
                np.isfinite(vol_ma5)
                and np.isfinite(self.vol_ma5_a_peak)
                and vol_ma5 < self.vol_ma5_a_peak * 0.65
            )
            bear_bar = (
                np.isfinite(row.get("ret_1d", np.nan))
                and float(row["ret_1d"]) <= -0.03
                and np.isfinite(ma10)
                and close < ma10
                and np.isfinite(ma20)
                and close < ma20
            )
            steep_down = np.isfinite(angle5) and angle5 <= -38.0
            if (
                under_ma60
                and dual_cap
                and b_vol_div
                and (failed_passivation or bool(row.get("kd_death_cross")))
                and bear_bar
                and steep_down
            ):
                self.state = WaveState.WAVE_C_CRASH
                hard = float(row["High"])
                if np.isfinite(self.PB):
                    hard = min(hard, self.PB)
                self.short_stop = hard
                signal = "LAB_SHORT_W_C_START"
                position_hint = "short"
                self.in_short = True
                self._emit(t, signal, short_stop=self.short_stop, PB=self.PB)
            elif failed_passivation or (
                ((np.isfinite(self.V3_peak) and np.isfinite(vol_ma5) and vol_ma5 < self.V3_peak * 0.6)
                 and (not np.isfinite(angle5) or angle5 < 35.0))
                and self._confirm_swing_high(t, row)
            ):
                self.PB = self.cand_high.price if np.isfinite(self.cand_high.price) else close
                if failed_passivation or (np.isfinite(ma20) and close < ma20) or (
                    np.isfinite(self.PA) and close < self.PA
                ):
                    self.state = WaveState.WAVE_C_CRASH
                    self._emit(t, "LAB_WC_START", PB=self.PB, kd_fail=failed_passivation)

        elif self.state == WaveState.WAVE_C_CRASH:
            position_hint = "short" if self.in_short else "flat"
            if self.in_short and np.isfinite(self.short_stop) and close > self.short_stop:
                signal = "LAB_SHORT_STOP_COVER"
                position_hint = "cover"
                self.in_short = False
                self.short_stop = float("nan")
                self._emit(t, signal)
            hit_target = False
            if self.in_short and np.isfinite(self.PA) and np.isfinite(self.P5) and np.isfinite(self.PB):
                len_a = abs(np.log(self.PA / self.P5)) if self.PA > 0 and self.P5 > 0 else float("nan")
                len_c = abs(np.log(close / self.PB)) if close > 0 and self.PB > 0 else float("nan")
                hit_target = np.isfinite(len_a) and np.isfinite(len_c) and len_c >= len_a * 1.0
            hammer_cover = bool(row.get("is_hammer_shape")) and bool(row.get("is_exhaustion_vol"))
            kd_low_golden = np.isfinite(k_val) and k_val < 20 and bool(row.get("kd_golden_cross"))
            if self.in_short and hit_target and (hammer_cover or kd_low_golden):
                signal = "LAB_SHORT_COVER_TARGET"
                position_hint = "cover"
                self.in_short = False
                self.short_stop = float("nan")
                self._emit(t, signal)
            if (
                bool(row.get("is_trough_vol"))
                and np.isfinite(ma60)
                and close > ma60
                and bool(row.get("is_key_bull_candle"))
            ):
                if self.in_short:
                    signal = "LAB_SHORT_COVER_BASE"
                    position_hint = "cover"
                    self.in_short = False
                    self._emit(t, signal)
                self.reset_structure()
                self._emit(t, "LAB_CYCLE_RESET")

        # 動態補上當日楔形下軌數值
        snap = self._snap(signal, position_hint, base_score)
        snap["diag_support"] = self._diag_line_at(t)
        return snap

    def run(self, df: pd.DataFrame, *, already_featured: bool = False) -> pd.DataFrame:
        feat = df if already_featured else compute_hsiao_features(df)
        if "prior_high_5" not in feat.columns:
            feat = feat.copy()
            feat["prior_high_5"] = feat["High"].shift(1).rolling(5).max()
        rows = []
        self.reset_structure()
        self.cand_high = SwingCandidate()
        self.cand_low = SwingCandidate()
        self.lab_events = []
        for t in range(len(feat)):
            rows.append(self.step(t, feat.iloc[t]))
        out = feat.copy()
        snap_df = pd.DataFrame(rows, index=feat.index)
        for col in snap_df.columns:
            out[col] = snap_df[col]
        out.attrs["phone_sync"] = PHONE_SYNC
        out.attrs["not_buy_signal"] = NOT_BUY_SIGNAL
        out.attrs["lab_events"] = list(self.lab_events)
        out.attrs["engine_version"] = "hsiao_v7"
        return out


__all__ = [
    "ElliottHsiaoEngine",
    "WaveState",
    "STATE_NAME",
    "PHONE_SYNC",
    "NOT_BUY_SIGNAL",
    "_log_retrace",
    "_log_len",
]
