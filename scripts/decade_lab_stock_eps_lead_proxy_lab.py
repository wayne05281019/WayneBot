#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""個股 lab：季 EPS「預先判斷」領先代理（靜默對質）。

目標（使用者 2026-11-10 營收刀未過閘 → 下一刀）：
預期已公告季 EPS 轉佳時，價量常先反映。
本刀只准用**已公告** quarterly_income.eps＋官方 OHLC／量，
**不准發明**未公告 EPS／營收數字。

領先代理（公告後 as-of 才準用）：
- eps_qoq_up：最新已公告季 EPS ＞ 前一季
- eps_qoq_up_2：連兩段 QoQ 轉佳
- eps_qoq_up_pos：QoQ 轉佳且最新 EPS＞0
- eps_turn_pos：前季≤0、本季＞0（轉虧為盈）
- 可疊 vol_expand／站上 ma20

進場核：SPIRIT_pull_fib618（present-data；≠leave_zero／≠sealed keep）
出場：hi20_or_desync
過閘：獨立開市日 n≥20 且 OOS 同時贏 sealed v106 early+fast；否則 keep=v106
phone_sync=blocked；buy_signal=false；不准改話筒／leave_zero

用法：
  WAYNE_DB_PATH=data/wayne_market.db \\
  python scripts/decade_lab_stock_eps_lead_proxy_lab.py

  python scripts/decade_lab_stock_eps_lead_proxy_lab.py --smoke
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
SELL_KEEP = "hi20_or_desync"
V106_REF = {
    "early": {"wr": 0.8269230769230769, "d": 51, "bars": 16.54901960784314},
    "fast": {"wr": 0.8545454545454545, "d": 54, "bars": 15.296296296296296},
}

CONFIRM_NAMES = (
    "plain",
    "eps_qoq_up",
    "eps_qoq_up_2",
    "eps_qoq_up_pos",
    "eps_turn_pos",
    "eps_qoq_up_above_ma20",
    "eps_qoq_up_vol_expand",
    "eps_qoq_up_2_vol_expand",
    "eps_turn_pos_vol_expand",
)


def _now() -> str:
    return datetime.now(TAIPEI).isoformat(timespec="seconds")


def _ymd(raw: Any) -> str:
    t = str(raw or "").replace("-", "")[:8]
    return t if len(t) == 8 and t.isdigit() else ""


def roc_pub_to_ymd(raw: Any) -> str:
    """出表日期：民國 YYYMMDD（如 1151106）→ 西元 YYYYMMDD；已是西元 8 碼則原樣。"""
    digits = "".join(c for c in str(raw or "") if c.isdigit())
    if len(digits) == 7:
        y = int(digits[:3]) + 1911
        md = digits[3:]
        if len(md) == 4 and 1 <= int(md[:2]) <= 12 and 1 <= int(md[2:]) <= 31:
            return f"{y}{md}"
        return ""
    if len(digits) == 8 and digits.startswith(("19", "20")):
        return digits
    return ""


def season_available_fallback(year: int, season: int) -> str:
    """無出表日時：公開財報截止日保守可用（台股常見）。"""
    try:
        y = int(year)
        s = int(season)
    except (TypeError, ValueError):
        return ""
    if s == 1:
        return f"{y}0515"
    if s == 2:
        return f"{y}0814"
    if s == 3:
        return f"{y}1114"
    if s == 4:
        return f"{y + 1}0331"
    return ""


def season_key(year: Any, season: Any) -> int:
    try:
        return int(year) * 10 + int(season)
    except (TypeError, ValueError):
        return -1


def load_quarterly_eps_rows(sid: str, db_path: Path = MARKET_DB) -> List[Dict[str, Any]]:
    if not db_path.is_file():
        return []
    con = sqlite3.connect(str(db_path))
    try:
        rows = con.execute(
            """
            SELECT year, season, eps, published_roc
            FROM quarterly_income
            WHERE stock_id=? AND eps IS NOT NULL
            ORDER BY year, season
            """,
            (str(sid),),
        ).fetchall()
    finally:
        con.close()
    out: List[Dict[str, Any]] = []
    for year, season, eps, pub in rows:
        try:
            eps_f = float(eps)
        except (TypeError, ValueError):
            continue
        if eps_f != eps_f:  # NaN
            continue
        sk = season_key(year, season)
        if sk < 0:
            continue
        avail = roc_pub_to_ymd(pub) or season_available_fallback(int(year), int(season))
        if not avail:
            continue
        out.append(
            {
                "year": int(year),
                "season": int(season),
                "season_key": sk,
                "eps": eps_f,
                "published_roc": str(pub or ""),
                "available_from": avail,
            }
        )
    # 同季多列時留最後一筆（依 season_key 排序後去重）
    by_key: Dict[int, Dict[str, Any]] = {}
    for r in out:
        by_key[int(r["season_key"])] = r
    return [by_key[k] for k in sorted(by_key)]


