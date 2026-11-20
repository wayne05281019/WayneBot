#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""藍▲出場協助獨立對質（雲端實驗室；不上話筒）。

背景（phone_trade_confront_latest.next_zh）：
- 進場固定＝leave_zero（官方高低卡畫法；不准改公式）
- ma60_lower 已可並列進場，但同套出場下隨機也贏 leave_zero → 不准改 leave_zero
- 本腳本只對質出場◇ first_hi20／減碼◆ sell_desync_cut 當獨立規則

出場變體（同一 leave_zero 進場核）：
- phone_stack：現況整段堆（首碰20高 → 如何賣不同步減碼 → 峰值回吐8% → 最多60日）
- first_hi20：只認出場◇（否則最多60日）
- sell_desync_cut：只認減碼◆（否則最多60日）
- hold_max：純抱到最多60日（基線）
- random_exit：持有窗內隨機日出（對照；同種子可重跑）

過閘：獨立開市日 n≥20 且同時贏 phone_stack 現況 ＋ random_exit；否則 phone_sync=blocked
不准改 leave_zero／ma60_lower 進場；buy_signal 不變；出場符號未過閘不上查股

soft_leader invent：關（3 次 thicken 失敗；keep v106）

用法：
  WAYNE_DB_PATH=data/wayne_market.db \\
  python scripts/decade_lab_stock_blue_arrow_exit_assist_confront_lab.py --smoke

  python scripts/decade_lab_stock_blue_arrow_exit_assist_confront_lab.py
