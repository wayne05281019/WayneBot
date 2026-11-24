# -*- coding: utf-8 -*-
"""BK-WAVE 浪則卡／段號證據桶載入（觀測手冊・非買訊）。

- 讀 ``docs/expert_notes/飆客/observe_manual/wave_rules_cards.json``
- 讀 ``segment_evidence.json``
- 給 forward／eod 掛 ``wave_rules_ref``／警語；不准改黃金買點。
- DC／我估（``mine_wave_rules``）分鍋：本模組只索引飆大／試標卡。
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

ROOT = Path(__file__).resolve().parent
MANUAL = ROOT / "docs" / "expert_notes" / "飆客" / "observe_manual"
CARDS_PATH = MANUAL / "wave_rules_cards.json"
EVIDENCE_PATH = MANUAL / "segment_evidence.json"

PHONE_WARNING_FIXED = "試標・推論／非他原文・非買訊・對質未過閘"


def load_wave_rules_cards(path: Optional[Path] = None) -> Dict[str, Any]:
    p = path or CARDS_PATH
    data = json.loads(p.read_text(encoding="utf-8"))
    cards = data.get("cards") or []
    if not isinstance(cards, list) or not cards:
        raise ValueError("wave_rules_cards.cards empty")
    ids = [str(c.get("id") or "") for c in cards]
    if len(ids) != len(set(ids)):
        raise ValueError("duplicate wave rule card id")
    if any(not i.startswith("WR-") for i in ids):
        raise ValueError("card id must start with WR-")
    n = int(data.get("n_cards") or 0)
    if n and n != len(cards):
        raise ValueError(f"n_cards={n} != len(cards)={len(cards)}")
    if data.get("buy_signal") is not False:
        raise ValueError("wave_rules_cards.buy_signal must be false")
    if data.get("phone_sync") not in ("blocked", "blocked_until_accuracy_gate"):
        raise ValueError("wave_rules_cards.phone_sync must stay blocked until gate")
    warn = str(data.get("phone_warning_fixed") or "")
    if warn != PHONE_WARNING_FIXED:
        raise ValueError("phone_warning_fixed mismatch MISSION_LOCK")
    return data


def cards_by_id(data: Optional[Dict[str, Any]] = None) -> Dict[str, Dict[str, Any]]:
    blob = data if data is not None else load_wave_rules_cards()
    out: Dict[str, Dict[str, Any]] = {}
    for c in blob.get("cards") or []:
        cid = str(c.get("id") or "")
        if cid:
            out[cid] = c
    return out


def load_segment_evidence(path: Optional[Path] = None) -> Dict[str, Any]:
    p = path or EVIDENCE_PATH
    data = json.loads(p.read_text(encoding="utf-8"))
    samples = data.get("samples") or []
    if not isinstance(samples, list) or not samples:
        raise ValueError("segment_evidence.samples empty")
    if data.get("buy_signal") is not False:
        raise ValueError("segment_evidence.buy_signal must be false")
    warn = str(data.get("phone_warning_fixed") or "")
    if warn != PHONE_WARNING_FIXED:
        raise ValueError("segment_evidence phone_warning_fixed mismatch")
    # every sample must cite ≥1 rule card
    for s in samples:
        rids = s.get("rule_ids") or []
        if not rids:
            raise ValueError(f"sample {s.get('id')} missing rule_ids")
        segs = s.get("segments_provisional") or []
        if not segs:
            raise ValueError(f"sample {s.get('id')} missing segments_provisional")
        if s.get("label_pot") == "trial_infer":
            if s.get("phone_warning") != PHONE_WARNING_FIXED:
                raise ValueError(f"trial sample {s.get('id')} missing fixed warning")
    n = int(data.get("n_samples") or 0)
    if n and n != len(samples):
        raise ValueError(f"n_samples={n} != len(samples)={len(samples)}")
    return data


def evidence_index_by_rule(
    evidence: Optional[Dict[str, Any]] = None,
) -> Dict[str, List[str]]:
    blob = evidence if evidence is not None else load_segment_evidence()
    idx: Dict[str, List[str]] = {}
    for s in blob.get("samples") or []:
        sid = str(s.get("id") or "")
        for rid in s.get("rule_ids") or []:
            idx.setdefault(str(rid), []).append(sid)
    return idx


def attach_wave_rules_ref(
    payload: Dict[str, Any],
    *,
    rule_ids: Optional[Sequence[str]] = None,
    mark_trial_segments: bool = True,
) -> Dict[str, Any]:
    """掛浪則卡索引＋固定警語到 forward／eod dict（原地改並回傳）。"""
    cards = load_wave_rules_cards()
    by_id = cards_by_id(cards)
    wanted = [str(x) for x in (rule_ids or []) if str(x) in by_id]
    if not wanted:
        # default: iron + trial warn + forward loop
        wanted = [
            "WR-IRON-14-OVERLAP",
            "WR-IRON-W3-NOT-SHORTEST",
            "WR-OPS-FAKE-BREAK",
            "WR-SEGMENT-TRIAL-WARN",
            "WR-FWD-LOOP",
            "WR-FWD-TOUCH-BOUNCE-RECLAIM",
            "WR-FWD-PENDING-NOT-VETO",
            "WR-LEVEL-ORAL-ONLY",
        ]
        wanted = [w for w in wanted if w in by_id]

    payload["wave_rules_ref"] = {
        "track": "BK-WAVE",
        "cards_file": str(CARDS_PATH.relative_to(ROOT)),
        "evidence_file": str(EVIDENCE_PATH.relative_to(ROOT)),
        "rule_ids": wanted,
        "phone_warning_fixed": PHONE_WARNING_FIXED,
        "buy_signal": False,
        "phone_sync": payload.get("phone_sync") or "blocked",
        "gap_file_zh": "wave_rules_cards.json#gap_vs_live_wave_code",
    }
    if mark_trial_segments:
        for path in payload.get("paths") or []:
            if not isinstance(path, dict):
                continue
            for seg in path.get("segments_provisional") or []:
                if not isinstance(seg, dict):
                    continue
                if not seg.get("phone_warning"):
                    seg["phone_warning"] = PHONE_WARNING_FIXED
                st = str(seg.get("status") or "")
                if "試標" not in st and "他標" not in st:
                    seg["status"] = "試標・推論"
    # hard guards
    payload["buy_signal"] = False
    if "not_buy_signal" not in payload:
        payload["not_buy_signal"] = True
    return payload


def summarize_cards_md(data: Optional[Dict[str, Any]] = None) -> str:
    blob = data if data is not None else load_wave_rules_cards()
    lines = [
        "# 浪則卡（BK-WAVE）",
        "",
        f"- as_of：`{blob.get('as_of_taipei')}`（Asia/Taipei）",
        f"- 卡數：**{blob.get('n_cards')}**",
        f"- 話筒警語（固定）：`{blob.get('phone_warning_fixed')}`",
        "- 非買訊；`phone_sync=blocked`；離開敘事不准進產品；DC句不准寫成他說。",
        "",
        "| id | 類別 | 出處鍋 | 標題 |",
        "|---|---|---|---|",
    ]
    for c in blob.get("cards") or []:
        lines.append(
            f"| `{c.get('id')}` | {c.get('category')} | {c.get('source_kind')} | {c.get('title_zh')} |"
        )
    gap = (blob.get("gap_vs_live_wave_code") or {}).get("items") or []
    if gap:
        lines.extend(["", "## 與現況 wave 碼落差", ""])
        for g in gap:
            lines.append(
                f"- **{g.get('area')}**：現況＝{g.get('live')} → 卡＝{g.get('cards')} → 下一步＝{g.get('next')}"
            )
    lines.append("")
    return "\n".join(lines)


def summarize_evidence_md(data: Optional[Dict[str, Any]] = None) -> str:
    blob = data if data is not None else load_segment_evidence()
    lines = [
        "# 段號證據桶（BK-WAVE）",
        "",
        f"- as_of：`{blob.get('as_of_taipei')}`（Asia/Taipei）",
        f"- 樣本：**{blob.get('n_samples')}**（有官方 TWII 柱 **{blob.get('n_with_official_twii')}**）",
        f"- 他標／原文鏈：**{blob.get('n_biaoke_oral')}**；試標推論：**{blob.get('n_trial_infer')}**",
        f"- 話筒警語（固定）：`{blob.get('phone_warning_fixed')}`",
        "- 非買訊；不准發明無憑據 5／9 當他原文。",
        "",
        "## 落差（摘）",
        "",
    ]
    for g in blob.get("gap_vs_live_wave_zh") or []:
        lines.append(f"- {g}")
    lines.extend(["", "## 樣本索引（id → rules）", ""])
    for s in blob.get("samples") or []:
        rules = ",".join(s.get("rule_ids") or [])
        bar = "Y" if s.get("has_official_twii") else "N"
        pot = s.get("label_pot")
        lines.append(
            f"- `{s.get('id')}` @ {s.get('as_of')} bar={bar} pot={pot} ← {rules}"
        )
    lines.append("")
    return "\n".join(lines)
