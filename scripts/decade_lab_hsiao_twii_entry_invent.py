#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Hsiao 大盤 decade 下一窗：TWII 進場 preset 矩陣（A4／A5）。

只跑實驗室；phone_sync=blocked；不准改買訊／不准搶個股 spirit mix。
decade 窗固定自 2006-01-02 起（≈20y）；深史 Yahoo 補洞允許，近窗官方量優先。
A4 續收；A5_index_dense＝下一版靜默對質（抬進場日密度）；未過閘不換。
"""
from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List
from zoneinfo import ZoneInfo

import pandas as pd

from scripts.decade_lab_hsiao_backtest import run_single_backtest
from scripts.decade_lab_hsiao_wave_engine import ENTRY_PRESETS

ROOT = Path(__file__).resolve().parents[1]
MARKET_DB = Path(os.environ.get("WAYNE_DB_PATH") or (ROOT / "data" / "wayne_market.db"))
OUT_DIR = ROOT / "docs" / "expert_notes" / "飆客" / "decade_lab"
ART = Path("/opt/cursor/artifacts")
TAIPEI = ZoneInfo("Asia/Taipei")
PHONE_SYNC = "blocked"
DECADE_START = "20060102"


def _now() -> str:
    return datetime.now(TAIPEI).strftime("%Y-%m-%dT%H:%M:%S%z")


def _load_twii() -> pd.DataFrame:
    con = sqlite3.connect(f"file:{MARKET_DB}?mode=ro", uri=True)
    try:
        df = pd.read_sql_query(
            "SELECT date, open, high, low, close, volume FROM index_daily "
            "WHERE symbol='TWII' AND date>=? ORDER BY date",
            con,
            params=(DECADE_START,),
        )
    finally:
        con.close()
    if df.empty:
        return df
    df["date"] = pd.to_datetime(df["date"])
    df = df.set_index("date")
    df.columns = ["Open", "High", "Low", "Close", "Volume"]
    return df


def _entry_days(trades: List[Dict[str, Any]]) -> List[str]:
    """獨立進場開市日（只計試單／破底翻買回；不加碼）。"""
    days: List[str] = []
    for tr in trades or []:
        act = str(tr.get("action") or "")
        if act not in {"buy_w3_trial", "REBUY_AFTER_WASHOUT"}:
            continue
        raw = str(tr.get("t") or "")[:10].replace("-", "")
        if len(raw) >= 8:
            day = raw[:8]
            if day not in days:
                days.append(day)
    return days


def _vs_a0(cand: Dict[str, Any], a0: Dict[str, Any]) -> Dict[str, Any]:
    n_indep = int(cand.get("n_entry_days") or 0)
    gate_n20 = n_indep >= 20
    beat_a0 = bool(
        n_indep > int(a0.get("n_entry_days") or 0)
        and float(cand.get("total_return") or 0.0) > float(a0.get("total_return") or 0.0)
    )
    return {
        "n_entry_days": n_indep,
        "n_trades": int(cand.get("n_trades") or 0),
        "total_return": cand.get("total_return"),
        "gate_n20": gate_n20,
        "beat_a0": beat_a0,
    }


def run() -> Dict[str, Any]:
    twii = _load_twii()
    n = int(len(twii))
    years = float((twii.index[-1] - twii.index[0]).days / 365.25) if n >= 2 else 0.0
    rows: List[Dict[str, Any]] = []
    by_preset: Dict[str, Any] = {}
    for preset in ENTRY_PRESETS:
        bt = run_single_backtest(twii, symbol="TWII", entry_preset=preset)
        s = bt.summary
        entry_days = _entry_days(bt.trades)
        row = {
            "entry_preset": preset,
            "n_trades": int(s.get("n_trades") or 0),
            "n_entry_days": int(len(entry_days)),
            "entry_days": entry_days,
            "total_return": s.get("total_return"),
            "max_drawdown": s.get("max_drawdown"),
            "n_bars": s.get("n_bars"),
            "has_entries": int(len(entry_days)) > 0,
        }
        rows.append(row)
        by_preset[preset] = row
    # 選有成交且回撤較可控者當下一窗候選（仍不換話筒）
    with_entries = [r for r in rows if r["has_entries"]]
    pick = None
    if with_entries:
        pick = sorted(
            with_entries,
            key=lambda r: (
                -int(r["n_entry_days"]),
                -int(r["n_trades"]),
                abs(float(r.get("max_drawdown") or 0.0)),
            ),
        )[0]
    a0 = by_preset.get("A0_strict") or {}
    a4 = by_preset.get("A4_index_soft") or {}
    a5 = by_preset.get("A5_index_dense") or {}
    a4_vs = _vs_a0(a4, a0)
    a5_vs = _vs_a0(a5, a0)
    # 換閘看 pick 軌（通常 A5 denser）；仍須 n≥20 且清贏 A0
    cand = pick or a5 or a4
    cand_key = str((cand or {}).get("entry_preset") or "A5_index_dense")
    cand_vs = _vs_a0(cand or {}, a0)
    years_ok = years >= 19.5
    replace = bool(years_ok and cand_vs["gate_n20"] and cand_vs["beat_a0"])
    if not (years_ok and cand_vs["gate_n20"] and cand_vs["beat_a0"]):
        replace = False
    gate_flags = [
        "phone_sync_blocked",
        "not_buy_signal",
        "no_stock_spirit_mix_in_this_invent",
    ]
    if not years_ok:
        gate_flags.append("n_lt_20y_window")
    if not cand_vs["gate_n20"]:
        gate_flags.append("n_entry_days_lt_20")
    if not cand_vs["beat_a0"]:
        gate_flags.append("not_clear_win_vs_A0")
    # A4 未過閘時仍標 A4 閘旗，方便續收
    if not a4_vs["gate_n20"]:
        gate_flags.append("a4_n_entry_days_lt_20")
    seal = {
        "as_of": _now(),
        "tz": "Asia/Taipei",
        "track": "market_tw",
        "pot": "hsiao_twii_entry_invent",
        "phone_sync": PHONE_SYNC,
        "buy_signal": False,
        "not_buy_signal": True,
        "WAVE_NEURONS_MATCH": False,
        "purpose_zh": "蕭氏大盤 decade：A0–A5 進場矩陣；A5 denser 下一版靜默；不上話筒",
        "data": {
            "symbol": "TWII",
            "n": n,
            "years": round(years, 4),
            "start": str(twii.index[0].date()) if n else None,
            "end": str(twii.index[-1].date()) if n else None,
            "decade_start": DECADE_START,
            "honesty_zh": (
                "decade 窗自 2006-01-02；本機 index_daily 深史可含 Yahoo 補洞，"
                "近窗官方量優先；不准謊稱無補洞的二十年官方績效"
            ),
        },
        "presets": rows,
        "pick_lab_only": pick,
        "a4_vs_a0": {
            "A0_strict": {
                "n_entry_days": int(a0.get("n_entry_days") or 0),
                "n_trades": int(a0.get("n_trades") or 0),
                "total_return": a0.get("total_return"),
            },
            "A4_index_soft": a4_vs,
            "years_ok": years_ok,
            "gate_n20": a4_vs["gate_n20"],
            "beat_a0": a4_vs["beat_a0"],
            "replace": False,  # A4 本輪未過閘不換；換閘看下方 cand
        },
        "a5_vs_a0": {
            "A0_strict": {
                "n_entry_days": int(a0.get("n_entry_days") or 0),
                "n_trades": int(a0.get("n_trades") or 0),
                "total_return": a0.get("total_return"),
            },
            "A5_index_dense": a5_vs,
            "years_ok": years_ok,
            "gate_n20": a5_vs["gate_n20"],
            "beat_a0": a5_vs["beat_a0"],
            "replace": bool(years_ok and a5_vs["gate_n20"] and a5_vs["beat_a0"]),
        },
        "cand_vs_a0": {
            "entry_preset": cand_key,
            **cand_vs,
            "years_ok": years_ok,
            "replace": replace,
        },
        "replace": replace,
        "keep": "hsiao_v7 A0_strict lab isolation" if not replace else None,
        "gate_flags": gate_flags,
        "next_long_window_zh": (
            f"{cand_key} vs A0：獨立進場開市日 n≥20 且清贏 A0 才談換（仍非買訊）；"
            "A4 續收、A5 denser 同軌靜默對質"
            if years_ok
            else (
                "補齊 TWII≈20y 真柱後重跑 A4／A5 vs A0；"
                "獨立開市日 n≥20 且贏現況才談換（仍非買訊）"
            )
        ),
        "invent_next_zh": "A5_index_dense＝A4 再生下一版；未過閘不換、不上話筒",
        "no_invent_wave_5_9_on_stocks": True,
    }
    # 硬閘：即便 a5_vs 算過也以頂層 replace 為準
    if not replace:
        seal["a5_vs_a0"]["replace"] = False
        seal["cand_vs_a0"]["replace"] = False
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    ART.mkdir(parents=True, exist_ok=True)
    text = json.dumps(seal, ensure_ascii=False, indent=2)
    (OUT_DIR / "hsiao_twii_entry_invent_latest.json").write_text(text, encoding="utf-8")
    (ART / "hsiao_twii_entry_invent_latest.json").write_text(text, encoding="utf-8")
    # A5 invent 封印（下一版鍵）
    invent = {
        "as_of": seal["as_of"],
        "tz": "Asia/Taipei",
        "track": "market_tw",
        "pot": "hsiao_twii_entry_invent",
        "invent_key": "A5_index_dense",
        "parent_keep": "hsiao_v7 A0_strict lab isolation",
        "phone_sync": PHONE_SYNC,
        "buy_signal": False,
        "not_buy_signal": True,
        "WAVE_NEURONS_MATCH": False,
        "replace": False,
        "a4_vs_a0": seal["a4_vs_a0"],
        "a5_vs_a0": seal["a5_vs_a0"],
        "gate_flags": gate_flags,
        "next_long_window_zh": seal["next_long_window_zh"],
        "no_invent_wave_5_9_on_stocks": True,
    }
    invent_text = json.dumps(invent, ensure_ascii=False, indent=2)
    (OUT_DIR / "hsiao_twii_a5_dense_invent.json").write_text(invent_text, encoding="utf-8")
    (ART / "hsiao_twii_a5_dense_invent.json").write_text(invent_text, encoding="utf-8")
    print(
        "GATE hsiao_twii_entry",
        f"n={n} years={years:.2f}",
        "A4_entry_days=",
        a4_vs["n_entry_days"],
        "A5_entry_days=",
        a5_vs["n_entry_days"],
        "cand=",
        cand_key,
        "gate_n20=",
        cand_vs["gate_n20"],
        "beat_a0=",
        cand_vs["beat_a0"],
        f"replace={replace}",
        "phone_sync=blocked",
    )
    return seal


if __name__ == "__main__":
    run()