def eps_lead_masks_for_dates(
    dates: Sequence[str],
    eps_rows: Sequence[Dict[str, Any]],
) -> Dict[str, pd.Series]:
    """依交易日 as-of 只吃已公告季 EPS，產出轉佳／轉虧為盈遮罩。"""
    idx = list(range(len(dates)))
    ymds = [_ymd(d) for d in dates]
    qoq = pd.Series(False, index=idx)
    qoq2 = pd.Series(False, index=idx)
    qoq_pos = pd.Series(False, index=idx)
    turn = pd.Series(False, index=idx)
    if not eps_rows:
        return {
            "eps_qoq_up": qoq,
            "eps_qoq_up_2": qoq2,
            "eps_qoq_up_pos": qoq_pos,
            "eps_turn_pos": turn,
        }

    sorted_rows = sorted(eps_rows, key=lambda r: int(r["season_key"]))
    for i, ymd in enumerate(ymds):
        if not ymd:
            continue
        known = [r for r in sorted_rows if str(r["available_from"]) <= ymd]
        if len(known) < 2:
            continue
        a, b = known[-2], known[-1]
        eps_a, eps_b = float(a["eps"]), float(b["eps"])
        is_up = bool(eps_b > eps_a)
        qoq.iloc[i] = is_up
        qoq_pos.iloc[i] = bool(is_up and eps_b > 0.0)
        turn.iloc[i] = bool(eps_a <= 0.0 and eps_b > 0.0)
        if is_up and len(known) >= 3:
            z = known[-3]
            qoq2.iloc[i] = bool(eps_a > float(z["eps"]))
    return {
        "eps_qoq_up": qoq,
        "eps_qoq_up_2": qoq2,
        "eps_qoq_up_pos": qoq_pos,
        "eps_turn_pos": turn,
    }


