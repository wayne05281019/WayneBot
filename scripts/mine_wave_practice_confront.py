#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""DC→我估｜擴延1618／前端傾斜 官方柱樣例對質（對／偏／未完）。

硬邊界：
- pot=MINE；三鍋分標；不准冒充飆大原文；不准寫回黃金買點／海選／洞燭。
- 只讀已收官方柱（index_daily TWII／daily_quotes）；盤中未收不當收。
- Asia/Taipei；勝率只記我估鍋；§13 再生下一版鍵一併落檔。
- 輸出：docs/expert_notes/dc_wave/mine_practice_*.json
"""
from __future__ import annotations

import argparse
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

from mine_wave_rules import (  # noqa: E402
    RULE_NEXT_EXT,
    RULE_NEXT_LD,
    RULE_PHONE_EXT,
    RULE_PHONE_LD,
    evaluate_mine_wave_gates,
    judge_mine_practice,
    summarize_mine_practice,
)

MARKET_DB = ROOT / "data" / "wayne_market.db"
OUT_DIR = ROOT / "docs" / "expert_notes" / "dc_wave"
TP = ZoneInfo("Asia/Taipei")

# 獨立 as_of 樣例窗（台北開市日；用官方末日≤as_of）
SAMPLE_ASOFS: List[Dict[str, str]] = [
    {"symbol": "TWII", "as_of": "20240315", "kind": "index"},
    {"symbol": "TWII", "as_of": "20240628", "kind": "index"},
    {"symbol": "TWII", "as_of": "20240930", "kind": "index"},
    {"symbol": "TWII", "as_of": "20241220", "kind": "index"},
    {"symbol": "TWII", "as_of": "20250314", "kind": "index"},
    {"symbol": "TWII", "as_of": "20250630", "kind": "index"},
    {"symbol": "TWII", "as_of": "20250926", "kind": "index"},
    {"symbol": "TWII", "as_of": "20251128", "kind": "index"},
    {"symbol": "TWII", "as_of": "20260227", "kind": "index"},
    {"symbol": "TWII", "as_of": "20260529", "kind": "index"},
    {"symbol": "TWII", "as_of": "20260716", "kind": "index"},
    {"symbol": "TWII", "as_of": "20260729", "kind": "index"},
    {"symbol": "TWII", "as_of": "20260930", "kind": "index"},
    {"symbol": "TWII", "as_of": "20261106", "kind": "index"},
    {"symbol": "2330", "as_of": "20240315", "kind": "stock"},
    {"symbol": "2330", "as_of": "20240628", "kind": "stock"},
    {"symbol": "2330", "as_of": "20240930", "kind": "stock"},
    {"symbol": "2330", "as_of": "20241220", "kind": "stock"},
    {"symbol": "2330", "as_of": "20250314", "kind": "stock"},
    {"symbol": "2330", "as_of": "20250630", "kind": "stock"},
    {"symbol": "2330", "as_of": "20250926", "kind": "stock"},
    {"symbol": "2330", "as_of": "20260227", "kind": "stock"},
    {"symbol": "2330", "as_of": "20260729", "kind": "stock"},
    {"symbol": "2330", "as_of": "20261106", "kind": "stock"},
    {"symbol": "0050", "as_of": "20240628", "kind": "stock"},
    {"symbol": "0050", "as_of": "20241220", "kind": "stock"},
    {"symbol": "0050", "as_of": "20250630", "kind": "stock"},
    {"symbol": "0050", "as_of": "20261106", "kind": "stock"},
]

SWING_N = 48
POST_N = 12
PIVOT_LEFT = 2
PIVOT_RIGHT = 2


def _now_tp() -> str:
    return datetime.now(TP).strftime("%Y-%m-%dT%H:%M:%S%z")


def _f(x: Any) -> Optional[float]:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    if v != v:
        return None
    return v


def _load_bars(symbol: str, as_of: str, *, kind: str, window: int) -> Tuple[List[Dict[str, Any]], List[str]]:
    gaps: List[str] = []
    ymd = str(as_of).replace("-", "")[:8]
    if not MARKET_DB.exists():
        return [], [f"缺庫：{MARKET_DB}"]
    con = sqlite3.connect(f"file:{MARKET_DB}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    rows: List[Dict[str, Any]] = []
    try:
        if kind == "index":
            cur = con.execute(
                """
                SELECT date, open, high, low, close, volume FROM index_daily
                WHERE symbol=? AND date<=?
                ORDER BY date DESC LIMIT ?
                """,
                (symbol, ymd, window),
            )
        else:
            cur = con.execute(
                """
                SELECT date, open, high, low, close, volume FROM daily_quotes
                WHERE stock_id=? AND date<=?
                ORDER BY date DESC LIMIT ?
                """,
                (symbol, ymd, window),
            )
        rows = [dict(r) for r in cur.fetchall()]
        rows.reverse()
    finally:
        con.close()
    if not rows:
        gaps.append(f"缺柱：{symbol} ≤{ymd}")
    elif rows[-1]["date"] != ymd:
        gaps.append(f"末日≠as_of：請求{ymd} 近窗末{rows[-1]['date']}（不腦補當日收）")
    return rows, gaps


def _load_post(symbol: str, as_of: str, *, kind: str, n: int = POST_N) -> Tuple[List[Dict[str, Any]], List[str]]:
    gaps: List[str] = []
    ymd = str(as_of).replace("-", "")[:8]
    if not MARKET_DB.exists():
        return [], [f"缺庫：{MARKET_DB}"]
    con = sqlite3.connect(f"file:{MARKET_DB}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    rows: List[Dict[str, Any]] = []
    try:
        if kind == "index":
            cur = con.execute(
                """
                SELECT date, open, high, low, close, volume FROM index_daily
                WHERE symbol=? AND date>?
                ORDER BY date ASC LIMIT ?
                """,
                (symbol, ymd, n),
            )
        else:
            cur = con.execute(
                """
                SELECT date, open, high, low, close, volume FROM daily_quotes
                WHERE stock_id=? AND date>?
                ORDER BY date ASC LIMIT ?
                """,
                (symbol, ymd, n),
            )
        rows = [dict(r) for r in cur.fetchall()]
    finally:
        con.close()
    if len(rows) < 3:
        gaps.append(f"後續柱不足：{symbol}>{ymd} n={len(rows)}")
    return rows, gaps


def _local_pivots(bars: Sequence[Dict[str, Any]]) -> List[Tuple[float, str]]:
    closes: List[Tuple[str, float]] = []
    for b in bars:
        c = _f(b.get("close"))
        d = str(b.get("date") or "")
        if c is None or not d:
            continue
        closes.append((d, c))
    pivots: List[Tuple[float, str]] = []
    n = len(closes)
    left, right = PIVOT_LEFT, PIVOT_RIGHT
    for i in range(left, n - right):
        window = [closes[j][1] for j in range(i - left, i + right + 1)]
        v = closes[i][1]
        if v != max(window) and v != min(window):
            continue
        if pivots and abs(pivots[-1][0] - v) < 1e-9:
            continue
        pivots.append((v, closes[i][0]))
    return pivots


def _photo(bars: Sequence[Dict[str, Any]], n: int = 8) -> List[Dict[str, Any]]:
    tail = list(bars)[-n:]
    return [
        {
            "date": b.get("date"),
            "o": _f(b.get("open")),
            "h": _f(b.get("high")),
            "l": _f(b.get("low")),
            "c": _f(b.get("close")),
            "v": _f(b.get("volume")),
        }
        for b in tail
    ]


def _post_move_pct(anchor: float, post: Sequence[Dict[str, Any]]) -> Optional[float]:
    if anchor <= 0 or not post:
        return None
    last = _f(post[-1].get("close"))
    if last is None:
        return None
    return (last - anchor) / anchor


def confront_one(sample: Dict[str, str]) -> Dict[str, Any]:
    symbol = sample["symbol"]
    as_of = sample["as_of"]
    kind = sample["kind"]
    bars, g1 = _load_bars(symbol, as_of, kind=kind, window=SWING_N)
    post, g2 = _load_post(symbol, as_of, kind=kind, n=POST_N)
    gaps = g1 + g2
    pivots = _local_pivots(bars) if bars else []
    incomplete = len(pivots) < 3 or len(bars) < 20

    gate = evaluate_mine_wave_gates(pivots=[(p[0],) for p in pivots]) if pivots else evaluate_mine_wave_gates(lengths={})
    anchor = _f(bars[-1].get("close")) if bars else None
    move = _post_move_pct(anchor or 0.0, post) if anchor else None
    if incomplete or move is None or len(post) < 5:
        incomplete = True

    # 擴延閘：過關預期延續（收>錨）；前端傾斜 candidate 同 implication=continuation
    j_ext_v1 = judge_mine_practice(
        (gate.get("extension") or {}).get("pass"),
        post_move_pct=move,
        expect_continuation=True,
        incomplete=incomplete,
    )
    j_ext_v2 = judge_mine_practice(
        (gate.get("extension_next") or {}).get("pass"),
        post_move_pct=move,
        expect_continuation=True,
        incomplete=incomplete,
    )
    j_ld_v1 = judge_mine_practice(
        (gate.get("leading_diagonal") or {}).get("candidate"),
        post_move_pct=move,
        expect_continuation=True,
        incomplete=incomplete or (gate.get("leading_diagonal") or {}).get("w1_w4_overlap") is None,
    )
    j_ld_v2 = judge_mine_practice(
        (gate.get("leading_diagonal_next") or {}).get("candidate"),
        post_move_pct=move,
        expect_continuation=True,
        incomplete=incomplete or (gate.get("leading_diagonal_next") or {}).get("w1_w4_overlap") is None,
    )

    return {
        "symbol": symbol,
        "as_of": as_of,
        "kind": kind,
        "tz": "Asia/Taipei",
        "pot": "MINE",
        "≠biaoke": True,
        "≠golden_buy": True,
        "gaps": gaps,
        "swing_n": len(bars),
        "post_n": len(post),
        "pivots_n": len(pivots),
        "pivot_dates": [p[1] for p in pivots[-8:]],
        "near_window_ohlcv": _photo(bars),
        "post_tail_ohlcv": _photo(post, n=min(8, len(post))),
        "gate": gate,
        "judges": {
            RULE_PHONE_EXT: j_ext_v1,
            RULE_NEXT_EXT: j_ext_v2,
            RULE_PHONE_LD: j_ld_v1,
            RULE_NEXT_LD: j_ld_v2,
        },
        # 主列用現況擴延閘（話筒鍵）；下一版另軌
        "judge": j_ext_v1,
        "judge_next": j_ext_v2,
    }


def run(samples: Optional[Sequence[Dict[str, str]]] = None) -> Dict[str, Any]:
    rows = [confront_one(s) for s in (samples or SAMPLE_ASOFS)]
    # 分軌彙總（只記我估）
    def _wrap(key: str) -> List[Dict[str, Any]]:
        out = []
        for r in rows:
            out.append({"judge": (r.get("judges") or {}).get(key) or {"verdict": "未完", "scoreable": False}})
        return out

    summary_phone = summarize_mine_practice(rows)
    summary_next = summarize_mine_practice(_wrap(RULE_NEXT_EXT))
    summary_ld = summarize_mine_practice(_wrap(RULE_PHONE_LD))
    summary_ld_next = summarize_mine_practice(_wrap(RULE_NEXT_LD))

    by_verdict = {"對": [], "偏": [], "未完": []}
    for r in rows:
        v = (r.get("judge") or {}).get("verdict") or "未完"
        by_verdict.setdefault(v, []).append(
            {"symbol": r["symbol"], "as_of": r["as_of"], "judge": r.get("judge")}
        )

    return {
        "generated_at_taipei": _now_tp(),
        "pot": "MINE",
        "source": "mine",
        "label": "我估｜擴延1618／前端傾斜 官方柱對質",
        "≠biaoke": True,
        "≠golden_buy": True,
        "≠mixed_winrate": True,
        "track_keys": {
            "phone_ext": RULE_PHONE_EXT,
            "next_ext": RULE_NEXT_EXT,
            "phone_ld": RULE_PHONE_LD,
            "next_ld": RULE_NEXT_LD,
        },
        "gate_changes": {
            RULE_PHONE_EXT: "L_max≥1.618×L_2nd（現況）",
            RULE_NEXT_EXT: "v1＋③非最短＋禁標準 impulse 1–4 重疊當擴延 pass",
            RULE_PHONE_LD: "①④重疊→candidate；confirmed 要位置＋5-3-5-3-5",
            RULE_NEXT_LD: "重疊深度≥8%＋位置或結構至少一項才 candidate",
        },
        "summary": {
            RULE_PHONE_EXT: summary_phone,
            RULE_NEXT_EXT: summary_next,
            RULE_PHONE_LD: summary_ld,
            RULE_NEXT_LD: summary_ld_next,
        },
        "by_verdict": by_verdict,
        "rows": rows,
        "basis": "官方已收柱樣例；勝率只記我估鍋；n≥20且贏現況才換並再生（§13）",
    }


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="我估擴延／前端傾斜官方柱對質")
    ap.add_argument(
        "--out-dir",
        type=Path,
        default=OUT_DIR,
        help="輸出目錄（預設 docs/expert_notes/dc_wave）",
    )
    args = ap.parse_args(list(argv) if argv is not None else None)
    out_dir: Path = args.out_dir
    out_dir.mkdir(parents=True, exist_ok=True)

    payload = run()
    stamp = datetime.now(TP).strftime("%Y%m%d")
    full_path = out_dir / f"mine_practice_{stamp}.json"
    latest_path = out_dir / "mine_practice_latest.json"
    hit_path = out_dir / "mine_practice_hit.json"
    miss_path = out_dir / "mine_practice_miss.json"
    pending_path = out_dir / "mine_practice_pending.json"
    next_path = out_dir / "mine_practice_next_keys.json"

    full_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    latest_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def _slice(verdict: str) -> Dict[str, Any]:
        ids = (payload.get("by_verdict") or {}).get(verdict) or []
        return {
            "generated_at_taipei": payload["generated_at_taipei"],
            "pot": "MINE",
            "verdict": verdict,
            "n": len(ids),
            "items": ids,
            "track_keys": payload["track_keys"],
        }

    hit_path.write_text(json.dumps(_slice("對"), ensure_ascii=False, indent=2), encoding="utf-8")
    miss_path.write_text(json.dumps(_slice("偏"), ensure_ascii=False, indent=2), encoding="utf-8")
    pending_path.write_text(json.dumps(_slice("未完"), ensure_ascii=False, indent=2), encoding="utf-8")
    next_path.write_text(
        json.dumps(
            {
                "generated_at_taipei": payload["generated_at_taipei"],
                "pot": "MINE",
                "§13": "換完必須留下下一版候選；本檔即再生鍵",
                "phone": {
                    "ext": RULE_PHONE_EXT,
                    "ld": RULE_PHONE_LD,
                },
                "next_candidates": {
                    "ext": RULE_NEXT_EXT,
                    "ld": RULE_NEXT_LD,
                    "notes": payload["gate_changes"],
                },
                "summary_next_vs_phone": {
                    "phone": payload["summary"][RULE_PHONE_EXT],
                    "next": payload["summary"][RULE_NEXT_EXT],
                },
                "≠biaoke": True,
                "≠golden_buy": True,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    s = payload["summary"][RULE_PHONE_EXT]
    print(
        json.dumps(
            {
                "ok": True,
                "pot": "MINE",
                "n_scoreable": s.get("n_scoreable"),
                "winrate": s.get("winrate"),
                "n_pending": s.get("n_pending"),
                "out": str(full_path),
                "next_keys": [RULE_NEXT_EXT, RULE_NEXT_LD],
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
