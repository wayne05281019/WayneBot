#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""個股 lab：v106 keep 進場 × 技術確認濾／賣出變體（靜默對質）。

規則（硬）：
- 只用官方 OHLC／量／可重述均線（MA5/10/20/60、量均、60低、20高）
- 不准發明密技／紫箭／假成本／外資投信成本
- phone_sync=blocked；buy_signal=false；不准改 leave_zero／黃金／話筒
- 買端確認＝訊號日收盤後條件（隔日開進場）；賣端固定 hi20_or_desync 對照
- 賣端變體另軌：非純 MA5/10 跌破（已知輸 keep）；測 hi20+量縮、desync+MA60 等
- 過閘才談替換：獨立開市日 n≥20 且贏 CURRENT keep；否則 keep=v106
- 勝率不准混浪形軌；不准再推法人濾

用法：
  WAYNE_LAB_MIX_ROOT=/tmp/wayne-lab-mix \\
  WAYNE_DB_PATH=data/wayne_market.db \\
  python scripts/decade_lab_stock_tech_confirm_lab.py

  python scripts/decade_lab_stock_tech_confirm_lab.py --smoke
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
MIX_ROOT = Path(os.environ.get("WAYNE_LAB_MIX_ROOT") or "").expanduser()
for p in (str(ROOT), str(MIX_ROOT) if MIX_ROOT else ""):
    if p and p not in sys.path:
        sys.path.insert(0, p)

TAIPEI = ZoneInfo("Asia/Taipei")
PHONE_SYNC = "blocked"
BUY_SIGNAL = False
ART = Path("/opt/cursor/artifacts")
DOC = ROOT / "docs" / "expert_notes" / "飆客" / "decade_lab"
MARKET_DB = Path(os.environ.get("WAYNE_DB_PATH") or (ROOT / "data" / "wayne_market.db"))
MIN_N_DAYS = 20
KEEP_EARLY = "ei_n2_lu5"
KEEP_FAST = "lu5_vol_next"
SELL_KEEP = "hi20_or_desync"
# v106 sealed reference (early U220 / fast U250)
V106_REF = {
    "early": {"wr": 0.8269230769230769, "d": 51, "bars": 16.54901960784314},
    "fast": {"wr": 0.8545454545454545, "d": 54, "bars": 15.296296296296296},
}

BUY_CONFIRM_NAMES = (
    "plain",
    "vol_gt_ma20_1p5",
    "vol_gt_ma20_2",
    "bias20_lt8",
    "bias20_lt5",
    "close_gt_ma5_ma10",
    "close_gt_ma20",
    "room_from_low60_lt15",
    "vol_1p5_and_bias_lt8",
    "reclaim_ma20",
)

SELL_MODE_NAMES = (
    "hi20_or_desync",  # keep baseline
    "hi20_vol_fade_or_desync",
    "hi20_or_desync_ma60",
    "hi20_vol_fade_or_desync_ma60",
)


def _now() -> str:
    return datetime.now(TAIPEI).isoformat(timespec="seconds")


def _ymd(raw: Any) -> str:
    t = str(raw or "").replace("-", "")[:8]
    return t if len(t) == 8 and t.isdigit() else ""


def tech_features(df: pd.DataFrame) -> pd.DataFrame:
    """官方柱可重述欄：均線／量均／乖離／距60低。缺量＝量確認 False。"""
    cl = df["close"].astype(float)
    vo = df["volume"].astype(float) if "volume" in df.columns else pd.Series(np.nan, index=df.index)
    ma5 = cl.rolling(5, min_periods=5).mean()
    ma10 = cl.rolling(10, min_periods=10).mean()
    ma20 = cl.rolling(20, min_periods=20).mean()
    ma60 = cl.rolling(60, min_periods=60).mean()
    vol_ma20 = vo.rolling(20, min_periods=10).mean()
    low60 = cl.rolling(60, min_periods=20).min()
    bias20 = pd.Series(np.nan, index=df.index, dtype=float)
    ok = ma20 > 0
    bias20.loc[ok] = (cl.loc[ok] - ma20.loc[ok]) / ma20.loc[ok] * 100.0
    dist_low60 = pd.Series(np.nan, index=df.index, dtype=float)
    ok_l = low60 > 0
    dist_low60.loc[ok_l] = (cl.loc[ok_l] - low60.loc[ok_l]) / low60.loc[ok_l]
    prev_close = cl.shift(1)
    return pd.DataFrame(
        {
            "close": cl,
            "volume": vo,
            "ma5": ma5,
            "ma10": ma10,
            "ma20": ma20,
            "ma60": ma60,
            "vol_ma20": vol_ma20,
            "low60": low60,
            "bias20": bias20,
            "dist_low60": dist_low60,
            "reclaim_ma20": (cl > ma20) & (prev_close <= ma20),
        },
        index=df.index,
    )


