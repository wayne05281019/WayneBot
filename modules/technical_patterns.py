"""
WayneBot 台股量化交易系統
模組名稱：technical_patterns.py
功能說明：Phase 6 - 量化技術指標與 K 線形態特徵識別模組
"""

import numpy as np
import pandas as pd
from typing import Dict, Any, List, Optional, Tuple


# =====================================================================
# 1. 基礎技術指標計算模組
# =====================================================================

def calculate_ma(df: pd.DataFrame, windows: List[int] = [5, 10, 20, 60]) -> pd.DataFrame:
    """計算指定週期的移動平均線與均線斜率"""
    df_out = df.copy()
    for w in windows:
        col_name = f"ma{w}"
        df_out[col_name] = df_out['close'].rolling(window=w, min_periods=1).mean()
        df_out[f"{col_name}_slope"] = (df_out[col_name] - df_out[col_name].shift(1)) / df_out[col_name].shift(1) * 100
    return df_out


def check_ma_alignment(df: pd.DataFrame) -> Dict[str, Any]:
    """判定均線多頭/空頭排列與離散度"""
    if len(df) == 0:
        return {"is_bullish": False, "is_bearish": False, "spread_pct": 0.0, "alignment_score": 0.0}
    
    last = df.iloc[-1]
    ma5 = last.get('ma5', np.nan)
    ma10 = last.get('ma10', np.nan)
    ma20 = last.get('ma20', np.nan)
    ma60 = last.get('ma60', np.nan)

    if pd.isna(ma5) or pd.isna(ma10) or pd.isna(ma20):
        return {"is_bullish": False, "is_bearish": False, "spread_pct": 0.0, "alignment_score": 0.0}

    if not pd.isna(ma60):
        is_bullish = (ma5 > ma10) and (ma10 > ma20) and (ma20 > ma60)
        is_bearish = (ma5 < ma10) and (ma10 < ma20) and (ma20 < ma60)
        mas = [ma5, ma10, ma20, ma60]
    else:
        is_bullish = (ma5 > ma10) and (ma10 > ma20)
        is_bearish = (ma5 < ma10) and (ma10 < ma20)
        mas = [ma5, ma10, ma20]

    spread = (max(mas) - min(mas)) / min(mas) if min(mas) > 0 else 0.0
    score = 100.0 if is_bullish else (40.0 if (ma5 > ma10 and ma10 > ma20) else 0.0)

    return {
        "is_bullish": bool(is_bullish),
        "is_bearish": bool(is_bearish),
        "spread_pct": float(round(spread * 100, 2)),
        "alignment_score": float(score)
    }


def calculate_kd(df: pd.DataFrame, n: int = 9, m1: int = 3, m2: int = 3) -> pd.DataFrame:
    """計算台股標準 KD 指標 (預設 9, 3, 3，初始值為 50.0)"""
    df_out = df.copy()
    low_min = df_out['low'].rolling(window=n, min_periods=1).min()
    high_max = df_out['high'].rolling(window=n, min_periods=1).max()
    
    denom = (high_max - low_min).replace(0, np.nan)
    rsv = ((df_out['close'] - low_min) / denom * 100).fillna(50.0)

    k_vals, d_vals = [], []
    k_curr, d_curr = 50.0, 50.0

    weight_k1, weight_k2 = (m1 - 1) / m1, 1.0 / m1
    weight_d1, weight_d2 = (m2 - 1) / m2, 1.0 / m2

    for r in rsv:
        k_curr = weight_k1 * k_curr + weight_k2 * r
        d_curr = weight_d1 * d_curr + weight_d2 * k_curr
        k_vals.append(k_curr)
        d_vals.append(d_curr)

    df_out['k'] = k_vals
    df_out['d'] = d_vals
    return df_out


def calculate_rsi(df: pd.DataFrame, period: int = 14) -> pd.DataFrame:
    """計算 RSI 指標 (採用 Wilder 平滑法)"""
    df_out = df.copy()
    delta = df_out['close'].diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)

    avg_gain = gain.ewm(alpha=1.0 / period, min_periods=period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1.0 / period, min_periods=period, adjust=False).mean()

    rs = avg_gain / avg_loss.replace(0, np.nan)
    rsi = 100 - (100 / (1 + rs))
    df_out[f'rsi{period}'] = rsi.fillna(50.0)
    return df_out


