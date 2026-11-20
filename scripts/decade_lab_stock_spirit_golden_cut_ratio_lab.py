#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""個股 lab：定義黃金切割率回撤位對質（靜默）。

使用者 2026-11-10：營收／EPS 刀後下一刀「以黃金切割率來算」。
只用已定義切割率 0.382／0.5／0.618／0.786（＝RETRACE_RATIOS），不准另發明。

進場核：WAVE_pullbase × BK_not_avoid（present-data）
確認變體：貼近各回撤切割位（±1.5%）／any／0382|0618／再疊 vol_expand
出場：hi20_or_desync
過閘：獨立開市日 n≥20 且 OOS 同時贏 sealed v106 early+fast；否則 keep=v106
phone_sync=blocked；buy_signal=false；不准改話筒／leave_zero

用法：
  WAYNE_DB_PATH=data/wayne_market.db \\
  python scripts/decade_lab_stock_spirit_golden_cut_ratio_lab.py

  python scripts/decade_lab_stock_spirit_golden_cut_ratio_lab.py --smoke
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
SELL_KEEP = "hi20_or_desync"
V106_REF = {
    "early": {"wr": 0.8269230769230769, "d": 51, "bars": 16.54901960784314},
    "fast": {"wr": 0.8545454545454545, "d": 54, "bars": 15.296296296296296},
}

CONFIRM_NAMES = (
    "plain",
    "near_0382",
    "near_0500",
    "near_0618",
    "near_0786",
    "near_any",
    "near_0382_or_0618",
    "near_0618_vol_expand",
    "near_0382_vol_expand",
    "near_0500_vol_expand",
    "near_0786_vol_expand",
)


def _now() -> str:
    return datetime.now(TAIPEI).isoformat(timespec="seconds")


def _ymd(raw: Any) -> str:
    t = str(raw or "").replace("-", "")[:8]
    return t if len(t) == 8 and t.isdigit() else ""


def spirit_pullbase_bk_entry_mask(df: pd.DataFrame, raw: pd.DataFrame) -> pd.Series:
    """進場核：pullbase × BK_not_avoid（切割率當確認層，不鎖死 0.618）。"""
    from scripts.decade_lab_hsiao_data_preprocessor import prepare_ohlcv
    from scripts.decade_lab_hsiao_quant_features import compute_hsiao_features
    from scripts.decade_lab_phone_extreme_hillclimb import _align_feat, _wave_hsiao_bank
    from scripts.decade_lab_phone_spirit_masks import build_spirit_masks
    from scripts.decade_lab_phone_wave_filter import _align_wave, _wave_frame, _wave_masks

    feat = _align_feat(df, compute_hsiao_features(prepare_ohlcv(raw)))
    wave = _align_wave(df, _wave_frame(raw))
    wmasks = _wave_masks(wave)
    bank = _wave_hsiao_bank(feat, wmasks, wave)
    spirit = build_spirit_masks(df, feat, wmasks=wmasks, bank=bank)
    pull = spirit.get("WAVE_pullbase", pd.Series(False, index=df.index))
    bk = spirit.get("BK_not_avoid", pd.Series(False, index=df.index))
    return (
        pull.reindex(df.index).fillna(False) & bk.reindex(df.index).fillna(False)
    )


