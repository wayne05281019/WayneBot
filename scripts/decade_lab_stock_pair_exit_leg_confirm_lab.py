#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""個股 lab：v106 keep × 成對出場比較 ＋ 急跌四腿可重述代理確認層（靜默對質）。

兩軌同一封印：
1) paired entry/exit：同一 v106 進場核，比賣出變體 vs hi20_or_desync（非純買端 wr）
2) crash four-leg CONFIRM：v106 觸發後可選濾——leader_tag ＋ PE 近自身近期低 ＋ 近60低（臨界代理）
   不准把 5／9／abc／1-4 浪級當計分特徵

硬規則：
- 官方 OHLC／量／daily_valuation.pe（twse_bwibbu）／話筒龍頭表；不准假成本
- phone_sync=blocked；buy_signal=false；不准改 leave_zero／黃金／話筒
- 過閘：獨立開市日 n≥20 且 OOS 贏 sealed v106 keep；否則 keep=v106
- 勝率不准混浪形軌；法人／技術確認不重推

用法：
  WAYNE_LAB_MIX_ROOT=/tmp/wayne-lab-mix \\
  WAYNE_DB_PATH=data/wayne_market.db \\
  python scripts/decade_lab_stock_pair_exit_leg_confirm_lab.py

  python scripts/decade_lab_stock_pair_exit_leg_confirm_lab.py --smoke
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple
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
V106_REF = {
    "early": {"wr": 0.8269230769230769, "d": 51, "bars": 16.54901960784314},
    "fast": {"wr": 0.8545454545454545, "d": 54, "bars": 15.296296296296296},
}

# 急跌四腿可重述代理（無 abc／1-4／5／9 浪級計分）
CONFIRM_NAMES = (
    "plain",
    "near_low60_5",
    "near_low60_8",
    "near_low60_12",
    "pe_near_min_5",
    "pe_near_min_10",
    "leader_tag",
    "leader_and_near_low60_8",
    "pe_and_near_low60_8",
    "leader_and_pe_near_min",
    "leader_pe_near_low60",
)

# 成對出場：同一進場核比較
SELL_MODE_NAMES = (
    "hi20_or_desync",
    "hi20_only",
    "desync_only",
    "desync_after_mfe5",
    "desync_after_mfe8",
    "hi20_vol_fade_or_desync",
    "hi20_or_desync_ma60",
)


def _now() -> str:
    return datetime.now(TAIPEI).isoformat(timespec="seconds")


def _ymd(raw: Any) -> str:
    t = str(raw or "").replace("-", "")[:8]
    return t if len(t) == 8 and t.isdigit() else ""


def leader_self_sids() -> Set[str]:
    """話筒龍頭表：自己就是龍頭的代號（可重述；非日更成交額第一）。"""
    try:
        from biaoke_judge import _FOLLOW, _LONG_HOLD
    except Exception:
        return set()
    out: Set[str] = set(str(k) for k in _LONG_HOLD.keys())
    for sid, (lid, _name) in _FOLLOW.items():
        sid_s = str(sid)
        lid_s = str(lid)
        if lid_s == sid_s:
            out.add(sid_s)
        out.add(lid_s)  # 族領袖本身
    # 領袖列在 _FOLLOW 值裡但未必當 key＝自己；再補一輪
    for _sid, (lid, _name) in _FOLLOW.items():
        out.add(str(lid))
    return out


def load_pe_by_sid(sid: str, db_path: Path = MARKET_DB) -> Dict[str, float]:
    """官方本益比（daily_valuation.pe／twse_bwibbu）；缺＝不發明。"""
    out: Dict[str, float] = {}
    if not db_path.is_file():
        return out
    conn = sqlite3.connect(str(db_path), timeout=30.0)
    try:
        rows = conn.execute(
            """
            SELECT date, pe FROM daily_valuation
            WHERE stock_id=? AND pe IS NOT NULL AND pe > 0
            ORDER BY date
            """,
            (str(sid),),
        ).fetchall()
    except sqlite3.Error:
        conn.close()
        return out
    conn.close()
    for d, pe in rows:
        day = _ymd(d)
        if not day:
            continue
        try:
            v = float(pe)
        except (TypeError, ValueError):
            continue
        if np.isfinite(v) and v > 0:
            out[day] = v
    return out


