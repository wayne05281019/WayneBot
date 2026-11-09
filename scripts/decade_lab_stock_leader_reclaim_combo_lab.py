#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""個股 lab：v106 keep × leader_tag × reclaim_ma20 交叉確認（靜默對質）。

承接：
- stock_tech_confirm_lab：reclaim_ma20 對 plain 微正Δ、未贏 sealed keep
- stock_pair_exit_leg_confirm_lab：leader_tag 對 plain 正Δ、未贏 sealed keep

硬規則：
- 官方 OHLC／量／話筒龍頭表；不准假成本／浪級計分
- phone_sync=blocked；buy_signal=false；不准改 leave_zero／黃金／話筒
- 過閘：獨立開市日 n≥20 且 OOS 贏 sealed v106 keep；否則 keep=v106
- 勝率不准混浪形軌

用法：
  WAYNE_LAB_MIX_ROOT=/tmp/wayne-lab-mix \\
  WAYNE_DB_PATH=data/wayne_market.db \\
  python scripts/decade_lab_stock_leader_reclaim_combo_lab.py

  python scripts/decade_lab_stock_leader_reclaim_combo_lab.py --smoke
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
V106_REF = {
    "early": {"wr": 0.8269230769230769, "d": 51, "bars": 16.54901960784314},
    "fast": {"wr": 0.8545454545454545, "d": 54, "bars": 15.296296296296296},
}

CONFIRM_NAMES = (
    "plain",
    "leader_tag",
    "reclaim_ma20",
    "leader_and_reclaim_ma20",
    "leader_reclaim_and_near_low60_8",
    "leader_reclaim_and_vol_1p5",
)


def _now() -> str:
    return datetime.now(TAIPEI).isoformat(timespec="seconds")


def _ymd(raw: Any) -> str:
    t = str(raw or "").replace("-", "")[:8]
    return t if len(t) == 8 and t.isdigit() else ""


