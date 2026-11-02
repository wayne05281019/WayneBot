#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""十年回測旁路｜序B：他點過的大盤日對質批次（每日 A→H 紀錄欄）。

種子日來自 knowhow／timeline JSONL（有老師答案優先）。
近窗照片讀 ``data/decade_lab.db``／``index_daily``；缺柱標缺；不數發明浪號。
三鍋分標。不是買訊。
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
LAB_DB = Path(ROOT / "data" / "decade_lab.db")
MARKET_DB = Path(ROOT / "data" / "wayne_market.db")
OUT_DIR = ROOT / "docs" / "expert_notes" / "飆客" / "decade_lab"
TP = ZoneInfo("Asia/Taipei")

# 第一小波：他點過、knowhow 已有判定的大盤日（台北）
SEED_DAYS: List[Dict[str, Any]] = [
    {
        "event_date": "2026-07-16",
        "event_time": "夜",
        "symbol": "TWII",
        "level_hypothesis": "B-a 多標籤並存（B-a-2／B-a-4／A-c）",
        "said": "三種標籤並存；台積電量價→B-a-2 九成；絕對不可能破 40000",
        "alive_labels": [
            {"label": "B-a-2", "kill": "跌破他設下降壓且台積量價否決"},
            {"label": "B-a-4", "kill": "結構走完後無法延續"},
            {"label": "A-c擴延", "kill": "夜盤有效穿刺下降壓"},
        ],
        "teacher_verdict_hint": "多標籤對；不破40000錯",
        "source_ref": "knowhow.md §A 2026-07",
    },
    {
        "event_date": "2026-07-24",
        "event_time": "18:31",
        "symbol": "TWII",
        "level_hypothesis": "B-a-2 完成＝當日最低",
        "said": "夜盤 B-a-2 完成則今天最低",
        "alive_labels": [
            {"label": "B-a-2完成", "kill": "後續日創新低"},
            {"label": "仍在主跌", "kill": "站回下降壓且台積量價翻多"},
        ],
        "teacher_verdict_hint": "錯，後面深得多（7/29 低39385）",
        "source_ref": "knowhow.md §A 2026-07",
    },
    {
        "event_date": "2026-07-28",
        "event_time": "00:12",
        "symbol": "TWII",
        "level_hypothesis": "細微波 5-3 走完；台積已跌完",
        "said": "細微波 5-3 走完；台積電已跌完",
        "alive_labels": [
            {"label": "5-3完成", "kill": "台積／加權續創新低"},
            {"label": "末跌未完", "kill": "兩根確認止跌＋量價"},
        ],
        "teacher_verdict_hint": "偏早1～2日",
        "source_ref": "knowhow.md §A 2026-07",
    },
    {
        "event_date": "2026-07-29",
        "event_time": "17:54",
        "symbol": "TWII",
        "level_hypothesis": "A波低＝次級四浪價區＋下跌5",
        "said": "夜盤過第一關40816；第一次回測波浪四點價區；後確認A波低39384",
        "alive_labels": [
            {"label": "A波低", "kill": "收盤後續破低且無兩根翻"},
            {"label": "仍可擴延", "kill": "台積＋金融商品量價100%確認"},
        ],
        "teacher_verdict_hint": "低點確認對（庫內39385）",
        "source_ref": "knowhow.md §A 2026-07",
    },
    {
        "event_date": "2026-06-26",
        "event_time": "00:09",
        "symbol": "TWII",
        "level_hypothesis": "A-a 超過八成跌完（夜盤改口）",
        "said": "更正：夜盤跌不下去，A-a 超過 8 成跌完",
        "alive_labels": [
            {"label": "A-a近完", "kill": "日盤續探新低"},
            {"label": "夜盤領先失效", "kill": "日盤同向確認"},
        ],
        "teacher_verdict_hint": "夜盤改口偏早，日盤還有一段（低44454）",
        "source_ref": "knowhow.md §B 2026-06",
    },
    {
        "event_date": "2025-03-04",
        "event_time": "",
        "symbol": "TWII",
        "level_hypothesis": "細微波主跌完、估破22000",
        "said": "細微波主跌完、估破 22000",
        "alive_labels": [
            {"label": "主跌完近22000", "kill": "深破且續跌"},
            {"label": "主跌未完", "kill": "1-4重疊＋站回"},
        ],
        "teacher_verdict_hint": "方向對，22000偏高；他自己改口20696",
        "source_ref": "knowhow.md §D",
    },
    {
        "event_date": "2025-09-26",
        "event_time": "",
        "symbol": "TWII",
        "level_hypothesis": "15分5波下跌、測25174",
        "said": "15 分 5 波下跌、測 25174",
        "alive_labels": [
            {"label": "穿頭破底續跌", "kill": "未破25174且回升"},
            {"label": "假跌破整理", "kill": "破低站不回"},
        ],
        "teacher_verdict_hint": "穿頭破底沒發生",
        "source_ref": "knowhow.md §D",
    },
    {
        "event_date": "2026-02-02",
        "event_time": "",
        "symbol": "TWII",
        "level_hypothesis": "周五夜盤擴延沒算到、測31200",
        "said": "周五夜盤擴延沒算到、測 31200",
        "alive_labels": [
            {"label": "擴延測31200", "kill": "未觸及即V轉"},
            {"label": "已數完", "kill": "夜盤續創新低"},
        ],
        "teacher_verdict_hint": "他自己認錯擴延",
        "source_ref": "knowhow.md §D",
    },
]