def align_pe_ffill(df: pd.DataFrame, pe_map: Dict[str, float]) -> pd.Series:
    """訊號日用≤當日最近一筆官方 PE（不偷看未來）。"""
    dates = [_ymd(x) for x in df["date"].astype(str).tolist()]
    if not pe_map:
        return pd.Series(np.nan, index=df.index, dtype=float)
    keys = sorted(pe_map.keys())
    vals = [pe_map[k] for k in keys]
    out = np.full(len(dates), np.nan, dtype=float)
    j = -1
    for i, d in enumerate(dates):
        while j + 1 < len(keys) and keys[j + 1] <= d:
            j += 1
        if j >= 0:
            out[i] = vals[j]
    return pd.Series(out, index=df.index, dtype=float)


def crash_proxy_features(
    df: pd.DataFrame,
    *,
    pe: pd.Series,
    is_leader: bool,
    pe_roll: int = 32,
) -> pd.DataFrame:
    """可重述欄：近60低、PE 近自身近期低、龍頭標。無浪級。"""
    cl = df["close"].astype(float)
    low60 = cl.rolling(60, min_periods=20).min()
    dist_low60 = pd.Series(np.nan, index=df.index, dtype=float)
    ok = low60 > 0
    dist_low60.loc[ok] = (cl.loc[ok] - low60.loc[ok]) / low60.loc[ok]
    pe_min = pe.rolling(pe_roll, min_periods=max(5, pe_roll // 4)).min()
    pe_vs_min = pd.Series(np.nan, index=df.index, dtype=float)
    ok_p = pe.notna() & pe_min.notna() & (pe_min > 0)
    pe_vs_min.loc[ok_p] = pe.loc[ok_p] / pe_min.loc[ok_p] - 1.0
    return pd.DataFrame(
        {
            "close": cl,
            "low60": low60,
            "dist_low60": dist_low60,
            "pe": pe,
            "pe_min": pe_min,
            "pe_vs_min": pe_vs_min,
            "leader_tag": pd.Series(bool(is_leader), index=df.index),
        },
        index=df.index,
    )


def confirm_masks(feat: pd.DataFrame) -> Dict[str, pd.Series]:
    """訊號日收盤後確認；缺 PE／缺60低＝該濾 False。"""
    dist = feat["dist_low60"]
    pe_vs = feat["pe_vs_min"]
    lead = feat["leader_tag"].fillna(False)

    near5 = (dist.notna() & (dist <= 0.05)).fillna(False)
    near8 = (dist.notna() & (dist <= 0.08)).fillna(False)
    near12 = (dist.notna() & (dist <= 0.12)).fillna(False)
    pe5 = (pe_vs.notna() & (pe_vs <= 0.05)).fillna(False)
    pe10 = (pe_vs.notna() & (pe_vs <= 0.10)).fillna(False)

    return {
        "plain": pd.Series(True, index=feat.index),
        "near_low60_5": near5,
        "near_low60_8": near8,
        "near_low60_12": near12,
        "pe_near_min_5": pe5,
        "pe_near_min_10": pe10,
        "leader_tag": lead,
        "leader_and_near_low60_8": (lead & near8).fillna(False),
        "pe_and_near_low60_8": (pe10 & near8).fillna(False),
        "leader_and_pe_near_min": (lead & pe10).fillna(False),
        "leader_pe_near_low60": (lead & pe10 & near8).fillna(False),
    }


def tech_sell_aux(df: pd.DataFrame) -> pd.DataFrame:
    cl = df["close"].astype(float)
    vo = df["volume"].astype(float) if "volume" in df.columns else pd.Series(np.nan, index=df.index)
    return pd.DataFrame(
        {
            "volume": vo,
            "vol_ma20": vo.rolling(20, min_periods=10).mean(),
            "ma60": cl.rolling(60, min_periods=60).mean(),
        },
        index=df.index,
    )


def _simulate_paired_sell(
    df: pd.DataFrame,
    entry_mask: pd.Series,
    *,
    hl: pd.Series,
    temp_label: pd.Series,
    aux: pd.DataFrame,
    sid: str,
    entry_tag: str,
    mode: str,
) -> List[Dict[str, Any]]:
    """同一進場核 × 賣出變體（成對比較用）。"""
    from sell_discipline import classify_how_to_sell
    from scripts.decade_lab_phone_trade_confront import FRICTION, MAX_HOLD

    cl = df["close"].astype(float)
    op = df["open"].astype(float)
    hi = df["high"].astype(float)
    lo = df["low"].astype(float)
    vo = aux["volume"]
    vma = aux["vol_ma20"]
    ma60 = aux["ma60"]
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
            mfe = peak / entry_px - 1.0
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
                    exit_i, exit_reason = j + 1, "first_hi20"
                    break
                if desync:
                    exit_i, exit_reason = j + 1, "sell_desync_cut"
                    break
            elif mode == "hi20_only":
                if hl_j == "20高":
                    exit_i, exit_reason = j + 1, "first_hi20"
                    break
            elif mode == "desync_only":
                if desync:
                    exit_i, exit_reason = j + 1, "sell_desync_cut"
                    break
            elif mode == "desync_after_mfe5":
                if hl_j == "20高":
                    exit_i, exit_reason = j + 1, "first_hi20"
                    break
                if mfe >= 0.05 and desync:
                    exit_i, exit_reason = j + 1, "sell_desync_cut"
                    break
            elif mode == "desync_after_mfe8":
                if hl_j == "20高":
                    exit_i, exit_reason = j + 1, "first_hi20"
                    break
                if mfe >= 0.08 and desync:
                    exit_i, exit_reason = j + 1, "sell_desync_cut"
                    break
            elif mode == "hi20_vol_fade_or_desync":
                if hl_j == "20高" and vol_fade:
                    exit_i, exit_reason = j + 1, "hi20_vol_fade"
                    break
                if desync:
                    exit_i, exit_reason = j + 1, "sell_desync_cut"
                    break
            elif mode == "hi20_or_desync_ma60":
                if hl_j == "20高":
                    exit_i, exit_reason = j + 1, "first_hi20"
                    break
                if desync and below_ma60:
                    exit_i, exit_reason = j + 1, "desync_ma60_fail"
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
                "entry_i": int(entry_i),
                "exit_i": int(exit_i),
                "entry_date": str(df["date"].iloc[entry_i]) if "date" in df.columns else str(entry_i),
                "exit_date": str(df["date"].iloc[exit_i]) if "date" in df.columns else str(exit_i),
                "net_ret": net,
                "hold_days": int(exit_i - entry_i),
                "exit_reason": exit_reason,
                "win": int(net > 0),
                "mfe": peak / entry_px - 1.0,
                "mae": trough / entry_px - 1.0,
                "sell_mode": mode,
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


def _delta_wr_safe(a: Dict[str, Any], b_wr: Optional[float]) -> Optional[float]:
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
        "delta_oos_wr": _delta_wr_safe(oos, plain_oos.get("win_rate")),
        "delta_vs_v106_keep_wr": _delta_wr_safe(oos, keep_ref.get("wr")),
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
            "version": "stock_pair_exit_leg_confirm_lab_v1",
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
    leaders = leader_self_sids()
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
    # 急跌例檔必納
    for sid in ("6442", "2383", "2330", "3017", "2308"):
        if sid not in symbols:
            symbols.append(sid)
    symbols = symbols[:n_use]

    _, mkt_raw = S["_twii_wave_pack"](entry_preset="A0_strict", score_threshold=40.0)

    confirm_buckets: Dict[str, Dict[str, List[Dict[str, Any]]]] = {
        c: {f: [] for f in CONFIRM_NAMES} for c in ("early", "fast")
    }
    sell_buckets: Dict[str, Dict[str, List[Dict[str, Any]]]] = {
        c: {m: [] for m in SELL_MODE_NAMES} for c in ("early", "fast")
    }
    all_dates: List[str] = []
    errors: List[str] = []
    meta_n = 0
    pe_hit_n = 0

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
            pe_map = load_pe_by_sid(sid, MARKET_DB)
            if pe_map:
                pe_hit_n += 1
            pe = align_pe_ffill(df, pe_map)
            feat = crash_proxy_features(df, pe=pe, is_leader=(sid in leaders))
            cmasks = confirm_masks(feat)
            aux = tech_sell_aux(df)

            early = masks[KEEP_EARLY].fillna(False)
            fast = masks[KEEP_FAST].fillna(False)

            for core_name, base in (("early", early), ("fast", fast)):
                for fname, fmask in cmasks.items():
                    em = (base & fmask.reindex(df.index).fillna(False)).fillna(False)
                    confirm_buckets[core_name][fname].extend(
                        _simulate_paired_sell(
                            df,
                            em,
                            hl=hl,
                            temp_label=temp,
                            aux=aux,
                            sid=sid,
                            entry_tag=f"confirm_{core_name}__{fname}",
                            mode=SELL_KEEP,
                        )
                    )
                for smode in SELL_MODE_NAMES:
                    sell_buckets[core_name][smode].extend(
                        _simulate_paired_sell(
                            df,
                            base,
                            hl=hl,
                            temp_label=temp,
                            aux=aux,
                            sid=sid,
                            entry_tag=f"sell_{core_name}__{smode}",
                            mode=smode,
                        )
                    )
        except Exception as e:  # noqa: BLE001
            errors.append(f"{sid}:{type(e).__name__}:{e}")

    train_d, test_d = _half_split_dates(all_dates)
    confirm_tracks: Dict[str, Any] = {}
    sell_tracks: Dict[str, Any] = {}
    best_confirm: Optional[Dict[str, Any]] = None
    best_sell: Optional[Dict[str, Any]] = None

    for core_name in ("early", "fast"):
        plain_full = _score(confirm_buckets[core_name]["plain"])
        plain_oos = _score(_filter_trades(confirm_buckets[core_name]["plain"], test_d))
        plain_is = _score(_filter_trades(confirm_buckets[core_name]["plain"], train_d))
        variants = {}
        for fname in CONFIRM_NAMES:
            if fname == "plain":
                continue
            full = _score(confirm_buckets[core_name][fname])
            oos = _score(_filter_trades(confirm_buckets[core_name][fname], test_d))
            is_ = _score(_filter_trades(confirm_buckets[core_name][fname], train_d))
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
                    "leg": "crash_confirm",
                    "core": core_name,
                    "variant": fname,
                    "kind": "vs_plain",
                    "oos_wr": oos.get("win_rate"),
                    "oos_d": oos.get("n_unique_entry_days"),
                    "plain_oos_wr": plain_oos.get("win_rate"),
                    "plain_oos_d": plain_oos.get("n_unique_entry_days"),
                    "delta_oos_wr": row["delta_oos_wr"],
                    "beats_v106_keep_oos": row["beats_v106_keep_oos"],
                    "delta_vs_v106_keep_wr": row["delta_vs_v106_keep_wr"],
                }
                if best_confirm is None or float(cand["delta_oos_wr"] or -1) > float(
                    best_confirm.get("delta_oos_wr") or -1
                ):
                    best_confirm = cand
        confirm_tracks[core_name] = {
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
                    "leg": "paired_exit",
                    "core": core_name,
                    "variant": smode,
                    "kind": "vs_hi20_or_desync",
                    "oos_wr": oos.get("win_rate"),
                    "oos_d": oos.get("n_unique_entry_days"),
                    "plain_oos_wr": sell_plain_oos.get("win_rate"),
                    "plain_oos_d": sell_plain_oos.get("n_unique_entry_days"),
                    "delta_oos_wr": row["delta_oos_wr"],
                    "beats_v106_keep_oos": row["beats_v106_keep_oos"],
                    "delta_vs_v106_keep_wr": row["delta_vs_v106_keep_wr"],
                }
                if best_sell is None or float(cand["delta_oos_wr"] or -1) > float(
                    best_sell.get("delta_oos_wr") or -1
                ):
                    best_sell = cand
        sell_tracks[core_name] = {
            "entry": KEEP_EARLY if core_name == "early" else KEEP_FAST,
            "sell_baseline": SELL_KEEP,
            "note_zh": "同一進場核成對比較賣出；非買端獨算 wr",
            "plain": {"full": sell_plain_full, "is": sell_plain_is, "oos": sell_plain_oos},
            "variants": sell_variants,
            "v106_ref": V106_REF[core_name],
        }

    shared_confirm: List[str] = []
    for fname in confirm_tracks["early"]["variants"]:
        if confirm_tracks["early"]["variants"][fname].get("beats_v106_keep_oos") and confirm_tracks[
            "fast"
        ]["variants"].get(fname, {}).get("beats_v106_keep_oos"):
            shared_confirm.append(fname)
    shared_sell: List[str] = []
    for smode in sell_tracks["early"]["variants"]:
        if sell_tracks["early"]["variants"][smode].get("beats_v106_keep_oos") and sell_tracks[
            "fast"
        ]["variants"].get(smode, {}).get("beats_v106_keep_oos"):
            shared_sell.append(smode)

    both_confirm_ok = bool(shared_confirm)
    both_sell_ok = bool(shared_sell)
    gate_passed = bool(both_confirm_ok or both_sell_ok)

    best: Optional[Dict[str, Any]] = None
    if both_confirm_ok:
        best = {
            "leg": "crash_confirm",
            "core": "both",
            "variant": shared_confirm[0],
            "shared": shared_confirm,
            "kind": "vs_v106_keep",
            "early_oos": confirm_tracks["early"]["variants"][shared_confirm[0]]["oos"],
            "fast_oos": confirm_tracks["fast"]["variants"][shared_confirm[0]]["oos"],
        }
    elif both_sell_ok:
        best = {
            "leg": "paired_exit",
            "core": "both",
            "variant": shared_sell[0],
            "shared": shared_sell,
            "kind": "vs_v106_keep",
            "early_oos": sell_tracks["early"]["variants"][shared_sell[0]]["oos"],
            "fast_oos": sell_tracks["fast"]["variants"][shared_sell[0]]["oos"],
        }
    else:
        cands = [c for c in (best_confirm, best_sell) if c is not None]
        if cands:
            best = max(cands, key=lambda c: float(c.get("delta_oos_wr") or -1))

    plain_edge = bool(best is not None and best.get("kind") in ("vs_plain", "vs_hi20_or_desync"))
    status = (
        "gate_pass_vs_v106_keep"
        if gate_passed
        else ("plain_delta_only_keep_v106" if plain_edge else "no_beat_keep_v106")
    )
    if smoke:
        status = "smoke_" + status

    gate = (
        f"stock_pair_exit_leg_confirm n={meta_n} smoke={int(smoke)}; "
        f"early_plain_oos_wr={confirm_tracks['early']['plain']['oos'].get('win_rate')} "
        f"d={confirm_tracks['early']['plain']['oos'].get('n_unique_entry_days')}; "
        f"fast_plain_oos_wr={confirm_tracks['fast']['plain']['oos'].get('win_rate')} "
        f"d={confirm_tracks['fast']['plain']['oos'].get('n_unique_entry_days')}; "
        f"best={best}; promote={gate_passed}"
    )

    finding = (
        "成對出場＋急跌四腿可重述代理確認（leader／PE近自身低／近60低；無abc／5／9／1-4計分）："
        + (
            f"共享變體 {best.get('variant')}（{best.get('leg')}）兩邊 OOS 贏 sealed v106 keep → 理論過閘；本件仍封 keep=v106／phone blocked。"
            if gate_passed
            else (
                f"相對同跑 baseline 有 Δ（{best}），但未贏 sealed v106 keep → keep v106。"
                if plain_edge
                else "各變體未贏 sealed v106 keep（或 n<20）→ keep v106。"
            )
        )
        + " 法人濾／技術確認不重推。"
    )

    out: Dict[str, Any] = {
        "version": "stock_pair_exit_leg_confirm_lab_v1",
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
        "tracks_zh": {
            "paired_exit": "同一 v106 進場核 × 賣出變體 vs hi20_or_desync",
            "crash_confirm": "v106 後確認層：leader_tag＋PE近自身近期低＋近60低（臨界代理）；非新買訊",
        },
        "forbidden_scored_zh": "不准發明／計分 wave 5／9／abc／1-4 浪級標籤",
        "data_sources": {
            "ohlc_volume": "daily_quotes open/high/low/close/volume",
            "pe": "daily_valuation.pe（twse_bwibbu；非成本）",
            "leader_tag": "biaoke_judge._FOLLOW／_LONG_HOLD 自為龍頭",
            "derived": "rolling low60、pe_vs_own_min32、dist_low60",
        },
        "n_stocks": meta_n,
        "n_stocks_with_pe": pe_hit_n,
        "n_leader_tags": len(leaders),
        "smoke": smoke,
        "confirm_tracks": confirm_tracks,
        "sell_tracks": sell_tracks,
        "best_candidate": best,
        "best_confirm_vs_plain": best_confirm,
        "best_sell_vs_keep_sell": best_sell,
        "shared_confirm_vs_keep": shared_confirm,
        "shared_sell_vs_keep": shared_sell,
        "gate_one_liner": gate,
        "finding_zh": finding,
        "elapsed_s": round(time.time() - t0, 1),
        "errors_n": len(errors),
        "errors_sample": errors[:8],
        "db_path": str(MARKET_DB),
        "parent_keep": "phone_spirit_mix_dual_track_v106_decision.json",
        "prev_failed": [
            "stock_inst_filter_lab_decision.json",
            "stock_tech_confirm_lab_decision.json",
        ],
        "next": "keep v106；成對出場／四腿代理可當後續候選；不准混浪形軌、不准改話筒",
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
    (ART / "stock_pair_exit_leg_confirm_lab_latest.json").write_text(text, encoding="utf-8")
    (DOC / "stock_pair_exit_leg_confirm_lab_latest.json").write_text(text, encoding="utf-8")


def _write_decision(out: Dict[str, Any]) -> None:
    best = out.get("best_candidate")
    decision = {
        "version": "stock_pair_exit_leg_confirm_lab_v1",
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
        "variant_tested_zh": (
            "成對出場（同進場比賣出）＋急跌四腿可重述代理確認"
            "（leader／PE近自身低／近60低；無abc／5／9／1-4計分）"
        ),
        "n_stocks": out.get("n_stocks"),
        "n_stocks_with_pe": out.get("n_stocks_with_pe"),
        "smoke": out.get("smoke"),
        "best_candidate": best,
        "best_confirm_vs_plain": out.get("best_confirm_vs_plain"),
        "best_sell_vs_keep_sell": out.get("best_sell_vs_keep_sell"),
        "shared_confirm_vs_keep": out.get("shared_confirm_vs_keep"),
        "shared_sell_vs_keep": out.get("shared_sell_vs_keep"),
        "oos_vs_v106_keep": {
            "early_plain_oos": (out.get("confirm_tracks") or {})
            .get("early", {})
            .get("plain", {})
            .get("oos"),
            "fast_plain_oos": (out.get("confirm_tracks") or {})
            .get("fast", {})
            .get("plain", {})
            .get("oos"),
            "v106_ref": V106_REF,
        },
        "gate_one_liner": out.get("gate_one_liner"),
        "finding_zh": out.get("finding_zh"),
        "latest": "stock_pair_exit_leg_confirm_lab_latest.json",
        "parent_keep": "phone_spirit_mix_dual_track_v106_decision.json",
        "prev_failed": out.get("prev_failed"),
        "next": out.get("next"),
    }
    text = json.dumps(decision, ensure_ascii=False, indent=2, default=str) + "\n"
    (ART / "stock_pair_exit_leg_confirm_lab_decision.json").write_text(text, encoding="utf-8")
    (DOC / "stock_pair_exit_leg_confirm_lab_decision.json").write_text(text, encoding="utf-8")


def main(argv: Optional[Sequence[str]] = None) -> Dict[str, Any]:
    ap = argparse.ArgumentParser(description="v106 × 成對出場＋急跌四腿確認 lab")
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
