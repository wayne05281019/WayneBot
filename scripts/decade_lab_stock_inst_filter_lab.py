#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""個股 lab：v106 keep 進場 × 三大法人股數／市場淨額過濾（靜默對質）。

規則（硬）：
- 只用官方股數淨額（daily_quotes foreign/trust/dealer_net）與 TWSE BFI82U 市場金額淨額
- 不准發明外資／投信成本
- phone_sync=blocked；buy_signal=false；不准改 leave_zero／黃金／話筒
- 賣出固定 hi20_or_desync（與 v106 keep 同）
- 過濾＝訊號日收盤後條件（隔日開進場；非當沖）
- 過閘才談替換：獨立開市日 n≥20 且贏 CURRENT keep；否則 keep=v106
- 勝率不准混浪形軌

用法：
  WAYNE_LAB_MIX_ROOT=/tmp/wayne-lab-mix \\
  WAYNE_DB_PATH=data/wayne_market.db \\
  python scripts/decade_lab_stock_inst_filter_lab.py

  python scripts/decade_lab_stock_inst_filter_lab.py --smoke
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
SELL_MODE = "hi20_or_desync"
# v106 sealed reference (early U220 / fast U250); lab compares OOS vs plain same-run baseline
V106_REF = {
    "early": {"wr": 0.8269230769230769, "d": 51, "bars": 16.54901960784314},
    "fast": {"wr": 0.8545454545454545, "d": 54, "bars": 15.296296296296296},
}


def _now() -> str:
    return datetime.now(TAIPEI).isoformat(timespec="seconds")


def _ymd(raw: Any) -> str:
    t = str(raw or "").replace("-", "")[:8]
    return t if len(t) == 8 and t.isdigit() else ""


def load_market_bfi(db_path: Path = MARKET_DB) -> Dict[str, Dict[str, float]]:
    """TWSE BFI82U 市場三大法人買賣金額淨額（億）；非成本。"""
    out: Dict[str, Dict[str, float]] = {}
    if not db_path.is_file():
        return out
    conn = sqlite3.connect(str(db_path), timeout=30.0)
    try:
        rows = conn.execute(
            """
            SELECT date, foreign_net_yi, trust_net_yi, dealer_net_yi, three_net_yi
            FROM market_inst_bfi_daily
            """
        ).fetchall()
    except sqlite3.Error:
        conn.close()
        return out
    conn.close()
    for d, f, t, dlr, th in rows:
        day = _ymd(d)
        if not day:
            continue
        out[day] = {
            "foreign_yi": float(f or 0.0),
            "trust_yi": float(t or 0.0),
            "dealer_yi": float(dlr or 0.0),
            "three_yi": float(th or 0.0),
        }
    return out


def load_stock_inst_nets(sid: str, db_path: Path = MARKET_DB) -> Dict[str, Dict[str, float]]:
    """個股官方買賣超股數（張／股數欄；非成本）。缺＝不進過濾分子。"""
    out: Dict[str, Dict[str, float]] = {}
    if not db_path.is_file():
        return out
    conn = sqlite3.connect(str(db_path), timeout=30.0)
    try:
        rows = conn.execute(
            """
            SELECT REPLACE(CAST(date AS TEXT),'-',''),
                   foreign_net, trust_net, dealer_net
            FROM daily_quotes
            WHERE stock_id=?
            ORDER BY 1
            """,
            (str(sid),),
        ).fetchall()
    except sqlite3.Error:
        conn.close()
        return out
    conn.close()
    for d, f, t, dlr in rows:
        day = _ymd(d)
        if not day:
            continue
        # NULL 三欄都缺＝無官方法人列；0 仍算有列
        if f is None and t is None and dlr is None:
            continue
        ff = float(f or 0.0)
        tt = float(t or 0.0)
        dd = float(dlr or 0.0)
        out[day] = {
            "foreign": ff,
            "trust": tt,
            "dealer": dd,
            "three": ff + tt + dd,
            "has_row": 1.0,
        }
    return out


