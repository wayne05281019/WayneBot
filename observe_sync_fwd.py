# -*- coding: utf-8 -*-
"""SYNC-FWD／BK-FWD：forward miss → 觀測手冊下一版鍵／敘述修正（非買訊）。

讀 ``wave_eod_verify_*.json`` 的 ``miss_analysis``，產出可操作回寫：
- 下一版候選鍵（§13 再生；勝率不准混海選／黃金買點）
- 敘述修正建議（話筒文敘／三窗；段號仍警語層）
- 掛 ``observe_wave_rules`` 浪則卡 id＋段號證據桶樣本

硬邊界：Asia/Taipei；未收不當收；phone_sync=blocked；不是買訊。
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple
from zoneinfo import ZoneInfo

from observe_wave_rules import (
    MANUAL,
    PHONE_WARNING_FIXED,
    ROOT,
    attach_wave_rules_ref,
    cards_by_id,
    load_segment_evidence,
    load_wave_rules_cards,
    summarize_cards_md,
    summarize_evidence_md,
)

TAIPEI = ZoneInfo("Asia/Taipei")
LAB = ROOT / "docs" / "expert_notes" / "飆客" / "decade_lab"
CARDS_PATH = MANUAL / "wave_rules_cards.json"
EVIDENCE_PATH = MANUAL / "segment_evidence.json"
WRITEBACK_JSON = MANUAL / "fwd_miss_writeback_latest.json"
WRITEBACK_MD = MANUAL / "fwd_miss_writeback_latest.md"

TRACK = "bk_fwd"
VARIANT_CURRENT = "bk_fwd_v1_miss_map"
VARIANT_NEXT = "bk_fwd_v2_bounce_reclaim_priority"
PHONE_SYNC = "blocked"

# 新浪則卡（§13 下一版候選；試標鍋）
CARD_TOUCH_BOUNCE_RECLAIM = {
    "id": "WR-FWD-TOUCH-BOUNCE-RECLAIM",
    "title_zh": "目標觸及後收彈→升權假跌破收回",
    "category": "verify",
    "source_kind": "trial_infer",
    "his_words": [],
    "trial_note_zh": (
        "來自 eod miss_analysis（20261123）：preferred＝延伸測口頭目標帶時，"
        "若 L 已觸／切入目標帶但收明顯反彈且仍＜假跌破收回位，"
        "標 M3_touched_then_bounce＋N1_partial，下一窗升權 FB reclaim；"
        "續弱失敗才回目標帶。不准當新五波①、不准發明未口述新低、不是買訊。"
    ),
    "provenance": [
        "wave_eod_verify_20261123.json#miss_analysis",
        "wave_forward_infer_20261124.json",
        "observe_sync_fwd.py",
    ],
    "ops_check_zh": (
        "條件：preferred 續弱／延伸測口頭目標；官方已收柱 L＜目標上沿（或切入帶）"
        "且 C 明顯反彈、C 仍＜假跌破收回位。動作：升權 false_break_reclaim；"
        "降權『當日必續弱到底』。硬禁：發明①／未口述新低／當買訊／改黃金買點。"
    ),
    "segment_labels": [
        "M3_touched_then_bounce",
        "N1_partial",
        "false_break_reclaim",
    ],
    "phone_ok_with_warning": True,
    "phone_warning": PHONE_WARNING_FIXED,
    "not_buy_signal": True,
}

CARD_PENDING_NOT_VETO = {
    "id": "WR-FWD-PENDING-NOT-VETO",
    "title_zh": "未觸及≠路徑否決（pending 升權）",
    "category": "verify",
    "source_kind": "trial_infer",
    "his_words": [],
    "trial_note_zh": (
        "來自 eod miss_analysis（20261117～19）：preferred＝升權測位時，"
        "若仍失上一撐且 L 落在『帶下～目標之上』，標 N1_follow_through＋M*_pending，"
        "不准把『未測到目標』當該路徑否決，也不准標新①。"
    ),
    "provenance": [
        "wave_eod_verify_20261117.json#miss_analysis",
        "wave_eod_verify_20261119.json#miss_analysis",
        "observe_sync_fwd.py",
    ],
    "ops_check_zh": (
        "條件：preferred 測某口頭位；當日 L 未觸該位但結構仍失上一守。動作：pending 升權、"
        "不否決；L 每靠近一檔可升權 pending，仍非觸發。硬禁：未觸就否決／發明①。"
    ),
    "segment_labels": [
        "M3_pending",
        "N1_follow_through",
        "pending_not_veto",
    ],
    "phone_ok_with_warning": True,
    "phone_warning": PHONE_WARNING_FIXED,
    "not_buy_signal": True,
}

NEW_CARDS = (CARD_TOUCH_BOUNCE_RECLAIM, CARD_PENDING_NOT_VETO)


def _now() -> str:
    return datetime.now(TAIPEI).strftime("%Y-%m-%dT%H:%M:%S%z")


def _ymd(raw: Any) -> str:
    t = str(raw or "").replace("-", "")[:8]
    return t if len(t) == 8 and t.isdigit() else ""


def list_eod_verify_paths(lab: Optional[Path] = None) -> List[Path]:
    base = lab or LAB
    out = sorted(base.glob("wave_eod_verify_20*.json"))
    return [p for p in out if "latest" not in p.name]


def load_eod_verify(path: Path) -> Dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{path.name} not object")
    return data


def classify_miss(
    *,
    as_of: str,
    preferred: Optional[str],
    miss: Dict[str, Any],
) -> Dict[str, Any]:
    """把 miss_analysis 收成可操作 kind＋修正建議（非買訊）。"""
    rp = str(miss.get("rule_patch") or "")
    which = str(miss.get("which_segment_broke") or "")
    unexpected = str(miss.get("unexpected_level") or "")
    actual = str(miss.get("actual_path") or "")
    blob = rp + which + unexpected + actual

    kind = "narrative_only"
    next_variant = VARIANT_NEXT
    rule_ids: List[str] = ["WR-FWD-LOOP", "WR-LEVEL-ORAL-ONLY", "WR-SEGMENT-TRIAL-WARN"]
    prefer_path = ""
    labels: List[str] = []
    code_fix_zh = ""
    narrative_fix_zh = ""

    if (
        "touched_then_bounce" in blob
        or ("收明顯反彈" in rp and "37837" in rp)
        or ("反彈" in unexpected and "假跌破" in rp)
    ):
        kind = "target_touch_bounce_elevate_reclaim"
        next_variant = "bk_fwd_v2_bounce_reclaim_priority"
        rule_ids = [
            "WR-FWD-TOUCH-BOUNCE-RECLAIM",
            "WR-OPS-FAKE-BREAK",
            "WR-FWD-LOOP",
            "WR-LEVEL-ORAL-ONLY",
            "WR-SEGMENT-TRIAL-WARN",
        ]
        prefer_path = "FB_reclaim_37837_watch"
        labels = ["M3_touched_then_bounce", "N1_partial", "false_break_reclaim"]
        code_fix_zh = (
            "preferred 續弱測口頭目標時：L 觸／切入帶＋收彈且仍＜收回位 → "
            "標 M3_touched_then_bounce＋N1_partial，下一窗升權 FB_reclaim；"
            "不准把反彈當新五波①。"
        )
        narrative_fix_zh = (
            "文敘改口：目標帶曾觸、收彈觀察假跌破收回；續弱句降權為備援；"
            "段號試標＋固定警語；非買訊。"
        )
    elif "M3_triggered_broke" in blob or (
        "L已＜" in rp and "假跌破觀察" in rp
    ):
        kind = "level_broke_follow_oral_band"
        next_variant = "bk_fwd_v2_bounce_reclaim_priority"
        rule_ids = [
            "WR-OPS-FAKE-BREAK",
            "WR-LEVEL-ORAL-ONLY",
            "WR-FWD-LOOP",
            "WR-SEGMENT-TRIAL-WARN",
        ]
        prefer_path = "N1_follow_through_below_band"
        labels = ["M3_triggered_broke", "N1_follow_through", "false_break_reclaim"]
        code_fix_zh = (
            "preferred＝測位且 L／收皆破 → 標觸發＋續弱 follow；"
            "下一窗改口頭已有之更低帶為對照、原位收回為假跌破觀察；不准發明未口述新低。"
        )
        narrative_fix_zh = (
            "文敘：已破位改對照口頭下一帶；收回＝假跌破觀察；不准當新①。"
        )
    elif "pending" in rp.lower() or "不准把『未測到" in rp or "M3_pending" in blob:
        kind = "pending_not_veto"
        next_variant = "bk_fwd_v2b_pending_not_veto"
        rule_ids = [
            "WR-FWD-PENDING-NOT-VETO",
            "WR-FWD-LOOP",
            "WR-LEVEL-ORAL-ONLY",
            "WR-SEGMENT-TRIAL-WARN",
        ]
        prefer_path = str(preferred or "") or "M3_seek_continue"
        labels = ["M3_pending", "N1_follow_through", "pending_not_veto"]
        code_fix_zh = (
            "未觸目標≠否決：標 pending＋N1_follow；L 靠近可升權 pending，仍非觸發。"
        )
        narrative_fix_zh = "文敘維持升權測位句；寫清『尚未觸及、路徑未否決』；非買訊。"
    elif "post_hold" in rp or "升為必經" in rp or "升權測" in rp:
        kind = "hold_fail_escalate"
        next_variant = "bk_fwd_v2c_hold_fail_escalate"
        rule_ids = [
            "WR-OPS-PRESS-TO-SUPPORT",
            "WR-FWD-LOOP",
            "WR-LEVEL-ORAL-ONLY",
            "WR-SEGMENT-TRIAL-WARN",
        ]
        labels = ["post_hold_fail", "escalate_lower_level"]
        code_fix_zh = rp.strip() or "收失守後升權下一口頭位；不准標新①。"
        narrative_fix_zh = "文敘改下一必經回測位；上一撐改為已失狀態。"
    elif "遞延" in rp or ("取消" in rp and "必經" in rp):
        kind = "condition_defer"
        next_variant = "bk_fwd_v2d_condition_defer"
        rule_ids = ["WR-FWD-LOOP", "WR-LEVEL-ORAL-ONLY", "WR-OPS-TWO-BAR"]
        labels = ["condition_defer", "premise_invalid"]
        code_fix_zh = rp.strip() or "前提失效則取消當日必經、改標對照路徑。"
        narrative_fix_zh = "文敘寫清前提失效／路徑遞延；不准硬套原必經。"
    else:
        code_fix_zh = rp.strip() or "僅敘述修正；未達可程式閘。"
        narrative_fix_zh = (
            str((miss.get("two_diff") or {}).get("vs_biaoke_zh") or "")[:200]
            or "對照他說 vs 官方柱後再改口。"
        )

    actionable = kind != "narrative_only"
    return {
        "as_of": as_of,
        "preferred_was": preferred,
        "kind": kind,
        "actionable": actionable,
        "rule_ids": rule_ids,
        "prefer_path_id": prefer_path,
        "segment_labels": labels,
        "code_fix_zh": code_fix_zh,
        "narrative_fix_zh": narrative_fix_zh,
        "rule_patch_src": rp,
        "which_segment_broke": which,
        "next_variant": next_variant,
        "phone_warning_fixed": PHONE_WARNING_FIXED,
        "buy_signal": False,
        "not_buy_signal": True,
        "phone_sync": PHONE_SYNC,
        "mix_forbidden_zh": "勝率不准混進海選／黃金買點",
    }


def map_all_misses(lab: Optional[Path] = None) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for path in list_eod_verify_paths(lab):
        data = load_eod_verify(path)
        miss = data.get("miss_analysis")
        if not isinstance(miss, dict) or not miss:
            continue
        as_of = _ymd(data.get("as_of")) or _ymd(path.stem.split("_")[-1])
        # 未收／缺官方柱不當收：eod 檔必須有 official 或 bar_status 已收
        bar_status = str(data.get("bar_status") or "")
        official = data.get("official") or {}
        if not official and "未收" in bar_status:
            continue
        row = classify_miss(
            as_of=as_of,
            preferred=data.get("preferred_was"),
            miss=miss,
        )
        try:
            row["source_file"] = str(path.relative_to(ROOT))
        except ValueError:
            row["source_file"] = str(path)
        row["expected_segments"] = miss.get("expected_segments") or []
        row["actual_path"] = miss.get("actual_path")
        rows.append(row)
    return rows


def ensure_fwd_cards(cards_blob: Dict[str, Any]) -> Tuple[Dict[str, Any], List[str]]:
    """把 SYNC-FWD 浪則卡併入 cards（idempotent）。"""
    by = cards_by_id(cards_blob)
    added: List[str] = []
    cards = list(cards_blob.get("cards") or [])
    for card in NEW_CARDS:
        cid = card["id"]
        if cid in by:
            # refresh trial note / ops from canonical
            for i, old in enumerate(cards):
                if old.get("id") == cid:
                    cards[i] = dict(card)
                    break
            continue
        cards.append(dict(card))
        added.append(cid)
    cards_blob["cards"] = cards
    cards_blob["n_cards"] = len(cards)
    cards_blob["as_of_taipei"] = _now()
    # gap note：BK-FWD 已接 miss 回寫
    gap = cards_blob.setdefault("gap_vs_live_wave_code", {})
    items = list(gap.get("items") or [])
    fwd_items = [g for g in items if g.get("area") != "sync_fwd_writeback"]
    fwd_items.append(
        {
            "area": "sync_fwd_writeback",
            "live": "eod miss_analysis 有 rule_patch，未自動回寫手冊鍵",
            "cards": "WR-FWD-TOUCH-BOUNCE-RECLAIM / WR-FWD-PENDING-NOT-VETO",
            "next": "observe_sync_fwd 落 fwd_miss_writeback_*＋證據桶；§13 下一版鍵收集中",
        }
    )
    # update forward_verify next text
    for g in fwd_items:
        if g.get("area") == "forward_verify":
            g["next"] = "BK-FWD miss→手冊鍵已掛；BK-VERIFY 吃證據桶；phone_sync 仍 blocked"
    gap["items"] = fwd_items
    cards_blob["gap_vs_live_wave_code"] = gap
    cards_blob["buy_signal"] = False
    cards_blob["phone_sync"] = cards_blob.get("phone_sync") or PHONE_SYNC
    cards_blob["phone_warning_fixed"] = PHONE_WARNING_FIXED
    return cards_blob, added


def _seg(label: str, role: str = "", level: Optional[float] = None) -> Dict[str, Any]:
    out: Dict[str, Any] = {
        "label": label,
        "status": "試標・推論",
        "phone_warning": PHONE_WARNING_FIXED,
    }
    if role:
        out["role"] = role
    if level is not None:
        out["level"] = float(level)
    return out


def _twii_from_official(official: Any, as_of: str) -> Dict[str, Any]:
    """eod.official 可能是扁平 o/h/l/c，或巢狀 twii。"""
    blob = official if isinstance(official, dict) else {}
    tw = blob.get("twii") if isinstance(blob.get("twii"), dict) else blob
    return {
        "symbol": "TWII",
        "date": as_of,
        "o": tw.get("open") if tw.get("open") is not None else tw.get("o"),
        "h": tw.get("high") if tw.get("high") is not None else tw.get("h"),
        "l": tw.get("low") if tw.get("low") is not None else tw.get("l"),
        "c": tw.get("close") if tw.get("close") is not None else tw.get("c"),
        "v": tw.get("volume") if tw.get("volume") is not None else tw.get("v"),
        "source": "wave_eod_verify.official",
    }


def build_evidence_samples_from_eod(
    eod: Dict[str, Any],
    *,
    mapped: Dict[str, Any],
) -> List[Dict[str, Any]]:
    """從單一 eod＋miss 對照產出證據桶樣本（可併入 segment_evidence）。"""
    as_of = _ymd(eod.get("as_of")) or mapped.get("as_of")
    twii = _twii_from_official(eod.get("official") or {}, str(as_of))
    has_bar = twii.get("c") is not None or twii.get("l") is not None
    rule_ids = [r for r in (mapped.get("rule_ids") or []) if r]
    if not rule_ids:
        rule_ids = ["WR-FWD-LOOP", "WR-SEGMENT-TRIAL-WARN"]

    samples: List[Dict[str, Any]] = []
    # 主 miss 樣本
    sid = f"SE-FWD-MISS-{as_of}-{mapped.get('kind')}"
    labels = list(mapped.get("segment_labels") or []) or ["forward_path"]
    samples.append(
        {
            "id": sid,
            "rule_ids": rule_ids,
            "as_of": as_of,
            "tz": "Asia/Taipei",
            "source_kind": "trial_infer+official",
            "provenance": f"wave_eod_verify_{as_of}.json#miss_analysis",
            "his_claim_zh": str(mapped.get("rule_patch_src") or mapped.get("code_fix_zh") or "")[
                :240
            ],
            "his_levels": [],
            "segments_provisional": [_seg(lbl) for lbl in labels],
            "official_bars": {"twii": twii, "tx": []},
            "has_official_twii": bool(has_bar),
            "note_zh": mapped.get("code_fix_zh") or "",
            "buy_signal": False,
            "phone_sync": PHONE_SYNC,
            "metrics": {
                "kind": mapped.get("kind"),
                "prefer_path_id": mapped.get("prefer_path_id"),
                "next_variant": mapped.get("next_variant"),
            },
            "path_id": mapped.get("prefer_path_id") or "miss_writeback",
            "phone_warning": PHONE_WARNING_FIXED,
            "label_pot": "trial_infer",
        }
    )

    # 路徑級樣本（有官方柱才掛；沿用 eod paths）
    for path in eod.get("paths") or []:
        if not isinstance(path, dict):
            continue
        pid = str(path.get("id") or "")
        if not pid:
            continue
        segs = path.get("segments_provisional") or []
        if not segs:
            continue
        # 補警語
        norm_segs = []
        for s in segs:
            if not isinstance(s, dict):
                continue
            ns = dict(s)
            if not ns.get("phone_warning"):
                ns["phone_warning"] = PHONE_WARNING_FIXED
            st = str(ns.get("status") or "")
            if "試標" not in st and "他標" not in st:
                ns["status"] = "試標・推論"
            norm_segs.append(ns)
        if not norm_segs:
            continue
        samples.append(
            {
                "id": f"SE-EOD-{as_of}-{pid}",
                "rule_ids": list(
                    dict.fromkeys(
                        rule_ids
                        + ["WR-FWD-LOOP", "WR-SEGMENT-TRIAL-WARN"]
                    )
                ),
                "as_of": as_of,
                "tz": "Asia/Taipei",
                "source_kind": "trial_infer+official",
                "provenance": f"wave_eod_verify_{as_of}.json",
                "his_claim_zh": str(path.get("must_happen_zh") or path.get("status") or "")[:240],
                "his_levels": [],
                "segments_provisional": norm_segs,
                "official_bars": {"twii": twii, "tx": []},
                "has_official_twii": bool(has_bar),
                "note_zh": str(path.get("invalidate_zh") or "")[:200],
                "buy_signal": False,
                "phone_sync": PHONE_SYNC,
                "metrics": None,
                "path_id": pid,
                "phone_warning": PHONE_WARNING_FIXED,
                "label_pot": "trial_infer",
            }
        )
    return samples


def merge_evidence_samples(
    evidence: Dict[str, Any],
    new_samples: Sequence[Dict[str, Any]],
) -> Tuple[Dict[str, Any], int]:
    existing_ids = {str(s.get("id") or "") for s in (evidence.get("samples") or [])}
    added = 0
    samples = list(evidence.get("samples") or [])
    for s in new_samples:
        sid = str(s.get("id") or "")
        if not sid or sid in existing_ids:
            # refresh in place if miss sample
            if sid in existing_ids and sid.startswith("SE-FWD-MISS-"):
                for i, old in enumerate(samples):
                    if old.get("id") == sid:
                        samples[i] = s
                        break
            continue
        samples.append(s)
        existing_ids.add(sid)
        added += 1
    evidence["samples"] = samples
    evidence["n_samples"] = len(samples)
    evidence["n_with_official_twii"] = sum(
        1 for s in samples if s.get("has_official_twii")
    )
    evidence["n_trial_infer"] = sum(
        1 for s in samples if s.get("label_pot") == "trial_infer"
    )
    evidence["n_biaoke_oral"] = sum(
        1 for s in samples if s.get("label_pot") == "biaoke_oral"
    )
    evidence["as_of_taipei"] = _now()
    evidence["buy_signal"] = False
    evidence["phone_sync"] = PHONE_SYNC
    evidence["phone_warning_fixed"] = PHONE_WARNING_FIXED
    evidence["forward_verify_hook"] = (
        "observe_sync_fwd.writeback + observe_wave_rules.attach_wave_rules_ref"
    )
    gaps = list(evidence.get("gap_vs_live_wave_zh") or [])
    note = "SYNC-FWD：miss_analysis 可回寫下一版鍵／敘述修正＋證據桶（phone_sync=blocked）"
    if note not in gaps:
        gaps.append(note)
    evidence["gap_vs_live_wave_zh"] = gaps
    return evidence, added


def build_writeback_payload(
    *,
    lab: Optional[Path] = None,
    rows: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    mapped = rows if rows is not None else map_all_misses(lab)
    actionable = [r for r in mapped if r.get("actionable")]
    kind_counts: Dict[str, int] = {}
    for r in mapped:
        k = str(r.get("kind") or "")
        kind_counts[k] = kind_counts.get(k, 0) + 1

    # 最新可操作 miss 當「當令」敘述修正
    latest = None
    for r in sorted(mapped, key=lambda x: str(x.get("as_of") or ""), reverse=True):
        if r.get("actionable"):
            latest = r
            break

    narrative = {
        "phone_warning_fixed": PHONE_WARNING_FIXED,
        "prefer_path_id": (latest or {}).get("prefer_path_id") or "",
        "segment_labels": (latest or {}).get("segment_labels") or [],
        "fix_zh": (latest or {}).get("narrative_fix_zh") or "",
        "forbid_zh": [
            "不准把反彈／收彈當新五波①",
            "不准發明未口述之新低目標",
            "不准改黃金買點／不當買訊",
            "DC／我估句不准寫成他說",
        ],
        "as_of": (latest or {}).get("as_of"),
        "kind": (latest or {}).get("kind"),
    }

    # 掛 wave_rules_ref 形狀（給話筒／forward 讀）
    nav_labels = list(narrative.get("segment_labels") or []) or ["forward_path"]
    ref_payload = {
        "phone_sync": PHONE_SYNC,
        "buy_signal": False,
        "paths": [
            {
                "id": narrative["prefer_path_id"] or "sync_fwd_latest",
                "segments_provisional": [{"label": lbl} for lbl in nav_labels],
            }
        ],
    }
    rule_ids = (latest or {}).get("rule_ids") if latest else None
    try:
        attach_wave_rules_ref(ref_payload, rule_ids=rule_ids)
    except Exception:
        # cards 尚未寫入新 id 時仍可落檔
        ref_payload["wave_rules_ref"] = {
            "track": "BK-FWD",
            "rule_ids": rule_ids or ["WR-FWD-LOOP"],
            "phone_warning_fixed": PHONE_WARNING_FIXED,
            "buy_signal": False,
            "phone_sync": PHONE_SYNC,
        }

    return {
        "written_at": _now(),
        "tz": "Asia/Taipei",
        "track": TRACK,
        "purpose_zh": "forward miss 回寫 observe_manual 下一版鍵／敘述修正／證據桶",
        "phone_sync": PHONE_SYNC,
        "buy_signal": False,
        "not_buy_signal": True,
        "mix_forbidden_zh": "勝率不准混進海選／黃金買點；觀測≠主買訊",
        "current_variant": VARIANT_CURRENT,
        "next_variant": {
            "variant": VARIANT_NEXT,
            "from_kind": "target_touch_bounce_elevate_reclaim",
            "note_zh": "20261123 miss：目標觸及後收彈→升權 FB reclaim；同件再生收集中",
            "gate_zh": "獨立交易日 n≥20 且贏該功能現況才替換（§13）；空名單不算",
        },
        "n_eod_miss": len(mapped),
        "n_actionable": len(actionable),
        "kind_counts": kind_counts,
        "miss_to_fix": mapped,
        "latest_actionable": latest,
        "narrative_fix": narrative,
        "wave_rules_ref": ref_payload.get("wave_rules_ref"),
        "new_card_ids": [c["id"] for c in NEW_CARDS],
        "deps_zh": [
            "observe_wave_rules.py",
            "wave_eod_verify_*.json",
            "wave_forward_infer_*.json",
            "MISSION_LOCK_20261123.md A7／C12",
        ],
    }


def summarize_writeback_md(payload: Dict[str, Any]) -> str:
    lines = [
        "# SYNC-FWD・miss → 手冊回寫",
        "",
        f"- written_at：`{payload.get('written_at')}`（Asia/Taipei）",
        f"- 現況鍵：`{payload.get('current_variant')}`",
        f"- 下一版：`{(payload.get('next_variant') or {}).get('variant')}`",
        f"- eod miss：**{payload.get('n_eod_miss')}**／可操作：**{payload.get('n_actionable')}**",
        f"- 話筒警語（固定）：`{PHONE_WARNING_FIXED}`",
        "- 非買訊；`phone_sync=blocked`；勝率不准混海選／黃金買點。",
        "",
        "## miss → 修正對照",
        "",
        "| as_of | kind | prefer_path | rule_ids | code_fix（摘） |",
        "|---|---|---|---|---|",
    ]
    for r in payload.get("miss_to_fix") or []:
        rules = ",".join(r.get("rule_ids") or [])
        fix = str(r.get("code_fix_zh") or "").replace("|", "｜")[:80]
        lines.append(
            f"| `{r.get('as_of')}` | {r.get('kind')} | `{r.get('prefer_path_id') or '-'}` | {rules} | {fix} |"
        )
    nav = payload.get("narrative_fix") or {}
    lines.extend(
        [
            "",
            "## 當令敘述修正",
            "",
            f"- as_of / kind：`{nav.get('as_of')}` / `{nav.get('kind')}`",
            f"- prefer_path：`{nav.get('prefer_path_id')}`",
            f"- labels：{', '.join(nav.get('segment_labels') or [])}",
            f"- 修正：{nav.get('fix_zh')}",
            "",
            "## 硬禁",
            "",
        ]
    )
    for f in nav.get("forbid_zh") or []:
        lines.append(f"- {f}")
    lines.append("")
    return "\n".join(lines)


def apply_writeback(
    *,
    lab: Optional[Path] = None,
    write: bool = True,
    update_cards: bool = True,
    update_evidence: bool = True,
) -> Dict[str, Any]:
    """執行回寫：卡片＋證據桶＋fwd_miss_writeback_*。"""
    # 1) cards（讀寫走本模組 CARDS_PATH，測得可 monkeypatch）
    added_cards: List[str] = []
    if update_cards and CARDS_PATH.is_file():
        cards = json.loads(CARDS_PATH.read_text(encoding="utf-8"))
        # 輕量校驗（與 load_wave_rules_cards 對齊）
        if cards.get("buy_signal") is not False:
            raise ValueError("wave_rules_cards.buy_signal must be false")
        cards, added_cards = ensure_fwd_cards(cards)
        if write:
            CARDS_PATH.write_text(
                json.dumps(cards, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            (MANUAL / "wave_rules_cards.md").write_text(
                summarize_cards_md(cards), encoding="utf-8"
            )

    # 2) map misses（卡片寫入後再掛 ref）
    rows = map_all_misses(lab)
    payload = build_writeback_payload(lab=lab, rows=rows)

    # 3) evidence：只併 20261120／23 深破／收彈案（可操作 miss）
    added_ev = 0
    if update_evidence and EVIDENCE_PATH.is_file():
        evidence = json.loads(EVIDENCE_PATH.read_text(encoding="utf-8"))
        new_samples: List[Dict[str, Any]] = []
        want_days = set()
        for r in rows:
            if r.get("actionable") and r.get("as_of") in (
                "20261120",
                "20261123",
            ):
                want_days.add(str(r["as_of"]))
        # 若沒有指定日，仍吃最新可操作
        if not want_days:
            latest = payload.get("latest_actionable") or {}
            if latest.get("as_of"):
                want_days.add(str(latest["as_of"]))
        by_asof = {str(r.get("as_of")): r for r in rows}
        for day in sorted(want_days):
            eod_path = (lab or LAB) / f"wave_eod_verify_{day}.json"
            if not eod_path.is_file():
                continue
            eod = load_eod_verify(eod_path)
            mapped = by_asof.get(day) or classify_miss(
                as_of=day,
                preferred=eod.get("preferred_was"),
                miss=eod.get("miss_analysis") or {},
            )
            new_samples.extend(build_evidence_samples_from_eod(eod, mapped=mapped))
        evidence, added_ev = merge_evidence_samples(evidence, new_samples)
        if write:
            EVIDENCE_PATH.write_text(
                json.dumps(evidence, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            (MANUAL / "segment_evidence.md").write_text(
                summarize_evidence_md(evidence), encoding="utf-8"
            )

    payload["cards_added"] = added_cards
    payload["evidence_samples_added"] = added_ev
    # rebuild ref after cards exist
    payload = build_writeback_payload(lab=lab, rows=rows)
    payload["cards_added"] = added_cards
    payload["evidence_samples_added"] = added_ev

    if write:
        MANUAL.mkdir(parents=True, exist_ok=True)
        WRITEBACK_JSON.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        WRITEBACK_MD.write_text(summarize_writeback_md(payload), encoding="utf-8")
        # dated copy
        latest = (payload.get("latest_actionable") or {}).get("as_of") or "latest"
        dated = MANUAL / f"fwd_miss_writeback_{latest}.json"
        dated.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    return payload


def propose_forward_narrative_patch(
    forward: Dict[str, Any],
    writeback: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """給 wave_forward_infer 的敘述修正建議（不改買訊；可選併入）。"""
    wb = writeback or (
        json.loads(WRITEBACK_JSON.read_text(encoding="utf-8"))
        if WRITEBACK_JSON.is_file()
        else build_writeback_payload()
    )
    nav = wb.get("narrative_fix") or {}
    out = dict(forward)
    out["sync_fwd_narrative_fix"] = {
        "from_variant": wb.get("current_variant"),
        "next_variant": (wb.get("next_variant") or {}).get("variant"),
        "prefer_path_id": nav.get("prefer_path_id"),
        "fix_zh": nav.get("fix_zh"),
        "forbid_zh": nav.get("forbid_zh"),
        "phone_warning_fixed": PHONE_WARNING_FIXED,
        "buy_signal": False,
        "not_buy_signal": True,
    }
    # 不覆蓋既有 phone_narrative；只附加建議句
    base = str(out.get("phone_narrative_zh") or "").strip()
    tip = str(nav.get("fix_zh") or "").strip()
    if tip and tip not in base:
        out["phone_narrative_zh"] = (
            (base + "；" if base else "")
            + f"【SYNC-FWD】{tip}（{PHONE_WARNING_FIXED}）"
        )
    out["buy_signal"] = False
    out["not_buy_signal"] = True
    out["phone_sync"] = out.get("phone_sync") or PHONE_SYNC
    attach_wave_rules_ref(
        out,
        rule_ids=(wb.get("latest_actionable") or {}).get("rule_ids"),
    )
    return out