def spirit_fib_ratio_masks(df: pd.DataFrame, raw: pd.DataFrame) -> Dict[str, pd.Series]:
    """回傳定義切割率近位遮罩（與 build_spirit_masks 同一套）。"""
    from scripts.decade_lab_hsiao_data_preprocessor import prepare_ohlcv
    from scripts.decade_lab_hsiao_quant_features import compute_hsiao_features
    from scripts.decade_lab_phone_extreme_hillclimb import _align_feat, _wave_hsiao_bank
    from scripts.decade_lab_phone_spirit_masks import RETRACE_RATIOS, build_spirit_masks
    from scripts.decade_lab_phone_wave_filter import _align_wave, _wave_frame, _wave_masks

    assert RETRACE_RATIOS == (0.382, 0.5, 0.618, 0.786)
    feat = _align_feat(df, compute_hsiao_features(prepare_ohlcv(raw)))
    wave = _align_wave(df, _wave_frame(raw))
    wmasks = _wave_masks(wave)
    bank = _wave_hsiao_bank(feat, wmasks, wave)
    spirit = build_spirit_masks(df, feat, wmasks=wmasks, bank=bank)
    idx = df.index
    out = {
        "near_0382": spirit["FIB_near_382"].reindex(idx).fillna(False),
        "near_0500": spirit["FIB_near_500"].reindex(idx).fillna(False),
        "near_0618": spirit["FIB_near_618"].reindex(idx).fillna(False),
        "near_0786": spirit["FIB_near_786"].reindex(idx).fillna(False),
        "near_any": spirit["FIB_near_any"].reindex(idx).fillna(False),
    }
    out["near_0382_or_0618"] = (out["near_0382"] | out["near_0618"]).fillna(False)
    return out


def confirm_masks_golden_cut(
    *,
    df: pd.DataFrame,
    raw: pd.DataFrame,
    tech_feat: pd.DataFrame,
) -> Dict[str, pd.Series]:
    from scripts.decade_lab_stock_spirit_soft_leader_fib618_vol_expand_lab import (
        vol_expand_mask,
    )

    idx = df.index
    fib = spirit_fib_ratio_masks(df, raw)
    vol15 = vol_expand_mask(tech_feat, mult=1.5).reindex(idx).fillna(False)
    return {
        "plain": pd.Series(True, index=idx),
        "near_0382": fib["near_0382"],
        "near_0500": fib["near_0500"],
        "near_0618": fib["near_0618"],
        "near_0786": fib["near_0786"],
        "near_any": fib["near_any"],
        "near_0382_or_0618": fib["near_0382_or_0618"],
        "near_0618_vol_expand": (fib["near_0618"] & vol15).fillna(False),
        "near_0382_vol_expand": (fib["near_0382"] & vol15).fillna(False),
        "near_0500_vol_expand": (fib["near_0500"] & vol15).fillna(False),
        "near_0786_vol_expand": (fib["near_0786"] & vol15).fillna(False),
    }


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