def combo_confirm_masks(
    *,
    is_leader: bool,
    tech_feat: pd.DataFrame,
    crash_feat: pd.DataFrame,
) -> Dict[str, pd.Series]:
    """交叉確認層：leader × reclaim（可選近60低／量）。不准浪級鍵。"""
    from scripts.decade_lab_stock_tech_confirm_lab import buy_confirm_masks
    from scripts.decade_lab_stock_pair_exit_leg_confirm_lab import confirm_masks

    tmasks = buy_confirm_masks(tech_feat)
    cmasks = confirm_masks(crash_feat)
    lead = cmasks["leader_tag"]
    reclaim = tmasks["reclaim_ma20"]
    near8 = cmasks["near_low60_8"]
    vol15 = tmasks["vol_gt_ma20_1p5"]
    idx = tech_feat.index
    # leader_tag 在非龍頭股全 False；這裡仍用 crash_feat 的 lead 列（內部已寫 is_leader）
    _ = is_leader  # 呼叫端已注入 crash_feat
    return {
        "plain": pd.Series(True, index=idx),
        "leader_tag": lead.reindex(idx).fillna(False),
        "reclaim_ma20": reclaim.reindex(idx).fillna(False),
        "leader_and_reclaim_ma20": (lead.reindex(idx).fillna(False) & reclaim.reindex(idx).fillna(False)),
        "leader_reclaim_and_near_low60_8": (
            lead.reindex(idx).fillna(False)
            & reclaim.reindex(idx).fillna(False)
            & near8.reindex(idx).fillna(False)
        ),
        "leader_reclaim_and_vol_1p5": (
            lead.reindex(idx).fillna(False)
            & reclaim.reindex(idx).fillna(False)
            & vol15.reindex(idx).fillna(False)
        ),
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


def _import_spirit_stack():
    from scripts.decade_lab_stock_pair_exit_leg_confirm_lab import (
        _import_spirit_stack as _pair_import,
        spirit_stack_available,
    )

    if not spirit_stack_available():
        raise RuntimeError("spirit stack missing")
    return _pair_import()


def spirit_stack_available() -> bool:
    try:
        from scripts.decade_lab_stock_pair_exit_leg_confirm_lab import (
            spirit_stack_available as _ok,
        )

        return bool(_ok())
    except Exception:
        return False


def _write_outputs(out: Dict[str, Any]) -> None:
    DOC.mkdir(parents=True, exist_ok=True)
    ART.mkdir(parents=True, exist_ok=True)
    latest = DOC / "stock_leader_reclaim_combo_lab_latest.json"
    decision = DOC / "stock_leader_reclaim_combo_lab_decision.json"
    seed = DOC / "stock_leader_reclaim_combo_lab_seed.json"
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
            }
        )
        seed.write_text(json.dumps(seed_obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    art = ART / "stock_leader_reclaim_combo_lab_decision.json"
    art.write_text(json.dumps(slim, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def run(*, n_stocks: int = 220, min_avg_turnover_k: float = 800_000.0, smoke: bool = False) -> Dict[str, Any]:
    from scripts.decade_lab_stock_pair_exit_leg_confirm_lab import (
        _simulate_paired_sell,
        crash_proxy_features,
        leader_self_sids,
        tech_sell_aux,
        align_pe_ffill,
        load_pe_by_sid,
    )
    from scripts.decade_lab_stock_tech_confirm_lab import tech_features

    t0 = time.time()
    if not spirit_stack_available():
        out = {
            "version": "stock_leader_reclaim_combo_lab_v1",
            "as_of": _now(),
            "tz": "Asia/Taipei",
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
    for sid in ("6442", "2383", "2330", "3017", "2308"):
        if sid not in symbols:
            symbols.append(sid)
    symbols = symbols[:n_use]

    _, mkt_raw = S["_twii_wave_pack"](entry_preset="A0_strict", score_threshold=40.0)
    buckets: Dict[str, Dict[str, List[Dict[str, Any]]]] = {
        c: {f: [] for f in CONFIRM_NAMES} for c in ("early", "fast")
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
            pe = align_pe_ffill(df, load_pe_by_sid(sid, MARKET_DB))
            is_lead = sid in leaders
            crash_feat = crash_proxy_features(df, pe=pe, is_leader=is_lead)
            tech_feat = tech_features(df)
            cmasks = combo_confirm_masks(
                is_leader=is_lead, tech_feat=tech_feat, crash_feat=crash_feat
            )
            aux = tech_sell_aux(df)
            early = masks[KEEP_EARLY].fillna(False)
            fast = masks[KEEP_FAST].fillna(False)
            for core_name, base in (("early", early), ("fast", fast)):
                for fname, fmask in cmasks.items():
                    em = (base & fmask.reindex(df.index).fillna(False)).fillna(False)
                    buckets[core_name][fname].extend(
                        _simulate_paired_sell(
                            df,
                            em,
                            hl=hl,
                            temp_label=temp,
                            aux=aux,
                            sid=sid,
                            entry_tag=f"combo_{core_name}__{fname}",
                            mode=SELL_KEEP,
                        )
                    )
        except Exception as e:  # noqa: BLE001
            errors.append(f"{sid}:{type(e).__name__}:{e}")

    train_d, test_d = _half_split_dates(all_dates)
    tracks: Dict[str, Any] = {}
    best: Optional[Dict[str, Any]] = None
    shared: List[str] = []

    for core_name in ("early", "fast"):
        plain_full = _score(buckets[core_name]["plain"])
        plain_oos = _score(_filter_trades(buckets[core_name]["plain"], test_d))
        plain_is = _score(_filter_trades(buckets[core_name]["plain"], train_d))
        variants = {}
        for fname in CONFIRM_NAMES:
            if fname == "plain":
                continue
            full = _score(buckets[core_name][fname])
            oos = _score(_filter_trades(buckets[core_name][fname], test_d))
            is_ = _score(_filter_trades(buckets[core_name][fname], train_d))
            row = {
                "full": full,
                "is": is_,
                "oos": oos,
                "beats_plain_oos": _beats(oos, plain_oos),
                "beats_v106_keep_oos": _beats_keep(oos, V106_REF[core_name]),
                "delta_oos_wr": _delta_wr_safe(oos, plain_oos.get("win_rate")),
                "delta_vs_v106_keep_wr": _delta_wr_safe(oos, V106_REF[core_name].get("wr")),
            }
            variants[fname] = row
            if row["beats_plain_oos"]:
                cand = {
                    "leg": "leader_reclaim_combo",
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
                if best is None or float(cand["delta_oos_wr"] or -1) > float(
                    best.get("delta_oos_wr") or -1
                ):
                    best = cand
        tracks[core_name] = {
            "entry": KEEP_EARLY if core_name == "early" else KEEP_FAST,
            "sell": SELL_KEEP,
            "plain": {"full": plain_full, "is": plain_is, "oos": plain_oos},
            "variants": variants,
            "v106_ref": V106_REF[core_name],
        }

    for fname in CONFIRM_NAMES:
        if fname == "plain":
            continue
        e = tracks["early"]["variants"].get(fname, {})
        f = tracks["fast"]["variants"].get(fname, {})
        if e.get("beats_v106_keep_oos") and f.get("beats_v106_keep_oos"):
            shared.append(fname)

    gate = bool(shared)
    promote = False  # 本件仍封；過閘才另 PR 談 phone
    status = "shared_beats_keep_but_phone_blocked" if gate else "plain_delta_only_keep_v106"
    finding = (
        f"leader×reclaim 交叉確認：最佳={best}；"
        + (
            f"共享變體 {shared[0]} 兩邊 OOS 贏 sealed keep → 理論過閘；本件仍封 keep=v106／phone blocked。"
            if gate
            else "未贏 sealed v106 keep → keep v106。不准改話筒。"
        )
    )
    out = {
        "version": "stock_leader_reclaim_combo_lab_v1",
        "as_of": _now(),
        "tz": "Asia/Taipei",
        "phone_sync": PHONE_SYNC,
        "buy_signal": BUY_SIGNAL,
        "promote_lookup": promote,
        "status": status,
        "gate_passed": gate and promote,
        "keep": "v106",
        "keep_detail": "early ei_n2_lu5／eg_bridge；fast lu5_vol_next；sell hi20_or_desync",
        "sell": SELL_KEEP,
        "variant_tested_zh": "v106 進場核 × leader_tag×reclaim_ma20 交叉（可選近60低／量1.5）",
        "n_stocks": meta_n,
        "smoke": bool(smoke),
        "best_candidate": best,
        "shared_vs_keep": shared,
        "tracks": tracks,
        "oos_vs_v106_keep": {
            "early_plain_oos": tracks["early"]["plain"]["oos"],
            "fast_plain_oos": tracks["fast"]["plain"]["oos"],
            "v106_ref": V106_REF,
        },
        "gate_one_liner": (
            f"stock_leader_reclaim_combo n={meta_n} smoke={int(smoke)}; "
            f"best={best}; shared={shared}; promote={promote}"
        ),
        "finding_zh": finding,
        "parent_keep": "phone_spirit_mix_dual_track_v106_decision.json",
        "prev_failed": [
            "stock_inst_filter_lab_decision.json",
            "stock_tech_confirm_lab_decision.json",
            "stock_pair_exit_leg_confirm_lab_decision.json",
        ],
        "next": (
            "若 gate 真過→同件再生下一鍵；否則換下一交叉（例 leader×vol_1p5×bias）"
            "；不准混浪形、不准改話筒"
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
    ap.add_argument("--n-stocks", type=int, default=220)
    args = ap.parse_args(list(argv) if argv is not None else None)
    return run(n_stocks=int(args.n_stocks), smoke=bool(args.smoke))


if __name__ == "__main__":
    main()