def calculate_macd(df: pd.DataFrame, fast: int = 12, slow: int = 26, signal: int = 9) -> pd.DataFrame:
    """計算 MACD 指標 (DIF, DEA, OSC 柱狀圖)"""
    df_out = df.copy()
    ema_fast = df_out['close'].ewm(span=fast, adjust=False).mean()
    ema_slow = df_out['close'].ewm(span=slow, adjust=False).mean()
    dif = ema_fast - ema_slow
    dea = dif.ewm(span=signal, adjust=False).mean()
    osc = dif - dea

    df_out['macd_dif'] = dif
    df_out['macd_dea'] = dea
    df_out['macd_osc'] = osc
    return df_out


def calculate_bbands(df: pd.DataFrame, period: int = 20, num_std: float = 2.0) -> pd.DataFrame:
    """計算布林通道 (上軌, 中軌, 下軌, 帶寬, %B)"""
    df_out = df.copy()
    mid = df_out['close'].rolling(window=period, min_periods=1).mean()
    std = df_out['close'].rolling(window=period, min_periods=1).std().fillna(0)
    upper = mid + num_std * std
    lower = mid - num_std * std
    
    bandwidth = (upper - lower) / mid.replace(0, np.nan)
    band_range = (upper - lower).replace(0, np.nan)
    pct_b = (df_out['close'] - lower) / band_range

    df_out['bb_mid'] = mid
    df_out['bb_upper'] = upper
    df_out['bb_lower'] = lower
    df_out['bb_bandwidth'] = bandwidth.fillna(0.0)
    df_out['bb_percent_b'] = pct_b.fillna(0.5)
    return df_out


def compute_all_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """整合運算所有技術指標與成交量均線"""
    df_res = df.copy()
    if 'volume' in df_res.columns:
        df_res['vma5'] = df_res['volume'].rolling(window=5, min_periods=1).mean()
        df_res['vma20'] = df_res['volume'].rolling(window=20, min_periods=1).mean()
    
    df_res = calculate_ma(df_res, [5, 10, 20, 60])
    df_res = calculate_kd(df_res, 9, 3, 3)
    df_res = calculate_rsi(df_res, 14)
    df_res = calculate_macd(df_res, 12, 26, 9)
    df_res = calculate_bbands(df_res, 20, 2.0)
    return df_res


# =====================================================================
# 2. 輔助運算：局部波段極值點 (Swing High / Low) 萃取
# =====================================================================

def find_extrema(series: pd.Series, order: int = 2) -> Tuple[List[int], List[int]]:
    """尋找局部波段高點 (Peaks) 與低點 (Troughs) 索引"""
    vals = series.values
    n = len(vals)
    peaks, troughs = [], []
    for i in range(order, n - order):
        window = vals[i - order : i + order + 1]
        if np.all(vals[i] >= window) and np.any(vals[i] > window):
            peaks.append(i)
        elif np.all(vals[i] <= window) and np.any(vals[i] < window):
            troughs.append(i)
    return peaks, troughs


# =====================================================================
# 3. 台股經典勝率形態識別演算法模組
# =====================================================================