def buy_confirm_masks(feat: pd.DataFrame) -> Dict[str, pd.Series]:
    """訊號日（收盤後可知）技術確認；全部可由官方 OHLC／量重述。"""
    vo = feat["volume"]
    vma = feat["vol_ma20"]
    has_vol = vo.notna() & vma.notna() & (vma > 0)
    bias = feat["bias20"]
    cl = feat["close"]
    ma5 = feat["ma5"]
    ma10 = feat["ma10"]
    ma20 = feat["ma20"]
    dist = feat["dist_low60"]

    vol_1p5 = (has_vol & (vo > 1.5 * vma)).fillna(False)
    vol_2 = (has_vol & (vo > 2.0 * vma)).fillna(False)
    bias_lt8 = (bias.notna() & (bias < 8.0)).fillna(False)
    bias_lt5 = (bias.notna() & (bias < 5.0)).fillna(False)
    gt_ma5_10 = (cl.notna() & ma5.notna() & ma10.notna() & (cl > ma5) & (cl > ma10)).fillna(False)
    gt_ma20 = (cl.notna() & ma20.notna() & (cl > ma20)).fillna(False)
    room15 = (dist.notna() & (dist < 0.15)).fillna(False)
    reclaim = feat["reclaim_ma20"].fillna(False)

    return {
        "plain": pd.Series(True, index=feat.index),
        "vol_gt_ma20_1p5": vol_1p5,
        "vol_gt_ma20_2": vol_2,
        "bias20_lt8": bias_lt8,
        "bias20_lt5": bias_lt5,
        "close_gt_ma5_ma10": gt_ma5_10,
        "close_gt_ma20": gt_ma20,
        "room_from_low60_lt15": room15,
        "vol_1p5_and_bias_lt8": (vol_1p5 & bias_lt8).fillna(False),
        "reclaim_ma20": reclaim,
    }