def _ymd(s: str) -> str:
    return str(s or "").replace("-", "")[:8]


def _load_bars(symbol: str, as_of: str, window: int = 8) -> Tuple[List[Dict[str, Any]], List[str]]:
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
                WHERE symbol=? AND adj_kind='raw_quote' AND date<=?
                ORDER BY date DESC LIMIT ?
                """,
                (symbol, ymd, window),
            )
            rows = [dict(r) for r in cur.fetchall()]
            rows.reverse()
        finally:
            con.close()
    if not rows and MARKET_DB.exists() and symbol == "TWII":
        con = sqlite3.connect(f"file:{MARKET_DB}?mode=ro", uri=True)
        con.row_factory = sqlite3.Row
        try:
            cur = con.execute(
                """
                SELECT date, open, high, low, close, volume FROM index_daily
                WHERE symbol='TWII' AND date<=?
                ORDER BY date DESC LIMIT ?
                """,
                (ymd, window),
            )
            rows = [dict(r) for r in cur.fetchall()]
            rows.reverse()
        finally:
            con.close()
    if not rows:
        gaps.append(f"缺柱：{symbol} as_of≤{ymd} 近窗空")
    else:
        # 當日是否有柱
        if rows[-1]["date"] != ymd:
            # 找是否剛好缺當日
            gaps.append(
                f"缺柱或休市：{symbol} 請求日 {ymd}；近窗末日 {rows[-1]['date']}（不腦補當日收）"
            )
    return rows, gaps


def _tx_sessions(as_of: str) -> Tuple[Dict[str, Any], List[str]]:
    gaps: List[str] = []
    ymd = _ymd(as_of)
    out: Dict[str, Any] = {}
    if not MARKET_DB.exists():
        gaps.append("缺：wayne_market.db")
        return out, gaps
    con = sqlite3.connect(f"file:{MARKET_DB}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    try:
        for sess in ("regular", "night"):
            r = con.execute(
                """
                SELECT date, session, open, high, low, close, volume, contract_month
                FROM futures_daily WHERE symbol='TX' AND session=? AND date=?
                """,
                (sess, ymd),
            ).fetchone()
            if r:
                out[sess] = dict(r)
            else:
                gaps.append(f"缺柱：TX {sess} {ymd}")
    finally:
        con.close()
    return out, gaps


def _tsmc_bar(as_of: str) -> Tuple[Optional[Dict[str, Any]], List[str]]:
    gaps: List[str] = []
    ymd = _ymd(as_of)
    if LAB_DB.exists():
        con = sqlite3.connect(f"file:{LAB_DB}?mode=ro", uri=True)
        con.row_factory = sqlite3.Row
        try:
            r = con.execute(
                """
                SELECT date, open, high, low, close, volume, adj_kind FROM lab_daily
                WHERE symbol='2330' AND adj_kind='raw_quote' AND date=?
                """,
                (ymd,),
            ).fetchone()
            if r:
                return dict(r), gaps
        finally:
            con.close()
    gaps.append(f"缺柱：2330 {ymd}")
    return None, gaps


def _sox_bar(as_of: str) -> Tuple[Optional[Dict[str, Any]], List[str]]:
    """美股已收對台北日：嚴格早於台北日的最近 SOX session。"""
    gaps: List[str] = []
    ymd = _ymd(as_of)
    if not LAB_DB.exists():
        gaps.append("缺：decade_lab.db SOX")
        return None, gaps
    con = sqlite3.connect(f"file:{LAB_DB}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    try:
        r = con.execute(
            """
            SELECT date, open, high, low, close, volume FROM lab_daily
            WHERE symbol='SOX' AND adj_kind='raw_quote' AND date<?
            ORDER BY date DESC LIMIT 1
            """,
            (ymd,),
        ).fetchone()
        if not r:
            gaps.append(f"缺柱：SOX prior to {ymd}")
            return None, gaps
        return dict(r), gaps
    finally:
        con.close()


def _map_outcome(hint: str) -> str:
    h = hint or ""
    if "改口" in h or "認錯" in h:
        return "他改口"
    if "錯" in h or "偏早" in h or "偏高" in h or "沒發生" in h:
        return "偏"
    if "對" in h or "確認對" in h or "完全同" in h:
        return "對"
    return "未完"


def _form_record(seed: Dict[str, Any]) -> Dict[str, Any]:
    as_of = seed["event_date"]
    symbol = seed.get("symbol") or "TWII"
    bars, gap_bars = _load_bars(symbol, as_of, window=8)
    tx, gap_tx = _tx_sessions(as_of)
    tsmc, gap_tsmc = _tsmc_bar(as_of)
    sox, gap_sox = _sox_bar(as_of)
    all_gaps = gap_bars + gap_tx + gap_tsmc + gap_sox

    near = [
        {
            "date": b["date"],
            "o": b.get("open"),
            "h": b.get("high"),
            "l": b.get("low"),
            "c": b.get("close"),
            "v": b.get("volume"),
        }
        for b in bars
    ]
    outcome = _map_outcome(seed.get("teacher_verdict_hint") or "")
    # H：一條可操作修正（實驗室；負結果也記）
    if outcome in ("偏", "他改口"):
        fix = "硬句／當日最低類主張必須留殺條件；確認常晚1～2日；負結果保留進年表"
    elif outcome == "對":
        fix = "低點確認要叠台積量價＋已點位碰到；不單靠浪號"
    else:
        fix = "樣本未完；只記已點位與缺柱，不發明新價"

    # D 閘：本小波不做 Fib/DC 計算（教材未齊／防混鍋），只記分鍋狀態
    d_gate = {
        "iron_rules": "本小波未重算③非最短／1-4重疊／⑤＞B；只對他已點位",
        "fib": "跳過（序C）",
        "dc": "跳過（末端教材未齊；DC→我估不准冒充他說）",
        "pot_split": True,
    }

    record = {
        "A": {
            "event_date": as_of,
            "event_time_taipei": seed.get("event_time") or "",
            "symbol": symbol,
            "level_hypothesis": seed.get("level_hypothesis"),
            "said": seed.get("said"),
            "source_ref": seed.get("source_ref"),
        },
        "B": {
            "alive_labels": (seed.get("alive_labels") or [])[:3],
        },
        "C": {
            "near_window_ohlcv": near,
            "window_n": len(near),
        },
        "D": d_gate,
        "E": {
            "volume_price_story": "見台積當日量價列；無量／爆量本小波只附柱不編故事碼全集",
            "outer": {
                "2330": tsmc,
                "TX": tx,
                "SOX_prior_us_session": sox,
            },
        },
        "F": {
            "teacher_claim_pot": "他說／飆預測",
            "lab_pot": "實驗室",
            "dc_estimate_pot": "DC→我估（本列未用）",
        },
        "G": {
            "outcome": outcome,
            "teacher_verdict_hint": seed.get("teacher_verdict_hint"),
        },
        "H": {
            "actionable_fix": fix,
            "negative_logged": outcome in ("偏", "他改口"),
        },
        "flags": {
            "missing_bars": all_gaps,
            "missing_curriculum": [],
            "as_of_cutoff": f"{_ymd(as_of)} 收盤後可知；盤中未收不當收",
            "limit_up_down": None,
            "settlement_week": None,
            "gap_open": None,
        },
        "meta": {
            "written_at": datetime.now(TP).isoformat(),
            "tz": "Asia/Taipei",
            "not_buy_signal": True,
            "batch": "B0_seed_wave1",
        },
    }
    # 空代號／空近窗＝不算有記
    record["counted"] = bool(symbol) and len(near) > 0
    return record


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    records = [_form_record(s) for s in SEED_DAYS]
    counted = [r for r in records if r.get("counted")]
    stamp = datetime.now(TP).strftime("%Y%m%d")
    out_jsonl = OUT_DIR / f"market_confront_AH_{stamp}.jsonl"
    with out_jsonl.open("w", encoding="utf-8") as f:
        for r in counted:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    alias = OUT_DIR / "market_confront_AH_latest.jsonl"
    alias.write_text(out_jsonl.read_text(encoding="utf-8"), encoding="utf-8")

    # 人類可讀逐日
    md_lines = [
        "# 序B｜大盤日對質批次（第一小波 A→H）",
        "",
        f"寫入：`{datetime.now(TP).isoformat()}`（Asia/Taipei）。",
        f"種子日 n={len(SEED_DAYS)}；有記（非空近窗）n={len(counted)}。",
        "鍋：他說＝原文主張；實驗室＝結局／修正；DC→我估本列未用。",
        "",
        "不是買訊。",
        "",
    ]
    for r in counted:
        a = r["A"]
        md_lines.append(f"## {a['event_date']} {a.get('event_time_taipei') or ''} {a['symbol']}".rstrip())
        md_lines.append("")
        md_lines.append(f"- **A** 級別假設：{a.get('level_hypothesis')}")
        md_lines.append(f"  - 他說：{a.get('said')}")
        labels = r["B"]["alive_labels"]
        md_lines.append(
            "- **B** 存活標籤："
            + "；".join(f"{x['label']}（殺：{x['kill']}）" for x in labels)
        )
        near = r["C"]["near_window_ohlcv"]
        if near:
            last = near[-1]
            md_lines.append(
                f"- **C** 近窗末日 {last['date']} OHLCV "
                f"{last['o']}/{last['h']}/{last['l']}/{last['c']}/{last['v']}（共{len(near)}根）"
            )
        else:
            md_lines.append("- **C** 缺柱")
        md_lines.append(
            f"- **D** 鐵律／Fib／DC：{r['D']['iron_rules']}；Fib={r['D']['fib']}；DC={r['D']['dc']}"
        )
        md_lines.append(
            f"- **E** 外圍：2330={'有' if r['E']['outer'].get('2330') else '缺'}；"
            f"TX日={'有' if r['E']['outer'].get('TX',{}).get('regular') else '缺'}；"
            f"TX夜={'有' if r['E']['outer'].get('TX',{}).get('night') else '缺'}；"
            f"SOX先={'有' if r['E']['outer'].get('SOX_prior_us_session') else '缺'}"
        )
        md_lines.append(
            f"- **F** 鍋：{r['F']['teacher_claim_pot']}｜{r['F']['lab_pot']}｜{r['F']['dc_estimate_pot']}"
        )
        md_lines.append(
            f"- **G** 結局：{r['G']['outcome']}（{r['G'].get('teacher_verdict_hint')}）"
        )
        md_lines.append(f"- **H** 修正：{r['H']['actionable_fix']}")
        flags = r["flags"].get("missing_bars") or []
        if flags:
            md_lines.append("- **缺柱／缺窗**：" + "；".join(flags[:6]))
        md_lines.append("")

    md_path = OUT_DIR / "market_confront_AH_latest.md"
    md_path.write_text("\n".join(md_lines), encoding="utf-8")
    summary = {
        "written_at": datetime.now(TP).isoformat(),
        "n_seed": len(SEED_DAYS),
        "n_counted": len(counted),
        "jsonl": str(alias.relative_to(ROOT)),
        "md": str(md_path.relative_to(ROOT)),
    }
    (OUT_DIR / "market_confront_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(summary, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