def detect_w_bottom(df: pd.DataFrame, lookback: int = 60) -> Dict[str, Any]:
    """W底（雙底突破頸線）辨識"""
    if len(df) < 20:
        return {"detected": False, "score": 0.0, "details": {}}

    sub_df = df.iloc[-lookback:].copy().reset_index(drop=True)
    _, troughs = find_extrema(sub_df['low'], order=2)
    peaks, _ = find_extrema(sub_df['high'], order=2)

    if len(troughs) < 2 or len(peaks) < 1:
        return {"detected": False, "score": 0.0, "details": {}}

    best_match = None
    max_score = 0.0

    for i in range(len(troughs) - 1):
        t1_idx = troughs[i]
        for j in range(i + 1, len(troughs)):
            t2_idx = troughs[j]
            if t2_idx - t1_idx < 4:
                continue

            mid_peaks = [p for p in peaks if t1_idx < p < t2_idx]
            if not mid_peaks:
                continue

            p_idx = max(mid_peaks, key=lambda x: sub_df['high'].iloc[x])
            t1_val = sub_df['low'].iloc[t1_idx]
            t2_val = sub_df['low'].iloc[t2_idx]
            p_val = sub_df['high'].iloc[p_idx]

            if p_val <= max(t1_val, t2_val) * 1.025:
                continue

            t_diff_pct = abs(t1_val - t2_val) / t1_val
            if t_diff_pct > 0.045:
                continue

            curr_close = sub_df['close'].iloc[-1]
            curr_high = sub_df['high'].iloc[-1]
            breakout_condition = (curr_close >= p_val * 0.99) or (curr_high >= p_val and curr_close >= p_val * 0.98)
            if not breakout_condition:
                continue

            score = 50.0
            if t2_val >= t1_val:
                score += 15.0
            else:
                score += max(0.0, 10.0 - t_diff_pct * 200)

            breakout_pct = (curr_close - p_val) / p_val * 100
            score += min(15.0, max(0.0, breakout_pct * 3.0))

            curr_vol = sub_df['volume'].iloc[-1]
            vma20 = sub_df['vma20'].iloc[-1] if 'vma20' in sub_df.columns else sub_df['volume'].mean()
            vol_ratio = curr_vol / vma20 if vma20 > 0 else 1.0
            if vol_ratio >= 1.2:
                score += min(20.0, (vol_ratio - 1.0) * 15.0)

            if score > max_score:
                max_score = score
                best_match = {
                    "t1_price": float(round(t1_val, 2)),
                    "neckline_price": float(round(p_val, 2)),
                    "t2_price": float(round(t2_val, 2)),
                    "breakout_pct": float(round(breakout_pct, 2)),
                    "vol_ratio": float(round(vol_ratio, 2)),
                    "score": float(round(min(100.0, score), 1))
                }

    if best_match and max_score >= 60.0:
        return {"detected": True, "score": best_match["score"], "details": best_match}
    return {"detected": False, "score": 0.0, "details": {}}


def detect_head_and_shoulders_bottom(df: pd.DataFrame, lookback: int = 70) -> Dict[str, Any]:
    """頭肩底形態辨識"""
    if len(df) < 30:
        return {"detected": False, "score": 0.0, "details": {}}

    sub_df = df.iloc[-lookback:].copy().reset_index(drop=True)
    _, troughs = find_extrema(sub_df['low'], order=2)
    peaks, _ = find_extrema(sub_df['high'], order=2)

    if len(troughs) < 3 or len(peaks) < 2:
        return {"detected": False, "score": 0.0, "details": {}}

    best_match = None
    max_score = 0.0

    for i in range(len(troughs) - 2):
        ls_idx = troughs[i]
        for j in range(i + 1, len(troughs) - 1):
            h_idx = troughs[j]
            if h_idx - ls_idx < 3:
                continue
            for k in range(j + 1, len(troughs)):
                rs_idx = troughs[k]
                if rs_idx - h_idx < 3:
                    continue

                ls_val = sub_df['low'].iloc[ls_idx]
                h_val = sub_df['low'].iloc[h_idx]
                rs_val = sub_df['low'].iloc[rs_idx]

                if not (h_val < ls_val * 0.985 and h_val < rs_val * 0.985):
                    continue

                shoulder_diff = abs(ls_val - rs_val) / ls_val
                if shoulder_diff > 0.06:
                    continue

                p1_candidates = [p for p in peaks if ls_idx < p < h_idx]
                p2_candidates = [p for p in peaks if h_idx < p < rs_idx]
                if not p1_candidates or not p2_candidates:
                    continue

                p1_val = sub_df['high'].iloc[max(p1_candidates, key=lambda x: sub_df['high'].iloc[x])]
                p2_val = sub_df['high'].iloc[max(p2_candidates, key=lambda x: sub_df['high'].iloc[x])]
                neckline_val = (p1_val + p2_val) / 2.0

                curr_close = sub_df['close'].iloc[-1]
                if curr_close < neckline_val * 0.985:
                    continue

                rs_vol = sub_df['volume'].iloc[rs_idx - 1 : rs_idx + 2].mean()
                h_vol = sub_df['volume'].iloc[h_idx - 1 : h_idx + 2].mean()
                volume_contracted = (rs_vol <= h_vol * 1.1)

                score = 55.0
                if rs_val >= ls_val:
                    score += 10.0
                score += max(0.0, 10.0 - shoulder_diff * 150)
                if volume_contracted:
                    score += 10.0

                breakout_pct = (curr_close - neckline_val) / neckline_val * 100
                score += min(15.0, max(0.0, breakout_pct * 3.0))

                curr_vol = sub_df['volume'].iloc[-1]
                vma20 = sub_df['vma20'].iloc[-1] if 'vma20' in sub_df.columns else sub_df['volume'].mean()
                vol_ratio = curr_vol / vma20 if vma20 > 0 else 1.0
                if vol_ratio >= 1.2:
                    score += min(10.0, (vol_ratio - 1.0) * 10.0)

                if score > max_score:
                    max_score = score
                    best_match = {
                        "left_shoulder": float(round(ls_val, 2)),
                        "head": float(round(h_val, 2)),
                        "right_shoulder": float(round(rs_val, 2)),
                        "neckline_price": float(round(neckline_val, 2)),
                        "breakout_pct": float(round(breakout_pct, 2)),
                        "vol_ratio": float(round(vol_ratio, 2)),
                        "score": float(round(min(100.0, score), 1))
                    }

    if best_match and max_score >= 60.0:
        return {"detected": True, "score": best_match["score"], "details": best_match}
    return {"detected": False, "score": 0.0, "details": {}}


