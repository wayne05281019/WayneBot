# -*- coding: utf-8 -*-
"""蕭氏量／價／時間／角度特徵 V2（實驗室；不是買訊；phone_sync=blocked）。

V2 新增：週日線共振、均線糾結、扣抵加速、乖離過熱、四維分數。
因果：所有 rolling／shift 只用 <= t 的資料。
週線：W-FRI 算完後 shift(1) 再 ffill 回日 K，週五結果下週一才生效。
"""
from __future__ import annotations

import numpy as np
import pandas as pd

PHONE_SYNC = "blocked"
NOT_BUY_SIGNAL = True


def _wilder_atr(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> pd.Series:
    prev_close = close.shift(1)
    tr = pd.concat(
        [
            (high - low).abs(),
            (high - prev_close).abs(),
            (low - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    atr = tr.copy()
    atr.iloc[: period - 1] = np.nan
    if len(tr) >= period:
        atr.iloc[period - 1] = float(tr.iloc[:period].mean())
        alpha = 1.0 / float(period)
        for i in range(period, len(tr)):
            atr.iloc[i] = atr.iloc[i - 1] * (1.0 - alpha) + float(tr.iloc[i]) * alpha
    return atr


def _rolling_linreg_angle(close: pd.Series, atr: pd.Series, window: int) -> pd.Series:
    """對每個 t：y_i = Close[t-K+1+i] / ATR_14[t]，x=0..K-1，角度 = degrees(arctan(slope))."""
    c = close.to_numpy(dtype=float)
    a = atr.to_numpy(dtype=float)
    n = len(c)
    out = np.full(n, np.nan, dtype=float)
    if window < 2 or n < window:
        return pd.Series(out, index=close.index)
    x = np.arange(window, dtype=float)
    x_mean = x.mean()
    x_var = ((x - x_mean) ** 2).sum()
    if x_var <= 0:
        return pd.Series(out, index=close.index)
    for t in range(window - 1, n):
        atr_t = a[t]
        if not np.isfinite(atr_t) or atr_t <= 0:
            continue
        y = c[t - window + 1 : t + 1] / atr_t
        if not np.isfinite(y).all():
            continue
        y_mean = y.mean()
        cov = ((x - x_mean) * (y - y_mean)).sum()
        slope = cov / x_var
        out[t] = float(np.degrees(np.arctan(slope)))
    return pd.Series(out, index=close.index)


def _align_weekly_to_daily(daily_index: pd.DatetimeIndex, weekly: pd.DataFrame) -> pd.DataFrame:
    """週五收盤值 shift(1) 後 ffill 到日 K：下週一才生效，防未來函數。"""
    if weekly is None or len(weekly) == 0:
        empty = pd.DataFrame(index=daily_index)
        for col in (
            "W_Close",
            "W_MA13",
            "W_MA26",
            "W_ATR_14",
            "w_ma13_safety",
            "weekly_trend_bullish",
        ):
            empty[col] = np.nan if col != "weekly_trend_bullish" else False
        return empty
    shifted = weekly.shift(1)
    # 用日期對齊：把週列放到對應日再 ffill
    aligned = shifted.reindex(daily_index.union(shifted.index)).sort_index()
    aligned = aligned.ffill()
    return aligned.reindex(daily_index)


def _compute_weekly_features(out: pd.DataFrame) -> pd.DataFrame:
    """日 K → W-FRI 週 K → 週指標 → shift(1)+ffill 回日。"""
    idx = out.index
    if not isinstance(idx, pd.DatetimeIndex):
        # 無日期索引則週線欄全 NaN／False
        out["W_Close"] = np.nan
        out["W_MA13"] = np.nan
        out["W_MA26"] = np.nan
        out["W_ATR_14"] = np.nan
        out["w_ma13_safety"] = np.nan
        out["weekly_trend_bullish"] = False
        return out

    ohlc = out[["Open", "High", "Low", "Close", "Volume"]].copy()
    weekly = ohlc.resample("W-FRI").agg(
        {
            "Open": "first",
            "High": "max",
            "Low": "min",
            "Close": "last",
            "Volume": "sum",
        }
    )
    weekly = weekly.dropna(subset=["Close"])
    w_close = weekly["Close"]
    w_high = weekly["High"]
    w_low = weekly["Low"]
    weekly["W_Close"] = w_close
    weekly["W_MA13"] = w_close.rolling(13).mean()
    weekly["W_MA26"] = w_close.rolling(26).mean()
    weekly["W_ATR_14"] = _wilder_atr(w_high, w_low, w_close, 14)
    w_atr = weekly["W_ATR_14"].replace(0, np.nan)
    weekly["w_ma13_safety"] = (w_close - w_close.shift(13)) / w_atr
    weekly["weekly_trend_bullish"] = (w_close > weekly["W_MA13"]) & (
        weekly["w_ma13_safety"] > -0.2
    )
    # V4：週線 KD（同樣 shift(1) 後才對齊日 K）
    _wrsv, wk, wd = _kd_933(w_high, w_low, w_close)
    weekly["W_K"], weekly["W_D"] = wk, wd
    weekly["w_kd_high_passivation"] = (wk >= 80).astype(float).rolling(3).sum() >= 3

    cols = [
        "W_Close",
        "W_MA13",
        "W_MA26",
        "W_ATR_14",
        "w_ma13_safety",
        "weekly_trend_bullish",
        "W_K",
        "W_D",
        "w_kd_high_passivation",
    ]
    aligned = _align_weekly_to_daily(idx, weekly[cols])
    for col in cols:
        out[col] = aligned[col]
    out["weekly_trend_bullish"] = out["weekly_trend_bullish"].fillna(False).astype(bool)
    out["w_kd_high_passivation"] = out["w_kd_high_passivation"].fillna(False).astype(bool)
    return out


def _kd_933(high: pd.Series, low: pd.Series, close: pd.Series) -> tuple[pd.Series, pd.Series, pd.Series]:
    """台股標準 KD(9,3,3)：RSV=9，K/D 用 1/3 權重遞迴。"""
    lowest = low.rolling(9).min()
    highest = high.rolling(9).max()
    denom = (highest - lowest).replace(0, np.nan)
    rsv = 100.0 * (close - lowest) / denom
    rsv = rsv.fillna(50.0)
    k = pd.Series(np.nan, index=close.index, dtype=float)
    d = pd.Series(np.nan, index=close.index, dtype=float)
    k_prev, d_prev = 50.0, 50.0
    for i in range(len(close)):
        r = float(rsv.iloc[i])
        if not np.isfinite(r):
            r = 50.0
        k_prev = (1.0 / 3.0) * r + (2.0 / 3.0) * k_prev
        d_prev = (1.0 / 3.0) * k_prev + (2.0 / 3.0) * d_prev
        k.iloc[i] = k_prev
        d.iloc[i] = d_prev
    return rsv, k, d


def _hsiao_4d_score(out: pd.DataFrame) -> pd.Series:
    """量／價／時間／角度四維實驗室分數 0–100（不是買訊）。"""
    score = pd.Series(0.0, index=out.index)
    # 量 0–25
    score += np.where(out["is_attack_vol"].fillna(False), 25.0, 0.0)
    score += np.where(
        (~out["is_attack_vol"].fillna(False))
        & out["vol_attack_ratio"].fillna(0).ge(1.5),
        12.0,
        0.0,
    )
    # 價 0–25
    score += np.where(out["is_key_bull_candle"].fillna(False), 25.0, 0.0)
    score += np.where(
        (~out["is_key_bull_candle"].fillna(False)) & out["bull_alignment"].fillna(False),
        12.0,
        0.0,
    )
    # 時間 0–25
    s20 = out["ma20_time_safety"]
    score += np.where(s20.fillna(-9) > 0.5, 25.0, 0.0)
    score += np.where((s20.fillna(-9) > 0) & (s20.fillna(-9) <= 0.5), 15.0, 0.0)
    score += np.where(out["deduction_accelerating"].fillna(False), 5.0, 0.0)
    # 角度 0–25
    a5 = out["angle_5"]
    score += np.where(a5.fillna(-9) >= 45.0, 25.0, 0.0)
    score += np.where((a5.fillna(-9) >= 35.0) & (a5.fillna(-9) < 45.0), 18.0, 0.0)
    score += np.where((a5.fillna(-9) >= 25.0) & (a5.fillna(-9) < 35.0), 10.0, 0.0)
    # 糾結突破加分（封頂 100）
    score += np.where(out["had_ma_compression_5d"].fillna(False), 8.0, 0.0)
    # 過熱扣分
    score -= np.where(out["is_overextended"].fillna(False), 20.0, 0.0)
    return score.clip(0.0, 100.0)


def compute_hsiao_features(df: pd.DataFrame) -> pd.DataFrame:
    """輸入欄位 Open/High/Low/Close/Volume（大小寫皆可），輸出特徵表（含原 OHLC）。"""
    if df is None or len(df) == 0:
        return pd.DataFrame()
    colmap = {str(c).strip().lower().replace(" ", "_"): c for c in df.columns}
    need = ("open", "high", "low", "close", "volume")
    missing = [k for k in need if k not in colmap]
    if missing:
        raise ValueError(f"缺少欄位: {missing}")
    out = pd.DataFrame(index=df.index.copy())
    o = df[colmap["open"]].astype(float)
    h = df[colmap["high"]].astype(float)
    low = df[colmap["low"]].astype(float)
    c = df[colmap["close"]].astype(float)
    v = df[colmap["volume"]].astype(float)
    out["Open"], out["High"], out["Low"], out["Close"], out["Volume"] = o, h, low, c, v

    out["ATR_14"] = _wilder_atr(h, low, c, 14)
    out["MA5"] = c.rolling(5).mean()
    out["MA10"] = c.rolling(10).mean()
    out["MA20"] = c.rolling(20).mean()
    out["MA60"] = c.rolling(60).mean()
    out["MA120"] = c.rolling(120).mean()
    out["VOL_MA5"] = v.rolling(5).mean()
    out["VOL_MA20"] = v.rolling(20).mean()
    out["VOL_MA60"] = v.rolling(60).mean()

    out["vol_rolling_max_20"] = v.rolling(20).max()
    # V5：真凹洞量＝量縮 + 振幅收斂且非一字鎖死
    out["intraday_range"] = (h - low) / c.shift(1).replace(0, np.nan)
    vol_shrink = (v <= 0.22 * out["vol_rolling_max_20"]) | (
        out["VOL_MA5"] <= 0.40 * out["VOL_MA60"]
    )
    range_ok = (out["intraday_range"] <= 0.04) & (h > low)
    out["is_trough_vol"] = vol_shrink & range_ok
    out["had_trough_vol_10d"] = out["is_trough_vol"].astype(float).rolling(10).max() > 0

    # V5：處置股／流動性突變 — 近 5 日大漲但量階梯斷崖且振幅仍大
    ret5 = c.pct_change(5)
    vol_step_crash = (
        (v < v.shift(1) * 0.30)
        & (v.shift(1) < v.shift(2) * 0.30)
        & (v.shift(2) < v.shift(3) * 0.30)
    )
    # 連續 3 日相對各自前日跌超 70%（階梯斷崖）
    out["is_illiquid_anomaly"] = (
        (ret5 > 0.08)
        & vol_step_crash
        & (out["intraday_range"] > 0.05)
    )
    out["block_new_entries"] = out["is_illiquid_anomaly"].astype(float).rolling(5).max() > 0
    vol_ma5_prev = out["VOL_MA5"].shift(1)
    vol_ma20_prev = out["VOL_MA20"].shift(1)
    out["vol_attack_ratio"] = v / vol_ma5_prev.replace(0, np.nan)
    out["is_attack_vol"] = (out["vol_attack_ratio"] >= 2.0) & (v >= 1.3 * vol_ma20_prev)
    body_up = (c - o).clip(lower=0)
    out["is_exhaustion_vol"] = (v >= 3.2 * vol_ma20_prev) & (
        (c < o) | ((h - c) > body_up * 1.2)
    )

    out["ret_1d"] = c.pct_change()
    hl = (h - low) + 1e-8
    out["candle_body_ratio"] = (c - o) / hl
    out["upper_shadow_ratio"] = (h - np.maximum(o, c)) / hl
    out["lower_shadow_ratio"] = (np.minimum(o, c) - low) / hl
    # V6：錘子線／避雷針候選（狀態機再定性）
    out["is_hammer_shape"] = (
        (out["lower_shadow_ratio"] >= 0.60) & (c > (h + low) / 2.0)
    )
    out["is_long_upper_shadow_vol"] = (
        (out["upper_shadow_ratio"] >= 0.55) & (v > 1.8 * out["VOL_MA5"])
    )

    # V3：2015-06-01 漲跌幅制度變遷自適應
    limit_cut = pd.Timestamp("2015-06-01")
    if isinstance(out.index, pd.DatetimeIndex):
        pre_regime = out.index < limit_cut
    else:
        pre_regime = pd.Series(False, index=out.index)
    out["bull_ret_thresh"] = np.where(pre_regime, 0.025, 0.035)
    out["limit_up_thresh"] = np.where(pre_regime, 0.066, 0.095)
    # Close==High 允許微小浮點誤差
    close_at_high = (c - h).abs() <= (h.abs() * 1e-8 + 1e-8)
    out["is_limit_up"] = close_at_high & (out["ret_1d"] >= out["limit_up_thresh"])
    close_at_low = (c - low).abs() <= (low.abs() * 1e-8 + 1e-8)
    out["is_limit_down"] = close_at_low & (out["ret_1d"] <= -out["limit_up_thresh"])
    # V7：一字鎖死（無量／全日未開）
    flat_bar = (h - low).abs() <= (h.abs() * 1e-8 + 1e-8)
    out["is_limit_up_locked"] = out["is_limit_up"] & (
        flat_bar | ((o - h).abs() <= 1e-8) & ((o - low).abs() <= 1e-8)
    )
    out["is_limit_down_locked"] = out["is_limit_down"] & (
        flat_bar | ((o - h).abs() <= 1e-8) & ((o - low).abs() <= 1e-8)
    )

    prior_3h = h.shift(1).rolling(3).max()
    out["is_key_bull_candle"] = (
        (out["ret_1d"] >= out["bull_ret_thresh"])
        & (out["candle_body_ratio"] >= 0.65)
        & (c > prior_3h)
    )
    out["bull_alignment"] = (out["MA5"] > out["MA20"]) & (out["MA20"] > out["MA60"])
    out["prior_high_5"] = h.shift(1).rolling(5).max()

    # V3：跳空缺口四維
    prior_high = h.shift(1)
    out["bull_gap"] = low > (prior_high * 1.005)
    out["gap_support"] = np.where(out["bull_gap"], prior_high, np.nan)
    # 候選突破缺口（狀態確認在 wave engine）
    out["gap_breakaway_candidate"] = out["bull_gap"] & out["is_attack_vol"].fillna(False)
    # 高檔竭盡缺口候選：跳空＋爆量長黑／長上影（狀態末端由引擎確認）
    out["gap_exhaustion_candidate"] = out["bull_gap"] & out["is_exhaustion_vol"].fillna(False)
    # 3 日內回補 gap_support
    gap_sup_ffill = pd.Series(out["gap_support"], index=out.index).ffill(limit=3)
    filled_within_3 = (c < gap_sup_ffill) & gap_sup_ffill.notna()
    # 僅在缺口發生後 1–3 日標記回補（因果：當日收盤才知）
    gap_day = out["bull_gap"].astype(float)
    recent_gap = gap_day.shift(1).rolling(3).max() > 0
    out["gap_filled_within_3d"] = recent_gap & filled_within_3 & (~out["bull_gap"].fillna(False))

    # V3：假突破緊急撤退標記（在 t+1 收盤確認；因果欄位落在 t+1）
    # 前日爆量突破：前日 is_attack_vol 且前日紅 K
    prev_attack = out["is_attack_vol"].shift(1).fillna(False)
    prev_bull = (c.shift(1) > o.shift(1))
    prev_mid = (o.shift(1) + c.shift(1)) / 2.0
    vol_shrink = v < (v.shift(1) * 0.55)  # 萎縮超過 45%
    today_bear = c < o
    open_high_close_weak = (o >= c.shift(1) * 0.995) & today_bear & (c < prev_mid)
    out["fake_breakout_exit"] = (
        prev_attack & prev_bull & open_high_close_weak & vol_shrink
    )
    out["vol_shrink_ratio"] = v / v.shift(1).replace(0, np.nan)

    atr = out["ATR_14"].replace(0, np.nan)
    out["deduct_20_now"] = (c - c.shift(20)) / atr
    # t-19..t-15 的最高收＝Close.shift(15).rolling(5).max()（皆為過去價）
    out["future_deduct_20_max5"] = c.shift(15).rolling(5).max()
    out["ma20_time_safety"] = (c - out["future_deduct_20_max5"]) / atr
    out["future_deduct_60_max5"] = c.shift(55).rolling(5).max()
    out["ma60_time_safety"] = (c - out["future_deduct_60_max5"]) / atr

    # V2：扣抵加速預判（未來 1–3 日 vs 4–8 日將扣抵的歷史價；無未來函數）
    near_deduct = c.shift(17).rolling(3).mean()
    far_deduct = c.shift(12).rolling(5).mean()
    out["deduction_accelerating"] = near_deduct > (far_deduct + 1.2 * out["ATR_14"])

    # V2：均線糾結度
    ma_hi = np.maximum(out["MA5"], np.maximum(out["MA10"], out["MA20"]))
    ma_lo = np.minimum(out["MA5"], np.minimum(out["MA10"], out["MA20"]))
    out["ma_compression"] = (ma_hi - ma_lo) / out["MA20"].replace(0, np.nan)
    out["had_ma_compression_5d"] = (
        (out["ma_compression"] <= 0.04).astype(float).rolling(5).max() > 0
    )

    # V2：乖離過熱禁止追高
    bias_pct = (c - out["MA20"]) / out["MA20"].replace(0, np.nan)
    bias_atr = (c - out["MA20"]) / atr
    out["is_overextended"] = (bias_pct > 0.16) | (bias_atr > 3.5)

    out["angle_5"] = _rolling_linreg_angle(c, out["ATR_14"], 5)
    out["angle_10"] = _rolling_linreg_angle(c, out["ATR_14"], 10)
    # MA60 斜率角度（供 W-X-Y 複合修正鎖定）
    out["ma60_angle"] = _rolling_linreg_angle(out["MA60"].bfill(), out["ATR_14"], 10)

    # V6：MACD(12,26,9)
    ema12 = c.ewm(span=12, adjust=False).mean()
    ema26 = c.ewm(span=26, adjust=False).mean()
    out["DIF"] = ema12 - ema26
    out["DEA"] = out["DIF"].ewm(span=9, adjust=False).mean()
    out["MACD_HIST"] = out["DIF"] - out["DEA"]
    out["macd_hist_contracting"] = out["MACD_HIST"] < out["MACD_HIST"].shift(1)

    # 20MA 正乖離（仙人指路 vs 避雷針）
    out["bias_ma20_pct"] = (c - out["MA20"]) / out["MA20"].replace(0, np.nan)

    # V4：日線 KD(9,3,3) 與高檔鈍化
    _rsv, k_d, d_d = _kd_933(h, low, c)
    out["RSV"], out["K"], out["D"] = _rsv, k_d, d_d
    out["kd_high_passivation"] = (k_d >= 80).astype(float).rolling(3).sum() >= 3
    out["kd_golden_cross"] = (k_d > d_d) & (k_d.shift(1) <= d_d.shift(1))
    out["kd_death_cross"] = (k_d < d_d) & (k_d.shift(1) >= d_d.shift(1))
    out["kd_pullback_buy_zone"] = (k_d >= 35.0) & (k_d <= 55.0) & out["kd_golden_cross"]

    # V4：周轉率（有發行股數才算）
    shares_col = None
    for cand in ("shares_outstanding", "shares", "issued_shares"):
        if cand in colmap:
            shares_col = colmap[cand]
            break
    if shares_col is not None:
        shares = df[shares_col].astype(float).replace(0, np.nan)
        out["turnover_rate"] = v / shares
        out["turnover_ok"] = (out["turnover_rate"] >= 0.025) & (out["turnover_rate"] <= 0.18)
    else:
        out["turnover_rate"] = np.nan
        out["turnover_ok"] = True  # 缺資料不擋，由回測可選強制

    # 紅／黑 K 量（供狀態機累積鎖碼比）
    out["up_bar_vol"] = np.where(c > o, v, 0.0)
    out["down_bar_vol"] = np.where(c < o, v, 0.0)

    # V2：週日線多週期共振（含週 KD）
    out = _compute_weekly_features(out)

    # V7：可選籌碼面（有欄才啟用）
    has_chips = all(
        k in colmap or k in {str(c).strip().lower().replace(" ", "_") for c in df.columns}
        for k in ()
    )
    # 直接從 out / df 找
    def _opt(*names):
        for n in names:
            key = n.lower().replace(" ", "_")
            if key in colmap:
                return df[colmap[key]].astype(float)
            if n in df.columns:
                return df[n].astype(float)
            if key in out.columns:
                return out[key].astype(float)
        return None

    foreign = _opt("foreign_buy", "Foreign_Buy")
    trust = _opt("trust_buy", "Trust_Buy")
    margin = _opt("margin_balance", "Margin_Balance")
    short_b = _opt("short_balance", "Short_Balance")
    out["chips_enabled"] = foreign is not None or trust is not None or margin is not None
    if foreign is not None:
        out["Foreign_Buy"] = foreign
        out["foreign_buy_5d"] = foreign.rolling(5).sum()
    else:
        out["Foreign_Buy"] = np.nan
        out["foreign_buy_5d"] = np.nan
    if trust is not None:
        out["Trust_Buy"] = trust
        out["trust_buy_5d"] = trust.rolling(5).sum()
    else:
        out["Trust_Buy"] = np.nan
        out["trust_buy_5d"] = np.nan
    if margin is not None:
        out["Margin_Balance"] = margin
        out["margin_chg_from_peak20"] = margin / margin.rolling(20).max().replace(0, np.nan) - 1.0
    else:
        out["Margin_Balance"] = np.nan
        out["margin_chg_from_peak20"] = np.nan
    if short_b is not None and margin is not None:
        out["Short_Balance"] = short_b
        out["short_margin_ratio"] = short_b / (margin + 1.0)
        out["is_short_squeeze_setup"] = out["short_margin_ratio"] >= 0.15
    else:
        out["Short_Balance"] = np.nan
        out["short_margin_ratio"] = np.nan
        out["is_short_squeeze_setup"] = False

    # 法人承接＋融資清洗候選（狀態機在 W2 確認）
    inst_buy = (out["foreign_buy_5d"].fillna(0) > 0) | (out["trust_buy_5d"].fillna(0) > 0)
    margin_wash = out["margin_chg_from_peak20"].fillna(0) <= -0.05
    out["chip_clean_candidate"] = inst_buy & margin_wash

    # 流動性枯竭（輔助一字鎖死）
    out["liquidity_dried"] = v < (out["VOL_MA20"].shift(1) * 0.05)
    out["is_limit_down_locked"] = out["is_limit_down_locked"] | (
        out["is_limit_down"] & out["liquidity_dried"]
    )
    out["is_limit_up_locked"] = out["is_limit_up_locked"] | (
        out["is_limit_up"] & out["liquidity_dried"]
    )

    out["hsiao_4d_score"] = _hsiao_4d_score(out)
    # 籌碼加分在狀態機依 W2 脈絡再 +15；此處先標註
    out.attrs["phone_sync"] = PHONE_SYNC
    out.attrs["not_buy_signal"] = NOT_BUY_SIGNAL
    out.attrs["feature_version"] = "hsiao_v7"
    return out


__all__ = ["compute_hsiao_features", "PHONE_SYNC", "NOT_BUY_SIGNAL"]
