#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""藍▲出場協助：觸發順序／合併門檻對質（雲端實驗室；不上話筒）。

承接 confront（stock_blue_arrow_exit_assist_confront_lab）：
- first_hi20／sell_desync_cut 各自贏 phone_stack wr/E，但輸 random_exit 期望值 → gate_passed=false
- 本刀固定 leave_zero 進場；只換出場◇／減碼◆的**觸發順序**與 **OR／AND＋冷卻日**

出場變體：
- phone_stack：現況整段堆（基線）
- first_hi20／sell_desync_cut：confront 單符對照
- hi20_then_desync／desync_then_hi20：同日優先序（先看誰）
- merge_or：日曆上任一先觸發即出（同日雙觸＝merge_or_both）
- merge_and_cd{1,3,5}：兩符都要；第二符須落在第一符後 cooldown 日內
- hold_max／random_exit：對照

過閘：n_days≥20 且同時贏 phone_stack **與** random_exit 的 wr＋E；否則 phone_sync=blocked
不准改 leave_zero／ma60_lower；buy_signal=false；未過閘不上查股

用法：
  WAYNE_DB_PATH=data/wayne_market.db \\
  python scripts/decade_lab_stock_blue_arrow_exit_order_merge_lab.py --smoke

  python scripts/decade_lab_stock_blue_arrow_exit_order_merge_lab.py