def detect_false_breakdown(df: pd.DataFrame, lookback: int = 40) -> Dict[str, Any]:
    """破底翻（假跌破關鍵支撐後帶量長紅收復）辨識"""
    if len(df) < 20:
        return {"detected": False, "score": 0.0, "details": {}}

    sub_df = df.iloc[-lookback:].copy().reset_index(drop=True)
    n = len(sub_df)
    
    prior_window = sub_df.iloc[:-5]
    if len(prior_window) < 10:
        return {"detected": False, "score": 0.0, "details": {}}

    support_s = prior_window['low'].min()
    recent_5 = sub_df.iloc[-5:]
    recent_low = recent_5['low'].min()
    recent_low_idx = recent_5['low'].idxmin()

    if recent_low > support_s * 0.997:
        return {"detected": False, "score": 0.0, "details": {}}

    curr_bar = sub_df.iloc[-1]
    curr_open = curr_bar['open']
    curr_close = curr_bar['close']
    curr_high = curr_bar['high']
    curr_low = curr_bar['low']
    curr_vol = curr_bar['volume']

    reclaimed = (curr_close >= support_s * 1.002)
    if not reclaimed:
        return {"detected": False, "score": 0.0, "details": {}}

    candle_body_pct = (curr_close - curr_open) / curr_open * 100
    is_red_candle = (curr_close > curr_open) and (candle_body_pct >= 1.0)
    
    bar_range = curr_high - curr_low
    close_to_high_ratio = (curr_close - curr_low) / bar_range if bar_range > 0 else 1.0

    if not (is_red_candle or close_to_high_ratio >= 0.70):
        return {"detected": False, "score": 0.0, "details": {}}

    vma20 = sub_df['vma20'].iloc[-1] if 'vma20' in sub_df.columns else sub_df['volume'].mean()
    vol_ratio = curr_vol / vma20 if vma20 > 0 else 1.0

    score = 55.0
    shakeout_bars = n - 1 - recent_low_idx
    if shakeout_bars <= 2:
        score += 15.0
    elif shakeout_bars <= 4:
        score += 10.0

    score += min(15.0, candle_body_pct * 3.0)

    if vol_ratio >= 1.3:
        score += min(15.0, (vol_ratio - 1.0) * 10.0)

    details = {
        "support_level": float(round(support_s, 2)),
        "breakdown_low": float(round(recent_low, 2)),
        "shakeout_bars": int(shakeout_bars),
        "recovery_close": float(round(curr_close, 2)),
        "vol_ratio": float(round(vol_ratio, 2)),
        "candle_body_pct": float(round(candle_body_pct, 2)),
        "score": float(round(min(100.0, score), 1))
    }

    return {
        "detected": True,
        "score": details["score"],
        "details": details
    }