def _write_outputs(out: Dict[str, Any]) -> None:
    DOC.mkdir(parents=True, exist_ok=True)
    ART.mkdir(parents=True, exist_ok=True)
    latest = DOC / "stock_spirit_golden_cut_ratio_lab_latest.json"
    decision = DOC / "stock_spirit_golden_cut_ratio_lab_decision.json"
    seed = DOC / "stock_spirit_golden_cut_ratio_lab_seed.json"
    latest.write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    slim = {k: out[k] for k in out if k not in ("tracks", "errors_sample")}
    decision.write_text(json.dumps(slim, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    seed_obj = {
        "version": out.get("version"),
        "status": out.get("status"),
        "gate_passed": out.get("gate_passed"),
        "as_of": out.get("as_of"),
        "best_candidate": out.get("best_candidate"),
        "shared_vs_keep": out.get("shared_vs_keep"),
        "promote_lookup": out.get("promote_lookup"),
        "phone_sync": PHONE_SYNC,
        "buy_signal": BUY_SIGNAL,
        "next": out.get("next"),
        "note_zh": "定義黃金切割率 0.382／0.5／0.618／0.786 近位對質；不准另發明切割率",
    }
    seed.write_text(json.dumps(seed_obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (ART / "stock_spirit_golden_cut_ratio_lab_decision.json").write_text(
        json.dumps(slim, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def run(*, n_stocks: int = 260, min_avg_turnover_k: float = 800_000.0, smoke: bool = False) -> Dict[str, Any]:
    from scripts.decade_lab_chart_marks_stats import _normalize_ohlc
    from scripts.decade_lab_hsiao_universe import MUST_INCLUDE, load_stock_ohlcv, select_g_universe
    from scripts.decade_lab_phone_trade_confront import _build_hl_temp
    from scripts.decade_lab_stock_pair_exit_leg_confirm_lab import (
        _simulate_paired_sell,
        tech_sell_aux,
    )
    from scripts.decade_lab_stock_tech_confirm_lab import tech_features

    t0 = time.time()
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
    for sid in ("2330", "2317", "2454", "2383", "2308", "3037", "6669"):
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
            base = spirit_pullbase_bk_entry_mask(df, raw)
            entry_hits += int(base.sum())
            hl, temp = _build_hl_temp(df)
            tech_feat = tech_features(df)
            cmasks = confirm_masks_golden_cut(df=df, raw=raw, tech_feat=tech_feat)
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
                        entry_tag=f"spirit_golden_cut__{fname}",
                        mode=SELL_KEEP,
                    )
                )
        except Exception as e:  # noqa: BLE001
            errors.append(f"{sid}:{type(e).__name__}:{e}")

    if entry_hits <= 0 or meta_n <= 0:
        out = {
            "version": "stock_spirit_golden_cut_ratio_lab_v1",
            "as_of": _now(),
            "tz": "Asia/Taipei",
            "phone_sync": PHONE_SYNC,
            "buy_signal": BUY_SIGNAL,
            "status": "blocked_empty",
            "finding_zh": "pullbase×BK 全空。keep 仍 v106。不准改話筒。",
            "keep": "v106",
            "promote": False,
            "promote_lookup": False,
            "gate_passed": False,
            "n_stocks": meta_n,
            "entry_hits": entry_hits,
            "db_path": str(MARKET_DB),
        }
        _write_outputs(out)
        return out

    train_d, test_d = _half_split_dates(all_dates)
    plain_full = _score(buckets["plain"])
    plain_oos = _score(_filter_trades(buckets["plain"], test_d))
    plain_is = _score(_filter_trades(buckets["plain"], train_d))
    # 現況對照：同核＋near_0618（＝舊 SPIRIT_pull_fib618 形）
    fib618_oos = _score(_filter_trades(buckets["near_0618"], test_d))
    variants: Dict[str, Any] = {}
    best: Optional[Dict[str, Any]] = None
    beats_early_keep: List[str] = []
    beats_fast_keep: List[str] = []
    beats_fib618: List[str] = []

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
            "beats_fib0618_oos": _beats(oos, fib618_oos) if fname != "near_0618" else False,
            "beats_v106_early_keep_oos": _beats_keep(oos, V106_REF["early"]),
            "beats_v106_fast_keep_oos": _beats_keep(oos, V106_REF["fast"]),
            "delta_oos_wr": _delta_wr_safe(oos, plain_oos.get("win_rate")),
            "delta_vs_fib0618_wr": _delta_wr_safe(oos, fib618_oos.get("win_rate")),
            "delta_vs_v106_early_wr": _delta_wr_safe(oos, V106_REF["early"].get("wr")),
            "delta_vs_v106_fast_wr": _delta_wr_safe(oos, V106_REF["fast"].get("wr")),
        }
        variants[fname] = row
        if row["beats_v106_early_keep_oos"]:
            beats_early_keep.append(fname)
        if row["beats_v106_fast_keep_oos"]:
            beats_fast_keep.append(fname)
        if row["beats_fib0618_oos"]:
            beats_fib618.append(fname)
        if row["beats_plain_oos"]:
            cand = {
                "leg": "spirit_golden_cut_ratio_confirm",
                "entry": "WAVE_pullbase_x_BK_not_avoid",
                "variant": fname,
                "kind": "vs_plain",
                "oos_wr": oos.get("win_rate"),
                "oos_d": oos.get("n_unique_entry_days"),
                "plain_oos_wr": plain_oos.get("win_rate"),
                "plain_oos_d": plain_oos.get("n_unique_entry_days"),
                "delta_oos_wr": row["delta_oos_wr"],
                "beats_fib0618_oos": row["beats_fib0618_oos"],
                "beats_v106_early_keep_oos": row["beats_v106_early_keep_oos"],
                "beats_v106_fast_keep_oos": row["beats_v106_fast_keep_oos"],
            }
            if best is None or float(cand["delta_oos_wr"] or -1) > float(
                best.get("delta_oos_wr") or -1
            ):
                best = cand

    shared = sorted(set(beats_early_keep) & set(beats_fast_keep))
    gate_theory = bool(shared)
    promote = False
    status = (
        "shared_beats_keep_but_phone_blocked"
        if gate_theory
        else ("plain_delta_only_keep_v106" if best else "no_beat_keep_v106")
    )
    finding = (
        f"黃金切割率近位對質（0.382／0.5／0.618／0.786）：最佳={best}；"
        + (
            f"共享變體 {shared[0]} OOS 同時贏 early+fast → 理論過閘；"
            "仍 phone blocked／replace=false。不准另發明切割率。"
            if gate_theory
            else "未同時贏 sealed v106 keep → keep v106。不准改話筒。"
        )
    )
    out = {
        "version": "stock_spirit_golden_cut_ratio_lab_v1",
        "as_of": _now(),
        "tz": "Asia/Taipei",
        "phone_sync": PHONE_SYNC,
        "buy_signal": BUY_SIGNAL,
        "promote_lookup": promote,
        "status": status,
        "gate_passed": False,
        "keep": "v106",
        "keep_detail": "compare vs sealed early ei_n2_lu5／fast lu5_vol_next；sell hi20_or_desync",
        "entry": "WAVE_pullbase_x_BK_not_avoid",
        "entry_note_zh": "切割率當確認；near_0618≈舊 SPIRIT_pull_fib618；≠leave_zero／≠買訊",
        "sell": SELL_KEEP,
        "variant_tested_zh": "定義回撤切割 0.382／0.5／0.618／0.786 近位±1.5%＋vol_expand",
        "ratios_zh": "0.382／0.5／0.618／0.786（RETRACE_RATIOS；不准另發明）",
        "n_stocks": meta_n,
        "entry_hits": entry_hits,
        "smoke": bool(smoke),
        "best_candidate": best,
        "shared_vs_keep": shared,
        "beats_v106_early_keep": beats_early_keep,
        "beats_v106_fast_keep": beats_fast_keep,
        "beats_fib0618_oos": beats_fib618,
        "tracks": {
            "spirit_golden_cut_ratio": {
                "entry": "WAVE_pullbase_x_BK_not_avoid",
                "sell": SELL_KEEP,
                "plain": {"full": plain_full, "is": plain_is, "oos": plain_oos},
                "fib0618_oos": fib618_oos,
                "variants": variants,
                "v106_ref": V106_REF,
            }
        },
        "oos_vs_v106_keep": {
            "plain_oos": plain_oos,
            "fib0618_oos": fib618_oos,
            "v106_ref": V106_REF,
        },
        "gate_one_liner": (
            f"stock_spirit_golden_cut_ratio n={meta_n} hits={entry_hits} smoke={int(smoke)}; "
            f"best={best}; shared={shared}; promote={promote}"
        ),
        "finding_zh": finding,
        "parent_keep": "phone_spirit_mix_dual_track_v106_decision.json",
        "parent_prev_knife": "stock_eps_lead_proxy_lab（薄史無法對質）",
        "next": (
            "理論過閘仍 blocked；下一刀可疊 soft_leader／延伸 1.272／1.618 賣端；不准改話筒"
            if gate_theory
            else "未過閘；下一刀 soft_leader×最佳切割率 或 延伸目標賣端；不准另發明切割率、不准改話筒"
        ),
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
    print("STATUS", out.get("status"), "keep=v106", "gate", out.get("gate_passed"), flush=True)
    print("GATE", out.get("gate_one_liner"), flush=True)
    return out


if __name__ == "__main__":
    main()