"""
from __future__ import annotations

import argparse
import json
import math
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from scripts.decade_lab_chart_marks_stats import _build_mark_masks, _normalize_ohlc
from scripts.decade_lab_hsiao_universe import MUST_INCLUDE, load_stock_ohlcv, select_g_universe
from scripts.decade_lab_phone_trade_confront import (
    FRICTION,
    GIVEBACK,
    MAX_HOLD,
    _agg_trades,
    _build_hl_temp,
)

TAIPEI = ZoneInfo("Asia/Taipei")
PHONE_SYNC = "blocked"
BUY_SIGNAL = False
NOT_BUY_SIGNAL = True
ROOT = Path(__file__).resolve().parents[1]
ART = Path("/opt/cursor/artifacts")
DOC = ROOT / "docs" / "expert_notes" / "飆客" / "decade_lab"
MIN_N_DAYS = 20
ENTRY_TAG = "leave_zero_blue_tri"
VERSION = "stock_blue_arrow_exit_order_merge_lab_v1"
KEEP = "v106"
RANDOM_SEED = 20261110
PARENT_CONFRONT = "stock_blue_arrow_exit_assist_confront_lab"

# 合併 AND 冷卻日（結構參數；非發明價位）
MERGE_AND_COOLDOWNS = (1, 3, 5)

EXIT_MODES = (
    "phone_stack",
    "first_hi20",
    "sell_desync_cut",
    "hi20_then_desync",
    "desync_then_hi20",
    "merge_or",
    "merge_and_cd1",
    "merge_and_cd3",
    "merge_and_cd5",
    "hold_max",
    "random_exit",
)

# 過閘候選＝順序／合併刀（不含單符對照與基線對照）
ASSIST_CANDIDATE_KEYS = (
    "hi20_then_desync",
    "desync_then_hi20",
    "merge_or",
    "merge_and_cd1",
    "merge_and_cd3",
    "merge_and_cd5",
)

SOFT_LEADER_INVENT_OFF = {
    "status": "off",
    "reason_zh": "soft_leader invent 三次 thicken 失敗；keep v106；本軌改對質藍▲出場協助順序／合併",
    "keep": KEEP,
    "thicken_failures_n": 3,
}


def _now() -> str:
    return datetime.now(TAIPEI).isoformat(timespec="seconds")


def _wilson_ci(hits: int, n: int, z: float = 1.96) -> Tuple[float, float]:
    if n <= 0:
        return (float("nan"), float("nan"))
    p = hits / n
    den = 1.0 + z * z / n
    centre = (p + z * z / (2 * n)) / den
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
    return (max(0.0, centre - half), min(1.0, centre + half))


def _parse_merge_and_cd(exit_mode: str) -> Optional[int]:
    if not exit_mode.startswith("merge_and_cd"):
        return None
    try:
        return int(exit_mode.replace("merge_and_cd", "", 1))
    except ValueError:
        return None


def _day_signals(hl_j: str, sell_act: str) -> Tuple[bool, bool]:
    return (hl_j == "20高", str(sell_act or "") == "直接減碼")


def _simulate_exit_mode(
    df: pd.DataFrame,
    entry_mask: pd.Series,
    *,
    hl: pd.Series,
    temp_label: pd.Series,
    sid: str,
    exit_mode: str,
    rng: np.random.Generator,
    sell_acts: Optional[Sequence[str]] = None,
) -> List[Dict[str, Any]]:
    """同一 leave_zero 進場；出場只換 exit_mode。次日開進。"""
    cl = df["close"].astype(float)
    op = df["open"].astype(float)
    lo = df["low"].astype(float)
    hi = df["high"].astype(float)
    dates = df["date"].astype(str).tolist() if "date" in df.columns else [str(i) for i in range(len(df))]
    n = len(df)
    if sell_acts is None:
        sell_acts = [""] * n
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
        peak = entry_px
        trough = entry_px
        exit_i: Optional[int] = None
        exit_reason: Optional[str] = None
        saw_hi20 = False
        hold_cap = min(n - 1, entry_i + MAX_HOLD)
        and_cd = _parse_merge_and_cd(exit_mode)
        armed_hi20_j: Optional[int] = None
        armed_desync_j: Optional[int] = None

        if exit_mode == "random_exit":
            span = max(1, hold_cap - entry_i)
            offset = int(rng.integers(1, span + 1))
            exit_i = min(hold_cap, entry_i + offset)
            exit_reason = "random_exit"
        elif exit_mode == "hold_max":
            exit_i = hold_cap
            exit_reason = "max_hold_60"
        else:
            for j in range(entry_i, hold_cap):
                c = float(cl.iloc[j])
                h = float(hi.iloc[j])
                l = float(lo.iloc[j])
                if np.isfinite(h):
                    peak = max(peak, h)
                if np.isfinite(l):
                    trough = min(trough, l)
                if j <= entry_i:
                    continue
                hl_j = str(hl.iloc[j] or "")
                is_hi20, is_desync = _day_signals(hl_j, str(sell_acts[j] or ""))

                if exit_mode == "phone_stack":
                    if is_hi20 and not saw_hi20:
                        saw_hi20 = True
                        exit_i = j + 1
                        exit_reason = "first_hi20"
                        break
                    if is_desync:
                        exit_i = j + 1
                        exit_reason = "sell_desync_cut"
                        break
                    if peak > 0 and np.isfinite(c) and c <= peak * (1.0 - GIVEBACK):
                        exit_i = j + 1
                        exit_reason = "giveback_8pct"
                        break

                elif exit_mode == "first_hi20":
                    if is_hi20 and not saw_hi20:
                        saw_hi20 = True
                        exit_i = j + 1
                        exit_reason = "first_hi20"
                        break

                elif exit_mode == "sell_desync_cut":
                    if is_desync:
                        exit_i = j + 1
                        exit_reason = "sell_desync_cut"
                        break

                elif exit_mode == "hi20_then_desync":
                    # 同日優先 hi20，否則 desync
                    if is_hi20 and not saw_hi20:
                        saw_hi20 = True
                        exit_i = j + 1
                        exit_reason = "first_hi20"
                        break
                    if is_desync:
                        exit_i = j + 1
                        exit_reason = "sell_desync_cut"
                        break

                elif exit_mode == "desync_then_hi20":
                    # 同日優先 desync，否則 hi20
                    if is_desync:
                        exit_i = j + 1
                        exit_reason = "sell_desync_cut"
                        break
                    if is_hi20 and not saw_hi20:
                        saw_hi20 = True
                        exit_i = j + 1
                        exit_reason = "first_hi20"
                        break

                elif exit_mode == "merge_or":
                    if is_hi20 and is_desync:
                        exit_i = j + 1
                        exit_reason = "merge_or_both"
                        break
                    if is_hi20 and not saw_hi20:
                        saw_hi20 = True
                        exit_i = j + 1
                        exit_reason = "first_hi20"
                        break
                    if is_desync:
                        exit_i = j + 1
                        exit_reason = "sell_desync_cut"
                        break

                elif and_cd is not None:
                    # AND＋冷卻：先觸發者 armed；另一符須在 cooldown 日內出現才出
                    # 未配對臂過期則清掉，當日符可重新 arm
                    if (
                        armed_hi20_j is not None
                        and armed_desync_j is None
                        and (j - armed_hi20_j) > and_cd
                    ):
                        armed_hi20_j = None
                    if (
                        armed_desync_j is not None
                        and armed_hi20_j is None
                        and (j - armed_desync_j) > and_cd
                    ):
                        armed_desync_j = None
                    if is_hi20 and armed_hi20_j is None:
                        armed_hi20_j = j
                    if is_desync and armed_desync_j is None:
                        armed_desync_j = j
                    if armed_hi20_j is not None and armed_desync_j is not None:
                        gap = abs(int(armed_hi20_j) - int(armed_desync_j))
                        if gap <= and_cd:
                            exit_i = j + 1
                            exit_reason = f"merge_and_cd{and_cd}"
                            break
                        # 雙臂但間距已超冷卻：丢掉較舊的，保留當日較新者
                        if armed_hi20_j < armed_desync_j:
                            armed_hi20_j = j if is_hi20 else None
                        else:
                            armed_desync_j = j if is_desync else None
                        if is_hi20 and armed_hi20_j is None:
                            armed_hi20_j = j
                        if is_desync and armed_desync_j is None:
                            armed_desync_j = j

            if exit_i is None:
                exit_i = hold_cap
                exit_reason = "max_hold_60"

        if exit_i is None:
            exit_i = hold_cap
            exit_reason = "max_hold_60"
        if exit_i >= n:
            exit_i = n - 1

        peak = entry_px
        trough = entry_px
        for j in range(entry_i, min(exit_i + 1, n)):
            h = float(hi.iloc[j])
            l = float(lo.iloc[j])
            if np.isfinite(h):
                peak = max(peak, h)
            if np.isfinite(l):
                trough = min(trough, l)

        if exit_reason == "max_hold_60" or exit_i == n - 1:
            exit_px = float(cl.iloc[exit_i])
        else:
            exit_px = float(op.iloc[exit_i]) if np.isfinite(op.iloc[exit_i]) else float(cl.iloc[exit_i])
        if not (np.isfinite(exit_px) and exit_px > 0):
            i = max(i + 1, exit_i)
            continue
        gross = exit_px / entry_px - 1.0
        net = gross - FRICTION
        trades.append(
            {
                "sid": sid,
                "entry_tag": ENTRY_TAG,
                "exit_mode": exit_mode,
                "entry_signal_date": dates[i],
                "entry_date": dates[entry_i],
                "exit_date": dates[exit_i],
                "exit_reason": exit_reason,
                "hold_days": int(exit_i - entry_i),
                "gross_ret": gross,
                "net_ret": net,
                "win": 1 if net > 0 else 0,
                "mfe": peak / entry_px - 1.0,
                "mae": trough / entry_px - 1.0,
            }
        )
        i = exit_i + 1
    return trades


def _beats_status(
    cand: Dict[str, Any],
    base: Dict[str, Any],
) -> bool:
    """贏基線：n≥20 且 wr 與 E **同時**嚴格更高。"""
    nd = int(cand.get("n_unique_entry_days") or 0)
    bd = int(base.get("n_unique_entry_days") or 0)
    if nd < MIN_N_DAYS or bd < MIN_N_DAYS:
        return False
    ce = cand.get("expectancy")
    be = base.get("expectancy")
    cw = cand.get("win_rate")
    bw = base.get("win_rate")
    if not (np.isfinite(ce) and np.isfinite(be) and np.isfinite(cw) and np.isfinite(bw)):
        return False
    return float(ce) > float(be) and float(cw) > float(bw)


def _assist_actually_fired(stats: Dict[str, Any], mode: str) -> bool:
    """出場協助必須真觸發；全是 max_hold＝跟 hold_max 同義，不准冒充過閘。"""
    reasons = stats.get("exit_reason_counts") or {}
    if mode == "first_hi20":
        return int(reasons.get("first_hi20") or 0) >= MIN_N_DAYS
    if mode == "sell_desync_cut":
        return int(reasons.get("sell_desync_cut") or 0) >= MIN_N_DAYS
    if mode in ("hi20_then_desync", "desync_then_hi20", "merge_or"):
        n_hi = int(reasons.get("first_hi20") or 0)
        n_de = int(reasons.get("sell_desync_cut") or 0)
        n_both = int(reasons.get("merge_or_both") or 0)
        return (n_hi + n_de + n_both) >= MIN_N_DAYS
    and_cd = _parse_merge_and_cd(mode)
    if and_cd is not None:
        return int(reasons.get(f"merge_and_cd{and_cd}") or 0) >= MIN_N_DAYS
    return True


def run_lab(*, n_universe: int = 100, smoke: bool = False) -> Dict[str, Any]:
    t0 = time.time()
    ART.mkdir(parents=True, exist_ok=True)
    DOC.mkdir(parents=True, exist_ok=True)

    uni = select_g_universe(n=n_universe, include_twse_top100=True)
    symbols = uni["stock_id"].astype(str).tolist()
    for sid in MUST_INCLUDE:
        if sid not in symbols:
            symbols.append(sid)
    if smoke:
        symbols = list(dict.fromkeys(list(MUST_INCLUDE.keys()) + symbols[:8]))

    bucket: Dict[str, List[Dict[str, Any]]] = {m: [] for m in EXIT_MODES}
    data_meta: Dict[str, Any] = {}
    errors: List[str] = []
    rng = np.random.default_rng(RANDOM_SEED)

    for sid in symbols:
        try:
            raw = load_stock_ohlcv(sid)
            if len(raw) < 120:
                continue
            data_meta[sid] = {
                "source": raw.attrs.get("source"),
                "years": raw.attrs.get("years"),
                "span": raw.attrs.get("span"),
                "adj_kind": raw.attrs.get("adj_kind"),
                "name": MUST_INCLUDE.get(sid)
                or (
                    str(uni.loc[uni.stock_id == sid, "stock_name"].iloc[0])
                    if (uni.stock_id == sid).any()
                    else sid
                ),
            }
            df = _normalize_ohlc(raw)
            masks = _build_mark_masks(df)
            hl, temp_label = _build_hl_temp(df)
            from sell_discipline import sell_action_series

            sell_acts = sell_action_series(hl.tolist(), temp_label.tolist())
            entry = masks.get(ENTRY_TAG)
            if entry is None:
                continue
            entry_m = entry.fillna(False)
            try:
                sid_num = int(sid)
            except ValueError:
                sid_num = sum(ord(ch) for ch in sid)
            sid_seed = (RANDOM_SEED + sid_num * 9973) % (2**32 - 1)
            mode_salt = {m: i + 1 for i, m in enumerate(EXIT_MODES)}
            for mode in EXIT_MODES:
                mode_rng = np.random.default_rng((sid_seed + mode_salt[mode] * 10007) % (2**32 - 1))
                trades = _simulate_exit_mode(
                    df,
                    entry_m,
                    hl=hl,
                    temp_label=temp_label,
                    sid=sid,
                    exit_mode=mode,
                    rng=mode_rng if mode == "random_exit" else rng,
                    sell_acts=sell_acts,
                )
                bucket[mode].extend(trades)
        except Exception as e:
            errors.append(f"{sid}:{type(e).__name__}:{e}")

    by_exit = {m: _agg_trades(trs) for m, trs in bucket.items()}
    phone = by_exit.get("phone_stack") or {}
    random_ctrl = by_exit.get("random_exit") or {}
    hold_max_stats = by_exit.get("hold_max") or {}

    comparisons: Dict[str, Any] = {}
    for mode in EXIT_MODES:
        if mode == "phone_stack":
            continue
        stats = by_exit[mode]
        fired = _assist_actually_fired(stats, mode)
        comparisons[f"{mode}_vs_phone_stack"] = {
            "gate_n20": int(stats.get("n_unique_entry_days") or 0) >= MIN_N_DAYS,
            "assist_fired": fired,
            "expectancy_delta": (
                float(stats["expectancy"]) - float(phone["expectancy"])
                if np.isfinite(stats.get("expectancy", np.nan))
                and np.isfinite(phone.get("expectancy", np.nan))
                else float("nan")
            ),
            "win_rate_delta": (
                float(stats["win_rate"]) - float(phone["win_rate"])
                if np.isfinite(stats.get("win_rate", np.nan))
                and np.isfinite(phone.get("win_rate", np.nan))
                else float("nan")
            ),
            "beats_phone_stack": _beats_status(stats, phone),
            "beats_random_exit": _beats_status(stats, random_ctrl),
            "beats_hold_max": _beats_status(stats, hold_max_stats),
            "tag_days": stats.get("n_unique_entry_days"),
            "phone_days": phone.get("n_unique_entry_days"),
            "random_days": random_ctrl.get("n_unique_entry_days"),
        }

    promote_candidates: List[str] = []
    for key in ASSIST_CANDIDATE_KEYS:
        cmp_ = comparisons.get(f"{key}_vs_phone_stack") or {}
        if (
            cmp_.get("assist_fired")
            and cmp_.get("beats_phone_stack")
            and cmp_.get("beats_random_exit")
        ):
            promote_candidates.append(key)

    gate_passed = bool(promote_candidates)
    promote_lookup = False
    phone_sync = "blocked"
    status = "gate_clear_lab_only" if gate_passed else "no_beat_keep_phone_stack_blocked"

    wr_d = {
        m: {
            "wr": by_exit[m].get("win_rate"),
            "d": by_exit[m].get("n_unique_entry_days"),
            "E": by_exit[m].get("expectancy"),
            "n_trades": by_exit[m].get("n_trades"),
            "avg_hold": by_exit[m].get("avg_hold"),
            "exit_reason_counts": by_exit[m].get("exit_reason_counts"),
        }
        for m in EXIT_MODES
    }

    must_named: Dict[str, Any] = {}
    for sid in MUST_INCLUDE:
        must_named[sid] = {"name": MUST_INCLUDE[sid], "data": data_meta.get(sid), "by_exit": {}}
        for mode, trs in bucket.items():
            sub = [t for t in trs if t["sid"] == sid]
            must_named[sid]["by_exit"][mode] = _agg_trades(sub)

    symbol_map = {
        "leave_zero_blue_tri": {
            "role": "entry_fixed",
            "phone_now": True,
            "glyph_zh": "藍▲紅框",
            "note": "進場固定；公式不改",
        },
        "first_hi20": {
            "role": "exit_assist_ref",
            "phone_now": False,
            "glyph_zh": "出場◇（confront 單符）",
            "note": "承接 confront；本刀不當 promote 鍵",
        },
        "sell_desync_cut": {
            "role": "exit_assist_ref",
            "phone_now": "text_only",
            "glyph_zh": "減碼◆（confront 單符）",
            "note": "承接 confront；本刀不當 promote 鍵",
        },
        "hi20_then_desync": {
            "role": "exit_order",
            "phone_now": False,
            "glyph_zh": "先◇後◆",
            "note": "同日優先 20高，否則減碼",
        },
        "desync_then_hi20": {
            "role": "exit_order",
            "phone_now": False,
            "glyph_zh": "先◆後◇",
            "note": "同日優先減碼，否則 20高",
        },
        "merge_or": {
            "role": "exit_merge",
            "phone_now": False,
            "glyph_zh": "◇∨◆",
            "note": "任一先觸發；同日雙觸＝merge_or_both",
        },
        "merge_and_cd1": {
            "role": "exit_merge",
            "phone_now": False,
            "glyph_zh": "◇∧◆ cd1",
            "note": "兩符；第二符須在第一符後 1 日內",
        },
        "merge_and_cd3": {
            "role": "exit_merge",
            "phone_now": False,
            "glyph_zh": "◇∧◆ cd3",
            "note": "兩符；第二符須在第一符後 3 日內",
        },
        "merge_and_cd5": {
            "role": "exit_merge",
            "phone_now": False,
            "glyph_zh": "◇∧◆ cd5",
            "note": "兩符；第二符須在第一符後 5 日內",
        },
        "phone_stack": {
            "role": "exit_baseline_current",
            "phone_now": True,
            "glyph_zh": "現況出場堆",
            "note": "first_hi20→sell_desync→giveback8→max60",
        },
        "hold_max": {
            "role": "exit_baseline",
            "phone_now": False,
            "glyph_zh": "抱滿60日",
            "note": "基線",
        },
        "random_exit": {
            "role": "exit_control",
            "phone_now": False,
            "glyph_zh": "隨機出場對照",
            "note": "持有窗均勻抽日；過閘必須贏它",
        },
    }

    best = None
    if promote_candidates:
        best = max(
            promote_candidates,
            key=lambda k: float(
                (comparisons.get(f"{k}_vs_phone_stack") or {}).get("expectancy_delta") or -1e9
            ),
        )

    def _wr_e(mode: str) -> str:
        s = by_exit.get(mode) or {}
        return f"{mode} wr={s.get('win_rate')} E={s.get('expectancy')} d={s.get('n_unique_entry_days')}"

    gate_one = (
        f"entry=leave_zero fixed; {_wr_e('phone_stack')}; "
        f"{_wr_e('hi20_then_desync')}; {_wr_e('desync_then_hi20')}; {_wr_e('merge_or')}; "
        f"{_wr_e('merge_and_cd3')}; {_wr_e('random_exit')}; "
        f"gate={'PASS' if gate_passed else 'FAIL'} promote={promote_candidates or []} "
        f"phone_sync={phone_sync}"
    )

    next_zh = (
        "順序／合併過閘（lab）；另開 §13 審查是否畫上查股；仍不准改 leave_zero"
        if gate_passed
        else (
            "順序／合併未同時贏現況堆＋隨機對照（wr+E）→ 維持 text_only／不畫；"
            "下一刀可試既有 GIVEBACK 開關（0.08 on/off）或 confront 單符＋持有過濾，仍固定 leave_zero 進場"
        )
    )

    out: Dict[str, Any] = {
        "version": VERSION,
        "as_of": _now(),
        "tz": "Asia/Taipei",
        "phone_sync": phone_sync,
        "buy_signal": BUY_SIGNAL,
        "not_buy_signal": NOT_BUY_SIGNAL,
        "promote_lookup": promote_lookup,
        "promote_lab_signal": gate_passed,
        "promote_candidates": promote_candidates,
        "best_candidate": best,
        "gate_passed": gate_passed,
        "status": status,
        "keep": KEEP,
        "soft_leader_invent": SOFT_LEADER_INVENT_OFF,
        "entry": ENTRY_TAG,
        "entry_note_zh": "固定 leave_zero 官方畫法；不准改公式；ma60_lower 本跑不重測進場",
        "friction": FRICTION,
        "max_hold": MAX_HOLD,
        "giveback": GIVEBACK,
        "merge_and_cooldowns": list(MERGE_AND_COOLDOWNS),
        "random_seed": RANDOM_SEED,
        "smoke": smoke,
        "n_stocks_meta": len(data_meta),
        "elapsed_s": round(time.time() - t0, 1),
        "method_zh": "leave_zero 次日開進；出場順序／合併變體對質；淨報酬扣 0.3% 摩擦",
        "symbol_map": symbol_map,
        "by_exit": by_exit,
        "wr_d": wr_d,
        "comparisons_vs_phone_stack": comparisons,
        "must_named": must_named,
        "gate_one_liner": gate_one,
        "errors_n": len(errors),
        "errors_sample": errors[:8],
        "parent_track": PARENT_CONFRONT,
        "finding_zh": (
            f"藍▲出場順序／合併對質：gate={'過' if gate_passed else '不過'}；"
            f"候選={promote_candidates or '無'}；soft_leader invent 已關 keep {KEEP}；"
            f"不准改 leave_zero／不上話筒。"
        ),
        "next_zh": next_zh,
        "honest_caveat_zh": (
            "過閘只證明順序／合併相對現況堆＋隨機有增量；真畫查股另過 §13。"
            "threshold 只動結構冷卻日與既有 GIVEBACK 常數，不准發明價位。"
        ),
    }

    decision = {
        "version": VERSION,
        "as_of": out["as_of"],
        "tz": "Asia/Taipei",
        "phone_sync": phone_sync,
        "buy_signal": BUY_SIGNAL,
        "promote_lookup": promote_lookup,
        "promote_lab_signal": gate_passed,
        "promote_candidates": promote_candidates,
        "best_candidate": best,
        "gate_passed": gate_passed,
        "status": status,
        "keep": KEEP,
        "soft_leader_invent": SOFT_LEADER_INVENT_OFF,
        "entry": ENTRY_TAG,
        "smoke": smoke,
        "n_stocks_meta": len(data_meta),
        "wr_d": wr_d,
        "comparisons_vs_phone_stack": {
            k: comparisons[k]
            for k in comparisons
            if any(
                k.startswith(p)
                for p in (
                    "hi20_then",
                    "desync_then",
                    "merge_or",
                    "merge_and",
                    "first_hi20",
                    "sell_desync",
                    "hold_max",
                    "random",
                )
            )
        },
        "gate_one_liner": gate_one,
        "finding_zh": out["finding_zh"],
        "next_zh": next_zh,
        "parent_track": out["parent_track"],
    }

    latest_path = DOC / "stock_blue_arrow_exit_order_merge_lab_latest.json"
    decision_path = DOC / "stock_blue_arrow_exit_order_merge_lab_decision.json"
    seed_path = DOC / "stock_blue_arrow_exit_order_merge_lab_seed.json"
    text = json.dumps(out, ensure_ascii=False, indent=2, default=str)
    dec_text = json.dumps(decision, ensure_ascii=False, indent=2, default=str)
    seed = {
        "version": VERSION,
        "status": status,
        "phone_sync": phone_sync,
        "buy_signal": BUY_SIGNAL,
        "keep": KEEP,
        "soft_leader_invent": "off",
        "entry": ENTRY_TAG,
        "exit_modes": list(EXIT_MODES),
        "assist_candidate_keys": list(ASSIST_CANDIDATE_KEYS),
        "merge_and_cooldowns": list(MERGE_AND_COOLDOWNS),
        "gate": "beats phone_stack AND random_exit on BOTH wr and expectancy; n_unique_entry_days>=20",
        "note_zh": "再生下一版靜默對質種子；本檔只鎖規格不改話筒",
        "parent_confront": PARENT_CONFRONT,
    }
    seed_text = json.dumps(seed, ensure_ascii=False, indent=2, default=str)

    latest_path.write_text(text, encoding="utf-8")
    decision_path.write_text(dec_text, encoding="utf-8")
    seed_path.write_text(seed_text, encoding="utf-8")
    (ART / "stock_blue_arrow_exit_order_merge_lab_latest.json").write_text(text, encoding="utf-8")
    (ART / "stock_blue_arrow_exit_order_merge_lab_decision.json").write_text(dec_text, encoding="utf-8")

    print("GATE", gate_one, flush=True)
    print("STATUS", status, "promote", promote_candidates, "keep", KEEP, flush=True)
    print("WR_D", json.dumps(wr_d, ensure_ascii=False, default=str)[:1600], flush=True)
    return out


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--smoke", action="store_true", help="小母體煙測")
    ap.add_argument("--n-universe", type=int, default=100)
    args = ap.parse_args(list(argv) if argv is not None else None)
    run_lab(n_universe=int(args.n_universe), smoke=bool(args.smoke))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
