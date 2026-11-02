#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""十年回測旁路｜序C：Fib／等長／DC 擴延閘／2–4 交替／台積周線（我估）。

硬邊界：
- 只寫 ``docs/.../decade_lab/``；讀 ``wayne_market.db``／可選 ``decade_lab.db``。
- 三鍋分標：本腳本輸出鍋＝**DC→我估**；不准冒充他說；不是買訊。
- 盤中未收不當收；缺柱／缺教材（DC 末端）只標缺；不寫回黃金買點／海選／洞燭／話筒。
- as-of：量測位只用 ≤ 事件日已收柱；結局對照可讀後續柱但分欄標 ``post_as_of``。
"""
from __future__ import annotations

import json
import sqlite3
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
_SCRIPTS = ROOT / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from mine_wave_rules import (  # noqa: E402
    alternation_2_4_hint,
    check_w1_w4_overlap,
    detect_extension_1618,
    fib_extension_targets,
    fib_retracement_levels,
    leading_diagonal_flags,
    lengths_from_pivots,
    wave_equality_guide,
)
from decade_lab_market_confront import SEED_DAYS, _load_bars, _ymd  # noqa: E402

LAB_DB = Path(ROOT / "data" / "decade_lab.db")
MARKET_DB = Path(ROOT / "data" / "wayne_market.db")
OUT_DIR = ROOT / "docs" / "expert_notes" / "飆客" / "decade_lab"
TP = ZoneInfo("Asia/Taipei")

RETRACE_RATIOS = (0.382, 0.5, 0.618, 0.75, 0.786)
EXT_RATIOS = (1.0, 1.272, 1.618, 2.618)
PHOTO_N = 8
SWING_N = 40
POST_N = 10


def _now_tp() -> datetime:
    return datetime.now(TP)


def _f(x: Any) -> Optional[float]:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    if v != v:
        return None
    return v


def _load_twii(as_of: str, n: int) -> Tuple[List[Dict[str, Any]], List[str]]:
    rows, gaps = _load_bars("TWII", as_of, window=n)
    return rows, gaps


def _load_2330_daily(as_of: str, n: int) -> Tuple[List[Dict[str, Any]], List[str]]:
    gaps: List[str] = []
    ymd = _ymd(as_of)
    rows: List[Dict[str, Any]] = []
    if LAB_DB.exists():
        con = sqlite3.connect(f"file:{LAB_DB}?mode=ro", uri=True)
        con.row_factory = sqlite3.Row
        try:
            cur = con.execute(
                """
                SELECT date, open, high, low, close, volume FROM lab_daily
                WHERE symbol='2330' AND adj_kind='raw_quote' AND date<=?
                ORDER BY date DESC LIMIT ?
                """,
                (ymd, n),
            )
            rows = [dict(r) for r in cur.fetchall()]
            rows.reverse()
        finally:
            con.close()
    if not rows and MARKET_DB.exists():
        con = sqlite3.connect(f"file:{MARKET_DB}?mode=ro", uri=True)
        con.row_factory = sqlite3.Row
        try:
            cur = con.execute(
                """
                SELECT date, open, high, low, close, volume FROM daily_quotes
                WHERE stock_id='2330' AND date<=?
                ORDER BY date DESC LIMIT ?
                """,
                (ymd, n),
            )
            rows = [dict(r) for r in cur.fetchall()]
            rows.reverse()
        finally:
            con.close()
    if not rows:
        gaps.append(f"缺柱：2330 as_of≤{ymd}")
    return rows, gaps


def _weekly_bars(dailies: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """簡易自然週（一～日）聚合；缺量就略。"""
    weeks: Dict[str, Dict[str, Any]] = {}
    order: List[str] = []
    for b in dailies:
        d = str(b.get("date") or "")
        if len(d) < 8:
            continue
        try:
            dt = datetime.strptime(d[:8], "%Y%m%d")
        except ValueError:
            continue
        iso = dt.isocalendar()
        key = f"{iso.year}-W{iso.week:02d}"
        o, h, l, c = _f(b.get("open")), _f(b.get("high")), _f(b.get("low")), _f(b.get("close"))
        v = _f(b.get("volume")) or 0.0
        if None in (o, h, l, c):
            continue
        if key not in weeks:
            weeks[key] = {
                "week": key,
                "open": o,
                "high": h,
                "low": l,
                "close": c,
                "volume": v,
                "n": 1,
                "from": d,
                "to": d,
            }
            order.append(key)
        else:
            w = weeks[key]
            w["high"] = max(w["high"], h)
            w["low"] = min(w["low"], l)
            w["close"] = c
            w["volume"] += v
            w["n"] += 1
            w["to"] = d
    return [weeks[k] for k in order]


def _swing_hi_lo(bars: Sequence[Dict[str, Any]]) -> Tuple[Optional[float], Optional[float], Optional[str], Optional[str]]:
    hi = lo = None
    hi_d = lo_d = None
    for b in bars:
        h, l = _f(b.get("high")), _f(b.get("low"))
        d = str(b.get("date") or "")
        if h is not None and (hi is None or h >= hi):
            hi, hi_d = h, d
        if l is not None and (lo is None or l <= lo):
            lo, lo_d = l, d
    return hi, lo, hi_d, lo_d


def _local_pivots(bars: Sequence[Dict[str, Any]], *, left: int = 2, right: int = 2) -> List[Tuple[float, str]]:
    """簡易 swing 轉折（收盤）；樣本不足回空。"""
    closes: List[Tuple[str, float]] = []
    for b in bars:
        c = _f(b.get("close"))
        d = str(b.get("date") or "")
        if c is None or not d:
            continue
        closes.append((d, c))
    pivots: List[Tuple[float, str]] = []
    n = len(closes)
    for i in range(left, n - right):
        window = [closes[j][1] for j in range(i - left, i + right + 1)]
        v = closes[i][1]
        if v == max(window) or v == min(window):
            if pivots and pivots[-1][1] == closes[i][0]:
                continue
            # 去連續同向：若新轉折與上一個同側且更極端才替換
            if pivots:
                prev_v = pivots[-1][0]
                # 同值略過
                if abs(prev_v - v) < 1e-9:
                    continue
            pivots.append((v, closes[i][0]))
    return pivots


def _post_path(symbol: str, as_of: str, n: int = POST_N) -> Tuple[List[Dict[str, Any]], List[str]]:
    """事件日之後已收柱（對照用；標 post_as_of）。"""
    gaps: List[str] = []
    ymd = _ymd(as_of)
    rows: List[Dict[str, Any]] = []
    if not MARKET_DB.exists() or symbol != "TWII":
        gaps.append("post_as_of 僅 TWII／wayne_market")
        return rows, gaps
    con = sqlite3.connect(f"file:{MARKET_DB}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    try:
        cur = con.execute(
            """
            SELECT date, open, high, low, close, volume FROM index_daily
            WHERE symbol='TWII' AND date>?
            ORDER BY date ASC LIMIT ?
            """,
            (ymd, n),
        )
        rows = [dict(r) for r in cur.fetchall()]
    finally:
        con.close()
    if not rows:
        gaps.append(f"缺後續柱：TWII >{ymd}")
    return rows, gaps


def _nearest_level_touch(
    levels: Dict[str, float],
    path: Sequence[Dict[str, Any]],
    *,
    tol_pct: float = 0.003,
) -> Dict[str, Any]:
    """後續路徑是否觸及各 Fib 位（實驗室對照；非當時判斷）。"""
    hits: Dict[str, Any] = {}
    for k, lv in (levels or {}).items():
        hit_date = None
        for b in path:
            lo, hi = _f(b.get("low")), _f(b.get("high"))
            if lo is None or hi is None or lv is None or lv == 0:
                continue
            band = abs(lv) * tol_pct
            if lo - band <= lv <= hi + band:
                hit_date = str(b.get("date"))
                break
        hits[k] = {"level": lv, "touched": hit_date is not None, "first_touch_date": hit_date}
    return hits


def _form_record(seed: Dict[str, Any]) -> Dict[str, Any]:
    as_of = seed["event_date"]
    symbol = seed.get("symbol") or "TWII"
    gaps: List[str] = []
    missing_curriculum: List[str] = ["DC末端／motive 全表待補 → 末端傾斜教材跳過"]

    swing_bars, g1 = _load_twii(as_of, SWING_N)
    gaps.extend(g1)
    photo = swing_bars[-PHOTO_N:] if swing_bars else []
    post, g_post = _post_path(symbol, as_of)
    gaps.extend(g_post)

    hi, lo, hi_d, lo_d = _swing_hi_lo(swing_bars)
    # 方向：若低點日晚於高點日 → 主跌後反彈測壓；反之回檔測撐
    if hi is not None and lo is not None and hi_d and lo_d:
        if lo_d >= hi_d:
            direction = "bounce_from_low"
        else:
            direction = "pullback_from_high"
    else:
        direction = "bounce_from_low"

    fib_ret = fib_retracement_levels(hi or 0, lo or 0, ratios=RETRACE_RATIOS, direction=direction)
    if not fib_ret.get("ok"):
        gaps.append("Fib回撤：近窗缺高低")

    # 等長 C／延伸：以 swing 高低為參考浪，自另一端投影
    if hi is not None and lo is not None:
        if direction == "bounce_from_low":
            fib_ext = fib_extension_targets(hi, lo, ratios=EXT_RATIOS, from_price=lo)
        else:
            fib_ext = fib_extension_targets(lo, hi, ratios=EXT_RATIOS, from_price=hi)
    else:
        fib_ext = {"ok": False, "targets": {}, "basis": "缺高低"}

    pivots = _local_pivots(swing_bars)
    lengths = lengths_from_pivots([(p[0],) for p in pivots]) if pivots else {}
    # 動機浪粗取奇數段 1/3/5（有才送擴延閘）
    motive = {k: lengths[k] for k in ("1", "3", "5") if k in lengths}
    ext1618 = detect_extension_1618(motive) if len(motive) >= 2 else {
        "pass": False,
        "variant": "insufficient_legs",
        "basis": "近窗轉折不足兩段動機浪",
        "lengths": motive,
    }

    # 前端傾斜：若有≥5 轉折，取段1 與段4 價區
    ld_flags: Dict[str, Any]
    if len(pivots) >= 5:
        p = [x[0] for x in pivots[:5]]
        ov = check_w1_w4_overlap(p[0], p[1], p[3], p[4])
        ld_flags = leading_diagonal_flags(
            w1_w4_overlap=ov.get("overlap"),
            position_ok=None,  # 位置／5-3-5-3-5 本批不腦補
            structure_53535=None,
        )
        ld_flags["w1_w4_check"] = ov
    else:
        ld_flags = {
            "candidate": False,
            "confirmed": False,
            "basis": "轉折<5；前端傾斜結構未判",
            "w1_w4_overlap": None,
        }
        gaps.append("前端傾斜：轉折點不足（標缺，不腦補 5-3-5-3-5）")

    # 等長指引：若有段1與段3
    eq = (
        wave_equality_guide(lengths["1"], lengths.get("3") or lengths.get("2") or 0)
        if "1" in lengths
        else {"ok": False, "basis": "缺段長"}
    )

    # 2／4 交替：用段2、段4 相對前推動浪回撤％（有才算）
    alt: Dict[str, Any]
    if all(k in lengths for k in ("1", "2", "3", "4")) and lengths["1"] > 0 and lengths["3"] > 0:
        r2 = lengths["2"] / lengths["1"]
        r4 = lengths["4"] / lengths["3"]
        alt = alternation_2_4_hint(r2, r4)
    else:
        alt = {"ok": False, "alternates": None, "basis": "缺 1–4 段長"}

    touch = _nearest_level_touch(fib_ret.get("levels") or {}, post) if fib_ret.get("ok") else {}

    tsmc_d, g_tsmc = _load_2330_daily(as_of, 60)
    gaps.extend(g_tsmc)
    weekly = _weekly_bars(tsmc_d)[-8:] if tsmc_d else []
    if not weekly:
        gaps.append("台積周線：近窗無周聚合")

    near_photo = [
        {
            "date": b["date"],
            "o": b.get("open"),
            "h": b.get("high"),
            "l": b.get("low"),
            "c": b.get("close"),
            "v": b.get("volume"),
        }
        for b in photo
    ]

    record = {
        "A": {
            "event_date": as_of,
            "event_time_taipei": seed.get("event_time") or "",
            "symbol": symbol,
            "level_hypothesis": seed.get("level_hypothesis"),
            "said": seed.get("said"),
            "source_ref": seed.get("source_ref"),
            "seq": "C",
        },
        "B": {
            "alive_labels": (seed.get("alive_labels") or [])[:3],
            "measure_tags": [
                {"label": "Fib回撤行為", "kill": "換版作廢舊錨／與鐵律衝突→鐵律優先"},
                {"label": "擴延1618閘", "kill": "未達1.618且非稀有變體→不標推進擴延"},
                {"label": "等長／2-4交替", "kill": "段長不足或非交替→只旁證"},
            ],
        },
        "C": {
            "near_window_ohlcv": near_photo,
            "window_n": len(near_photo),
            "swing_window_n": len(swing_bars),
            "swing_high": hi,
            "swing_low": lo,
            "swing_high_date": hi_d,
            "swing_low_date": lo_d,
        },
        "D": {
            "pot": "DC→我估",
            "iron_rules_priority": "與鐵律衝突＝鐵律優先（本列不重算③非最短／活畫⑤＞B）",
            "fib_retracement": fib_ret,
            "fib_extension": fib_ext,
            "wave_equality": eq,
            "alternation_2_4": alt,
            "dc_extension_1618": ext1618,
            "dc_leading_diagonal": ld_flags,
            "dc_ending_diagonal": {
                "status": "skipped",
                "reason": "末端教材未齊",
            },
            "time_proportion": {
                "status": "旁證未量化本批",
                "note": "段天數只旁證",
            },
            "≠_extension_vs_c_target": "擴延1618閘 ≠ Fib 1.618 C目標價",
        },
        "E": {
            "volume_price_story": "序C不編裸K全集（留序D）",
            "outer": {
                "2330_weekly_tail": weekly,
                "pivots_n": len(pivots),
                "pivot_dates": [p[1] for p in pivots[-8:]],
            },
        },
        "F": {
            "teacher_claim_pot": "他說／飆預測（只附種子原文）",
            "lab_pot": "實驗室（後續觸及對照）",
            "dc_estimate_pot": "DC→我估（Fib／等長／擴延閘／交替／周線）",
        },
        "G": {
            "outcome": "未完",
            "lab_fib_touch_post_as_of": touch,
            "teacher_verdict_hint": seed.get("teacher_verdict_hint"),
            "note": "序C度量為我估指引；結局不混老師對錯勝率",
        },
        "H": {
            "actionable_fix": (
                "Fib／等長／交替分欄；擴延閘與 C 目標價分鍋；"
                "末端教材到齊前不准標 ending_diagonal；負結果（未觸及／假陽性）也留"
            ),
            "negative_logged": True,
        },
        "flags": {
            "missing_bars": gaps,
            "missing_curriculum": missing_curriculum,
            "as_of_cutoff": f"{_ymd(as_of)} 收盤後可知；盤中未收不當收",
            "post_as_of_only_for_touch": True,
            "limit_up_down": None,
            "settlement_week": None,
            "gap_open": None,
        },
        "meta": {
            "written_at": _now_tp().isoformat(),
            "tz": "Asia/Taipei",
            "not_buy_signal": True,
            "batch": "C0_measure_wave1",
            "seed_n_ref": "decade_lab_market_confront.SEED_DAYS",
        },
    }
    record["counted"] = bool(symbol) and len(near_photo) > 0 and bool(fib_ret.get("ok") or motive)
    return record


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    records = [_form_record(s) for s in SEED_DAYS]
    counted = [r for r in records if r.get("counted")]
    stamp = _now_tp().strftime("%Y%m%d")
    out_jsonl = OUT_DIR / f"seq_c_measure_{stamp}.jsonl"
    with out_jsonl.open("w", encoding="utf-8") as f:
        for r in counted:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    alias = OUT_DIR / "seq_c_measure_latest.jsonl"
    alias.write_text(out_jsonl.read_text(encoding="utf-8"), encoding="utf-8")

    n_ext = sum(1 for r in counted if (r.get("D") or {}).get("dc_extension_1618", {}).get("pass"))
    n_fib = sum(1 for r in counted if (r.get("D") or {}).get("fib_retracement", {}).get("ok"))
    n_week = sum(1 for r in counted if (r.get("E") or {}).get("outer", {}).get("2330_weekly_tail"))

    md = [
        "# 序C｜度量與 DC／經典指引（我估）第一批",
        "",
        f"寫入：`{_now_tp().isoformat()}`（Asia/Taipei）。",
        f"種子日 n={len(SEED_DAYS)}；有記 n={len(counted)}。",
        f"Fib 回撤可算 n={n_fib}；擴延1618 過閘 n={n_ext}；台積周線尾 n={n_week}。",
        "",
        "鍋：**DC→我估**（Fib／等長／交替／擴延閘／前端傾斜候選）。他說只附種子原文。",
        "末端傾斜教材未齊 → 跳過。不是買訊。不准寫回黃金買點／海選／洞燭。",
        "",
        f"JSONL：`{alias.relative_to(ROOT)}`",
        "",
    ]
    for r in counted:
        a = r["A"]
        d = r["D"]
        fib = d.get("fib_retracement") or {}
        ext = d.get("dc_extension_1618") or {}
        md.append(f"## {a['event_date']} {a.get('event_time_taipei') or ''} {a['symbol']}".rstrip())
        md.append("")
        md.append(f"- **A** {a.get('level_hypothesis')}")
        md.append(f"  - 他說（附）：{a.get('said')}")
        levels = fib.get("levels") or {}
        if levels:
            lv_s = "／".join(f"{k}={v:.0f}" for k, v in levels.items())
            md.append(f"- **D Fib回撤**（{fib.get('direction')}；高{fib.get('swing_high')} 低{fib.get('swing_low')}）：{lv_s}")
        else:
            md.append("- **D Fib回撤**：缺")
        md.append(
            f"- **D 擴延1618**：pass={ext.get('pass')} ratio={ext.get('ratio')} "
            f"longest={ext.get('longest')} variant={ext.get('variant')}"
        )
        eq = d.get("wave_equality") or {}
        alt = d.get("alternation_2_4") or {}
        md.append(
            f"- **D 等長／交替**：equalish={eq.get('equalish')} ratio={eq.get('ratio')}；"
            f"alternates={alt.get('alternates')} ({alt.get('w2_kind')}/{alt.get('w4_kind')})"
        )
        ld = d.get("dc_leading_diagonal") or {}
        md.append(f"- **D 前端傾斜**：candidate={ld.get('candidate')} confirmed={ld.get('confirmed')}")
        gaps = (r.get("flags") or {}).get("missing_bars") or []
        if gaps:
            md.append("- **缺**：" + "；".join(gaps[:4]) + ("…" if len(gaps) > 4 else ""))
        md.append("")

    md_path = OUT_DIR / "seq_c_measure_latest.md"
    md_path.write_text("\n".join(md) + "\n", encoding="utf-8")
    summary = {
        "written_at": _now_tp().isoformat(),
        "tz": "Asia/Taipei",
        "n_seed": len(SEED_DAYS),
        "n_counted": len(counted),
        "n_fib_ok": n_fib,
        "n_ext1618_pass": n_ext,
        "n_weekly_2330": n_week,
        "jsonl": str(alias.relative_to(ROOT)),
        "md": str(md_path.relative_to(ROOT)),
        "not_buy_signal": True,
        "pot": "DC→我估",
        "skipped": ["dc_ending_diagonal_curriculum"],
    }
    (OUT_DIR / "seq_c_measure_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(summary, ensure_ascii=False))
    return 0 if counted else 1


if __name__ == "__main__":
    raise SystemExit(main())