def detect_v_reversal(df: pd.DataFrame, lookback: int = 20) -> Dict[str, Any]:
    """V型反轉識別演算法"""
    if len(df) < 15:
        return {"detected": False, "score": 0.0, "details": {}}

    sub_df = df.iloc[-lookback:].copy().reset_index(drop=True)

    recent_window = sub_df.iloc[-5:]
    trough_idx = recent_window['low'].idxmin()
    trough_val = sub_df['low'].iloc[trough_idx]

    prior_peak_idx = sub_df['high'].iloc[max(0, trough_idx - 7) : trough_idx].idxmax() if trough_idx > 1 else 0
    prior_peak_val = sub_df['high'].iloc[prior_peak_idx]

    drop_pct = (prior_peak_val - trough_val) / prior_peak_val * 100
    if drop_pct < 5.0 or (trough_idx - prior_peak_idx) < 2:
        return {"detected": False, "score": 0.0, "details": {}}

    curr_close = sub_df['close'].iloc[-1]
    rebound_pct = (curr_close - trough_val) / trough_val * 100
    if rebound_pct < 4.0:
        return {"detected": False, "score": 0.0, "details": {}}

    ma5 = sub_df['ma5'].iloc[-1] if 'ma5' in sub_df.columns else sub_df['close'].rolling(5).mean().iloc[-1]
    reclaim_ma = (curr_close >= ma5)

    curr_vol = sub_df['volume'].iloc[-1]
    vma20 = sub_df['vma20'].iloc[-1] if 'vma20' in sub_df.columns else sub_df['volume'].mean()
    vol_ratio = curr_vol / vma20 if vma20 > 0 else 1.0

    score = 50.0
    score += min(20.0, rebound_pct * 2.5)
    if reclaim_ma:
        score += 15.0
    if vol_ratio >= 1.2:
        score += min(15.0, (vol_ratio - 1.0) * 10.0)

    details = {
        "trough_price": float(round(trough_val, 2)),
        "drop_pct": float(round(drop_pct, 2)),
        "rebound_pct": float(round(rebound_pct, 2)),
        "vol_ratio": float(round(vol_ratio, 2)),
        "score": float(round(min(100.0, score), 1))
    }

    return {
        "detected": True,
        "score": details["score"],
        "details": details
    }