def align_stock_inst(df: pd.DataFrame, nets: Dict[str, Dict[str, float]]) -> pd.DataFrame:
    """對齊日 K；無官方列的日子 has_row=0。"""
    dates = df["date"].astype(str).map(_ymd)
    rows = []
    for d in dates:
        r = nets.get(d) or {}
        rows.append(
            {
                "foreign": float(r.get("foreign", 0.0)),
                "trust": float(r.get("trust", 0.0)),
                "dealer": float(r.get("dealer", 0.0)),
                "three": float(r.get("three", 0.0)),
                "has_row": float(r.get("has_row", 0.0)),
            }
        )
    return pd.DataFrame(rows, index=df.index)


def align_market_bfi(df: pd.DataFrame, bfi: Dict[str, Dict[str, float]]) -> pd.DataFrame:
    dates = df["date"].astype(str).map(_ymd)
    rows = []
    for d in dates:
        r = bfi.get(d) or {}
        rows.append(
            {
                "foreign_yi": float(r.get("foreign_yi", 0.0)),
                "trust_yi": float(r.get("trust_yi", 0.0)),
                "dealer_yi": float(r.get("dealer_yi", 0.0)),
                "three_yi": float(r.get("three_yi", 0.0)),
                "has_bfi": 1.0 if d in bfi else 0.0,
            }
        )
    return pd.DataFrame(rows, index=df.index)


def inst_filter_masks(
    stock_i: pd.DataFrame,
    mkt_i: pd.DataFrame,
) -> Dict[str, pd.Series]:
    """訊號日（收盤後可知）法人條件；不含成本欄。

    stock_* 只在 has_row 日生效；mkt_* 只在 has_bfi 日生效。
    """
    has_s = stock_i["has_row"].astype(float) > 0
    has_m = mkt_i["has_bfi"].astype(float) > 0
    s3 = stock_i["three"].astype(float)
    sf = stock_i["foreign"].astype(float)
    st = stock_i["trust"].astype(float)
    m3 = mkt_i["three_yi"].astype(float)
    mf = mkt_i["foreign_yi"].astype(float)
    mt = mkt_i["trust_yi"].astype(float)

    return {
        "plain": pd.Series(True, index=stock_i.index),
        # 個股股數淨額（T86 類欄）
        "stock_three_gt0": (has_s & (s3 > 0)).fillna(False),
        "stock_foreign_gt0": (has_s & (sf > 0)).fillna(False),
        "stock_ft_both_gt0": (has_s & (sf > 0) & (st > 0)).fillna(False),
        # 市場 BFI82U 金額淨額（億）
        "mkt_three_gt0": (has_m & (m3 > 0)).fillna(False),
        "mkt_foreign_gt0": (has_m & (mf > 0)).fillna(False),
        "mkt_ft_both_gt0": (has_m & (mf > 0) & (mt > 0)).fillna(False),
        # 交叉：個股三大買超 × 市場三大買超
        "stock_three_x_mkt_three": (has_s & has_m & (s3 > 0) & (m3 > 0)).fillna(False),
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
        "win_ge_keep_hint": bool(np.isfinite(win) and win >= 0.80),
    }


def _beats(candidate: Dict[str, Any], baseline: Dict[str, Any]) -> bool:
    """相對同跑對照：n≥20 且 wr 嚴格較高（只作過濾有無用的 Δ，不是替換閘）。"""
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
    """替換閘：獨立進場日 n≥20 且 wr 嚴格贏 CURRENT keep（v106 sealed）。"""
    cd = int(candidate.get("n_unique_entry_days") or 0)
    cw = candidate.get("win_rate")
    kw = keep_ref.get("wr")
    if cd < MIN_N_DAYS or cw is None or kw is None:
        return False
    try:
        return float(cw) > float(kw)
    except (TypeError, ValueError):
        return False