def _simulate_tech_sell(
    df: pd.DataFrame,
    entry_mask: pd.Series,
    *,
    hl: pd.Series,
    temp_label: pd.Series,
    feat: pd.DataFrame,
    sid: str,
    entry_tag: str,
    mode: str,
) -> List[Dict[str, Any]]:
    """賣出變體（非純 MA5/10 跌破）。

    modes:
      - hi20_or_desync（keep）
      - hi20_vol_fade_or_desync：20高且量≤量均20，或如何賣減碼
      - hi20_or_desync_ma60：20高，或（減碼且收盤跌破 MA60）
      - hi20_vol_fade_or_desync_ma60：上述兩者合成
    """
    from sell_discipline import classify_how_to_sell
    from scripts.decade_lab_phone_trade_confront import FRICTION, MAX_HOLD

    cl = df["close"].astype(float)
    op = df["open"].astype(float)
    hi = df["high"].astype(float)
    lo = df["low"].astype(float)
    vo = feat["volume"]
    vma = feat["vol_ma20"]
    ma60 = feat["ma60"]
    n = len(df)
    trades: List[Dict[str, Any]] = []
    i = 0
    while i < n - 2:
        if not bool(entry_mask.iloc[i]):
            i += 1
            continue
        entry_i = i + 1
        if entry_i >= n - 1:
            break
        entry_px = float(op.iloc[entry_i])
        if not (np.isfinite(entry_px) and entry_px > 0):
            i += 1
            continue
        exit_i = None
        exit_reason = None
        peak = entry_px
        trough = entry_px
        for j in range(entry_i, min(n - 1, entry_i + MAX_HOLD)):
            h = float(hi.iloc[j])
            l = float(lo.iloc[j])
            if np.isfinite(h):
                peak = max(peak, h)
            if np.isfinite(l):
                trough = min(trough, l)
            if j <= entry_i:
                continue
            hl_j = str(hl.iloc[j] or "")
            flags = classify_how_to_sell(hl.iloc[j], temp_label.iloc[j])
            desync = str(flags.get("sell_action") or "") == "直接減碼"
            vol_fade = False
            try:
                vv = float(vo.iloc[j])
                vm = float(vma.iloc[j])
                vol_fade = np.isfinite(vv) and np.isfinite(vm) and vm > 0 and vv <= vm
            except (TypeError, ValueError):
                vol_fade = False
            below_ma60 = False
            try:
                cj = float(cl.iloc[j])
                m6 = float(ma60.iloc[j])
                below_ma60 = np.isfinite(cj) and np.isfinite(m6) and m6 > 0 and cj < m6
            except (TypeError, ValueError):
                below_ma60 = False

            if mode == "hi20_or_desync":
                if hl_j == "20高":
                    exit_i = j + 1
                    exit_reason = "first_hi20"
                    break
                if desync:
                    exit_i = j + 1
                    exit_reason = "sell_desync_cut"
                    break
            elif mode == "hi20_vol_fade_or_desync":
                if hl_j == "20高" and vol_fade:
                    exit_i = j + 1
                    exit_reason = "hi20_vol_fade"
                    break
                if desync:
                    exit_i = j + 1
                    exit_reason = "sell_desync_cut"
                    break
            elif mode == "hi20_or_desync_ma60":
                if hl_j == "20高":
                    exit_i = j + 1
                    exit_reason = "first_hi20"
                    break
                if desync and below_ma60:
                    exit_i = j + 1
                    exit_reason = "desync_ma60_fail"
                    break
            elif mode == "hi20_vol_fade_or_desync_ma60":
                if hl_j == "20高" and vol_fade:
                    exit_i = j + 1
                    exit_reason = "hi20_vol_fade"
                    break
                if desync and below_ma60:
                    exit_i = j + 1
                    exit_reason = "desync_ma60_fail"
                    break
            else:
                raise ValueError(f"unknown sell mode: {mode}")

        if exit_i is None:
            exit_i = min(n - 1, entry_i + MAX_HOLD)
            exit_reason = "max_hold_60"
        if exit_i >= n:
            exit_i = n - 1
        exit_px = (
            float(cl.iloc[exit_i])
            if exit_reason == "max_hold_60"
            else float(op.iloc[exit_i] if np.isfinite(op.iloc[exit_i]) else cl.iloc[exit_i])
        )
        if not (np.isfinite(exit_px) and exit_px > 0):
            i = max(i + 1, exit_i)
            continue
        net = exit_px / entry_px - 1.0 - FRICTION
        trades.append(
            {
                "sid": sid,
                "entry_tag": entry_tag,
                "entry_i": entry_i,
                "exit_i": exit_i,
                "entry_date": str(df["date"].iloc[entry_i]) if "date" in df.columns else str(entry_i),
                "exit_date": str(df["date"].iloc[exit_i]) if "date" in df.columns else str(exit_i),
                "net_ret": net,
                "hold_days": int(exit_i - entry_i),
                "exit_reason": exit_reason,
                "win": int(net > 0),
                "mfe": peak / entry_px - 1.0,
                "mae": trough / entry_px - 1.0,
            }
        )
        i = max(i + 1, exit_i)
    return trades


def _half_split_dates(dates: Sequence[str]) -> Tuple[set, set]:
    uniq = sorted({_ymd(x) for x in dates if _ymd(x)})
    mid = len(uniq) // 2
    return set(uniq[:mid]), set(uniq[mid:])


def _filter_trades(trades: List[Dict[str, Any]], keep_dates: set) -> List[Dict[str, Any]]:
    return [t for t in trades if _ymd(t.get("entry_date")) in keep_dates]


