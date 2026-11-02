#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""十年回測旁路｜序F：防穿越／分軌計分骨架第一批。

硬邊界：只讀 decade_lab 既有 JSONL 彙總；不准混勝率；不准寫回黃金買點／話筒。
n≥20 且贏該軌現況才准換——本批只報 n／可計分狀態，不觸發替換。
教具回放抽樣需出圖對齊 → 本批標缺跳過。能講同步話筒 → 未到。
"""
from __future__ import annotations

import json
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
LAB = ROOT / "docs" / "expert_notes" / "飆客" / "decade_lab"
TP = ZoneInfo("Asia/Taipei")

# 規則成形年粗切（knowhow／課綱公開句；晚年句不回打早年）
RULE_ERA_CUTS: List[Dict[str, str]] = [
    {"from": "2023-12", "tag": "裸K／不看均線指標", "note": "2023-12-21 起"},
    {"from": "2025-06", "tag": "量先價行可重複句", "note": "2025-06-05"},
    {"from": "2025-11", "tag": "台積量價否決權強化", "note": "2025-11-21 檢討"},
    {"from": "2026-02", "tag": "三買點＋產業波浪量價", "note": "2026-02"},
    {"from": "2026-04", "tag": "細微波四步教材大綱", "note": "2026-04-07"},
    {"from": "2026-07", "tag": "夜盤15分＋下降壓＋台積抓A低", "note": "2026-07"},
]


def _now_tp() -> datetime:
    return datetime.now(TP)


def _read_jsonl(path: Path) -> List[Dict[str, Any]]:
    if not path.exists():
        return []
    out: List[Dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


def _event_year_month(rec: Dict[str, Any]) -> str:
    a = rec.get("A") or {}
    d = str(a.get("event_date") or "")[:7]
    return d


def _era_for(ym: str) -> str:
    """事件日落在哪個規則成形年之後（只標適用上限，不回打）。"""
    applicable = [c for c in RULE_ERA_CUTS if c["from"] <= ym]
    if not applicable:
        return "pre_2023-12"
    return applicable[-1]["tag"]


def _outcome(rec: Dict[str, Any]) -> str:
    g = rec.get("G") or {}
    return str(g.get("outcome") or "未完")


def _score_track(name: str, rows: Iterable[Dict[str, Any]], pot: str) -> Dict[str, Any]:
    rows = list(rows)
    counted = [r for r in rows if r.get("counted")]
    oc = Counter(_outcome(r) for r in counted)
    n = len(counted)
    decided = oc.get("對", 0) + oc.get("偏", 0) + oc.get("他改口", 0)
    win = oc.get("對", 0)
    # 勝率只在同軌內；未滿 n≥20 不准宣稱可換
    rate = (win / decided) if decided else None
    return {
        "track": name,
        "pot": pot,
        "n_counted": n,
        "n_decided": decided,
        "outcome_counts": dict(oc),
        "hit_rate_among_decided": rate,
        "gate_n20": n >= 20 and decided >= 20,
        "replace_live": False,  # 本批永不自動換
        "note": "勝率不准與其他軌混；未過閘不准換現況編碼",
    }


def main() -> int:
    LAB.mkdir(parents=True, exist_ok=True)
    confront = _read_jsonl(LAB / "market_confront_AH_latest.jsonl")
    seq_c = _read_jsonl(LAB / "seq_c_measure_latest.jsonl")
    seq_d = _read_jsonl(LAB / "seq_d_barek_latest.jsonl")
    seq_e = _read_jsonl(LAB / "seq_e_named_latest.jsonl")
    timeline = _read_jsonl(LAB / "timeline_wrong_revision_hard_latest.jsonl")

    tracks = [
        _score_track("teacher_market_confront", confront, "他說／實驗室結局"),
        _score_track("mine_fib_dc_seq_c", seq_c, "DC→我估"),
        _score_track("lab_barek_seq_d", seq_d, "實驗室"),
        _score_track("teacher_named_seq_e", seq_e, "他說＋實驗室報酬"),
    ]

    # 規則年切開：timeline／confront 事件貼 era 標（不回打）
    era_rows: List[Dict[str, Any]] = []
    for src_name, rows in (
        ("timeline", timeline),
        ("confront", confront),
        ("named", seq_e),
    ):
        for r in rows:
            ym = _event_year_month(r) if "A" in r else str(r.get("date") or r.get("event_date") or "")[:7]
            if not ym:
                # timeline JSONL 可能用不同欄
                ym = str(r.get("when") or r.get("as_of") or "")[:7]
            if len(ym) < 7:
                continue
            era_rows.append(
                {
                    "source": src_name,
                    "ym": ym,
                    "era_tag": _era_for(ym),
                    "id": (r.get("A") or {}).get("event_date")
                    or r.get("id")
                    or r.get("stock_id")
                    or "",
                }
            )

    era_freq = Counter(x["era_tag"] for x in era_rows)

    summary = {
        "written_at": _now_tp().isoformat(),
        "tz": "Asia/Taipei",
        "seq": "F0",
        "not_buy_signal": True,
        "tracks": tracks,
        "rule_era_cuts": RULE_ERA_CUTS,
        "era_label_n": len(era_rows),
        "era_freq": dict(era_freq),
        "teach_replay_sample": {
            "status": "skipped",
            "reason": "教具遠／近／超近回放需出圖對齊當日照片欄；與實驗室分驗，本批不渲圖",
        },
        "phone_sync": {
            "status": "blocked",
            "reason": "能講的天未到；不准同步話筒說法",
        },
        "replace_gate": {
            "rule": "n≥20 且贏該軌現況才換並再生下一版",
            "any_track_ready": any(t["gate_n20"] for t in tracks),
            "action": "none",
        },
        "anti_lookahead": {
            "as_of_required": True,
            "note": "各序 JSONL flags.as_of_cutoff；後續觸及／報酬分欄 post_as_of",
        },
    }

    out_json = LAB / "seq_f_tracks_summary.json"
    out_json.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (LAB / "seq_f_era_labels_latest.jsonl").write_text(
        "\n".join(json.dumps(x, ensure_ascii=False) for x in era_rows) + ("\n" if era_rows else ""),
        encoding="utf-8",
    )

    md = [
        "# 序F｜防穿越／分軌計分骨架第一批",
        "",
        f"寫入：`{_now_tp().isoformat()}`（Asia/Taipei）。",
        "勝率不准混軌；本批**不**替換現況、**不**同步話筒、**不**渲教具回放。",
        "",
        "## 分軌計分",
        "",
    ]
    for t in tracks:
        rate = t["hit_rate_among_decided"]
        rate_s = "—" if rate is None else f"{rate:.0%}"
        md.append(
            f"- **{t['track']}**（{t['pot']}）：n={t['n_counted']} decided={t['n_decided']} "
            f"對/偏/改口={t['outcome_counts']} rate={rate_s} gate_n20={t['gate_n20']}"
        )
    md.extend(
        [
            "",
            "## 規則成形年切開",
            "",
        ]
    )
    for c in RULE_ERA_CUTS:
        md.append(f"- `{c['from']}`起：**{c['tag']}**（{c['note']}）")
    md.append("")
    md.append(f"已貼 era 標 n={len(era_rows)}；頻次={dict(era_freq)}")
    md.extend(
        [
            "",
            "## 跳過",
            "",
            "- 教具回放抽樣：標缺（不在本批渲圖）",
            "- 話筒同步：擋住（能講的天未到）",
            "- 替換閘：無軌過 n≥20 可換",
            "",
            "不是買訊。",
            "",
        ]
    )
    (LAB / "seq_f_tracks_latest.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    print(json.dumps({k: summary[k] for k in ("written_at", "tracks", "replace_gate", "phone_sync", "teach_replay_sample")}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
