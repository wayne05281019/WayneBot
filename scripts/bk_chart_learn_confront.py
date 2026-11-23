#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""BK-CHART：圖標價／結構抽出後，對近窗官方開高低收＋量（照片窗，非只最後一根）。

三鍋標籤（不准混）：
  - 他圖：他附圖／口述位寫在圖上的標價、趨勢線、浪標
  - 官方：庫內 TWII／TX regular 完整日柱（盤中未收不當收）
  - 試標推論：跨時期互比後的可重用觀盤規則（非他原文、非買訊）

Asia/Taipei。不改買訊、不進產品敘事。
"""
from __future__ import annotations

import argparse
import json
import sqlite3
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple
from zoneinfo import ZoneInfo

TAIPEI = ZoneInfo("Asia/Taipei")
POT_HIS = "他圖"
POT_OFFICIAL = "官方"
POT_INFER = "試標推論"

# 近窗＝照片：標價當日前後各 N 個交易日（含當日）。
# 結構圖常回指前波低（如 44210＝8/25），半窗 8 才能蓋到「他標的那張照片」而不是只貼最近一根。
DEFAULT_HALF_WINDOW = 8

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB = ROOT / "data" / "wayne_market.db"
DEFAULT_OUT = (
    ROOT
    / "docs"
    / "expert_notes"
    / "飆客"
    / "observe_manual"
    / "chart_learn_latest.json"
)


@dataclass(frozen=True)
class ChartMark:
    """一條從圖／圖註抽出的標價或結構。"""

    chart_id: str
    as_of: str  # YYYYMMDD 圖／文基準日（台北）
    theme: str
    mark_kind: str  # price_label | trend_line | channel_band | wave_label | note
    value: Optional[float]
    label: str
    instrument_hint: str  # TWII | TX | mixed | unknown
    source_path: str
    pot: str = POT_HIS
    extras: Dict[str, Any] = field(default_factory=dict)


@dataclass
class Bar:
    date: str  # YYYYMMDD
    open: Optional[float]
    high: float
    low: float
    close: float
    volume: Optional[float]
    symbol: str
    session: str = ""


@dataclass
class ConfrontRow:
    mark: ChartMark
    symbol: str
    window_dates: List[str]
    hit_bars: List[Dict[str, Any]]
    nearest: Optional[Dict[str, Any]]
    verdict: str  # 對 | 偏 | 還沒走完
    pot_official: str = POT_OFFICIAL
    note: str = ""


# ---------------------------------------------------------------------------
# 他圖抽出（只記圖上／已落地圖註看得到的，不准發明）
# ---------------------------------------------------------------------------

CHART_MARKS: List[ChartMark] = [
    # 2026-07-23 60m 加權附圖
    ChartMark(
        "src_20260723_60m",
        "20260723",
        "descent_pressure_Bwave",
        "price_label",
        48218.87,
        "60m 波段高 48218.87",
        "TWII",
        "docs/expert_notes/飆客/sources/20260723_60m_chart.jpg",
    ),
    ChartMark(
        "src_20260723_60m",
        "20260723",
        "descent_pressure_Bwave",
        "price_label",
        41967.75,
        "60m 波段低 41967.75",
        "TWII",
        "docs/expert_notes/飆客/sources/20260723_60m_chart.jpg",
    ),
    ChartMark(
        "src_20260723_60m",
        "20260723",
        "descent_pressure_Bwave",
        "trend_line",
        None,
        "下降壓力線（連 6 月末高→7 月一串更低高）",
        "TWII",
        "docs/expert_notes/飆客/sources/20260723_60m_chart.jpg",
        extras={"geometry": "descending_resistance"},
    ),
    ChartMark(
        "src_20260723_60m",
        "20260723",
        "descent_pressure_Bwave",
        "wave_label",
        None,
        "文配圖：B-a-2 或 B-a-4（當時分不清）",
        "TWII",
        "docs/expert_notes/飆客/sources/20260723_60m_chart.jpg",
        extras={"wave_candidates": ["B-a-2", "B-a-4"]},
    ),
    # 2026-07-29 15m 台指近月（空代號圖＝指數期）
    ChartMark(
        "cmoney_20260729_tx15m",
        "20260729",
        "july_crash_A_low",
        "price_label",
        45364.0,
        "15m 波段高 45364",
        "TX",
        "chart_index:aid=181132138",
    ),
    ChartMark(
        "cmoney_20260729_tx15m",
        "20260729",
        "july_crash_A_low",
        "price_label",
        39442.0,
        "15m 波段低 39442",
        "TX",
        "chart_index:aid=181132138",
    ),
    ChartMark(
        "cmoney_20260729_tx15m",
        "20260729",
        "july_crash_A_low",
        "price_label",
        40807.4,
        "水平線 ~40807（當下翻上測試）",
        "TX",
        "chart_index:aid=181132138",
    ),
    ChartMark(
        "cmoney_20260729_tx15m",
        "20260729",
        "july_crash_A_low",
        "trend_line",
        None,
        "多條加速下降壓力線（主／次／末殺扇形）",
        "TX",
        "chart_index:aid=181132138",
        extras={"geometry": "descending_fan"},
    ),
    # 庫內重畫對照圖（標的仍是他口述位，來源標他圖）
    ChartMark(
        "index_levels_20260731",
        "20260731",
        "july_crash_A_low",
        "price_label",
        41967.0,
        "41967 現貨／60m 低",
        "TWII",
        "docs/expert_notes/飆客/charts/index_levels_20260731.png",
    ),
    ChartMark(
        "index_levels_20260731",
        "20260731",
        "july_crash_A_low",
        "price_label",
        40816.0,
        "40816 夜盤第一關（口述）",
        "mixed",
        "docs/expert_notes/飆客/charts/index_levels_20260731.png",
    ),
    ChartMark(
        "index_levels_20260731",
        "20260731",
        "july_crash_A_low",
        "price_label",
        39385.0,
        "39385 A 波低（現貨）",
        "TWII",
        "docs/expert_notes/飆客/charts/index_levels_20260731.png",
    ),
    # 細微波位階帶（9/2・9/9 同主題）
    ChartMark(
        "index_levels_20260902",
        "20260902",
        "micro_wave_band",
        "price_label",
        46746.0,
        "46746 穿刺才不走 9 段（更正）",
        "TX",
        "docs/expert_notes/飆客/charts/index_levels_20260902.png",
    ),
    ChartMark(
        "index_levels_20260902",
        "20260902",
        "micro_wave_band",
        "channel_band",
        46250.0,
        "46250～46300 夜盤突破帶",
        "TX",
        "docs/expert_notes/飆客/charts/index_levels_20260902.png",
        extras={"band_hi": 46300.0},
    ),
    ChartMark(
        "index_levels_20260902",
        "20260902",
        "micro_wave_band",
        "price_label",
        45415.0,
        "45415 前波低／修正目標",
        "TX",
        "docs/expert_notes/飆客/charts/index_levels_20260902.png",
    ),
    ChartMark(
        "index_levels_20260902",
        "20260902",
        "micro_wave_band",
        "price_label",
        44210.0,
        "44210 更深前低（9 段走完才清楚）",
        "TWII",
        "docs/expert_notes/飆客/charts/index_levels_20260902.png",
    ),
    ChartMark(
        "index_levels_20260902",
        "20260902",
        "micro_wave_band",
        "wave_label",
        None,
        "細微波已跌 7 段；穿刺 46746 才不走 9 段",
        "TX",
        "docs/expert_notes/飆客/charts/index_levels_20260902.png",
        extras={"down_legs_claimed": 7, "full_legs": 9},
    ),
    ChartMark(
        "index_levels_20260909",
        "20260909",
        "micro_wave_band",
        "price_label",
        46746.0,
        "46746（同主題延續）",
        "TX",
        "docs/expert_notes/飆客/charts/index_levels_20260909.png",
    ),
    ChartMark(
        "index_levels_20260909",
        "20260909",
        "micro_wave_band",
        "channel_band",
        46300.0,
        "46300 帶上緣（同主題延續）",
        "TX",
        "docs/expert_notes/飆客/charts/index_levels_20260909.png",
        extras={"band_lo": 46250.0},
    ),
    ChartMark(
        "index_levels_20260909",
        "20260909",
        "micro_wave_band",
        "price_label",
        45415.0,
        "45415（同主題延續）",
        "TX",
        "docs/expert_notes/飆客/charts/index_levels_20260909.png",
    ),
    ChartMark(
        "index_levels_20260909",
        "20260909",
        "micro_wave_band",
        "price_label",
        44210.0,
        "44210（同主題延續）",
        "TWII",
        "docs/expert_notes/飆客/charts/index_levels_20260909.png",
    ),
]


def ymd_compact(s: str) -> str:
    t = str(s).strip().replace("-", "").replace("/", "")[:8]
    if len(t) != 8 or not t.isdigit():
        raise ValueError(f"bad ymd: {s!r}")
    return t


def today_taipei_ymd() -> str:
    return datetime.now(TAIPEI).strftime("%Y%m%d")


def _bar_complete(bar: Bar, *, as_of_today: Optional[str] = None) -> bool:
    """盤中未收不當收：若 bar.date == 今日台北日，視為未完整。"""
    today = as_of_today or today_taipei_ymd()
    return bar.date < today


def load_twii_bars(conn: sqlite3.Connection, d0: str, d1: str) -> List[Bar]:
    d0, d1 = ymd_compact(d0), ymd_compact(d1)
    rows = conn.execute(
        """
        SELECT date, open, high, low, close, volume
        FROM index_daily
        WHERE symbol='TWII' AND date BETWEEN ? AND ?
        ORDER BY date
        """,
        (d0, d1),
    ).fetchall()
    out: List[Bar] = []
    for d, o, h, lo, c, v in rows:
        if h is None or lo is None or c is None:
            continue
        out.append(
            Bar(
                date=ymd_compact(d),
                open=float(o) if o is not None else None,
                high=float(h),
                low=float(lo),
                close=float(c),
                volume=float(v) if v is not None else None,
                symbol="TWII",
            )
        )
    return out


def load_tx_bars(
    conn: sqlite3.Connection, d0: str, d1: str, *, session: str = "regular"
) -> List[Bar]:
    d0, d1 = ymd_compact(d0), ymd_compact(d1)
    rows = conn.execute(
        """
        SELECT date, open, high, low, close, volume
        FROM futures_daily
        WHERE symbol='TX' AND session=? AND date BETWEEN ? AND ?
        ORDER BY date
        """,
        (session, d0, d1),
    ).fetchall()
    out: List[Bar] = []
    for d, o, h, lo, c, v in rows:
        if h is None or lo is None or c is None:
            continue
        out.append(
            Bar(
                date=ymd_compact(d),
                open=float(o) if o is not None else None,
                high=float(h),
                low=float(lo),
                close=float(c),
                volume=float(v) if v is not None else None,
                symbol="TX",
                session=session,
            )
        )
    return out


def list_trading_dates(conn: sqlite3.Connection, symbol: str = "TWII") -> List[str]:
    if symbol == "TX":
        rows = conn.execute(
            """
            SELECT DISTINCT date FROM futures_daily
            WHERE symbol='TX' AND session='regular' ORDER BY date
            """
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT DISTINCT date FROM index_daily WHERE symbol='TWII' ORDER BY date"
        ).fetchall()
    return [ymd_compact(r[0]) for r in rows]


def near_window_dates(
    all_dates: Sequence[str],
    center: str,
    *,
    half: int = DEFAULT_HALF_WINDOW,
) -> List[str]:
    """以 center 為中心取前後各 half 個交易日（含 center）；center 非交易日則取最近左側。"""
    center = ymd_compact(center)
    if not all_dates:
        return []
    if center in all_dates:
        i = list(all_dates).index(center)
    else:
        left = [d for d in all_dates if d <= center]
        if not left:
            return []
        i = list(all_dates).index(left[-1])
    lo = max(0, i - half)
    hi = min(len(all_dates), i + half + 1)
    return list(all_dates[lo:hi])


def bar_touches(bar: Bar, level: float, *, tol: float = 0.0) -> bool:
    return (bar.low - tol) <= level <= (bar.high + tol)


def nearest_bar_to_level(bars: Sequence[Bar], level: float) -> Optional[Dict[str, Any]]:
    if not bars:
        return None
    best = None
    best_dist = None
    for b in bars:
        if b.low <= level <= b.high:
            dist = 0.0
        else:
            dist = min(abs(b.low - level), abs(b.high - level))
        if best_dist is None or dist < best_dist:
            best_dist = dist
            best = {
                "date": b.date,
                "open": b.open,
                "high": b.high,
                "low": b.low,
                "close": b.close,
                "volume": b.volume,
                "dist": round(float(best_dist), 4),
                "pct_of_level": round(float(best_dist) / level * 100.0, 4) if level else None,
            }
    return best


def confront_price_mark(
    mark: ChartMark,
    bars: Sequence[Bar],
    *,
    as_of_today: Optional[str] = None,
    touch_tol_pct: float = 0.15,
) -> ConfrontRow:
    """對單一標價：近窗有完整柱碰到＝對；距 < tol%＝偏；否則還沒走完／未觸。"""
    today = as_of_today or today_taipei_ymd()
    complete = [b for b in bars if _bar_complete(b, as_of_today=today)]
    level = float(mark.value or 0.0)
    tol = level * touch_tol_pct / 100.0
    hits = []
    for b in complete:
        if bar_touches(b, level, tol=tol):
            hits.append(
                {
                    "date": b.date,
                    "open": b.open,
                    "high": b.high,
                    "low": b.low,
                    "close": b.close,
                    "volume": b.volume,
                }
            )
    nearest = nearest_bar_to_level(complete, level)
    symbol = bars[0].symbol if bars else mark.instrument_hint

    if hits:
        # 精確命中＝對；僅靠 tol 擦到但距 ≤1 點／≤0.05%（指數取整噪音）仍算對
        exact = any(h["low"] <= level <= h["high"] for h in hits)
        dist = float((nearest or {}).get("dist") or 0.0)
        pct = float((nearest or {}).get("pct_of_level") or 99.0)
        if exact or dist <= 1.0 or pct <= 0.05:
            verdict = "對"
        else:
            verdict = "偏"
        note = f"近窗命中 {len(hits)} 根完整柱"
    elif nearest is None:
        verdict = "還沒走完"
        note = "近窗無完整官方柱可對"
    else:
        pct = nearest.get("pct_of_level") or 99.0
        if pct <= touch_tol_pct:
            verdict = "偏"
            note = f"最近完整柱距 {nearest['dist']}（{pct}%）"
        elif mark.as_of >= today:
            verdict = "還沒走完"
            note = "基準日尚未走完／缺後續完整柱"
        else:
            # 基準日已過、近窗未觸 → 可能是更深／更晚才觸，或標的口徑不同
            if nearest["date"] > mark.as_of and nearest["dist"] > tol * 3:
                verdict = "還沒走完"
                note = f"近窗未觸；最近距 {nearest['dist']}（事後窗另比）"
            else:
                verdict = "偏"
                note = f"近窗未觸；最近完整柱距 {nearest['dist']}（{pct}%）"

    return ConfrontRow(
        mark=mark,
        symbol=symbol,
        window_dates=[b.date for b in complete],
        hit_bars=hits,
        nearest=nearest,
        verdict=verdict,
        note=note,
    )


def pick_bars_for_mark(
    conn: sqlite3.Connection,
    mark: ChartMark,
    *,
    half: int = DEFAULT_HALF_WINDOW,
) -> Tuple[str, List[Bar]]:
    hint = mark.instrument_hint
    if hint == "TX":
        dates = list_trading_dates(conn, "TX")
        win = near_window_dates(dates, mark.as_of, half=half)
        if not win:
            return "TX", []
        return "TX", load_tx_bars(conn, win[0], win[-1])
    if hint == "TWII":
        dates = list_trading_dates(conn, "TWII")
        win = near_window_dates(dates, mark.as_of, half=half)
        if not win:
            return "TWII", []
        return "TWII", load_twii_bars(conn, win[0], win[-1])
    # mixed：兩邊都取，優先 TX（夜盤位階常是期）再 TWII
    dates = list_trading_dates(conn, "TX")
    win = near_window_dates(dates, mark.as_of, half=half)
    if win:
        return "TX", load_tx_bars(conn, win[0], win[-1])
    dates = list_trading_dates(conn, "TWII")
    win = near_window_dates(dates, mark.as_of, half=half)
    if not win:
        return "mixed", []
    return "TWII", load_twii_bars(conn, win[0], win[-1])


def cross_theme_compare(rows: Sequence[ConfrontRow]) -> List[Dict[str, Any]]:
    """同主題跨時期互比（他圖標價是否沿用、官方後續是否確認）。"""
    by_theme: Dict[str, List[ConfrontRow]] = {}
    for r in rows:
        if r.mark.mark_kind not in ("price_label", "channel_band"):
            continue
        by_theme.setdefault(r.mark.theme, []).append(r)
    out: List[Dict[str, Any]] = []
    for theme, items in sorted(by_theme.items()):
        levels = sorted(
            {
                round(float(i.mark.value), 2)
                for i in items
                if i.mark.value is not None
            }
        )
        as_ofs = sorted({i.mark.as_of for i in items})
        verdicts = {i.verdict for i in items}
        reused = len(as_ofs) >= 2
        out.append(
            {
                "theme": theme,
                "as_of_list": as_ofs,
                "levels": levels,
                "reused_across_periods": reused,
                "verdicts": sorted(verdicts),
                "pot": POT_INFER,
                "note": (
                    "同主題多日圖重複標同一帶＝他當框架沿用"
                    if reused
                    else "單期圖；跨期互比材料不足"
                ),
            }
        )
    return out


OPERABLE_RULES: List[Dict[str, Any]] = [
    {
        "id": "R1_multi_tf_descent_line",
        "pot": POT_INFER,
        "rule": "大盤用 60 分畫下降壓力線判斷「是否仍在 B 波修正內」；日線官方柱驗證高低與收盤趨勢，不以 60m 極值硬套日線收盤。",
        "evidence_charts": ["src_20260723_60m", "index_levels_20260723"],
        "not_his_literal": True,
    },
    {
        "id": "R2_dual_wave_label_until_depth",
        "pot": POT_INFER,
        "rule": "結構分不清時圖上可並標兩種浪標（如 B-a-2／B-a-4）；事後用「修正深度」歸類，不准假裝當時已確定。",
        "evidence_charts": ["src_20260723_60m"],
        "not_his_literal": True,
    },
    {
        "id": "R3_level_photo_near_window",
        "pot": POT_INFER,
        "rule": "圖標價對質必須用近窗官方開高低收＋量（照片），不是只盯最後一根；盤中未收不當收。",
        "evidence_charts": ["index_levels_20260902", "index_levels_20260909"],
        "not_his_literal": True,
    },
    {
        "id": "R4_tx_spot_basis_band",
        "pot": POT_INFER,
        "rule": "夜盤突破帶（46250～46300）用 TX；現貨對照約低 50～150（如 45415 期 ↔ 45450 現）。跨口徑比對時先標儀器再判。",
        "evidence_charts": ["index_levels_20260902"],
        "not_his_literal": True,
    },
    {
        "id": "R5_same_band_reuse",
        "pot": POT_INFER,
        "rule": "同支撐／壓力帶他會跨日重複標（45415／44210／46746）；觀盤時把「重複出現的帶」當框架，單日新價若無圖無文則不准發明。",
        "evidence_charts": ["index_levels_20260902", "index_levels_20260909"],
        "not_his_literal": True,
    },
    {
        "id": "R6_segment_count_vs_pierce",
        "pot": POT_INFER,
        "rule": "細微波段數（7→9）與「穿刺某價才不走滿」綁在一起：未穿刺＝更深修正路徑仍開著（還沒走完），不是當日收盤猜頂。",
        "evidence_charts": ["index_levels_20260902"],
        "not_his_literal": True,
    },
    {
        "id": "R7_intraday_fan_then_daily_seal",
        "pot": POT_INFER,
        "rule": "急殺日 15 分圖可畫加速下降扇＋水平翻關（如 39442 低、40807 水平）；日線完整柱走完才封「A 波低」口徑，未收盤不封。",
        "evidence_charts": ["cmoney_20260729_tx15m", "index_levels_20260731"],
        "not_his_literal": True,
    },
]


def run_confront(
    db_path: Path,
    *,
    half: int = DEFAULT_HALF_WINDOW,
    as_of_today: Optional[str] = None,
    marks: Optional[Sequence[ChartMark]] = None,
) -> Dict[str, Any]:
    today = as_of_today or today_taipei_ymd()
    marks = list(marks or CHART_MARKS)
    conn = sqlite3.connect(str(db_path))
    try:
        rows: List[ConfrontRow] = []
        skipped: List[Dict[str, Any]] = []
        for m in marks:
            if m.mark_kind not in ("price_label", "channel_band"):
                skipped.append(
                    {
                        "chart_id": m.chart_id,
                        "mark_kind": m.mark_kind,
                        "label": m.label,
                        "reason": "非標價／帶：只歸檔圖結構，不做價碰柱",
                        "pot": POT_HIS,
                    }
                )
                continue
            if m.value is None:
                continue
            _sym, bars = pick_bars_for_mark(conn, m, half=half)
            rows.append(
                confront_price_mark(m, bars, as_of_today=today)
            )
        themes = cross_theme_compare(rows)
    finally:
        conn.close()

    def _row_dict(r: ConfrontRow) -> Dict[str, Any]:
        return {
            "chart_id": r.mark.chart_id,
            "as_of": r.mark.as_of,
            "theme": r.mark.theme,
            "mark_kind": r.mark.mark_kind,
            "value": r.mark.value,
            "label": r.mark.label,
            "instrument_hint": r.mark.instrument_hint,
            "source_path": r.mark.source_path,
            "pot_his": r.mark.pot,
            "symbol_used": r.symbol,
            "window_dates": r.window_dates,
            "hit_bars": r.hit_bars,
            "nearest": r.nearest,
            "verdict": r.verdict,
            "pot_official": r.pot_official,
            "note": r.note,
        }

    verdict_counts: Dict[str, int] = {}
    for r in rows:
        verdict_counts[r.verdict] = verdict_counts.get(r.verdict, 0) + 1

    return {
        "track": "BK-CHART",
        "generated_at_taipei": datetime.now(TAIPEI).isoformat(timespec="seconds"),
        "as_of_today": today,
        "half_window_sessions": half,
        "pots": [POT_HIS, POT_OFFICIAL, POT_INFER],
        "warning": "試標・推論／非他原文・非買訊・對質未過閘",
        "inventory": {
            "marks_total": len(marks),
            "price_confronted": len(rows),
            "structure_archived_only": len(skipped),
            "compare_groups": len(themes),
        },
        "verdict_counts": verdict_counts,
        "confront_rows": [_row_dict(r) for r in rows],
        "structure_only": skipped,
        "cross_theme": themes,
        "operable_rules": OPERABLE_RULES,
        "gaps": [
            {
                "item": "Drive 飆大資料夾",
                "status": "只有 1709／社團 20／72 語料 md，無獨立圖包可下",
            },
            {
                "item": "chart_index.json.gz 圖檔本體",
                "status": "索引 341 則 URL 可連；git 不存圖檔本體（README／index note）。本軌已下市場相關 76 張暫存對讀，不強制入庫。",
            },
            {
                "item": "本機 biaoke_posts",
                "status": "空表；無 overlay 新附圖可抽。缺 Render 碟／正式庫圖欄。",
            },
            {
                "item": "假圖",
                "status": "不准補；缺就寫在 gaps。",
            },
        ],
    }


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="BK-CHART 圖標價近窗官方柱對質")
    ap.add_argument("--db", type=Path, default=DEFAULT_DB)
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    ap.add_argument("--half-window", type=int, default=DEFAULT_HALF_WINDOW)
    ap.add_argument(
        "--as-of-today",
        default=None,
        help="覆寫「今日」YYYYMMDD（測試用）；預設台北今天。盤中未收不當收。",
    )
    args = ap.parse_args(list(argv) if argv is not None else None)
    if not args.db.exists():
        raise SystemExit(f"missing db: {args.db}")
    payload = run_confront(
        args.db, half=args.half_window, as_of_today=args.as_of_today
    )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    # dated copy
    dated = args.out.with_name(f"chart_learn_{payload['as_of_today']}.json")
    if dated != args.out:
        dated.write_text(args.out.read_text(encoding="utf-8"), encoding="utf-8")
    print(
        json.dumps(
            {
                "out": str(args.out),
                "dated": str(dated),
                "inventory": payload["inventory"],
                "verdict_counts": payload["verdict_counts"],
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