"""
from __future__ import annotations

import argparse
import json
import math
import time
from collections import defaultdict
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
VERSION = "stock_blue_arrow_exit_assist_confront_lab_v1"
KEEP = "v106"
RANDOM_SEED = 20261110

# 出場變體鍵（順序＝報告用）
EXIT_MODES = (
    "phone_stack",  # 現況整段堆＝對質基線
    "first_hi20",
    "sell_desync_cut",
    "hold_max",
    "random_exit",
)

SOFT_LEADER_INVENT_OFF = {
    "status": "off",
    "reason_zh": "soft_leader invent 三次 thicken 失敗；keep v106；本軌改對質藍▲出場協助",
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
    """同一 leave_zero 進場；出場只換 exit_mode。次日開進。

    如何賣必須吃「截至當日」的高低／溫度序列（sell_action_series）；
    單根字串會被當成字元序列，減碼◆永遠不觸發——本 lab 修正此用法。
    """
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

        if exit_mode == "random_exit":
            # 持有窗內均勻抽一日；次日開出（窗尾則收盤）
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

                if exit_mode in ("phone_stack", "first_hi20"):
                    if hl_j == "20高" and not saw_hi20:
                        saw_hi20 = True
                        exit_i = j + 1
                        exit_reason = "first_hi20"
                        break

                if exit_mode in ("phone_stack", "sell_desync_cut"):
                    # 進場當日不算；之後第一根「直接減碼」
                    if str(sell_acts[j] or "") == "直接減碼":
                        exit_i = j + 1
                        exit_reason = "sell_desync_cut"
                        break

                if exit_mode == "phone_stack":
                    if peak > 0 and np.isfinite(c) and c <= peak * (1.0 - GIVEBACK):
                        exit_i = j + 1
                        exit_reason = "giveback_8pct"
                        break

            if exit_i is None:
                exit_i = hold_cap
                exit_reason = "max_hold_60"

        if exit_i is None:
            exit_i = hold_cap
            exit_reason = "max_hold_60"
        if exit_i >= n:
            exit_i = n - 1

        # 再掃一次 MFE/MAE（random／hold_max 路徑上面沒累積）
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
    *,
    wr_slack: float = 0.01,
) -> bool:
    """贏基線：n≥20 且期望值嚴格更高，勝率不差超過 slack。"""
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
    return float(ce) > float(be) and float(cw) >= float(bw) - wr_slack


def _assist_actually_fired(stats: Dict[str, Any], mode: str) -> bool:
    """出場協助符號必須真的觸發過；全是 max_hold＝跟 hold_max 同義，不准冒充過閘。"""
    reasons = stats.get("exit_reason_counts") or {}
    if mode == "first_hi20":
        return int(reasons.get("first_hi20") or 0) >= MIN_N_DAYS
    if mode == "sell_desync_cut":
        return int(reasons.get("sell_desync_cut") or 0) >= MIN_N_DAYS
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
            # 每檔獨立子種子，避免跨檔順序影響 random_exit 可重現性
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
        fired = _assist_actually_fired(stats, mode) if mode in ("first_hi20", "sell_desync_cut") else True
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

    # 候選＝出場協助符號（不含 hold_max／random）
    # 過閘：真觸發 ＋ 贏 phone_stack ＋ 贏 random_exit（並要求至少不輸 hold_max 太多＝必須真觸發增量）
    assist_keys = ("first_hi20", "sell_desync_cut")
    promote_candidates = []
    for key in assist_keys:
        cmp_ = comparisons.get(f"{key}_vs_phone_stack") or {}
        if (
            cmp_.get("assist_fired")
            and cmp_.get("beats_phone_stack")
            and cmp_.get("beats_random_exit")
        ):
            promote_candidates.append(key)

    gate_passed = bool(promote_candidates)
    promote_lookup = False  # 即使過閘也只報告；真上查股另過 §13／使用者
    phone_sync = "blocked"  # 本腳本永不改話筒；過閘只開 lab promote 旗
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
            "role": "exit_assist",
            "phone_now": False,
            "glyph_zh": "出場◇（建議）",
            "note": "進場後首碰20高；過閘才畫查股",
        },
        "sell_desync_cut": {
            "role": "exit_assist",
            "phone_now": "text_only",
            "glyph_zh": "減碼◆（建議）",
            "note": "如何賣不同步直接減碼；符號化待過閘",
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
        # 以期望值增量挑最佳
        best = max(
            promote_candidates,
            key=lambda k: float((comparisons.get(f"{k}_vs_phone_stack") or {}).get("expectancy_delta") or -1e9),
        )

    gate_one = (
        f"entry=leave_zero fixed; phone_stack wr={phone.get('win_rate')} E={phone.get('expectancy')} "
        f"d={phone.get('n_unique_entry_days')}; "
        f"first_hi20 wr={by_exit['first_hi20'].get('win_rate')} E={by_exit['first_hi20'].get('expectancy')} "
        f"d={by_exit['first_hi20'].get('n_unique_entry_days')}; "
        f"sell_desync wr={by_exit['sell_desync_cut'].get('win_rate')} E={by_exit['sell_desync_cut'].get('expectancy')} "
        f"d={by_exit['sell_desync_cut'].get('n_unique_entry_days')}; "
        f"random wr={random_ctrl.get('win_rate')} E={random_ctrl.get('expectancy')}; "
        f"gate={'PASS' if gate_passed else 'FAIL'} promote={promote_candidates or []} phone_sync={phone_sync}"
    )

    next_zh = (
        "出場協助過閘（lab）；另開 §13 審查是否畫上查股◇／◆；仍不准改 leave_zero"
        if gate_passed
        else "出場◇／減碼◆未同時贏現況堆＋隨機對照 → 維持 text_only／不畫；下一刀可試先觸發順序或合併門檻，仍固定 leave_zero 進場"
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
        "random_seed": RANDOM_SEED,
        "smoke": smoke,
        "n_stocks_meta": len(data_meta),
        "elapsed_s": round(time.time() - t0, 1),
        "method_zh": "leave_zero 次日開進；出場變體獨立對質；淨報酬扣 0.3% 摩擦",
        "symbol_map": symbol_map,
        "by_exit": by_exit,
        "wr_d": wr_d,
        "comparisons_vs_phone_stack": comparisons,
        "must_named": must_named,
        "gate_one_liner": gate_one,
        "errors_n": len(errors),
        "errors_sample": errors[:8],
        "parent_track": "phone_trade_confront_latest.json",
        "finding_zh": (
            f"藍▲出場協助對質：gate={'過' if gate_passed else '不過'}；"
            f"候選={promote_candidates or '無'}；soft_leader invent 已關 keep {KEEP}；"
            f"不准改 leave_zero／不上話筒。"
        ),
        "next_zh": next_zh,
        "honest_caveat_zh": "過閘只證明出場符號相對現況堆＋隨機有增量；真畫查股另過 §13。隨機贏 leave_zero 進場的 caveat 仍在。",
    }

    # 決策精簡檔
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
            if k.startswith("first_hi20") or k.startswith("sell_desync") or k.startswith("hold_max") or k.startswith("random")
        },
        "gate_one_liner": gate_one,
        "finding_zh": out["finding_zh"],
        "next_zh": next_zh,
        "parent_track": out["parent_track"],
    }

    latest_path = DOC / "stock_blue_arrow_exit_assist_confront_lab_latest.json"
    decision_path = DOC / "stock_blue_arrow_exit_assist_confront_lab_decision.json"
    seed_path = DOC / "stock_blue_arrow_exit_assist_confront_lab_seed.json"
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
        "gate": "beats phone_stack AND random_exit; n_unique_entry_days>=20",
        "note_zh": "再生下一版靜默對質種子；本檔只鎖規格不改話筒",
    }
    seed_text = json.dumps(seed, ensure_ascii=False, indent=2, default=str)

    latest_path.write_text(text, encoding="utf-8")
    decision_path.write_text(dec_text, encoding="utf-8")
    seed_path.write_text(seed_text, encoding="utf-8")
    (ART / "stock_blue_arrow_exit_assist_confront_lab_latest.json").write_text(text, encoding="utf-8")
    (ART / "stock_blue_arrow_exit_assist_confront_lab_decision.json").write_text(dec_text, encoding="utf-8")

    print("GATE", gate_one, flush=True)
    print("STATUS", status, "promote", promote_candidates, "keep", KEEP, flush=True)
    print("WR_D", json.dumps(wr_d, ensure_ascii=False, default=str)[:1200], flush=True)
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
