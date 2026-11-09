#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Hsiao 大盤 decade 下一窗：TWII 進場 preset 矩陣（含 A4_index_soft）。

只跑實驗室；phone_sync=blocked；不准改買訊／不准搶個股 spirit mix。
本機 index_daily 多短於 20 年時誠實標 years／n。
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


def _now() -> str:
    return datetime.now(TAIPEI).strftime("%Y-%m-%dT%H:%M:%S%z")


def _load_twii() -> pd.DataFrame:
    con = sqlite3.connect(f"file:{MARKET_DB}?mode=ro", uri=True)
    try:
        df = pd.read_sql_query(
            "SELECT date, open, high, low, close, volume FROM index_daily "
            "WHERE symbol='TWII' ORDER BY date",
            con,
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
    n_indep = int(a4.get("n_entry_days") or 0)
    gate_n20 = n_indep >= 20
    # 對該軌現況 A0：獨立進場日更多且總報酬更高才算清贏（仍非買訊）
    beat_a0 = bool(
        n_indep > int(a0.get("n_entry_days") or 0)
        and float(a4.get("total_return") or 0.0) > float(a0.get("total_return") or 0.0)
    )
    years_ok = years >= 19.5
    replace = bool(years_ok and gate_n20 and beat_a0)
    # 本軌硬閘：未過閘一律不換；phone_sync 仍 blocked
    if not (years_ok and gate_n20 and beat_a0):
        replace = False
    gate_flags = [
        "phone_sync_blocked",
        "not_buy_signal",
        "no_stock_spirit_mix_in_this_invent",
    ]
    if not years_ok:
        gate_flags.append("n_lt_20y_window")
    if not gate_n20:
        gate_flags.append("n_entry_days_lt_20")
    if not beat_a0:
        gate_flags.append("not_clear_win_vs_A0")
    seal = {
        "as_of": _now(),
        "tz": "Asia/Taipei",
        "track": "market_tw",
        "pot": "hsiao_twii_entry_invent",
        "phone_sync": PHONE_SYNC,
        "buy_signal": False,
        "not_buy_signal": True,
        "WAVE_NEURONS_MATCH": False,
        "purpose_zh": "蕭氏大盤 decade：A0–A4 進場矩陣；修 TWII 0 成交；不上話筒",
        "data": {
            "symbol": "TWII",
            "n": n,
            "years": round(years, 4),
            "start": str(twii.index[0].date()) if n else None,
            "end": str(twii.index[-1].date()) if n else None,
            "honesty_zh": (
                "本機 index_daily 若短於≈20年＝只對可得窗；不准謊稱二十年績效；"
                "深史可含 Yahoo 補洞，近窗官方量優先"
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
            "A4_index_soft": {
                "n_entry_days": n_indep,
                "n_trades": int(a4.get("n_trades") or 0),
                "total_return": a4.get("total_return"),
            },
            "years_ok": years_ok,
            "gate_n20": gate_n20,
            "beat_a0": beat_a0,
            "replace": replace,
        },
        "replace": replace,
        "keep": "hsiao_v7 A0_strict lab isolation" if not replace else None,
        "gate_flags": gate_flags,
        "next_long_window_zh": (
            "A4 vs A0：獨立進場開市日 n≥20 且清贏 A0 才談換（仍非買訊）；"
            "目前續收／續調進場密度"
            if years_ok
            else (
                "補齊 TWII≈20y 真柱後重跑 A4_index_soft vs A0；"
                "獨立開市日 n≥20 且贏現況才談換（仍非買訊）"
            )
        ),
        "no_invent_wave_5_9_on_stocks": True,
    }
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    ART.mkdir(parents=True, exist_ok=True)
    text = json.dumps(seal, ensure_ascii=False, indent=2)
    (OUT_DIR / "hsiao_twii_entry_invent_latest.json").write_text(text, encoding="utf-8")
    (ART / "hsiao_twii_entry_invent_latest.json").write_text(text, encoding="utf-8")
    print(
        "GATE hsiao_twii_entry",
        f"n={n} years={years:.2f}",
        "A4_entry_days=",
        n_indep,
        "gate_n20=",
        gate_n20,
        "beat_a0=",
        beat_a0,
        "pick=",
        (pick or {}).get("entry_preset"),
        f"replace={replace}",
        "phone_sync=blocked",
    )
    return seal


if __name__ == "__main__":
    run()
