#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""十年回測旁路｜美股×台股連動／背離組合（靜默統計）。

方向（使用者）：落底／上漲都是多因子共現；美股大漲台股不跟、或美股大跌
台指／電子日夜卻抗跌 → 當異常組合（誘多／抗跌等），自己變化組合做量化。

硬邊界：官方柱；缺標缺；不是買訊；不准寫回話筒／黃金買點／海選／洞燭。
"""
from __future__ import annotations

import itertools
import json
import os
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
DB = Path(os.environ.get("WAYNE_DB_PATH") or (ROOT / "data" / "wayne_market.db"))
OUT_DIR = ROOT / "docs" / "expert_notes" / "飆客" / "decade_lab"
TAIPEI = ZoneInfo("Asia/Taipei")

US_UP = 1.0
US_DOWN = -1.5
TW_FLAT_ABS = 0.35
TW_HOLD_MIN = -0.55  # 美股大跌時台股「不太跌」
TW_WEAK = -0.8
SOX_DOWN = -2.0
TX_NIGHT_HOLD = -0.6
FWD_HS = (1, 3, 5)


def _ymd(raw: Any) -> str:
    t = str(raw or "").replace("-", "")[:8]
    return t if len(t) == 8 and t.isdigit() else ""


def _f(v: Any) -> Optional[float]:
    try:
        if v is None or v == "":
            return None
        n = float(v)
    except (TypeError, ValueError):
        return None
    if n != n:
        return None
    return n


def _load_index(conn: sqlite3.Connection, symbol: str) -> Dict[str, Dict[str, float]]:
    rows = conn.execute(
        """
        SELECT REPLACE(CAST(date AS TEXT),'-',''), open, high, low, close
        FROM index_daily WHERE symbol=? ORDER BY 1
        """,
        (symbol,),
    ).fetchall()
    out: Dict[str, Dict[str, float]] = {}
    prev_c = None
    for d, o, h, l, c in rows:
        day = _ymd(d)
        cc = _f(c)
        if not day or not cc or cc <= 0:
            continue
        ret = None if prev_c is None or prev_c <= 0 else (cc / prev_c - 1.0) * 100.0
        out[day] = {
            "open": _f(o) or cc,
            "high": _f(h) or cc,
            "low": _f(l) or cc,
            "close": cc,
            "ret": ret if ret is not None else 0.0,
            "ret_ok": ret is not None,
        }
        prev_c = cc
    return out


def _load_fut(conn: sqlite3.Connection, symbol: str, session: str) -> Dict[str, Dict[str, float]]:
    rows = conn.execute(
        """
        SELECT REPLACE(CAST(date AS TEXT),'-',''), open, high, low, close, pct_change
        FROM futures_daily WHERE symbol=? AND session=? ORDER BY 1
        """,
        (symbol, session),
    ).fetchall()
    out: Dict[str, Dict[str, float]] = {}
    for d, o, h, l, c, pct in rows:
        day = _ymd(d)
        cc = _f(c)
        if not day or not cc:
            continue
        ret = _f(pct)
        if ret is None:
            # fallback none
            ret = 0.0
            ok = False
        else:
            ok = True
        out[day] = {
            "open": _f(o) or cc,
            "high": _f(h) or cc,
            "low": _f(l) or cc,
            "close": cc,
            "ret": ret,
            "ret_ok": ok,
        }
    return out


def _prior_us_day(us_days: Sequence[str], tw_day: str) -> Optional[str]:
    """台股日 T 對應「嚴格早於 T」的最近美股交易日。"""
    t = _ymd(tw_day)
    prev = None
    for d in us_days:
        if d < t:
            prev = d
        else:
            break
    return prev


def _fwd_ret(twii: Dict[str, Dict[str, float]], days: Sequence[str], i: int, h: int) -> Optional[float]:
    if i < 0 or i + h >= len(days):
        return None
    d0 = days[i]
    d1 = days[i + h]
    c0 = twii[d0]["close"]
    c1 = twii[d1]["close"]
    if c0 <= 0:
        return None
    return (c1 / c0 - 1.0) * 100.0


def _combos(flags: Dict[str, bool], keys: Sequence[str], max_k: int = 3) -> List[Tuple[str, ...]]:
    on = [k for k in keys if flags.get(k)]
    out: List[Tuple[str, ...]] = []
    for k in range(1, min(max_k, len(on)) + 1):
        out.extend(itertools.combinations(sorted(on), k))
    return out


def main() -> int:
    if not DB.is_file():
        print(json.dumps({"error": "missing_db"}, ensure_ascii=False))
        return 2
    conn = sqlite3.connect(str(DB), timeout=30.0)
    try:
        twii = _load_index(conn, "TWII")
        ixic = _load_index(conn, "IXIC")
        sox = _load_index(conn, "SOX")
        tx_n = _load_fut(conn, "TX", "night")
        te_n = _load_fut(conn, "TE", "night")
        tx_r = _load_fut(conn, "TX", "regular")
    finally:
        conn.close()

    tw_days = sorted(twii.keys())
    us_days = sorted(set(ixic.keys()) | set(sox.keys()))
    rows: List[Dict[str, Any]] = []
    factor_keys = [
        "us_up_tw_flat",
        "us_down_tw_hold",
        "us_up_tw_down",
        "sox_down_tw_hold",
        "sox_down_txnight_hold",
        "us_down_txnight_hold_day_hold",
        "us_risk_off_tw_green",
    ]

    # aggregate combo → outcomes
    combo_stats: Dict[str, Dict[str, Any]] = {}

    def bump(combo: Tuple[str, ...], fwd: Dict[str, Optional[float]], tw_ret: float) -> None:
        key = "+".join(combo)
        st = combo_stats.setdefault(
            key,
            {
                "n": 0,
                "tw_ret_sum": 0.0,
                "fwd": {str(h): [] for h in FWD_HS},
            },
        )
        st["n"] += 1
        st["tw_ret_sum"] += tw_ret
        for h in FWD_HS:
            v = fwd.get(str(h))
            if v is not None:
                st["fwd"][str(h)].append(v)

    for i, day in enumerate(tw_days):
        bar = twii[day]
        if not bar.get("ret_ok"):
            continue
        tw_ret = float(bar["ret"])
        u = _prior_us_day(us_days, day)
        if not u:
            continue
        ix = ixic.get(u)
        sx = sox.get(u)
        if not ix or not ix.get("ret_ok"):
            continue
        ix_ret = float(ix["ret"])
        sx_ret = float(sx["ret"]) if sx and sx.get("ret_ok") else None

        txn = tx_n.get(day) or tx_n.get(u)  # night often labeled by evening calendar
        # prefer same TW date night bar; else previous
        if day not in tx_n:
            # try prior calendar night tied to u
            txn = tx_n.get(u)
        ten = te_n.get(day)
        txr = tx_r.get(day)

        flags = {
            "us_up_tw_flat": ix_ret >= US_UP and abs(tw_ret) <= TW_FLAT_ABS,
            "us_down_tw_hold": ix_ret <= US_DOWN and tw_ret >= TW_HOLD_MIN,
            "us_up_tw_down": ix_ret >= US_UP and tw_ret <= TW_WEAK,
            "sox_down_tw_hold": (sx_ret is not None and sx_ret <= SOX_DOWN and tw_ret >= TW_HOLD_MIN),
            "sox_down_txnight_hold": bool(
                sx_ret is not None
                and sx_ret <= SOX_DOWN
                and txn
                and txn.get("ret_ok")
                and float(txn["ret"]) >= TX_NIGHT_HOLD
            ),
            "us_down_txnight_hold_day_hold": bool(
                ix_ret <= US_DOWN
                and txn
                and txn.get("ret_ok")
                and float(txn["ret"]) >= TX_NIGHT_HOLD
                and tw_ret >= TW_HOLD_MIN
            ),
            "us_risk_off_tw_green": ix_ret <= US_DOWN and tw_ret > 0.2,
        }
        # TE night short history — keep as optional flag when present
        if ten and ten.get("ret_ok") and sx_ret is not None and sx_ret <= SOX_DOWN:
            flags["sox_down_tenight_hold"] = float(ten["ret"]) >= TX_NIGHT_HOLD
        else:
            flags["sox_down_tenight_hold"] = False

        all_keys = list(factor_keys) + ["sox_down_tenight_hold"]
        lit = {k: bool(flags.get(k)) for k in all_keys}
        if not any(lit.values()):
            continue

        fwd = {str(h): _fwd_ret(twii, tw_days, i, h) for h in FWD_HS}
        row = {
            "A": {
                "event_date": day,
                "us_as_of": u,
                "symbol": "TWII",
                "seq": "linkage_combos",
            },
            "B": {
                "flags": lit,
                "ixic_ret": ix_ret,
                "sox_ret": sx_ret,
                "twii_ret": tw_ret,
                "tx_night_ret": float(txn["ret"]) if txn and txn.get("ret_ok") else None,
                "te_night_ret": float(ten["ret"]) if ten and ten.get("ret_ok") else None,
                "tx_day_ret": float(txr["ret"]) if txr and txr.get("ret_ok") else None,
            },
            "C": {"fwd_twii_pct": fwd},
            "F": {"pot": "實驗室"},
            "G": {"note": "連動／背離組合觀測；誘多只是其中一種標籤方向，不是定論"},
            "H": {
                "gaps": [
                    "us_overnight 表過短→改用 index_daily IXIC/SOX",
                    "TE night 史短",
                    "未接主動 ETF／融資／兆元成交金額",
                ]
            },
        }
        rows.append(row)
        for combo in _combos(lit, all_keys, max_k=3):
            bump(combo, fwd, tw_ret)

    # baseline forward returns (all aligned days)
    base_fwd = {str(h): [] for h in FWD_HS}
    aligned_n = 0
    for i, day in enumerate(tw_days):
        if not twii[day].get("ret_ok"):
            continue
        u = _prior_us_day(us_days, day)
        if not u or u not in ixic or not ixic[u].get("ret_ok"):
            continue
        aligned_n += 1
        for h in FWD_HS:
            v = _fwd_ret(twii, tw_days, i, h)
            if v is not None:
                base_fwd[str(h)].append(v)

    def mean(xs: Sequence[float]) -> Optional[float]:
        return (sum(xs) / len(xs)) if xs else None

    combo_table = []
    for key, st in combo_stats.items():
        if st["n"] < 8:
            continue
        entry = {
            "combo": key,
            "n": st["n"],
            "avg_tw_ret_same_day": st["tw_ret_sum"] / st["n"],
            "fwd_avg": {h: mean(st["fwd"][h]) for h in st["fwd"]},
            "fwd_base": {h: mean(base_fwd[h]) for h in base_fwd},
            "fwd_edge": {},
        }
        for h in FWD_HS:
            a = entry["fwd_avg"].get(str(h))
            b = entry["fwd_base"].get(str(h))
            entry["fwd_edge"][str(h)] = (a - b) if a is not None and b is not None else None
        combo_table.append(entry)
    combo_table.sort(key=lambda r: (r["n"], abs(r["fwd_edge"].get("3") or 0)), reverse=True)

    # single-flag rates
    single = {}
    for k in list(factor_keys) + ["sox_down_tenight_hold"]:
        hit = [r for r in rows if r["B"]["flags"].get(k)]
        single[k] = {
            "n": len(hit),
            "avg_tw_ret": mean([float(r["B"]["twii_ret"]) for r in hit]) if hit else None,
            "fwd3": mean(
                [
                    float(r["C"]["fwd_twii_pct"]["3"])
                    for r in hit
                    if r["C"]["fwd_twii_pct"].get("3") is not None
                ]
            )
            if hit
            else None,
        }

    summary = {
        "written_at": datetime.now(TAIPEI).isoformat(timespec="seconds"),
        "tz": "Asia/Taipei",
        "db": str(DB),
        "aligned_days": aligned_n,
        "anomaly_days_written": len(rows),
        "params": {
            "US_UP": US_UP,
            "US_DOWN": US_DOWN,
            "TW_FLAT_ABS": TW_FLAT_ABS,
            "TW_HOLD_MIN": TW_HOLD_MIN,
            "TW_WEAK": TW_WEAK,
            "SOX_DOWN": SOX_DOWN,
            "TX_NIGHT_HOLD": TX_NIGHT_HOLD,
        },
        "single_flags": single,
        "top_combos": combo_table[:40],
        "base_fwd_avg": {h: mean(base_fwd[h]) for h in base_fwd},
        "not_buy_signal": True,
        "phone_sync": "blocked",
        "interpretation_zh": (
            "異常組合＝美股與台股／期貨表現脫鉤。"
            "fwd_edge>0 只代表樣本內後續加權偏強於基線，不是保證、不是買訊；"
            "誘多／抗跌要再叠量價／跌停／台積等共現才有辨識力。"
        ),
    }

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(TAIPEI).strftime("%Y%m%d")
    jsonl = OUT_DIR / f"linkage_combos_{stamp}.jsonl"
    latest = OUT_DIR / "linkage_combos_latest.jsonl"
    with jsonl.open("w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    latest.write_text(jsonl.read_text(encoding="utf-8"), encoding="utf-8")
    (OUT_DIR / "linkage_combos_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    md = [
        "# 美股×台股連動／背離組合（實驗室）",
        "",
        f"寫入：`{summary['written_at']}`（Asia/Taipei）。",
        f"對齊日 n={aligned_n}；至少點亮一項異常旗標的日 n={len(rows)}。",
        "",
        "## 單旗",
        "",
    ]
    for k, st in single.items():
        md.append(
            f"- `{k}`：n={st['n']} 當日加權均={st['avg_tw_ret']} 後3日均={st['fwd3']}"
        )
    md += ["", "## 組合（n≥8，按樣本與|後3日 edge|）", ""]
    for e in combo_table[:25]:
        md.append(
            f"- `{e['combo']}` n={e['n']} 後3日edge={e['fwd_edge'].get('3')} "
            f"(combo={e['fwd_avg'].get('3')} base={e['fwd_base'].get('3')})"
        )
    md += [
        "",
        summary["interpretation_zh"],
        "",
        "不是買訊。不准寫回黃金買點／海選／洞燭／話筒預測。",
        "",
        f"JSONL：`{latest.relative_to(ROOT)}`",
        "",
    ]
    (OUT_DIR / "linkage_combos_latest.md").write_text("\n".join(md), encoding="utf-8")
    print(json.dumps({k: summary[k] for k in ["aligned_days", "anomaly_days_written", "single_flags", "base_fwd_avg", "top_combos"]}, ensure_ascii=False, indent=2)[:6000])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