def _score(trades: List[Dict[str, Any]]) -> Dict[str, Any]:
    from scripts.decade_lab_phone_trade_confront import _agg_trades

    st = _agg_trades(trades)
    days = int(st.get("n_unique_entry_days") or 0)
    win = float(st.get("win_rate") or np.nan)
    return {
        "n_trades": st.get("n_trades"),
        "n_unique_entry_days": days,
        "win_rate": win if np.isfinite(win) else None,
        "expectancy": st.get("expectancy"),
        "avg_hold": st.get("avg_hold"),
        "exit_reason_counts": st.get("exit_reason_counts"),
        "gate_n20": bool(days >= MIN_N_DAYS),
    }


def _beats(candidate: Dict[str, Any], baseline: Dict[str, Any]) -> bool:
    cd = int(candidate.get("n_unique_entry_days") or 0)
    bd = int(baseline.get("n_unique_entry_days") or 0)
    cw = candidate.get("win_rate")
    bw = baseline.get("win_rate")
    if cd < MIN_N_DAYS or bd < MIN_N_DAYS:
        return False
    if cw is None or bw is None:
        return False
    try:
        return float(cw) > float(bw)
    except (TypeError, ValueError):
        return False


def _beats_keep(candidate: Dict[str, Any], keep_ref: Dict[str, Any]) -> bool:
    cd = int(candidate.get("n_unique_entry_days") or 0)
    cw = candidate.get("win_rate")
    kw = keep_ref.get("wr")
    if cd < MIN_N_DAYS or cw is None or kw is None:
        return False
    try:
        return float(cw) > float(kw)
    except (TypeError, ValueError):
        return False


def _delta_wr(a: Dict[str, Any], b_wr: Optional[float]) -> Optional[float]:
    if a.get("win_rate") is None or b_wr is None:
        return None
    try:
        return float(a["win_rate"]) - float(b_wr)
    except (TypeError, ValueError):
        return None


def _import_spirit_stack():
    from scripts.decade_lab_chart_marks_stats import _normalize_ohlc
    from scripts.decade_lab_hsiao_universe import MUST_INCLUDE, load_stock_ohlcv, select_g_universe
    from scripts.decade_lab_phone_market_wave_sync import _stock_wave_events, _twii_wave_pack
    from scripts.decade_lab_phone_spirit_mix_track_oos_v107 import _champ_masks
    from scripts.decade_lab_phone_trade_confront import _build_hl_temp

    return {
        "_normalize_ohlc": _normalize_ohlc,
        "MUST_INCLUDE": MUST_INCLUDE,
        "load_stock_ohlcv": load_stock_ohlcv,
        "select_g_universe": select_g_universe,
        "_stock_wave_events": _stock_wave_events,
        "_twii_wave_pack": _twii_wave_pack,
        "_champ_masks": _champ_masks,
        "_build_hl_temp": _build_hl_temp,
    }


def spirit_stack_available() -> bool:
    try:
        _import_spirit_stack()
        return True
    except Exception:
        return False


def _variant_row(
    full: Dict[str, Any],
    is_: Dict[str, Any],
    oos: Dict[str, Any],
    *,
    plain_oos: Dict[str, Any],
    plain_full: Dict[str, Any],
    keep_ref: Dict[str, Any],
) -> Dict[str, Any]:
    return {
        "full": full,
        "is": is_,
        "oos": oos,
        "beats_plain_oos": _beats(oos, plain_oos),
        "beats_plain_full": _beats(full, plain_full),
        "beats_v106_keep_oos": _beats_keep(oos, keep_ref),
        "delta_oos_wr": _delta_wr(oos, plain_oos.get("win_rate")),
        "delta_vs_v106_keep_wr": _delta_wr(oos, keep_ref.get("wr")),
        "delta_oos_d": int(oos.get("n_unique_entry_days") or 0)
        - int(plain_oos.get("n_unique_entry_days") or 0),
    }


