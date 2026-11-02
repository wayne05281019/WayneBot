#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""十年回測旁路｜序D：裸K意圖故事碼第一批。

硬邊界：只寫 decade_lab／；讀 wayne_market；三鍋分標；不是買訊；
不准寫回黃金買點／海選／洞燭／話筒。缺教材／缺欄只標缺。
"""
from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
_SCRIPTS = ROOT / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from decade_lab_market_confront import SEED_DAYS, _load_bars, _ymd  # noqa: E402
from decade_lab_story_codes import classify_barek_stories  # noqa: E402

OUT_DIR = ROOT / "docs" / "expert_notes" / "飆客" / "decade_lab"
TP = ZoneInfo("Asia/Taipei")
WINDOW = 20


def _now_tp() -> datetime:
    return datetime.now(TP)


def _form_record(seed: Dict[str, Any]) -> Dict[str, Any]:
    as_of = seed["event_date"]
    symbol = seed.get("symbol") or "TWII"
    bars, gaps = _load_bars(symbol, as_of, window=WINDOW)
    story = classify_barek_stories(bars)
    near = [
        {
            "date": b["date"],
            "o": b.get("open"),
            "h": b.get("high"),
            "l": b.get("low"),
            "c": b.get("close"),
            "v": b.get("volume"),
        }
        for b in bars[-8:]
    ]
    hits = story.get("hit_labels") or []
    record = {
        "A": {
            "event_date": as_of,
            "event_time_taipei": seed.get("event_time") or "",
            "symbol": symbol,
            "level_hypothesis": seed.get("level_hypothesis"),
            "said": seed.get("said"),
            "source_ref": seed.get("source_ref"),
            "seq": "D",
        },
        "B": {
            "alive_labels": (seed.get("alive_labels") or [])[:3],
            "story_hits": hits[:5],
        },
        "C": {"near_window_ohlcv": near, "window_n": len(near), "story_window_n": len(bars)},
        "D": {
            "pot": "實驗室",
            "barek_story": story,
            "fib": "見序C",
            "dc": "見序C；本列不重算",
        },
        "E": {
            "volume_price_story": "／".join(hits) if hits else "無命中旗標",
            "outer": {"teacher_hint": seed.get("teacher_verdict_hint")},
        },
        "F": {
            "teacher_claim_pot": "他說／飆預測（只附種子原文）",
            "lab_pot": "實驗室（故事碼粗檢）",
            "dc_estimate_pot": "DC→我估（本列未用）",
        },
        "G": {
            "outcome": "未完",
            "teacher_verdict_hint": seed.get("teacher_verdict_hint"),
            "note": "故事碼是實驗室旗標；勝率不與老師軌混",
        },
        "H": {
            "actionable_fix": (
                "無量續跌≠止穩；沒爆量破低≠止跌；量先價行单條視窗一換就不穩；"
                "兩根才確認；負結果（未命中／假陽性）也留"
            ),
            "negative_logged": True,
        },
        "flags": {
            "missing_bars": gaps,
            "missing_curriculum": story.get("missing") or [],
            "as_of_cutoff": f"{_ymd(as_of)} 收盤後可知；盤中未收不當收",
            "limit_up_down": (story.get("codes") or {}).get("limit_move_approx"),
            "settlement_week": None,
            "gap_open": (story.get("codes") or {}).get("gap_open"),
        },
        "meta": {
            "written_at": _now_tp().isoformat(),
            "tz": "Asia/Taipei",
            "not_buy_signal": True,
            "batch": "D0_barek_wave1",
        },
    }
    record["counted"] = bool(symbol) and len(near) > 0 and bool(story.get("ok"))
    return record


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    records = [_form_record(s) for s in SEED_DAYS]
    counted = [r for r in records if r.get("counted")]
    stamp = _now_tp().strftime("%Y%m%d")
    out_jsonl = OUT_DIR / f"seq_d_barek_{stamp}.jsonl"
    with out_jsonl.open("w", encoding="utf-8") as f:
        for r in counted:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    alias = OUT_DIR / "seq_d_barek_latest.jsonl"
    alias.write_text(out_jsonl.read_text(encoding="utf-8"), encoding="utf-8")

    # label frequency
    freq: Dict[str, int] = {}
    for r in counted:
        for lab in (r.get("B") or {}).get("story_hits") or []:
            freq[lab] = freq.get(lab, 0) + 1

    md: List[str] = [
        "# 序D｜裸K意圖故事碼第一批",
        "",
        f"寫入：`{_now_tp().isoformat()}`（Asia/Taipei）。",
        f"種子日 n={len(SEED_DAYS)}；有記 n={len(counted)}。",
        "鍋：**實驗室**（官方柱粗檢）。他說只附種子原文。不是買訊。",
        "半山腰／新聞擁擠／五件同點／官方漲跌停旗 → 標缺。",
        "",
        f"JSONL：`{alias.relative_to(ROOT)}`",
        "",
        "## 命中頻次",
        "",
    ]
    if freq:
        for k, v in sorted(freq.items(), key=lambda kv: (-kv[1], kv[0])):
            md.append(f"- {k}：{v}")
    else:
        md.append("- （無）")
    md.append("")
    for r in counted:
        a = r["A"]
        hits = (r.get("B") or {}).get("story_hits") or []
        md.append(f"## {a['event_date']} {a.get('event_time_taipei') or ''} {a['symbol']}".rstrip())
        md.append("")
        md.append(f"- **A** {a.get('level_hypothesis')}")
        md.append(f"  - 他說（附）：{a.get('said')}")
        md.append(f"- **E 故事碼命中**：{'／'.join(hits) if hits else '無'}")
        miss = (r.get("flags") or {}).get("missing_curriculum") or []
        if miss:
            md.append(f"- **缺**：{miss[0]}" + ("…" if len(miss) > 1 else ""))
        md.append("")

    md_path = OUT_DIR / "seq_d_barek_latest.md"
    md_path.write_text("\n".join(md) + "\n", encoding="utf-8")
    summary = {
        "written_at": _now_tp().isoformat(),
        "tz": "Asia/Taipei",
        "n_seed": len(SEED_DAYS),
        "n_counted": len(counted),
        "hit_freq": freq,
        "jsonl": str(alias.relative_to(ROOT)),
        "md": str(md_path.relative_to(ROOT)),
        "not_buy_signal": True,
        "pot": "實驗室",
        "skipped": ["news_crowd", "half_mountain_index", "five_piece_same_point", "official_limit_flag"],
    }
    (OUT_DIR / "seq_d_barek_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(summary, ensure_ascii=False))
    return 0 if counted else 1


if __name__ == "__main__":
    raise SystemExit(main())
