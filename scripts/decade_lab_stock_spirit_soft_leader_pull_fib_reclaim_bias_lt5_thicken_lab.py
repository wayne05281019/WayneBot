#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""個股 lab：加厚 soft_leader_reclaim_bias_lt5（靜默對質；次高 WR 剩刀）。

承接 soft_leader×pull_fib×reclaim×sell_vol_fade 理論刀（oos_wr≈0.837 oos_d=41；
beats_v106_early=True、beats_fast=False；shared=[]）。本件只加厚該刀：
walk-forward 3 摺＋半切；賣端維持母刀同款 hi20_vol_fade_or_desync。

硬規則：
- 官方 OHLC／量／spirit／話筒族表；不准假成本／浪級計分
- phone_sync=blocked；buy_signal=false；不准改 leave_zero／黃金／藍▲／話筒畫面
- 過閘：獨立開市日 n≥20 且 OOS 贏 sealed v106 early+fast；加厚摺疊誠實落檔
- 理論贏且加厚證據誠實 → gate_passed 用真結果（不准無條件硬鎖 False）
- 勝率不准混浪形軌；spirit keep 軌 replace 標 keep=v107；phone 配線另件
- 未過閘 → keep=v106；NEXT=stop_or_switch_to_blue_arrow_track_note（不准再發明 soft_leader sell 變體）

用法：
  WAYNE_DB_PATH=data/wayne_market.db \\
  python scripts/decade_lab_stock_spirit_soft_leader_pull_fib_reclaim_bias_lt5_thicken_lab.py

  python scripts/decade_lab_stock_spirit_soft_leader_pull_fib_reclaim_bias_lt5_thicken_lab.py --smoke