def run(
    *,
    n_stocks: int = 220,
    min_avg_turnover_k: float = 800_000.0,
    smoke: bool = False,
) -> Dict[str, Any]:
    t0 = time.time()
    DOC.mkdir(parents=True, exist_ok=True)
    ART.mkdir(parents=True, exist_ok=True)

    if not spirit_stack_available():
        out = {
            "version": "stock_tech_confirm_lab_v1",
            "as_of": _now(),
            "phone_sync": PHONE_SYNC,
            "buy_signal": BUY_SIGNAL,
            "status": "blocked_missing_spirit_stack",
            "finding_zh": "本機缺 spirit／v106 核依賴。請設 WAYNE_LAB_MIX_ROOT 再跑。keep 仍 v106。",
            "keep": "v106",
            "promote": False,
            "gate_passed": False,
            "db_path": str(MARKET_DB),
            "mix_root": str(MIX_ROOT) if MIX_ROOT else None,
        }
        _write_outputs(out)
        return out

    S = _import_spirit_stack()
    n_use = 12 if smoke else int(n_stocks)
    uni = S["select_g_universe"](
        n=max(80, n_use),
        include_twse_top100=True,
        min_avg_turnover_k=float(min_avg_turnover_k),
    )
    symbols: List[str] = uni["stock_id"].astype(str).tolist()
    for sid in S["MUST_INCLUDE"]:
        sid_s = str(sid)
        if sid_s not in symbols:
            symbols.append(sid_s)
    symbols = symbols[:n_use]

    _, mkt_raw = S["_twii_wave_pack"](entry_preset="A0_strict", score_threshold=40.0)

    buy_buckets: Dict[str, Dict[str, List[Dict[str, Any]]]] = {
        c: {f: [] for f in BUY_CONFIRM_NAMES} for c in ("early", "fast")
    }
    sell_buckets: Dict[str, Dict[str, List[Dict[str, Any]]]] = {
        c: {m: [] for m in SELL_MODE_NAMES} for c in ("early", "fast")
    }
    all_dates: List[str] = []
    errors: List[str] = []
    meta_n = 0

    for sid in symbols:
        try:
            raw = S["load_stock_ohlcv"](sid)
            if raw is None or len(raw) < 150:
                continue
            df = S["_normalize_ohlc"](raw)
            if df is None or len(df) < 150:
                continue
            meta_n += 1
            all_dates.extend(df["date"].astype(str).tolist())
            masks = S["_champ_masks"](df, raw, mkt_raw)
            hl, temp = S["_build_hl_temp"](df)
            feat = tech_features(df)
            bmasks = buy_confirm_masks(feat)

            early = masks[KEEP_EARLY].fillna(False)
            fast = masks[KEEP_FAST].fillna(False)

            for core_name, base in (("early", early), ("fast", fast)):
                # buy confirms × keep sell
                for fname, fmask in bmasks.items():
                    em = (base & fmask.reindex(df.index).fillna(False)).fillna(False)
                    buy_buckets[core_name][fname].extend(
                        _simulate_tech_sell(
                            df,
                            em,
                            hl=hl,
                            temp_label=temp,
                            feat=feat,
                            sid=sid,
                            entry_tag=f"buy_{core_name}__{fname}",
                            mode=SELL_KEEP,
                        )
                    )
                # sell variants × plain entry
                for smode in SELL_MODE_NAMES:
                    sell_buckets[core_name][smode].extend(
                        _simulate_tech_sell(
                            df,
                            base,
                            hl=hl,
                            temp_label=temp,
                            feat=feat,
                            sid=sid,
                            entry_tag=f"sell_{core_name}__{smode}",
                            mode=smode,
                        )
                    )
        except Exception as e:  # noqa: BLE001
            errors.append(f"{sid}:{type(e).__name__}:{e}")

    train_d, test_d = _half_split_dates(all_dates)
    buy_tracks: Dict[str, Any] = {}
    sell_tracks: Dict[str, Any] = {}
    best_buy: Optional[Dict[str, Any]] = None
    best_sell: Optional[Dict[str, Any]] = None

    for core_name in ("early", "fast"):
        plain_full = _score(buy_buckets[core_name]["plain"])
        plain_oos = _score(_filter_trades(buy_buckets[core_name]["plain"], test_d))
        plain_is = _score(_filter_trades(buy_buckets[core_name]["plain"], train_d))
        variants = {}
        for fname in BUY_CONFIRM_NAMES:
            if fname == "plain":
                continue
            full = _score(buy_buckets[core_name][fname])
            oos = _score(_filter_trades(buy_buckets[core_name][fname], test_d))
            is_ = _score(_filter_trades(buy_buckets[core_name][fname], train_d))
            row = _variant_row(
                full,
                is_,
                oos,
                plain_oos=plain_oos,
                plain_full=plain_full,
                keep_ref=V106_REF[core_name],
            )
            variants[fname] = row
            if row["beats_plain_oos"]:
                cand = {
                    "leg": "buy_confirm",
                    "core": core_name,
                    "variant": fname,
                    "kind": "vs_plain",
                    "oos_wr": oos.get("win_rate"),
                    "oos_d": oos.get("n_unique_entry_days"),
                    "plain_oos_wr": plain_oos.get("win_rate"),
                    "plain_oos_d": plain_oos.get("n_unique_entry_days"),
                    "delta_oos_wr": row["delta_oos_wr"],
                    "beats_v106_keep_oos": row["beats_v106_keep_oos"],
                }
                if best_buy is None or float(cand["delta_oos_wr"] or -1) > float(
                    best_buy.get("delta_oos_wr") or -1
                ):
                    best_buy = cand
        buy_tracks[core_name] = {
            "entry": KEEP_EARLY if core_name == "early" else KEEP_FAST,
            "sell": SELL_KEEP,
            "plain": {"full": plain_full, "is": plain_is, "oos": plain_oos},
            "variants": variants,
            "v106_ref": V106_REF[core_name],
        }

        sell_plain_full = _score(sell_buckets[core_name]["hi20_or_desync"])
        sell_plain_oos = _score(
            _filter_trades(sell_buckets[core_name]["hi20_or_desync"], test_d)
        )
        sell_plain_is = _score(
            _filter_trades(sell_buckets[core_name]["hi20_or_desync"], train_d)
        )
        sell_variants = {}
        for smode in SELL_MODE_NAMES:
            if smode == "hi20_or_desync":
                continue
            full = _score(sell_buckets[core_name][smode])
            oos = _score(_filter_trades(sell_buckets[core_name][smode], test_d))
            is_ = _score(_filter_trades(sell_buckets[core_name][smode], train_d))
            row = _variant_row(
                full,
                is_,
                oos,
                plain_oos=sell_plain_oos,
                plain_full=sell_plain_full,
                keep_ref=V106_REF[core_name],
            )
            sell_variants[smode] = row
            if row["beats_plain_oos"]:
                cand = {
                    "leg": "sell_confirm",
                    "core": core_name,
                    "variant": smode,
                    "kind": "vs_plain",
                    "oos_wr": oos.get("win_rate"),
                    "oos_d": oos.get("n_unique_entry_days"),
                    "plain_oos_wr": sell_plain_oos.get("win_rate"),
                    "plain_oos_d": sell_plain_oos.get("n_unique_entry_days"),
                    "delta_oos_wr": row["delta_oos_wr"],
                    "beats_v106_keep_oos": row["beats_v106_keep_oos"],
                }
                if best_sell is None or float(cand["delta_oos_wr"] or -1) > float(
                    best_sell.get("delta_oos_wr") or -1
                ):
                    best_sell = cand
        sell_tracks[core_name] = {
            "entry": KEEP_EARLY if core_name == "early" else KEEP_FAST,
            "sell_baseline": SELL_KEEP,
            "plain": {"full": sell_plain_full, "is": sell_plain_is, "oos": sell_plain_oos},
            "variants": sell_variants,
            "v106_ref": V106_REF[core_name],
        }

    # 替換閘：同一 buy confirm 在 early＋fast 兩邊 OOS 都贏 sealed v106 keep
    shared_buy: List[str] = []
    for fname in buy_tracks["early"]["variants"]:
        if buy_tracks["early"]["variants"][fname].get("beats_v106_keep_oos") and buy_tracks[
            "fast"
        ]["variants"].get(fname, {}).get("beats_v106_keep_oos"):
            shared_buy.append(fname)
    shared_sell: List[str] = []
    for smode in sell_tracks["early"]["variants"]:
        if sell_tracks["early"]["variants"][smode].get("beats_v106_keep_oos") and sell_tracks[
            "fast"
        ]["variants"].get(smode, {}).get("beats_v106_keep_oos"):
            shared_sell.append(smode)

    both_buy_ok = bool(shared_buy)
    both_sell_ok = bool(shared_sell)
    gate_passed = bool(both_buy_ok or both_sell_ok)

    # pick overall best for reporting (prefer gate beat, else max Δplain)
    best: Optional[Dict[str, Any]] = None
    if both_buy_ok:
        best = {
            "leg": "buy_confirm",
            "core": "both",
            "variant": shared_buy[0],
            "shared": shared_buy,
            "kind": "vs_v106_keep",
            "early_oos": buy_tracks["early"]["variants"][shared_buy[0]]["oos"],
            "fast_oos": buy_tracks["fast"]["variants"][shared_buy[0]]["oos"],
        }
    elif both_sell_ok:
        best = {
            "leg": "sell_confirm",
            "core": "both",
            "variant": shared_sell[0],
            "shared": shared_sell,
            "kind": "vs_v106_keep",
            "early_oos": sell_tracks["early"]["variants"][shared_sell[0]]["oos"],
            "fast_oos": sell_tracks["fast"]["variants"][shared_sell[0]]["oos"],
        }
    else:
        cands = [c for c in (best_buy, best_sell) if c is not None]
        if cands:
            best = max(cands, key=lambda c: float(c.get("delta_oos_wr") or -1))

    plain_edge = bool(best is not None and best.get("kind") == "vs_plain")
    status = (
        "gate_pass_vs_v106_keep"
        if gate_passed
        else ("plain_delta_only_keep_v106" if plain_edge else "no_beat_keep_v106")
    )
    if smoke:
        status = "smoke_" + status

    gate = (
        f"stock_tech_confirm_lab n={meta_n} smoke={int(smoke)}; "
        f"early_plain_oos_wr={buy_tracks['early']['plain']['oos'].get('win_rate')} "
        f"d={buy_tracks['early']['plain']['oos'].get('n_unique_entry_days')}; "
        f"fast_plain_oos_wr={buy_tracks['fast']['plain']['oos'].get('win_rate')} "
        f"d={buy_tracks['fast']['plain']['oos'].get('n_unique_entry_days')}; "
        f"best={best}; promote={gate_passed}"
    )

    finding = (
        "技術確認（量／乖離／均線／距60低；無密技無成本）："
        + (
            f"共享變體 {best.get('variant')}（{best.get('leg')}）兩邊 OOS 贏 sealed v106 keep → 理論過閘；本件仍封 keep=v106／phone blocked。"
            if gate_passed
            else (
                f"相對同跑 plain 有 Δ（{best}），但未贏 sealed v106 keep → keep v106。"
                if plain_edge
                else "各確認未贏 sealed v106 keep（或 n<20）→ keep v106。"
            )
        )
        + " 未重測純 MA5/10 跌破賣（已知輸 hi20_or_desync）。法人濾不重推。"
    )

    out: Dict[str, Any] = {
        "version": "stock_tech_confirm_lab_v1",
        "as_of": _now(),
        "tz": "Asia/Taipei",
        "phone_sync": PHONE_SYNC,
        "buy_signal": BUY_SIGNAL,
        "promote_lookup": False,
        "status": status,
        "gate_passed": bool(gate_passed),
        "keep": "v106",
        "keep_detail": (
            "early ei_n2_lu5／eg_bridge；fast lu5_vol_next；sell hi20_or_desync"
        ),
        "sell_keep": SELL_KEEP,
        "filter_kind_zh": "訊號日收盤後技術確認→隔日開進場；賣端另測量縮／MA60 確認",
        "data_sources": {
            "ohlc_volume": "daily_quotes open/high/low/close/volume",
            "derived": "MA5/10/20/60、vol_ma20、bias20、dist_low60、reclaim_ma20（皆可從官方柱重述）",
            "forbidden": "密技1–57／紫箭／假成本／外資投信成本",
        },
        "n_stocks": meta_n,
        "smoke": smoke,
        "buy_tracks": buy_tracks,
        "sell_tracks": sell_tracks,
        "best_candidate": best,
        "best_buy_vs_plain": best_buy,
        "best_sell_vs_plain": best_sell,
        "shared_buy_vs_keep": shared_buy,
        "shared_sell_vs_keep": shared_sell,
        "gate_one_liner": gate,
        "finding_zh": finding,
        "elapsed_s": round(time.time() - t0, 1),
        "errors_n": len(errors),
        "errors_sample": errors[:8],
        "db_path": str(MARKET_DB),
        "parent_keep": "phone_spirit_mix_dual_track_v106_decision.json",
        "next": "keep v106；技術確認可當後續候選；不准混浪形軌、不准改話筒",
    }
    out["gate_passed"] = bool(gate_passed)
    out["keep"] = "v106"
    out["buy_signal"] = False
    out["phone_sync"] = "blocked"

    _write_outputs(out)
    _write_decision(out)
    print("GATE", gate, flush=True)
    print("STATUS", status, "keep=v106", flush=True)
    return out


