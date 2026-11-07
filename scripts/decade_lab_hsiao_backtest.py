# -*- coding: utf-8 -*-
"""蕭氏實驗室 20 年回測 V7（假錢；不是買訊；phone_sync=blocked）。

- 台股 Tick 滑價、手續費／證交稅
- 風險平價部位（試單 60%＋突破加碼 40%）
- 棘輪移動停損、開盤破防即砍
- 一字漲跌停鎖死無法成交 → 延至打開日
- 破底翻洗盤觀察池
- 純多方 vs 多空雙向對比報表
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence

import numpy as np
import pandas as pd

from scripts.decade_lab_hsiao_data_preprocessor import prepare_ohlcv
from scripts.decade_lab_hsiao_predictor import run_hsiao_lab_predict
from scripts.decade_lab_hsiao_quant_features import compute_hsiao_features
from scripts.decade_lab_hsiao_wave_engine import ElliottHsiaoEngine

PHONE_SYNC = "blocked"
NOT_BUY_SIGNAL = True

FEE_RATE = 0.001425 * 0.6  # 折扣手續費近似
TAX_RATE = 0.003  # 證交稅（賣出）
RISK_PER_TRADE = 0.012
MAX_WEIGHT = 0.20
MIN_STOP_DIST = 0.035
TICK_CUTOVER = pd.Timestamp("2020-03-23")  # 逐筆交易實施


def get_tw_tick_size(price: float) -> float:
    p = float(price)
    if p < 10:
        return 0.01
    if p < 50:
        return 0.05
    if p < 100:
        return 0.1
    if p < 500:
        return 0.5
    if p < 1000:
        return 1.0
    return 5.0


def _slip_ticks(ts) -> float:
    try:
        t = pd.Timestamp(ts)
    except Exception:
        return 1.0
    return 1.5 if t < TICK_CUTOVER else 1.0


def apply_slippage(price: float, *, side: str, ts) -> float:
    """side: buy 加價 / sell 減價。"""
    tick = get_tw_tick_size(price)
    n = _slip_ticks(ts)
    if side == "buy":
        return float(price + n * tick)
    return float(price - n * tick)


def position_weight(entry: float, stop: float) -> float:
    if not (np.isfinite(entry) and entry > 0 and np.isfinite(stop)):
        return 0.0
    dist = max((entry - stop) / entry, MIN_STOP_DIST)
    if dist <= 0:
        dist = MIN_STOP_DIST
    return float(min(RISK_PER_TRADE / dist, MAX_WEIGHT))


def _norm_rank(s: pd.Series) -> pd.Series:
    if s is None or len(s) == 0:
        return s
    r = s.rank(method="average", pct=True)
    return r.fillna(0.5)


def priority_rank_score(cands: pd.DataFrame) -> pd.Series:
    """橫截面優先級（當日候選）。"""
    if cands is None or len(cands) == 0:
        return pd.Series(dtype=float)
    angle = _norm_rank(cands.get("angle_5", pd.Series(0, index=cands.index)))
    time_s = _norm_rank(
        cands.get("ma20_time_safety", pd.Series(0, index=cands.index)).fillna(0)
        + cands.get("ma60_time_safety", pd.Series(0, index=cands.index)).fillna(0)
    )
    vol_shrink = cands.get("vol_shrink_ratio", pd.Series(1.0, index=cands.index)).fillna(1.0)
    vol_term = _norm_rank(1.0 / (vol_shrink + 0.01))
    rs = _norm_rank(cands.get("rs_20d", pd.Series(0, index=cands.index)).fillna(0))
    score = 0.35 * angle + 0.25 * time_s + 0.20 * vol_term + 0.20 * rs
    if "sector_priority" in cands.columns:
        score = score + 0.05 * cands["sector_priority"].fillna(0)
    return score


@dataclass
class Position:
    symbol: str
    side: str  # long / short
    qty_value: float  # 名義金額
    entry_price: float
    stop: float
    entry_t: Any
    filled_frac: float = 0.6  # 已投入佔目標部位比例
    target_weight: float = 0.0
    trail_stop: float = float("nan")
    state_name: str = ""
    pending_exit: bool = False  # 鎖死待平
    pending_side: str = ""


@dataclass
class BacktestResult:
    equity: pd.Series
    trades: List[Dict[str, Any]]
    summary: Dict[str, Any]


def attach_benchmark_rs(feat: pd.DataFrame, benchmark_df: Optional[pd.DataFrame]) -> pd.DataFrame:
    out = feat.copy()
    if benchmark_df is None or len(benchmark_df) == 0:
        out["rs_20d"] = np.nan
        out["bench_ma60"] = np.nan
        out["bench_ma60_time_safety"] = np.nan
        out["market_risk_on"] = True
        return out
    b = prepare_ohlcv(benchmark_df) if "Close" in benchmark_df.columns or "close" in [
        str(c).lower() for c in benchmark_df.columns
    ] else benchmark_df
    if "Close" not in b.columns:
        cm = {str(c).lower(): c for c in b.columns}
        b = b.rename(columns={cm["close"]: "Close"})
    bf = compute_hsiao_features(b)
    aligned = bf.reindex(out.index).ffill()
    stock_ret20 = out["Close"].pct_change(20)
    bench_ret20 = aligned["Close"].pct_change(20)
    out["rs_20d"] = stock_ret20 - bench_ret20
    out["bench_ma60"] = aligned["MA60"]
    out["bench_ma60_time_safety"] = aligned["ma60_time_safety"]
    out["market_risk_on"] = ~(
        (aligned["Close"] < aligned["MA60"]) & (aligned["ma60_time_safety"] < -0.5)
    )
    return out


def _ratchet_stop(pos: Position, row: pd.Series) -> float:
    stop = pos.trail_stop if np.isfinite(pos.trail_stop) else pos.stop
    if pos.side != "long":
        return stop
    px = float(row["Close"])
    entry = pos.entry_price
    if entry <= 0:
        return stop
    upnl = px / entry - 1.0
    ma20 = float(row["MA20"]) if np.isfinite(row.get("MA20", np.nan)) else float("nan")
    ma10 = float(row["MA10"]) if np.isfinite(row.get("MA10", np.nan)) else float("nan")
    ma5 = float(row["MA5"]) if np.isfinite(row.get("MA5", np.nan)) else float("nan")
    angle5 = float(row["angle_5"]) if np.isfinite(row.get("angle_5", np.nan)) else float("nan")
    prev_low = float(row.get("prev_low", np.nan))
    new_stop = stop
    if upnl < 0.10:
        new_stop = stop
    elif upnl < 0.25:
        floor = entry * 1.01
        new_stop = max(stop, floor, ma20 if np.isfinite(ma20) else floor)
    else:
        if np.isfinite(angle5) and angle5 >= 60.0:
            cands = [x for x in (ma5, prev_low) if np.isfinite(x)]
            if cands:
                new_stop = max(stop, max(cands))
        elif np.isfinite(ma10):
            new_stop = max(stop, ma10)
    # 進入 W5 也緊縮
    if str(row.get("state_name", "")) in {"WAVE_5_FINAL", "WAVE_5_ENDING_DIAGONAL"}:
        if np.isfinite(ma10):
            new_stop = max(new_stop, ma10)
    return float(new_stop)


def run_single_backtest(
    ohlcv: pd.DataFrame,
    *,
    symbol: str = "SYM",
    benchmark_df: Optional[pd.DataFrame] = None,
    allow_short: bool = False,
    initial_cash: float = 1_000_000.0,
) -> BacktestResult:
    """單一標的實驗室回測。"""
    prep = prepare_ohlcv(ohlcv)
    feat = compute_hsiao_features(prep)
    feat = attach_benchmark_rs(feat, benchmark_df)
    feat["prev_low"] = feat["Low"].shift(1)
    eng = ElliottHsiaoEngine()
    labeled = eng.run(feat, already_featured=True)

    cash = float(initial_cash)
    pos: Optional[Position] = None
    equity = []
    trades: List[Dict[str, Any]] = []
    washout_pool: Dict[str, Dict[str, Any]] = {}

    for t, (ts, row) in enumerate(labeled.iterrows()):
        px_o = float(row["Open"])
        px_c = float(row["Close"])
        sig = str(row.get("lab_signal") or "")
        hint = str(row.get("position_hint") or "")
        locked_down = bool(row.get("is_limit_down_locked"))
        locked_up = bool(row.get("is_limit_up_locked"))
        market_ok = bool(row.get("market_risk_on", True))
        weekly_bull = bool(row.get("weekly_trend_bullish"))
        score = float(row.get("hsiao_score_eff", row.get("hsiao_4d_score", 0)) or 0)
        rs = float(row.get("rs_20d", np.nan))

        # --- 處理待平倉（鎖死延遲）---
        if pos is not None and pos.pending_exit:
            can = (pos.side == "long" and not locked_down and float(row["High"]) > float(row["Low"])) or (
                pos.side == "short" and not locked_up and float(row["High"]) > float(row["Low"])
            )
            if can:
                side = "sell" if pos.side == "long" else "buy"
                fill = apply_slippage(px_o, side=side, ts=ts)
                cash += _close_pnl(pos, fill, tax=(pos.side == "long"))
                trades.append(
                    {
                        "symbol": symbol,
                        "action": "exit_after_lock",
                        "side": pos.side,
                        "price": fill,
                        "t": str(ts),
                    }
                )
                pos = None

        # --- 開盤破防即砍（多）---
        if pos is not None and pos.side == "long" and not pos.pending_exit:
            stop = pos.trail_stop if np.isfinite(pos.trail_stop) else pos.stop
            if np.isfinite(stop) and px_o < stop:
                if locked_down:
                    pos.pending_exit = True
                else:
                    fill = apply_slippage(px_o, side="sell", ts=ts)
                    cash += _close_pnl(pos, fill, tax=True)
                    trades.append(
                        {"symbol": symbol, "action": "open_stop", "side": "long", "price": fill, "t": str(ts)}
                    )
                    # 洗盤觀察池
                    if float(row.get("Volume", 0)) < 0.75 * float(row.get("VOL_MA5", np.nan) or np.nan):
                        washout_pool[symbol] = {
                            "expire": t + 5,
                            "black_high": float(row.get("prev_high", row["High"])),
                            "exit_t": t,
                        }
                    pos = None

        # --- 棘輪 ---
        if pos is not None and pos.side == "long":
            pos.trail_stop = _ratchet_stop(pos, row)
            stop = pos.trail_stop
            if np.isfinite(stop) and px_c < stop and not pos.pending_exit:
                if locked_down:
                    pos.pending_exit = True
                else:
                    fill = apply_slippage(px_c, side="sell", ts=ts)
                    cash += _close_pnl(pos, fill, tax=True)
                    trades.append(
                        {"symbol": symbol, "action": "trail_stop", "side": "long", "price": fill, "t": str(ts)}
                    )
                    pos = None

        # --- 訊號出場 ---
        if pos is not None and hint in {"exit", "exit_next_open"} and not pos.pending_exit:
            if pos.side == "long":
                if locked_down:
                    pos.pending_exit = True
                else:
                    fill_px = px_o if hint == "exit_next_open" else px_c
                    # exit_next_open 在當日收盤標記，實際下根開盤；此簡化當日收盤賣
                    fill = apply_slippage(px_c if hint != "exit_next_open" else px_c, side="sell", ts=ts)
                    cash += _close_pnl(pos, fill, tax=True)
                    trades.append(
                        {"symbol": symbol, "action": "signal_exit", "side": "long", "price": fill, "t": str(ts), "sig": sig}
                    )
                    pos = None
            elif pos.side == "short" and hint == "cover":
                if locked_up:
                    pos.pending_exit = True
                else:
                    fill = apply_slippage(px_c, side="buy", ts=ts)
                    cash += _close_pnl(pos, fill, tax=False)
                    trades.append(
                        {"symbol": symbol, "action": "cover", "side": "short", "price": fill, "t": str(ts), "sig": sig}
                    )
                    pos = None

        if pos is not None and pos.side == "short" and (hint == "cover" or sig.startswith("LAB_SHORT_COVER")):
            if locked_up:
                pos.pending_exit = True
            else:
                fill = apply_slippage(px_c, side="buy", ts=ts)
                cash += _close_pnl(pos, fill, tax=False)
                trades.append(
                    {"symbol": symbol, "action": "cover", "side": "short", "price": fill, "t": str(ts), "sig": sig}
                )
                pos = None

        # --- 破底翻買回 ---
        wo = washout_pool.get(symbol)
        if pos is None and wo and t <= wo["expire"] and t > wo["exit_t"]:
            if (
                bool(row.get("is_key_bull_candle"))
                and float(row.get("Volume", 0)) > 1.5 * float(row.get("VOL_MA5", 0) or 0)
                and float(row["High"]) >= wo["black_high"]
            ):
                stop = float(row.get("hard_stop_price", row["Low"]))
                entry = apply_slippage(px_c, side="buy", ts=ts)
                w = position_weight(entry, stop) * 0.6
                if w > 0 and (not bool(row.get("block_new_entries", False))):
                    notional = cash * w
                    fee = notional * FEE_RATE
                    cash -= notional + fee
                    pos = Position(
                        symbol=symbol,
                        side="long",
                        qty_value=notional,
                        entry_price=entry,
                        stop=stop,
                        trail_stop=stop,
                        entry_t=ts,
                        filled_frac=0.6,
                        target_weight=position_weight(entry, stop),
                    )
                    trades.append(
                        {"symbol": symbol, "action": "REBUY_AFTER_WASHOUT", "price": entry, "t": str(ts), "w": w}
                    )
                    washout_pool.pop(symbol, None)

        # --- 進場：W3 試單 ---
        if pos is None and sig == "LAB_BUY_W3_START":
            rs_ok = (not np.isfinite(rs)) or rs > 0
            risk_cap = market_ok or (weekly_bull and score >= 85)
            if rs_ok and risk_cap and not bool(row.get("block_new_entries", False)):
                stop = float(row.get("hard_stop_price", row["Low"]))
                entry = apply_slippage(px_c, side="buy", ts=ts)
                tw = position_weight(entry, stop)
                if not market_ok:
                    tw = min(tw, 0.30 * tw / max(tw, 1e-8))  # 環境差時更小；總曝險由組合層控
                    tw = min(tw, 0.06)
                w = tw * 0.6
                if w > 0:
                    notional = cash * w
                    fee = notional * FEE_RATE
                    cash -= notional + fee
                    pos = Position(
                        symbol=symbol,
                        side="long",
                        qty_value=notional,
                        entry_price=entry,
                        stop=stop,
                        trail_stop=stop,
                        entry_t=ts,
                        filled_frac=0.6,
                        target_weight=tw,
                        state_name=str(row.get("state_name")),
                    )
                    trades.append(
                        {"symbol": symbol, "action": "buy_w3_trial", "price": entry, "t": str(ts), "w": w, "tw": tw}
                    )

        # --- 加碼 40%：破 P1 或仙人指路 ---
        if pos is not None and pos.side == "long" and pos.filled_frac < 0.99:
            p1 = float(row.get("P1", np.nan))
            add = False
            if np.isfinite(p1) and px_c > p1 and bool(row.get("is_attack_vol")):
                add = True
            if sig == "LAB_ADD_ON_IMMORTAL_BREAK":
                add = True
            if add:
                remain_w = pos.target_weight * 0.4
                notional = (cash + pos.qty_value) * remain_w  # 近似
                notional = min(notional, cash * 0.95)
                if notional > 0:
                    entry = apply_slippage(px_c, side="buy", ts=ts)
                    fee = notional * FEE_RATE
                    cash -= notional + fee
                    # 重新加權均價
                    total = pos.qty_value + notional
                    pos.entry_price = (pos.entry_price * pos.qty_value + entry * notional) / total
                    pos.qty_value = total
                    pos.filled_frac = 1.0
                    trades.append(
                        {"symbol": symbol, "action": "add_40", "price": entry, "t": str(ts), "w": remain_w}
                    )

        # --- 放空 ---
        if allow_short and pos is None and sig == "LAB_SHORT_W_C_START":
            stop = float(row.get("short_stop", row.get("PB", row["High"])))
            entry = apply_slippage(px_c, side="sell", ts=ts)
            # 空單風險距離
            dist = max((stop - entry) / entry, MIN_STOP_DIST) if entry > 0 else MIN_STOP_DIST
            tw = min(RISK_PER_TRADE / dist, MAX_WEIGHT)
            notional = cash * tw
            if notional > 0:
                fee = notional * FEE_RATE
                cash -= fee  # 賣出先收進近似：簡化用保證金記名目
                # 簡化：名目放入 pos，權益用標記
                pos = Position(
                    symbol=symbol,
                    side="short",
                    qty_value=notional,
                    entry_price=entry,
                    stop=stop,
                    trail_stop=stop,
                    entry_t=ts,
                    filled_frac=1.0,
                    target_weight=tw,
                )
                # 賣出得款
                cash += notional
                trades.append(
                    {"symbol": symbol, "action": "short_wc", "price": entry, "t": str(ts), "w": tw}
                )

        # 權益
        mtm = cash
        if pos is not None:
            if pos.side == "long":
                mtm += pos.qty_value * (px_c / pos.entry_price)
            else:
                mtm += pos.qty_value * (2.0 - px_c / pos.entry_price)  # 空單標記
        equity.append((ts, mtm))

    eq = pd.Series({t: v for t, v in equity}, dtype=float)
    ret = eq.pct_change().fillna(0)
    summary = {
        "symbol": symbol,
        "allow_short": allow_short,
        "n_trades": len(trades),
        "final_equity": float(eq.iloc[-1]) if len(eq) else initial_cash,
        "total_return": float(eq.iloc[-1] / initial_cash - 1) if len(eq) else 0.0,
        "max_drawdown": float((eq / eq.cummax() - 1).min()) if len(eq) else 0.0,
        "n_bars": int(len(eq)),
        "not_buy_signal": True,
        "phone_sync": PHONE_SYNC,
        "backtest_version": "hsiao_v7",
    }
    return BacktestResult(equity=eq, trades=trades, summary=summary)


def _close_pnl(pos: Position, fill: float, *, tax: bool) -> float:
    """回傳平倉後回到 cash 的金額（含名目）。"""
    if pos.side == "long":
        gross = pos.qty_value * (fill / pos.entry_price)
        cost = gross * (FEE_RATE + (TAX_RATE if tax else 0.0))
        return gross - cost
    # short：進場已 +notional；回補付出 fill 相對
    # 簡化：回補成本 = notional * fill/entry；盈虧 = notional*(entry-fill)/entry
    buy_cost = pos.qty_value * (fill / pos.entry_price)
    fee = buy_cost * FEE_RATE
    # 原先 cash 已含 +notional；這裡返回「應從現金扣的回補」的負向 → 呼叫端 cash += result
    # 令 result = notional - buy_cost - fee  （把名目拿回並付回補）
    return pos.qty_value - buy_cost - fee


def compare_long_only_vs_long_short(
    ohlcv: pd.DataFrame,
    *,
    symbol: str = "SYM",
    benchmark_df: Optional[pd.DataFrame] = None,
    initial_cash: float = 1_000_000.0,
) -> Dict[str, Any]:
    """一鍵：純多方 vs 多空雙向 20 年績效對比（實驗室）。"""
    long_only = run_single_backtest(
        ohlcv, symbol=symbol, benchmark_df=benchmark_df, allow_short=False, initial_cash=initial_cash
    )
    long_short = run_single_backtest(
        ohlcv, symbol=symbol, benchmark_df=benchmark_df, allow_short=True, initial_cash=initial_cash
    )
    report = {
        "long_only": long_only.summary,
        "long_short": long_short.summary,
        "delta_total_return": long_short.summary["total_return"] - long_only.summary["total_return"],
        "delta_max_drawdown": long_short.summary["max_drawdown"] - long_only.summary["max_drawdown"],
        "not_buy_signal": True,
        "phone_sync": PHONE_SYNC,
        "note": "實驗室假錢對照；不上話筒、不改買訊",
    }
    return {
        "report": report,
        "long_only": long_only,
        "long_short": long_short,
        "not_buy_signal": True,
        "phone_sync": PHONE_SYNC,
    }


__all__ = [
    "get_tw_tick_size",
    "apply_slippage",
    "position_weight",
    "priority_rank_score",
    "run_single_backtest",
    "compare_long_only_vs_long_short",
    "attach_benchmark_rs",
    "PHONE_SYNC",
    "NOT_BUY_SIGNAL",
]