def confirm_masks_eps_lead(
    *,
    df: pd.DataFrame,
    eps_rows: Sequence[Dict[str, Any]],
    tech_feat: pd.DataFrame,
) -> Dict[str, pd.Series]:
    from scripts.decade_lab_stock_spirit_soft_leader_fib618_vol_expand_lab import (
        vol_expand_mask,
    )

    idx = df.index
    dates = df["date"].astype(str).tolist() if "date" in df.columns else [str(i) for i in idx]
    base_m = eps_lead_masks_for_dates(dates, eps_rows)
    for k in list(base_m.keys()):
        s = base_m[k]
        s.index = idx
        base_m[k] = s.fillna(False)

    close = df["close"].astype(float)
    ma20 = close.rolling(20, min_periods=20).mean()
    above = (close > ma20).fillna(False)
    vol15 = vol_expand_mask(tech_feat, mult=1.5).reindex(idx).fillna(False)
    up = base_m["eps_qoq_up"]
    up2 = base_m["eps_qoq_up_2"]
    up_pos = base_m["eps_qoq_up_pos"]
    turn = base_m["eps_turn_pos"]
    return {
        "plain": pd.Series(True, index=idx),
        "eps_qoq_up": up,
        "eps_qoq_up_2": up2,
        "eps_qoq_up_pos": up_pos,
        "eps_turn_pos": turn,
        "eps_qoq_up_above_ma20": (up & above).fillna(False),
        "eps_qoq_up_vol_expand": (up & vol15).fillna(False),
        "eps_qoq_up_2_vol_expand": (up2 & vol15).fillna(False),
        "eps_turn_pos_vol_expand": (turn & vol15).fillna(False),
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
    latest = DOC / "stock_eps_lead_proxy_lab_latest.json"
    decision = DOC / "stock_eps_lead_proxy_lab_decision.json"
    seed = DOC / "stock_eps_lead_proxy_lab_seed.json"
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
        "note_zh": "已公告季 EPS QoQ 轉佳＋價量；不准發明未公告 EPS",
    }
    seed.write_text(json.dumps(seed_obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (ART / "stock_eps_lead_proxy_lab_decision.json").write_text(
        json.dumps(slim, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def stocks_with_eps_ge2(db_path: Path = MARKET_DB) -> List[str]:
    """庫內至少兩季已有 eps 的代號（lab 母體優先）。"""
    if not db_path.is_file():
        return []
    con = sqlite3.connect(str(db_path))
    try:
        rows = con.execute(
            """
            SELECT stock_id FROM quarterly_income
            WHERE eps IS NOT NULL
            GROUP BY stock_id
            HAVING COUNT(*) >= 2
            ORDER BY stock_id
            """
        ).fetchall()
    finally:
        con.close()
    return [str(r[0]) for r in rows]


def run(*, n_stocks: int = 260, min_avg_turnover_k: float = 800_000.0, smoke: bool = False) -> Dict[str, Any]:
    from scripts.decade_lab_chart_marks_stats import _normalize_ohlc
    from scripts.decade_lab_hsiao_universe import MUST_INCLUDE, load_stock_ohlcv, select_g_universe
    from scripts.decade_lab_phone_trade_confront import _build_hl_temp
    from scripts.decade_lab_stock_pair_exit_leg_confirm_lab import (
        _simulate_paired_sell,
        tech_sell_aux,
    )
    from scripts.decade_lab_stock_spirit_soft_leader_fib618_vol_expand_lab import (
        spirit_pull_fib618_entry_mask,
    )
    from scripts.decade_lab_stock_tech_confirm_lab import tech_features

    t0 = time.time()
    n_use = 12 if smoke else int(n_stocks)
    eps_pool = set(stocks_with_eps_ge2())
    uni = select_g_universe(
        n=max(400, n_use * 3),
        include_twse_top100=True,
        min_avg_turnover_k=float(min_avg_turnover_k),
    )
    # 流動母體 ∩ 至少兩季 EPS；不足再補 ge2 池與必含標
    liq: List[str] = uni["stock_id"].astype(str).tolist()
    symbols: List[str] = [s for s in liq if s in eps_pool]
    for sid in MUST_INCLUDE:
        sid_s = str(sid)
        if sid_s in eps_pool and sid_s not in symbols:
            symbols.append(sid_s)
    for sid in ("2330", "2317", "2454", "2383", "2308", "3037", "6669"):
        if sid in eps_pool and sid not in symbols:
            symbols.append(sid)
    if len(symbols) < n_use:
        for sid in sorted(eps_pool):
            if sid not in symbols:
                symbols.append(sid)
            if len(symbols) >= n_use:
                break
    symbols = symbols[:n_use]

    buckets: Dict[str, List[Dict[str, Any]]] = {f: [] for f in CONFIRM_NAMES}
    all_dates: List[str] = []
    errors: List[str] = []
    meta_n = 0
    entry_hits = 0
    eps_ok = 0

    for sid in symbols:
        try:
            raw = load_stock_ohlcv(sid)
            if raw is None or len(raw) < 150:
                continue
            df = _normalize_ohlc(raw)
            if df is None or len(df) < 150:
                continue
            eps_rows = load_quarterly_eps_rows(sid)
            if len(eps_rows) < 2:
                continue
            meta_n += 1
            eps_ok += 1
            all_dates.extend(df["date"].astype(str).tolist())
            base = spirit_pull_fib618_entry_mask(df, raw)
            entry_hits += int(base.sum())
            hl, temp = _build_hl_temp(df)
            tech_feat = tech_features(df)
            cmasks = confirm_masks_eps_lead(df=df, eps_rows=eps_rows, tech_feat=tech_feat)
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
                        entry_tag=f"spirit_eps_lead__{fname}",
                        mode=SELL_KEEP,
                    )
                )
        except Exception as e:  # noqa: BLE001
            errors.append(f"{sid}:{type(e).__name__}:{e}")

    if entry_hits <= 0 or meta_n <= 0:
        out = {
            "version": "stock_eps_lead_proxy_lab_v1",
            "as_of": _now(),
            "tz": "Asia/Taipei",
            "phone_sync": PHONE_SYNC,
            "buy_signal": BUY_SIGNAL,
            "status": "blocked_empty",
            "finding_zh": "季 EPS 列或進場核全空。keep 仍 v106。不准改話筒。",
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
                "leg": "spirit_eps_lead_proxy_confirm",
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
    promote = False
    confirm_trade_n = sum(
        int((variants[f]["full"] or {}).get("n_trades") or 0)
        for f in CONFIRM_NAMES
        if f != "plain" and f in variants
    )
    if confirm_trade_n <= 0:
        status = "blocked_thin_qi_overlap"
    elif gate_theory:
        status = "shared_beats_keep_but_phone_blocked"
    elif best:
        status = "plain_delta_only_keep_v106"
    else:
        status = "no_beat_keep_v106"
    if confirm_trade_n <= 0:
        finding = (
            "季 EPS 領先代理：流動母體季報史偏薄（多檔僅近 1～2 季），"
            "與 SPIRIT_pull_fib618 交集成交=0；無法對質。keep v106。"
            "不准發明未公告 EPS、不准改話筒。"
        )
    else:
        finding = (
            f"季 EPS 領先代理（已公告 QoQ 轉佳／轉虧為盈／價量）：最佳={best}；"
            + (
                f"共享變體 {shared[0]} OOS 同時贏 early+fast → 理論過閘；"
                "仍 phone blocked／replace=false。不准發明未公告 EPS。"
                if gate_theory
                else "未同時贏 sealed v106 keep → keep v106。不准改話筒。"
            )
        )
    out = {
        "version": "stock_eps_lead_proxy_lab_v1",
        "as_of": _now(),
        "tz": "Asia/Taipei",
        "phone_sync": PHONE_SYNC,
        "buy_signal": BUY_SIGNAL,
        "promote_lookup": promote,
        "status": status,
        "gate_passed": False,
        "keep": "v106",
        "keep_detail": "compare vs sealed early ei_n2_lu5／fast lu5_vol_next；sell hi20_or_desync",
        "entry": "SPIRIT_pull_fib618",
        "entry_note_zh": "present-data 替代核；≠sealed keep；≠leave_zero／黃金買訊",
        "sell": SELL_KEEP,
        "variant_tested_zh": "已公告季 EPS QoQ 轉佳／轉虧為盈＋ma20／vol_expand；不准未公告數字",
        "n_stocks": meta_n,
        "eps_ok_stocks": eps_ok,
        "entry_hits": entry_hits,
        "smoke": bool(smoke),
        "best_candidate": best,
        "confirm_trade_n": confirm_trade_n,
        "data_note_zh": (
            "OpenAPI 季報多為近窗；流動標與多季史交集不足時 confirm 成交可為 0"
        ),
        "shared_vs_keep": shared,
        "beats_v106_early_keep": beats_early_keep,
        "beats_v106_fast_keep": beats_fast_keep,
        "tracks": {
            "spirit_eps_lead_proxy": {
                "entry": "SPIRIT_pull_fib618",
                "sell": SELL_KEEP,
                "plain": {"full": plain_full, "is": plain_is, "oos": plain_oos},
                "variants": variants,
                "v106_ref": V106_REF,
            }
        },
        "oos_vs_v106_keep": {"plain_oos": plain_oos, "v106_ref": V106_REF},
        "gate_one_liner": (
            f"stock_eps_lead_proxy n={meta_n} hits={entry_hits} smoke={int(smoke)}; "
            f"best={best}; shared={shared}; promote={promote}"
        ),
        "finding_zh": finding,
        "parent_keep": "phone_spirit_mix_dual_track_v106_decision.json",
        "parent_prev_knife": "stock_revenue_lead_proxy_lab（營收加速未過閘）",
        "next": (
            "理論過閘仍 blocked；下一刀可加同業先動或拉長季史；不准改話筒"
            if gate_theory
            else (
                "季報史不足無法對質；下一刀優先補已公告多季 EPS 或改試同業價量領先；"
                "不准發明未公告 EPS、不准改話筒"
                if confirm_trade_n <= 0
                else "未過閘；下一刀同業領先／拉長季 EPS 史；不准發明未公告 EPS、不准改話筒"
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