def _write_outputs(out: Dict[str, Any]) -> None:
    text = json.dumps(out, ensure_ascii=False, indent=2, default=str) + "\n"
    ART.mkdir(parents=True, exist_ok=True)
    DOC.mkdir(parents=True, exist_ok=True)
    (ART / "stock_tech_confirm_lab_latest.json").write_text(text, encoding="utf-8")
    (DOC / "stock_tech_confirm_lab_latest.json").write_text(text, encoding="utf-8")


def _write_decision(out: Dict[str, Any]) -> None:
    """精簡決策檔（誠實 OOS vs keep）。"""
    best = out.get("best_candidate")
    decision = {
        "version": "stock_tech_confirm_lab_v1",
        "as_of": out.get("as_of"),
        "tz": "Asia/Taipei",
        "phone_sync": "blocked",
        "buy_signal": False,
        "promote_lookup": False,
        "status": out.get("status"),
        "gate_passed": bool(out.get("gate_passed")),
        "keep": "v106",
        "keep_detail": out.get("keep_detail"),
        "sell": SELL_KEEP,
        "variant_tested_zh": "v106 進場核 × 技術確認（量／乖離／均線／距60低）；賣端 hi20+量縮／desync+MA60",
        "n_stocks": out.get("n_stocks"),
        "smoke": out.get("smoke"),
        "best_candidate": best,
        "best_buy_vs_plain": out.get("best_buy_vs_plain"),
        "best_sell_vs_plain": out.get("best_sell_vs_plain"),
        "shared_buy_vs_keep": out.get("shared_buy_vs_keep"),
        "shared_sell_vs_keep": out.get("shared_sell_vs_keep"),
        "oos_vs_v106_keep": {
            "early_plain_oos": (out.get("buy_tracks") or {}).get("early", {}).get("plain", {}).get("oos"),
            "fast_plain_oos": (out.get("buy_tracks") or {}).get("fast", {}).get("plain", {}).get("oos"),
            "v106_ref": V106_REF,
        },
        "gate_one_liner": out.get("gate_one_liner"),
        "finding_zh": out.get("finding_zh"),
        "latest": "stock_tech_confirm_lab_latest.json",
        "parent_keep": "phone_spirit_mix_dual_track_v106_decision.json",
        "next": out.get("next"),
    }
    text = json.dumps(decision, ensure_ascii=False, indent=2, default=str) + "\n"
    (ART / "stock_tech_confirm_lab_decision.json").write_text(text, encoding="utf-8")
    (DOC / "stock_tech_confirm_lab_decision.json").write_text(text, encoding="utf-8")


def main(argv: Optional[Sequence[str]] = None) -> Dict[str, Any]:
    ap = argparse.ArgumentParser(description="v106 × 技術確認 lab")
    ap.add_argument("--smoke", action="store_true", help="小母體煙測")
    ap.add_argument("--n-stocks", type=int, default=220)
    ap.add_argument("--min-avg-turnover-k", type=float, default=800_000.0)
    args = ap.parse_args(list(argv) if argv is not None else None)
    return run(
        n_stocks=int(args.n_stocks),
        min_avg_turnover_k=float(args.min_avg_turnover_k),
        smoke=bool(args.smoke),
    )


if __name__ == "__main__":
    main()