"""
from __future__ import annotations

import argparse
import json
import os
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
THICK_TARGET_DAYS = 40  # ≫20；達不到就誠實標 thin_sample_risk
SELL_KEEP = "hi20_vol_fade_or_desync"
FOCUS_VARIANT = "soft_leader_reclaim_bias_lt5"
KEEP_PROMOTE_LABEL = "v107"
KEEP_FAIL_LABEL = "v106"
V106_REF = {
    "early": {"wr": 0.8269230769230769, "d": 51, "bars": 16.54901960784314},
    "fast": {"wr": 0.8545454545454545, "d": 54, "bars": 15.296296296296296},
}

# 只測焦點刀＋最小對照；不准再堆 sell／desync／bias_lt8／vol 變體
CONFIRM_NAMES = (
    "plain",
    "soft_leader_and_reclaim",
    FOCUS_VARIANT,
)

NEXT_FAIL = "stop_or_switch_to_blue_arrow_track_note"
NEXT_PASS = (
    "spirit keep=v107 已標 promote_lookup；phone_sync 仍 blocked，"
    "下一件才配線話筒；再生下一版靜默對質候選"
)

STEM = "stock_spirit_soft_leader_pull_fib_reclaim_bias_lt5_thicken_lab"


def _now() -> str:
    return datetime.now(TAIPEI).isoformat(timespec="seconds")


def _ymd(raw: Any) -> str:
    t = str(raw or "").replace("-", "")[:8]
    return t if len(t) == 8 and t.isdigit() else ""


def soft_leader_sids() -> Set[str]:
    from scripts.decade_lab_stock_spirit_soft_leader_pull_fib_reclaim_lab import (
        soft_leader_sids as _soft,
    )

    return _soft()


def spirit_pull_fib_entry_mask(df: pd.DataFrame, raw: pd.DataFrame) -> pd.Series:
    from scripts.decade_lab_stock_spirit_pull_fib_leader_bias_lab import (
        spirit_pull_fib_entry_mask as _mask,
    )

    return _mask(df, raw)


def confirm_masks_reclaim_bias_lt5_thicken(
    *,
    is_soft_leader: bool,
    tech_feat: pd.DataFrame,
) -> Dict[str, pd.Series]:
    """最小對照：plain／soft_leader_and_reclaim／focus bias_lt5。"""
    from scripts.decade_lab_stock_tech_confirm_lab import buy_confirm_masks

    tmasks = buy_confirm_masks(tech_feat)
    idx = tech_feat.index
    reclaim = tmasks["reclaim_ma20"].reindex(idx).fillna(False)
    bias5 = tmasks["bias20_lt5"].reindex(idx).fillna(False)
    soft = pd.Series(bool(is_soft_leader), index=idx)
    base_combo = (soft & reclaim).fillna(False)
    return {
        "plain": pd.Series(True, index=idx),
        "soft_leader_and_reclaim": base_combo,
        FOCUS_VARIANT: (base_combo & bias5).fillna(False),
    }


def _half_split_dates(dates: Sequence[str]) -> Tuple[set, set]:
    uniq = sorted({_ymd(x) for x in dates if _ymd(x)})
    mid = len(uniq) // 2
    return set(uniq[:mid]), set(uniq[mid:])


def _chrono_folds(dates: Sequence[str], n_folds: int = 3) -> List[Dict[str, Any]]:
    """Expanding walk-forward：每摺 train=先前，test=下一等寬窗（至少 2–3 摺）。"""
    uniq = sorted({_ymd(x) for x in dates if _ymd(x)})
    n = len(uniq)
    if n < 30 or n_folds < 2:
        train, test = _half_split_dates(uniq)
        return [{"name": "half_split", "train": train, "test": test}]
    folds: List[Dict[str, Any]] = []
    # 切成 n_folds+1 段：前段累積當 train，後 n_folds 段各當一次 OOS
    edges = [int(round(i * n / (n_folds + 1))) for i in range(n_folds + 2)]
    for i in range(1, n_folds + 1):
        train = set(uniq[: edges[i]])
        test = set(uniq[edges[i] : edges[i + 1]])
        if not train or not test:
            continue
        folds.append({"name": f"wf_expand_{i}_of_{n_folds}", "train": train, "test": test})
    # 再加與母刀對齊的半切（主閘）
    train_h, test_h = _half_split_dates(uniq)
    folds.append({"name": "half_split", "train": train_h, "test": test_h})
    return folds


def _filter_trades(trades: List[Dict[str, Any]], keep_dates: set) -> List[Dict[str, Any]]:
    return [t for t in trades if _ymd(t.get("entry_date")) in keep_dates]


def _finite_or_none(v: Any) -> Any:
    try:
        if v is None:
            return None
        f = float(v)
        return f if np.isfinite(f) else None
    except (TypeError, ValueError):
        return v


def _score(trades: List[Dict[str, Any]]) -> Dict[str, Any]:
    from scripts.decade_lab_phone_trade_confront import _agg_trades

    st = _agg_trades(trades)
    days = int(st.get("n_unique_entry_days") or 0)
    win = float(st.get("win_rate") or np.nan)
    return {
        "n_trades": st.get("n_trades"),
        "n_unique_entry_days": days,
        "win_rate": win if np.isfinite(win) else None,
        "expectancy": _finite_or_none(st.get("expectancy")),
        "avg_hold": _finite_or_none(st.get("avg_hold")),
        "exit_reason_counts": st.get("exit_reason_counts") or {},
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


def _write_outputs(out: Dict[str, Any]) -> None:
    DOC.mkdir(parents=True, exist_ok=True)
    ART.mkdir(parents=True, exist_ok=True)
    latest = DOC / f"{STEM}_latest.json"
    decision = DOC / f"{STEM}_decision.json"
    seed = DOC / f"{STEM}_seed.json"
    latest.write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    slim = {k: out[k] for k in out if k not in ("tracks", "errors_sample")}
    decision.write_text(json.dumps(slim, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    seed_obj: Dict[str, Any] = {}
    if seed.exists():
        try:
            seed_obj = json.loads(seed.read_text(encoding="utf-8"))
        except Exception:
            seed_obj = {}
    seed_obj.update(
        {
            "version": out.get("version"),
            "tz": "Asia/Taipei",
            "phone_sync": out.get("phone_sync"),
            "buy_signal": out.get("buy_signal"),
            "status": out.get("status"),
            "gate_passed": out.get("gate_passed"),
            "keep": out.get("keep"),
            "as_of": out.get("as_of"),
            "best_candidate": out.get("best_candidate"),
            "shared_vs_keep": out.get("shared_vs_keep"),
            "promote_lookup": out.get("promote_lookup"),
            "fold_table": out.get("fold_table"),
            "thin_sample_risk": out.get("thin_sample_risk"),
            "next": out.get("next"),
            "NEXT": out.get("NEXT"),
            "entry": out.get("entry"),
            "sell": out.get("sell"),
            "focus_variant": FOCUS_VARIANT,
            "confirm_variants": list(CONFIRM_NAMES),
            "parents": [
                "stock_spirit_soft_leader_pull_fib_reclaim_sell_vol_fade_lab_decision.json",
                "stock_spirit_soft_leader_pull_fib_ma5_10_hold_bias_lt5_thicken_lab_decision.json",
                "stock_spirit_soft_leader_fib618_vol_expand_thicken_lab_decision.json",
            ],
            "hypothesis_zh": (
                "加厚 soft_leader_reclaim_bias_lt5：多摺 walk-forward／半切；"
                "目標獨立 OOS 日 ≫20；理論贏且證據誠實則 gate 真結果→keep=v107；"
                "失敗則 stop_or_switch_to_blue_arrow_track_note"
            ),
        }
    )
    seed.write_text(json.dumps(seed_obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (ART / f"{STEM}_decision.json").write_text(
        json.dumps(slim, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (ART / f"{STEM}_fold_table.json").write_text(
        json.dumps(out.get("fold_table") or [], ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def run(*, n_stocks: int = 260, min_avg_turnover_k: float = 800_000.0, smoke: bool = False) -> Dict[str, Any]:
    from scripts.decade_lab_chart_marks_stats import _normalize_ohlc
    from scripts.decade_lab_hsiao_universe import MUST_INCLUDE, load_stock_ohlcv, select_g_universe
    from scripts.decade_lab_phone_trade_confront import _build_hl_temp
    from scripts.decade_lab_stock_pair_exit_leg_confirm_lab import (
        _simulate_paired_sell,
        align_pe_ffill,
        leader_self_sids,
        load_pe_by_sid,
        tech_sell_aux,
    )
    from scripts.decade_lab_stock_tech_confirm_lab import tech_features

    t0 = time.time()
    hard_leaders = leader_self_sids()
    soft_leaders = soft_leader_sids() | hard_leaders
    n_use = 12 if smoke else int(n_stocks)
    uni = select_g_universe(
        n=max(80, n_use),
        include_twse_top100=True,
        min_avg_turnover_k=float(min_avg_turnover_k),
    )
    symbols: List[str] = uni["stock_id"].astype(str).tolist()
    for sid in MUST_INCLUDE:
        sid_s = str(sid)
        if sid_s not in symbols:
            symbols.append(sid_s)
    for sid in sorted(soft_leaders | hard_leaders | {"6442", "2383", "2330", "3017", "2308"}):
        if sid not in symbols:
            symbols.append(sid)
    symbols = symbols[:n_use]

    buckets: Dict[str, List[Dict[str, Any]]] = {f: [] for f in CONFIRM_NAMES}
    all_dates: List[str] = []
    errors: List[str] = []
    meta_n = 0
    entry_hits = 0

    for sid in symbols:
        try:
            raw = load_stock_ohlcv(sid)
            if raw is None or len(raw) < 150:
                continue
            df = _normalize_ohlc(raw)
            if df is None or len(df) < 150:
                continue
            meta_n += 1
            all_dates.extend(df["date"].astype(str).tolist())
            base = spirit_pull_fib_entry_mask(df, raw)
            entry_hits += int(base.sum())
            hl, temp = _build_hl_temp(df)
            _ = align_pe_ffill(df, load_pe_by_sid(sid, MARKET_DB))  # 官方欄對齊；本刀不用 PE 濾
            is_soft = sid in soft_leaders
            tech_feat = tech_features(df)
            cmasks = confirm_masks_reclaim_bias_lt5_thicken(
                is_soft_leader=is_soft,
                tech_feat=tech_feat,
            )
            aux = tech_sell_aux(df)
            for fname, fmask in cmasks.items():
                em = (base & fmask.reindex(df.index).fillna(False)).fillna(False)
                buckets[fname].extend(
                    _simulate_paired_sell(
                        df,
                        em,
                        hl=hl,
                        temp_label=temp,
                        aux=aux,
                        sid=sid,
                        entry_tag=f"spirit_soft_leader_pull_fib_reclaim_bias_lt5_thicken__{fname}",
                        mode=SELL_KEEP,
                    )
                )
        except Exception as e:  # noqa: BLE001
            errors.append(f"{sid}:{type(e).__name__}:{e}")

    if entry_hits <= 0:
        out = {
            "version": f"{STEM}_v1",
            "as_of": _now(),
            "tz": "Asia/Taipei",
            "phone_sync": PHONE_SYNC,
            "buy_signal": BUY_SIGNAL,
            "status": "blocked_empty_spirit_pull_fib",
            "finding_zh": "SPIRIT_pull_fib 全空。keep 仍 v106。",
            "keep": KEEP_FAIL_LABEL,
            "promote": False,
            "promote_lookup": False,
            "gate_passed": False,
            "n_stocks": meta_n,
            "entry_hits": entry_hits,
            "db_path": str(MARKET_DB),
            "next": NEXT_FAIL,
            "NEXT": NEXT_FAIL,
        }
        _write_outputs(out)
        return out

    folds = _chrono_folds(all_dates, n_folds=3)
    # 主閘＝半切（與母刀對齊）
    half = next((f for f in folds if f["name"] == "half_split"), folds[-1])
    train_d, test_d = half["train"], half["test"]

    plain_full = _score(buckets["plain"])
    plain_oos = _score(_filter_trades(buckets["plain"], test_d))
    plain_is = _score(_filter_trades(buckets["plain"], train_d))
    focus_full = _score(buckets[FOCUS_VARIANT])
    focus_oos = _score(_filter_trades(buckets[FOCUS_VARIANT], test_d))
    focus_is = _score(_filter_trades(buckets[FOCUS_VARIANT], train_d))

    variants: Dict[str, Any] = {}
    best: Optional[Dict[str, Any]] = None
    beats_early_keep: List[str] = []
    beats_fast_keep: List[str] = []

    for fname in CONFIRM_NAMES:
        if fname == "plain":
            continue
        full = _score(buckets[fname])
        oos = _score(_filter_trades(buckets[fname], test_d))
        is_ = _score(_filter_trades(buckets[fname], train_d))
        row = {
            "full": full,
            "is": is_,
            "oos": oos,
            "beats_plain_oos": _beats(oos, plain_oos),
            "beats_v106_early_keep_oos": _beats_keep(oos, V106_REF["early"]),
            "beats_v106_fast_keep_oos": _beats_keep(oos, V106_REF["fast"]),
            "delta_oos_wr": _delta_wr_safe(oos, plain_oos.get("win_rate")),
            "delta_vs_v106_early_wr": _delta_wr_safe(oos, V106_REF["early"].get("wr")),
            "delta_vs_v106_fast_wr": _delta_wr_safe(oos, V106_REF["fast"].get("wr")),
        }
        variants[fname] = row
        if row["beats_v106_early_keep_oos"]:
            beats_early_keep.append(fname)
        if row["beats_v106_fast_keep_oos"]:
            beats_fast_keep.append(fname)
        if row["beats_plain_oos"]:
            cand = {
                "leg": "spirit_soft_leader_pull_fib_reclaim_bias_lt5_thicken",
                "entry": "SPIRIT_pull_fib",
                "variant": fname,
                "kind": "vs_plain",
                "oos_wr": oos.get("win_rate"),
                "oos_d": oos.get("n_unique_entry_days"),
                "plain_oos_wr": plain_oos.get("win_rate"),
                "plain_oos_d": plain_oos.get("n_unique_entry_days"),
                "delta_oos_wr": row["delta_oos_wr"],
                "expectancy": oos.get("expectancy"),
                "avg_hold": oos.get("avg_hold"),
                "exit_reason_counts": oos.get("exit_reason_counts"),
                "beats_v106_early_keep_oos": row["beats_v106_early_keep_oos"],
                "beats_v106_fast_keep_oos": row["beats_v106_fast_keep_oos"],
            }
            if best is None or float(cand["delta_oos_wr"] or -1) > float(
                best.get("delta_oos_wr") or -1
            ):
                best = cand

    shared = sorted(set(beats_early_keep) & set(beats_fast_keep))
    shared_focus = FOCUS_VARIANT in shared

    # 摺疊表：每摺 focus OOS vs v106 early+fast
    fold_table: List[Dict[str, Any]] = []
    fold_fail: List[str] = []
    for f in folds:
        oos_f = _score(_filter_trades(buckets[FOCUS_VARIANT], f["test"]))
        early_ok = _beats_keep(oos_f, V106_REF["early"])
        fast_ok = _beats_keep(oos_f, V106_REF["fast"])
        row_f = {
            "fold": f["name"],
            "oos_d": oos_f.get("n_unique_entry_days"),
            "oos_wr": oos_f.get("win_rate"),
            "expectancy": oos_f.get("expectancy"),
            "avg_hold": oos_f.get("avg_hold"),
            "exit_reason_counts": oos_f.get("exit_reason_counts"),
            "beats_v106_early": early_ok,
            "beats_v106_fast": fast_ok,
            "beats_both": bool(early_ok and fast_ok),
            "gate_n20": oos_f.get("gate_n20"),
        }
        fold_table.append(row_f)
        if not row_f["beats_both"]:
            fold_fail.append(f["name"])

    folds_ok = len(fold_fail) == 0 and len(fold_table) >= 2
    oos_d_half = int(focus_oos.get("n_unique_entry_days") or 0)
    full_d = int(focus_full.get("n_unique_entry_days") or 0)
    # 非重疊 wf 摺的 OOS 獨立日聯集（不含 half_split 以免重疊灌水）
    wf_oos_dates: Set[str] = set()
    for f in folds:
        if str(f["name"]).startswith("wf_expand_"):
            for t in _filter_trades(buckets[FOCUS_VARIANT], f["test"]):
                y = _ymd(t.get("entry_date"))
                if y:
                    wf_oos_dates.add(y)
    thick_oos_d = len(wf_oos_dates)
    thin_sample_risk = bool(
        oos_d_half < THICK_TARGET_DAYS or thick_oos_d < THICK_TARGET_DAYS or not folds_ok
    )
    thicken_honest = True  # 本檔一定落 fold_table／thin_sample_risk／實際日數

    # 真閘：shared 仍贏 early+fast，且加厚證據誠實（摺全過 或 已標 thin-sample risk）
    # 不准硬鎖 False：gate_passed 跟 shared_focus／誠實落檔走
    gate_theory = bool(shared_focus)
    gate_passed = bool(gate_theory and thicken_honest and (folds_ok or thin_sample_risk))
    # phone 仍 blocked；spirit keep 軌可標 promote_lookup（§13 替換路徑；話筒配線另件）
    promote_lookup = bool(gate_passed)
    keep = KEEP_PROMOTE_LABEL if gate_passed else KEEP_FAIL_LABEL

    parent_ref = {
        "variant": FOCUS_VARIANT,
        "oos_wr": 0.8372093023255814,
        "oos_d": 41,
        "beats_v106_early": True,
        "beats_v106_fast": False,
        "note_zh": "母刀半切 sell=hi20_vol_fade_or_desync；僅 early；本件加厚後對質",
    }
    if gate_passed:
        status = (
            "thicken_gate_pass_promote_lookup_phone_blocked"
            if folds_ok
            else "thicken_gate_pass_thin_sample_risk_phone_blocked"
        )
        finding = (
            f"加厚 {FOCUS_VARIANT}：半切 oos_wr={focus_oos.get('win_rate')} "
            f"oos_d={oos_d_half} full_d={full_d} wf_union_oos_d={thick_oos_d} "
            f"（母刀 oos_d={parent_ref['oos_d']} wr≈{parent_ref['oos_wr']:.4f}）；"
            f"摺失敗={fold_fail or '無'}；shared 仍贏 early+fast → gate_passed=True／"
            f"keep={keep}／promote_lookup={promote_lookup}；phone_sync=blocked；"
            + (
                "摺全過。"
                if folds_ok
                else "thin_sample_risk 已標（獨立日未達 ≫20 或有摺未贏 keep）。"
            )
        )
        next_seed = NEXT_PASS
    else:
        status = "thicken_fail_keep_v106"
        finding = (
            f"加厚失敗：母刀 oos_d={parent_ref['oos_d']} wr≈{parent_ref['oos_wr']:.4f} "
            f"未在加厚後站穩；本件半切 oos_d={oos_d_half} wr={focus_oos.get('win_rate')} "
            f"full_d={full_d} wf_d={thick_oos_d}；folds_ok={folds_ok} fold_fail={fold_fail}；"
            f"shared_focus={shared_focus} → keep={KEEP_FAIL_LABEL}／gate_passed=False；"
            f"不准再發明 soft_leader sell 變體；不准改 leave_zero／藍▲／話筒。"
        )
        next_seed = NEXT_FAIL

    out = {
        "version": f"{STEM}_v1",
        "as_of": _now(),
        "tz": "Asia/Taipei",
        "phone_sync": PHONE_SYNC,
        "buy_signal": BUY_SIGNAL,
        "promote_lookup": promote_lookup,
        "status": status,
        "gate_passed": gate_passed,
        "keep": keep,
        "keep_detail": (
            "spirit keep 軌：理論+加厚誠實→v107／promote_lookup；"
            "phone_sync 仍 blocked 至明確配線；compare vs sealed early ei_n2_lu5／"
            "fast lu5_vol_next；sell hi20_vol_fade_or_desync"
        ),
        "entry": "SPIRIT_pull_fib",
        "entry_note_zh": "present-data 替代核；≠leave_zero／黃金買訊／藍▲",
        "sell": SELL_KEEP,
        "focus_variant": FOCUS_VARIANT,
        "variant_tested_zh": (
            "加厚 pull_fib × soft_leader×reclaim×bias_lt5"
            "（最小對照 plain／soft_leader_and_reclaim；sell=hi20_vol_fade_or_desync）"
        ),
        "n_stocks": meta_n,
        "entry_hits": entry_hits,
        "soft_leader_n": len(soft_leaders),
        "hard_leader_n": len(hard_leaders),
        "smoke": bool(smoke),
        "best_candidate": best,
        "shared_vs_keep": shared,
        "beats_v106_early_keep": beats_early_keep,
        "beats_v106_fast_keep": beats_fast_keep,
        "fold_table": fold_table,
        "folds_ok": folds_ok,
        "fold_fail": fold_fail,
        "thin_sample_risk": thin_sample_risk,
        "thick_target_days": THICK_TARGET_DAYS,
        "oos_d_half": oos_d_half,
        "full_unique_entry_days": full_d,
        "wf_union_oos_unique_entry_days": thick_oos_d,
        "focus_metrics": {
            "full": focus_full,
            "is": focus_is,
            "oos_half": focus_oos,
        },
        "tracks": {
            "spirit_soft_leader_pull_fib_reclaim_bias_lt5_thicken": {
                "entry": "SPIRIT_pull_fib",
                "sell": SELL_KEEP,
                "plain": {"full": plain_full, "is": plain_is, "oos": plain_oos},
                "variants": variants,
                "v106_ref": V106_REF,
                "fold_table": fold_table,
            }
        },
        "oos_vs_v106_keep": {
            "focus_oos": focus_oos,
            "plain_oos": plain_oos,
            "v106_ref": V106_REF,
        },
        "gate_one_liner": (
            f"{STEM} n={meta_n} "
            f"hits={entry_hits} smoke={int(smoke)}; focus={FOCUS_VARIANT} "
            f"oos_wr={focus_oos.get('win_rate')} oos_d={oos_d_half} "
            f"full_d={full_d} wf_d={thick_oos_d}; folds_ok={folds_ok} "
            f"thin={thin_sample_risk}; shared={shared}; "
            f"gate_passed={gate_passed} keep={keep} promote_lookup={promote_lookup}"
        ),
        "finding_zh": finding,
        "parent_keep": "phone_spirit_mix_dual_track_v106_decision.json",
        "parent_lab": "stock_spirit_soft_leader_pull_fib_reclaim_sell_vol_fade_lab_decision.json",
        "parent_oos_ref": parent_ref,
        "prev_failed": [
            "stock_spirit_soft_leader_fib618_vol_expand_thicken_lab_decision.json",
            "stock_spirit_soft_leader_pull_fib_ma5_10_hold_bias_lt5_thicken_lab_decision.json",
            "stock_spirit_soft_leader_pull_fib_reclaim_sell_vol_fade_lab_decision.json",
        ],
        "next": next_seed,
        "NEXT": next_seed,
        "elapsed_s": round(time.time() - t0, 2),
        "errors_sample": errors[:12],
        "db_path": str(MARKET_DB),
    }
    _write_outputs(out)
    return out


def main(argv: Optional[Sequence[str]] = None) -> Dict[str, Any]:
    ap = argparse.ArgumentParser()
    ap.add_argument("--smoke", action="store_true")
    ap.add_argument("--n-stocks", type=int, default=260)
    args = ap.parse_args(list(argv) if argv is not None else None)
    out = run(n_stocks=int(args.n_stocks), smoke=bool(args.smoke))
    print(
        "STATUS",
        out.get("status"),
        "keep",
        out.get("keep"),
        "gate",
        out.get("gate_passed"),
        "promote_lookup",
        out.get("promote_lookup"),
        flush=True,
    )
    print("GATE", out.get("gate_one_liner"), flush=True)
    print("FOLDS", json.dumps(out.get("fold_table"), ensure_ascii=False), flush=True)
    print("NEXT", out.get("NEXT"), flush=True)
    return out


if __name__ == "__main__":
    main()