def detect_ma_entanglement_breakout(df: pd.DataFrame, lookback: int = 25) -> Dict[str, Any]:
    """均線糾結帶量長紅突破辨識"""
    if len(df) < 25:
        return {"detected": False, "score": 0.0, "details": {}}

    sub_df = df.iloc[-lookback:].copy().reset_index(drop=True)
    
    consolidation = sub_df.iloc[-12:-1]
    if len(consolidation) < 5:
        return {"detected": False, "score": 0.0, "details": {}}

    ma5_s = consolidation['ma5']
    ma10_s = consolidation['ma10']
    ma20_s = consolidation['ma20']

    ma_max = pd.concat([ma5_s, ma10_s, ma20_s], axis=1).max(axis=1)
    ma_min = pd.concat([ma5_s, ma10_s, ma20_s], axis=1).min(axis=1)
    dispersion = ((ma_max - ma_min) / ma20_s).mean()

    is_entangled = (dispersion <= 0.028)
    if not is_entangled:
        return {"detected": False, "score": 0.0, "details": {}}

    curr_bar = sub_df.iloc[-1]
    curr_open = curr_bar['open']
    curr_close = curr_bar['close']
    curr_vol = curr_bar['volume']

    candle_pct = (curr_close - curr_open) / curr_open * 100
    if candle_pct < 2.0:
        return {"detected": False, "score": 0.0, "details": {}}

    cons_high = consolidation['high'].max()
    is_breakout_high = (curr_close >= cons_high * 0.998)
    if not is_breakout_high:
        return {"detected": False, "score": 0.0, "details": {}}

    ma5_curr = curr_bar['ma5']
    ma10_curr = curr_bar['ma10']
    ma20_curr = curr_bar['ma20']
    above_all_mas = (curr_close > ma5_curr) and (curr_close > ma10_curr) and (curr_close > ma20_curr)
    if not above_all_mas:
        return {"detected": False, "score": 0.0, "details": {}}

    vma20 = curr_bar.get('vma20', sub_df['volume'].mean())
    vol_ratio = curr_vol / vma20 if vma20 > 0 else 1.0
    if vol_ratio < 1.4:
        return {"detected": False, "score": 0.0, "details": {}}

    score = 60.0
    score += max(0.0, (0.028 - dispersion) / 0.028 * 15.0)
    score += min(15.0, (vol_ratio - 1.4) * 10.0)
    score += min(10.0, (candle_pct - 2.0) * 2.5)

    details = {
        "ma_dispersion_pct": float(round(dispersion * 100, 2)),
        "consolidation_high": float(round(cons_high, 2)),
        "candle_gain_pct": float(round(candle_pct, 2)),
        "vol_ratio": float(round(vol_ratio, 2)),
        "score": float(round(min(100.0, score), 1))
    }

    return {
        "detected": True,
        "score": details["score"],
        "details": details
    }


# =====================================================================
# 4. 統一封裝函式 analyze_stock_patterns
# =====================================================================