def _import_spirit_stack():
    """需要 spirit／hsiao 堆（通常在 WAYNE_LAB_MIX_ROOT）。"""
    from scripts.decade_lab_chart_marks_stats import _normalize_ohlc
    from scripts.decade_lab_hsiao_universe import MUST_INCLUDE, load_stock_ohlcv, select_g_universe
    from scripts.decade_lab_phone_market_wave_sync import _stock_wave_events, _twii_wave_pack
    from scripts.decade_lab_phone_relhigh_sell import _simulate_relhigh
    from scripts.decade_lab_phone_spirit_mix_track_oos_v107 import _champ_masks
    from scripts.decade_lab_phone_trade_confront import _build_hl_temp

    return {
        "_normalize_ohlc": _normalize_ohlc,
        "MUST_INCLUDE": MUST_INCLUDE,
        "load_stock_ohlcv": load_stock_ohlcv,
        "select_g_universe": select_g_universe,
        "_stock_wave_events": _stock_wave_events,
        "_twii_wave_pack": _twii_wave_pack,
        "_simulate_relhigh": _simulate_relhigh,
        "_champ_masks": _champ_masks,
        "_build_hl_temp": _build_hl_temp,
    }


def spirit_stack_available() -> bool:
    try:
        _import_spirit_stack()
        return True
    except Exception:
        return False


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
            "version": "stock_inst_filter_lab_v1",
            "as_of": _now(),
            "phone_sync": PHONE_SYNC,
            "buy_signal": BUY_SIGNAL,
            "status": "blocked_missing_spirit_stack",
            "finding_zh": "本機缺 spirit／v106 核依賴（masks／relhigh／hsiao）。請設 WAYNE_LAB_MIX_ROOT 指向含 decade_lab_phone_spirit_* 的工作樹再跑。keep 仍 v106。",
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
    bfi = load_market_bfi(MARKET_DB)

    # track → filter → trades
    cores = ("early", "fast")
    filter_names = (
        "plain",
        "stock_three_gt0",
        "stock_foreign_gt0",
        "stock_ft_both_gt0",
        "mkt_three_gt0",
        "mkt_foreign_gt0",
        "mkt_ft_both_gt0",
        "stock_three_x_mkt_three",
    )
    buckets: Dict[str, Dict[str, List[Dict[str, Any]]]] = {
        c: {f: [] for f in filter_names} for c in cores
    }
    all_dates: List[str] = []
    errors: List[str] = []
    meta_n = 0
    stock_inst_days = 0
    stock_inst_nz = 0

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
            ev = S["_stock_wave_events"](raw, df)
            wave_top = (
                ev.get("LAB_W1_TOP") | ev.get("LAB_W3_TOP") | ev.get("LAB_SELL_W5_TOP")
            ).fillna(False)

            stock_i = align_stock_inst(df, load_stock_inst_nets(sid, MARKET_DB))
            mkt_i = align_market_bfi(df, bfi)
            stock_inst_days += int((stock_i["has_row"] > 0).sum())
            stock_inst_nz += int(((stock_i["has_row"] > 0) & (stock_i["three"] != 0)).sum())
            fmasks = inst_filter_masks(stock_i, mkt_i)

            early = masks[KEEP_EARLY].fillna(False)
            fast = masks[KEEP_FAST].fillna(False)
            for core_name, base in (("early", early), ("fast", fast)):
                for fname, fmask in fmasks.items():
                    em = (base & fmask.reindex(df.index).fillna(False)).fillna(False)
                    buckets[core_name][fname].extend(
                        S["_simulate_relhigh"](
                            df,
                            em,
                            hl=hl,
                            temp_label=temp,
                            sid=sid,
                            entry_tag=f"{core_name}__{fname}",
                            wave_top=wave_top,
                            mode=SELL_MODE,
                        )
                    )
        except Exception as e:  # noqa: BLE001
            errors.append(f"{sid}:{type(e).__name__}:{e}")

    train_d, test_d = _half_split_dates(all_dates)
    tracks: Dict[str, Any] = {}
    best: Optional[Dict[str, Any]] = None

    for core_name in cores:
        plain_full = _score(buckets[core_name]["plain"])
        plain_oos = _score(_filter_trades(buckets[core_name]["plain"], test_d))
        plain_is = _score(_filter_trades(buckets[core_name]["plain"], train_d))
        variants = {}
        for fname in filter_names:
            if fname == "plain":
                continue
            full = _score(buckets[core_name][fname])
            oos = _score(_filter_trades(buckets[core_name][fname], test_d))
            is_ = _score(_filter_trades(buckets[core_name][fname], train_d))
            beat_oos = _beats(oos, plain_oos)
            beat_full = _beats(full, plain_full)
            beat_keep = _beats_keep(oos, V106_REF[core_name])
            row = {
                "full": full,
                "is": is_,
                "oos": oos,
                "beats_plain_oos": beat_oos,
                "beats_plain_full": beat_full,
                "beats_v106_keep_oos": beat_keep,
                "delta_oos_wr": (
                    None
                    if oos.get("win_rate") is None or plain_oos.get("win_rate") is None
                    else float(oos["win_rate"]) - float(plain_oos["win_rate"])
                ),
                "delta_vs_v106_keep_wr": (
                    None
                    if oos.get("win_rate") is None
                    else float(oos["win_rate"]) - float(V106_REF[core_name]["wr"])
                ),
                "delta_oos_d": int(oos.get("n_unique_entry_days") or 0)
                - int(plain_oos.get("n_unique_entry_days") or 0),
            }
            variants[fname] = row
            if beat_oos:
                cand = {
                    "core": core_name,
                    "filter": fname,
                    "kind": "vs_plain",
                    "oos_wr": oos.get("win_rate"),
                    "oos_d": oos.get("n_unique_entry_days"),
                    "plain_oos_wr": plain_oos.get("win_rate"),
                    "plain_oos_d": plain_oos.get("n_unique_entry_days"),
                    "delta_oos_wr": row["delta_oos_wr"],
                    "beats_v106_keep_oos": beat_keep,
                }
                if best is None or float(cand["delta_oos_wr"] or -1) > float(
                    best.get("delta_oos_wr") or -1
                ):
                    best = cand
        tracks[core_name] = {
            "entry": KEEP_EARLY if core_name == "early" else KEEP_FAST,
            "sell": SELL_MODE,
            "plain": {"full": plain_full, "is": plain_is, "oos": plain_oos},
            "variants": variants,
            "v106_ref": V106_REF[core_name],
        }

    # 替換閘：同一 filter 在 early＋fast 兩邊 OOS 都贏 sealed v106 keep（n≥20）
    shared_keep: List[str] = []
    for fname in tracks["early"]["variants"]:
        if tracks["early"]["variants"][fname].get("beats_v106_keep_oos") and tracks[
            "fast"
        ]["variants"].get(fname, {}).get("beats_v106_keep_oos"):
            shared_keep.append(fname)
    both_ok = bool(shared_keep)
    if both_ok:
        best = {
            "core": "both",
            "filter": shared_keep[0],
            "shared_filters": shared_keep,
            "kind": "vs_v106_keep",
            "early_oos": tracks["early"]["variants"][shared_keep[0]]["oos"],
            "fast_oos": tracks["fast"]["variants"][shared_keep[0]]["oos"],
        }

    plain_edge = bool(best is not None and best.get("kind") == "vs_plain")
    status = (
        "gate_pass_vs_v106_keep"
        if both_ok
        else (
            "plain_delta_only_keep_v106"
            if plain_edge
            else "no_beat_keep_v106"
        )
    )
    if smoke:
        status = "smoke_" + status

    gate = (
        f"stock_inst_filter_lab n={meta_n} smoke={int(smoke)}; "
        f"early_plain_oos_wr={tracks['early']['plain']['oos'].get('win_rate')} "
        f"d={tracks['early']['plain']['oos'].get('n_unique_entry_days')}; "
        f"fast_plain_oos_wr={tracks['fast']['plain']['oos'].get('win_rate')} "
        f"d={tracks['fast']['plain']['oos'].get('n_unique_entry_days')}; "
        f"best={best}; promote={both_ok}"
    )

    finding = (
        "法人過濾（股數／市場淨額，無成本）："
        + (
            f"共享過濾 {best.get('filter')} 兩邊 OOS 都贏 sealed v106 keep → 理論過閘，本件仍封 keep=v106／phone blocked（需另令才換）。"
            if both_ok
            else (
                f"相對同跑 plain 有 Δ（{best}），但未贏 sealed v106 keep → keep v106。"
                if plain_edge
                else "各過濾未贏 sealed v106 keep（或 n<20）→ keep v106。"
            )
        )
        + f" 個股法人列覆蓋 bars≈{stock_inst_days}（非零≈{stock_inst_nz}）；BFI 日數={len(bfi)}。"
    )

    out: Dict[str, Any] = {
        "version": "stock_inst_filter_lab_v1",
        "as_of": _now(),
        "tz": "Asia/Taipei",
        "phone_sync": PHONE_SYNC,
        "buy_signal": BUY_SIGNAL,
        "promote_lookup": False,
        "status": status,
        "gate_passed": bool(both_ok),
        "keep": "v106",
        "keep_detail": (
            "early ei_n2_lu5／eg_bridge；fast lu5_vol_next；sell hi20_or_desync"
        ),
        "sell": SELL_MODE,
        "filter_kind_zh": "訊號日收盤後法人條件→隔日開進場；非當沖",
        "data_sources": {
            "stock_share_nets": "daily_quotes.foreign_net/trust_net/dealer_net（股數，非成本）",
            "market_amount_nets": "market_inst_bfi_daily BFI82U（億，非成本）",
        },
        "n_stocks": meta_n,
        "smoke": smoke,
        "bfi_days": len(bfi),
        "stock_inst_bars": stock_inst_days,
        "stock_inst_nz_bars": stock_inst_nz,
        "tracks": tracks,
        "best_candidate": best,
        "gate_one_liner": gate,
        "finding_zh": finding,
        "elapsed_s": round(time.time() - t0, 1),
        "errors_n": len(errors),
        "errors_sample": errors[:8],
        "db_path": str(MARKET_DB),
        "next": "keep v106；若要加深可補歷史 T86 覆蓋後重跑 stock_* 濾，或只留 mkt_* 長窗",
    }
    # 即使 both_ok，本件仍強制 keep=v106／不上話筒（使用者鎖；需明確閘才換）
    # both_ok 只記在 gate_passed；替換仍要 phone 規則 + 人工確認。本腳本永不自動改 keep。
    out["gate_passed"] = bool(both_ok)
    out["keep"] = "v106"
    out["buy_signal"] = False
    out["phone_sync"] = "blocked"

    _write_outputs(out)
    print("GATE", gate, flush=True)
    print("STATUS", status, "keep=v106", flush=True)
    return out


def _write_outputs(out: Dict[str, Any]) -> None:
    text = json.dumps(out, ensure_ascii=False, indent=2, default=str) + "\n"
    ART.mkdir(parents=True, exist_ok=True)
    DOC.mkdir(parents=True, exist_ok=True)
    (ART / "stock_inst_filter_lab_latest.json").write_text(text, encoding="utf-8")
    (DOC / "stock_inst_filter_lab_latest.json").write_text(text, encoding="utf-8")


def main(argv: Optional[Sequence[str]] = None) -> Dict[str, Any]:
    ap = argparse.ArgumentParser(description="v106 × 法人過濾 lab")
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
