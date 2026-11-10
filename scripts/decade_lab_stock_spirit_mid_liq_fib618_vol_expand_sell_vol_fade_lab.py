"""個股 lab：SPIRIT_pull_fib618 × mid_liq_family × vol_expand × 賣端 hi20_vol_fade_or_desync。

承接 soft_leader×fib618×vol_expand×sell_vol_fade（plain delta 未過閘）與 mid_liq×pull_fib×reclaim。
本刀 mid_liq_family＝硬龍頭∪（族內跟漲∩宇宙），買端 vol_expand×reclaim，賣端 vol_fade，
試能否 n≥20 且同時贏 sealed v106 early+fast keep。

硬規則：
- 官方 OHLC／量／spirit／話筒族表；不准假成本／浪級計分
- phone_sync=blocked；buy_signal=false；不准改 leave_zero／黃金／話筒
- 過閘：獨立開市日 n≥20 且 OOS 贏 sealed v106 keep；否則 keep=v106／replace=false
- 勝率不准混浪形軌

用法：
  WAYNE_DB_PATH=data/wayne_market.db \
  python scripts/decade_lab_stock_spirit_mid_liq_fib618_vol_expand_sell_vol_fade_lab.py

  python scripts/decade_lab_stock_spirit_mid_liq_fib618_vol_expand_sell_vol_fade_lab.py --smoke
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
SELL_KEEP = "hi20_vol_fade_or_desync"
V106_REF = {
    "early": {"wr": 0.8269230769230769, "d": 51, "bars": 16.54901960784314},
    "fast": {"wr": 0.8545454545454545, "d": 54, "bars": 15.296296296296296},
}

CONFIRM_NAMES = (
    "plain",
    "vol_expand_1p5",
    "vol_expand_2",
    "mid_liq_and_vol_expand",
    "mid_liq_vol_expand_reclaim",
    "mid_liq_vol_expand_2_reclaim",
    "mid_liq_vol_expand_reclaim_bias_lt8",
    "mid_liq_vol_expand_reclaim_near_low60_8",
    "hard_leader_vol_expand_reclaim",
    "reclaim_and_vol_expand",
)


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


def mid_liq_family_sids(universe_sids: Sequence[str], *, hard: Set[str], soft: Set[str]) -> Set[str]:
    from scripts.decade_lab_stock_spirit_mid_liq_family_pull_fib_reclaim_lab import (
        mid_liq_family_sids as _mid,
    )

    return _mid(universe_sids, hard=hard, soft=soft)


def spirit_pull_fib618_entry_mask(df: pd.DataFrame, raw: pd.DataFrame) -> pd.Series:
    from scripts.decade_lab_stock_spirit_fib618_reclaim_lab import (
        spirit_pull_fib618_entry_mask as _mask,
    )

    return _mask(df, raw)


def vol_expand_mask(tech_feat: pd.DataFrame, *, mult: float = 1.5) -> pd.Series:
    """當日量 > 量均20×mult（官方柱可重述）；缺量／均量＝False。"""
    from scripts.decade_lab_stock_tech_confirm_lab import buy_confirm_masks

    tmasks = buy_confirm_masks(tech_feat)
    key = "vol_gt_ma20_2" if float(mult) >= 2.0 else "vol_gt_ma20_1p5"
    return tmasks[key].reindex(tech_feat.index).fillna(False)


def confirm_masks_mid_liq_fib618_vol_expand(
    *,
    is_mid_liq: bool,
    is_hard_leader: bool,
    tech_feat: pd.DataFrame,
    crash_feat: pd.DataFrame,
) -> Dict[str, pd.Series]:
    """mid_liq × fib618 × vol_expand × reclaim／bias／近60低；不准浪級鍵。"""
    from scripts.decade_lab_stock_pair_exit_leg_confirm_lab import confirm_masks
    from scripts.decade_lab_stock_tech_confirm_lab import buy_confirm_masks

    tmasks = buy_confirm_masks(tech_feat)
    cmasks = confirm_masks(crash_feat)
    idx = tech_feat.index
    reclaim = tmasks["reclaim_ma20"].reindex(idx).fillna(False)
    bias8 = tmasks["bias20_lt8"].reindex(idx).fillna(False)
    near8 = cmasks["near_low60_8"].reindex(idx).fillna(False)
    vol15 = vol_expand_mask(tech_feat, mult=1.5).reindex(idx).fillna(False)
    vol2 = vol_expand_mask(tech_feat, mult=2.0).reindex(idx).fillna(False)
    mid = pd.Series(bool(is_mid_liq), index=idx)
    hard = pd.Series(bool(is_hard_leader), index=idx)
    return {
        "plain": pd.Series(True, index=idx),
        "vol_expand_1p5": vol15,
        "vol_expand_2": vol2,
        "mid_liq_and_vol_expand": (mid & vol15).fillna(False),
        "mid_liq_vol_expand_reclaim": (mid & vol15 & reclaim).fillna(False),
        "mid_liq_vol_expand_2_reclaim": (mid & vol2 & reclaim).fillna(False),
        "mid_liq_vol_expand_reclaim_bias_lt8": (mid & vol15 & reclaim & bias8).fillna(
            False
        ),
        "mid_liq_vol_expand_reclaim_near_low60_8": (
            mid & vol15 & reclaim & near8
        ).fillna(False),
        "hard_leader_vol_expand_reclaim": (hard & vol15 & reclaim).fillna(False),
        "reclaim_and_vol_expand": (reclaim & vol15).fillna(False),
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
    latest = DOC / "stock_spirit_mid_liq_fib618_vol_expand_sell_vol_fade_lab_latest.json"
    decision = DOC / "stock_spirit_mid_liq_fib618_vol_expand_sell_vol_fade_lab_decision.json"
    seed = DOC / "stock_spirit_mid_liq_fib618_vol_expand_sell_vol_fade_lab_seed.json"
    latest.write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    slim = {k: out[k] for k in out if k not in ("tracks", "errors_sample")}
    decision.write_text(json.dumps(slim, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if seed.exists():
        try:
            seed_obj = json.loads(seed.read_text(encoding="utf-8"))
        except Exception:
            seed_obj = {}
        seed_obj.update(
            {
                "status": out.get("status"),
                "gate_passed": out.get("gate_passed"),
                "as_of": out.get("as_of"),
                "best_candidate": out.get("best_candidate"),
                "shared_vs_keep": out.get("shared_vs_keep"),
                "promote_lookup": out.get("promote_lookup"),
                "next": out.get("next"),
            }
        )
        seed.write_text(json.dumps(seed_obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (ART / "stock_spirit_mid_liq_fib618_vol_expand_sell_vol_fade_lab_decision.json").write_text(
        json.dumps(slim, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def run(*, n_stocks: int = 260, min_avg_turnover_k: float = 800_000.0, smoke: bool = False) -> Dict[str, Any]:
    from scripts.decade_lab_chart_marks_stats import _normalize_ohlc
    from scripts.decade_lab_hsiao_universe import MUST_INCLUDE, load_stock_ohlcv, select_g_universe
    from scripts.decade_lab_phone_trade_confront import _build_hl_temp
    from scripts.decade_lab_stock_pair_exit_leg_confirm_lab import (
        _simulate_paired_sell,
        align_pe_ffill,
        crash_proxy_features,
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
    mid_liq = mid_liq_family_sids(symbols, hard=hard_leaders, soft=soft_leaders)

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
            base = spirit_pull_fib618_entry_mask(df, raw)
            entry_hits += int(base.sum())
            hl, temp = _build_hl_temp(df)
            pe = align_pe_ffill(df, load_pe_by_sid(sid, MARKET_DB))
            is_hard = sid in hard_leaders
            is_mid = sid in mid_liq
            crash_feat = crash_proxy_features(df, pe=pe, is_leader=is_hard)
            tech_feat = tech_features(df)
            cmasks = confirm_masks_mid_liq_fib618_vol_expand(
                is_mid_liq=is_mid,
                is_hard_leader=is_hard,
                tech_feat=tech_feat,
                crash_feat=crash_feat,
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
                        entry_tag=f"spirit_mid_liq_fib618_vol_expand_svf__{fname}",
                        mode=SELL_KEEP,
                    )
                )
        except Exception as e:  # noqa: BLE001
            errors.append(f"{sid}:{type(e).__name__}:{e}")

    if entry_hits <= 0:
        out = {
            "version": "stock_spirit_mid_liq_fib618_vol_expand_sell_vol_fade_lab_v1",
            "as_of": _now(),
            "tz": "Asia/Taipei",
            "phone_sync": PHONE_SYNC,
            "buy_signal": BUY_SIGNAL,
            "status": "blocked_empty_fib618",
            "finding_zh": "SPIRIT_pull_fib618 全空。keep 仍 v106。",
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
                "leg": "spirit_mid_liq_fib618_vol_expand_sell_vol_fade_confirm",
                "entry": "SPIRIT_pull_fib618",
                "variant": fname,
                "kind": "vs_plain",
                "oos_wr": oos.get("win_rate"),
                "oos_d": oos.get("n_unique_entry_days"),
                "plain_oos_wr": plain_oos.get("win_rate"),
                "plain_oos_d": plain_oos.get("n_unique_entry_days"),
                "delta_oos_wr": row["delta_oos_wr"],
                "beats_v106_early_keep_oos": row["beats_v106_early_keep_oos"],
                "beats_v106_fast_keep_oos": row["beats_v106_fast_keep_oos"],
            }
            if best is None or float(cand["delta_oos_wr"] or -1) > float(
                best.get("delta_oos_wr") or -1
            ):
                best = cand

    shared = sorted(set(beats_early_keep) & set(beats_fast_keep))
    gate_theory = bool(shared)
    # 硬鎖：本件不准 promote；過閘也只記理論，replace=false／phone blocked
    promote = False
    status = (
        "shared_beats_keep_but_phone_blocked"
        if gate_theory
        else ("plain_delta_only_keep_v106" if best else "no_beat_keep_v106")
    )
    finding = (
        f"fib618×mid_liq×vol_expand×sell_vol_fade：最佳={best}；"
        + (
            f"共享變體 {shared[0]} OOS 同時贏 early+fast sealed keep → 理論過閘；"
            "本件仍封 keep=v106／replace=false／phone blocked。"
            if gate_theory
            else "未同時贏 sealed v106 keep → keep v106。不准改話筒。"
        )
    )
    next_seed = (
        "mid_liq×fib618×vol_expand×sell_vol_fade×ma60_hold"
        if gate_theory
        else "mid_liq×fib618×vol_expand×sell_vol_fade×bias_lt5"
    )
    alt_seed = "soft_leader×fib618×vol_expand×sell_desync_mfe8"
    out = {
        "version": "stock_spirit_mid_liq_fib618_vol_expand_sell_vol_fade_lab_v1",
        "as_of": _now(),
        "tz": "Asia/Taipei",
        "phone_sync": PHONE_SYNC,
        "buy_signal": BUY_SIGNAL,
        "promote_lookup": promote,
        "status": status,
        "gate_passed": False,  # replace=false until explicit promote after clear win
        "keep": "v106",
        "keep_detail": "compare vs sealed early ei_n2_lu5／fast lu5_vol_next；sell hi20_vol_fade_or_desync",
        "entry": "SPIRIT_pull_fib618",
        "entry_note_zh": "present-data 替代核；≠sealed keep；≠leave_zero／黃金買訊",
        "sell": SELL_KEEP,
        "variant_tested_zh": "fib618 × mid_liq×vol_expand×reclaim；sell=hi20_vol_fade_or_desync",
        "n_stocks": meta_n,
        "entry_hits": entry_hits,
        "mid_liq_n": len(mid_liq),
        "soft_leader_n": len(soft_leaders),
        "hard_leader_n": len(hard_leaders),
        "smoke": bool(smoke),
        "best_candidate": best,
        "shared_vs_keep": shared,
        "beats_v106_early_keep": beats_early_keep,
        "beats_v106_fast_keep": beats_fast_keep,
        "tracks": {
            "spirit_mid_liq_fib618_vol_expand_sell_vol_fade": {
                "entry": "SPIRIT_pull_fib618",
                "sell": SELL_KEEP,
                "plain": {"full": plain_full, "is": plain_is, "oos": plain_oos},
                "variants": variants,
                "v106_ref": V106_REF,
            }
        },
        "oos_vs_v106_keep": {
            "plain_oos": plain_oos,
            "v106_ref": V106_REF,
        },
        "gate_one_liner": (
            f"stock_spirit_mid_liq_fib618_vol_expand_sell_vol_fade n={meta_n} hits={entry_hits} "
            f"smoke={int(smoke)}; best={best}; shared={shared}; promote={promote}"
        ),
        "finding_zh": finding,
        "parent_keep": "phone_spirit_mix_dual_track_v106_decision.json",
        "prev_failed": [
            "stock_spirit_soft_leader_fib618_vol_expand_sell_vol_fade_lab_decision.json",
            "stock_spirit_soft_leader_fib618_vol_expand_svf_bias_lt5_lab_decision.json",
            "stock_spirit_mid_liq_family_pull_fib_reclaim_lab_decision.json",
        ],
        "next": (
            (
                f"理論過閘但 phone blocked／replace=false；下一刀 {next_seed} 再生；"
                f"備選 {alt_seed}；不准改話筒"
            )
            if gate_theory
            else (
                f"未過閘；下一刀 {next_seed}；備選 {alt_seed}；不准混浪形、不准改話筒"
            )
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