def analyze_stock_patterns(df_kline: pd.DataFrame, symbol: str = "") -> Dict[str, Any]:
    """統一入口：接收 K 線數據，回傳所有技術指標、形態特徵與綜合多頭強度評分"""
    if df_kline is None or len(df_kline) == 0:
        raise ValueError("輸入的 df_kline 不能為空")

    df = df_kline.copy()
    df.columns = [c.lower() for c in df.columns]

    required_cols = ['open', 'high', 'low', 'close', 'volume']
    for col in required_cols:
        if col not in df.columns:
            raise ValueError(f"缺少必要 K 線欄位: {col}")

    df_calc = compute_all_indicators(df)
    last_row = df_calc.iloc[-1]
    prev_row = df_calc.iloc[-2] if len(df_calc) >= 2 else last_row

    ma_align = check_ma_alignment(df_calc)
    
    k_curr, d_curr = last_row['k'], last_row['d']
    k_prev, d_prev = prev_row['k'], prev_row['d']
    kd_golden_cross = bool(k_prev <= d_prev and k_curr > d_curr)
    kd_death_cross = bool(k_prev >= d_prev and k_curr < d_curr)
    kd_status = "超賣區" if k_curr < 20 else ("超買區" if k_curr > 80 else "中性整理區")

    rsi14 = last_row['rsi14']
    rsi_status = "強勢多頭" if rsi14 >= 60 else ("弱勢空頭" if rsi14 <= 40 else "常態盤整")

    dif, dea, osc = last_row['macd_dif'], last_row['macd_dea'], last_row['macd_osc']
    dif_prev, dea_prev = prev_row['macd_dif'], prev_row['macd_dea']
    macd_golden_cross = bool(dif_prev <= dea_prev and dif > dea)
    macd_death_cross = bool(dif_prev >= dea_prev and dif < dea)

    bb_mid = last_row['bb_mid']
    bb_upper = last_row['bb_upper']
    bb_lower = last_row['bb_lower']
    bb_bandwidth = last_row['bb_bandwidth']
    bb_percent_b = last_row['bb_percent_b']

    w_bottom = detect_w_bottom(df_calc)
    hs_bottom = detect_head_and_shoulders_bottom(df_calc)
    false_breakdown = detect_false_breakdown(df_calc)
    v_reversal = detect_v_reversal(df_calc)
    ma_breakout = detect_ma_entanglement_breakout(df_calc)

    bullish_signals = []
    
    if ma_align['is_bullish']:
        bullish_signals.append("均線四線多頭排列")
    if kd_golden_cross:
        bullish_signals.append("KD指標低檔黃金交叉" if k_curr <= 50 else "KD指標強勢黃金交叉")
    if macd_golden_cross or (osc > 0 and osc > prev_row['macd_osc']):
        bullish_signals.append("MACD紅柱擴大或黃金交叉")
    if 55 <= rsi14 <= 75:
        bullish_signals.append("RSI處於強勢攻擊區間")
    if bb_percent_b >= 0.8:
        bullish_signals.append("布林通道沿上軌強勢推升")

    pattern_scores = []
    if w_bottom['detected']:
        bullish_signals.append(f"W底雙底突破頸線 (強度:{w_bottom['score']}分)")
        pattern_scores.append(w_bottom['score'])
    if hs_bottom['detected']:
        bullish_signals.append(f"頭肩底形態量縮突破 (強度:{hs_bottom['score']}分)")
        pattern_scores.append(hs_bottom['score'])
    if false_breakdown['detected']:
        bullish_signals.append(f"破底翻假跌破強勢收復 (強度:{false_breakdown['score']}分)")
        pattern_scores.append(false_breakdown['score'])
    if v_reversal['detected']:
        bullish_signals.append(f"V型反轉急速強彈 (強度:{v_reversal['score']}分)")
        pattern_scores.append(v_reversal['score'])
    if ma_breakout['detected']:
        bullish_signals.append(f"均線糾結帶量長紅突破 (強度:{ma_breakout['score']}分)")
        pattern_scores.append(ma_breakout['score'])

    indicator_score = 0.0
    if ma_align['is_bullish']:
        indicator_score += 30.0
    elif last_row['ma5'] > last_row['ma20']:
        indicator_score += 15.0

    if kd_golden_cross or k_curr > d_curr:
        indicator_score += 20.0
    if osc > 0:
        indicator_score += 25.0
    if rsi14 >= 50:
        indicator_score += 15.0
    if bb_percent_b >= 0.6:
        indicator_score += 10.0

    top_pattern_score = max(pattern_scores) if pattern_scores else 0.0
    composite_score = round(indicator_score * 0.35 + top_pattern_score * 0.65, 1)

    latest_date_str = str(last_row.get('date', ''))

    result = {
        "symbol": symbol,
        "latest_date": latest_date_str,
        "latest_close": float(round(last_row['close'], 2)),
        "indicators": {
            "ma": {
                "ma5": float(round(last_row['ma5'], 2)),
                "ma10": float(round(last_row['ma10'], 2)),
                "ma20": float(round(last_row['ma20'], 2)),
                "ma60": float(round(last_row['ma60'], 2)) if not pd.isna(last_row['ma60']) else None,
                "is_bullish_alignment": ma_align['is_bullish'],
                "spread_pct": ma_align['spread_pct']
            },
            "kd": {
                "k": float(round(k_curr, 2)),
                "d": float(round(d_curr, 2)),
                "golden_cross": kd_golden_cross,
                "death_cross": kd_death_cross,
                "status": kd_status
            },
            "rsi": {
                "rsi14": float(round(rsi14, 2)),
                "status": rsi_status
            },
            "macd": {
                "dif": float(round(dif, 3)),
                "dea": float(round(dea, 3)),
                "osc": float(round(osc, 3)),
                "golden_cross": macd_golden_cross,
                "death_cross": macd_death_cross
            },
            "bbands": {
                "upper": float(round(bb_upper, 2)),
                "middle": float(round(bb_mid, 2)),
                "lower": float(round(bb_lower, 2)),
                "bandwidth": float(round(bb_bandwidth, 4)),
                "percent_b": float(round(bb_percent_b, 3))
            }
        },
        "patterns": {
            "w_bottom": w_bottom,
            "head_and_shoulders_bottom": hs_bottom,
            "false_breakdown": false_breakdown,
            "v_reversal": v_reversal,
            "ma_entanglement_breakout": ma_breakout
        },
        "composite_score": float(composite_score),
        "bullish_signals": bullish_signals
    }
    return result
