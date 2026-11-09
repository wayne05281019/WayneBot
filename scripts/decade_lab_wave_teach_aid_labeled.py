#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""MARKET WAVE LAB｜labeled teach pass（with_his 窗）。

只對他當日±近窗文裡**真點名**的指數位計分；不准用擺盪高低補位。
夜盤領先只記筆記，主分＝日盤柱。時間線封印相位打標。
對照 loose baseline（wave_decade with_his）；未過閘不換。
phone_sync=blocked／WAVE_NEURONS_MATCH=false／buy_signal=false。
不准發明 5／9；不准改買訊／海選。
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import sys
from dataclasses import asdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.decade_lab_wave_jan_replay import (  # noqa: E402
    HIS_POSTS_FROM,
    LEVEL_RE,
    PathInfer,
    _filter_index_levels,
    _f,
    _load_posts,
    _load_twii,
    _load_tx,
    _now,
    _open_days,
    _require_segments,
    _verify_paths,
    _ymd,
)

MARKET_DB = Path(os.environ.get("WAYNE_DB_PATH") or (ROOT / "data" / "wayne_market.db"))
OUT_DIR = ROOT / "docs" / "expert_notes" / "飆客" / "decade_lab"
ART = Path("/opt/cursor/artifacts")
TAIPEI = ZoneInfo("Asia/Taipei")
POT = "wave_teach_aid_labeled"
PHONE_SYNC = "blocked"
NEAR_OPEN_DAYS = 2  # 當日 ± 近窗：向前含 N 個開市日文

TIMELINE_SEAL = OUT_DIR / "biaoke_crash_warning_to_tail_timeline_202611.json"
TEACH_AID_LOCK = OUT_DIR / "phone_wave_crash_timeline_teach_aid_lock.json"
BASELINE_COMPARE = OUT_DIR / "wave_tight_vs_baseline_with_his.json"
BASELINE_SUMMARY = OUT_DIR / "wave_decade_replay_summary.json"

# 時間線相位簡稱（對 teach-aid 用語）
PHASE_ALIAS = {
    "warn_start": "warn",
    "path_change_guidance": "guidance",
    "crash_realized": "crash",
    "stop_fall_candidate": "candidate",
    "stop_fall_confirm": "confirm",
    "pre_confirm_stock_hunt": "stock_hunt_note",  # 對照教材，不進大盤計分
}

PHRASE_TAGS = [
    ("假跌破", "fake_breakdown"),
    ("有效穿刺", "eff_pierce"),
    ("穿刺", "pierce"),
    ("1 4不重疊", "overlap_14"),
    ("1-4不重疊", "overlap_14"),
    ("14重疊", "overlap_14"),
    ("1 4重疊", "overlap_14"),
    ("壓轉撐", "resist_to_support"),
    ("逃命", "escape"),
    ("止跌", "stop_fall"),
    ("空手", "empty_hand"),
    ("勿抄底", "no_dip"),
    ("不要再介入", "no_reentry"),
    ("C波", "c_wave"),
    ("主跌", "main_drop"),
]


def _load_timeline_phase_windows(path: Path) -> Dict[str, Dict[str, Any]]:
    """從封印相位文日期推 inclusive 日曆窗；缺文日用相鄰相位夾住。"""
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    order = list(data.get("phase_order") or [])
    phases = data.get("phases") or {}
    dated: Dict[str, List[str]] = {}
    for key in order:
        body = phases.get(key) or {}
        days: List[str] = []
        anc = body.get("anchor") or {}
        if anc.get("date"):
            days.append(str(anc["date"]).replace("-", "")[:8])
        for bucket in ("posts", "precursors", "confirm_posts", "candidate_posts"):
            for item in body.get(bucket) or []:
                if isinstance(item, dict) and item.get("date"):
                    days.append(str(item["date"]).replace("-", "")[:8])
        dated[key] = sorted({d for d in days if len(d) == 8 and d.isdigit()})

    windows: Dict[str, Dict[str, Any]] = {}
    for i, key in enumerate(order):
        ds = dated.get(key) or []
        if not ds:
            continue
        start = ds[0]
        end = ds[-1]
        # 延伸到下一相位開始前一日（日曆），避免相位空洞漏標
        if i + 1 < len(order):
            nxt = dated.get(order[i + 1]) or []
            if nxt:
                prev = (
                    datetime.strptime(nxt[0], "%Y%m%d") - timedelta(days=1)
                ).strftime("%Y%m%d")
                if prev > end:
                    end = prev
        alias = PHASE_ALIAS.get(key, key)
        levels_raw = (phases.get(key) or {}).get("levels_he_named") or []
        named_nums: List[float] = []
        for raw in levels_raw:
            for m in LEVEL_RE.findall(str(raw)):
                v = _f(m)
                if v is not None and 15000 <= v <= 60000:
                    named_nums.append(v)
        windows[key] = {
            "phase_key": key,
            "phase_tag": alias,
            "title_zh": (phases.get(key) or {}).get("title_zh"),
            "start": start,
            "end": end,
            "anchor_dates": ds,
            "levels_named_in_seal": sorted(set(named_nums)),
        }
    return windows


def _tag_phase(day: str, windows: Dict[str, Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    hits = []
    for key, w in windows.items():
        if w["start"] <= day <= w["end"]:
            hits.append(w)
    if not hits:
        return None
    # 多窗重疊取較晚開始者（時間線後段優先）
    hits.sort(key=lambda x: x["start"], reverse=True)
    w = hits[0]
    return {
        "phase_key": w["phase_key"],
        "phase_tag": w["phase_tag"],
        "title_zh": w["title_zh"],
        "window": {"start": w["start"], "end": w["end"]},
    }


def _phrase_tags(snip: str) -> List[str]:
    out: List[str] = []
    t = snip or ""
    for zh, tag in PHRASE_TAGS:
        if zh in t and tag not in out:
            out.append(tag)
    return out


def _posts_near_window(
    posts_by: Dict[str, List[Dict[str, Any]]],
    open_days: List[str],
    day_idx: int,
    *,
    near: int = NEAR_OPEN_DAYS,
) -> Tuple[List[Dict[str, Any]], List[str]]:
    """當日＋向前 near 個開市日的文（含當日）。"""
    lo = max(0, day_idx - near)
    days = open_days[lo : day_idx + 1]
    posts: List[Dict[str, Any]] = []
    for d in days:
        for p in posts_by.get(d) or []:
            q = dict(p)
            q["post_day"] = d
            q["phrases"] = _phrase_tags(p.get("snip") or "")
            posts.append(q)
    return posts, days


def _named_levels_from_posts(
    posts: List[Dict[str, Any]], *, ref_px: Optional[float]
) -> Dict[str, Any]:
    raw: List[float] = []
    waveish_n = 0
    phrases: List[str] = []
    for p in posts:
        raw.extend(p.get("levels") or [])
        if p.get("waveish"):
            waveish_n += 1
        for ph in p.get("phrases") or []:
            if ph not in phrases:
                phrases.append(ph)
    levels = _filter_index_levels(raw, ref_px)
    caps, floors = [], []
    if levels:
        mid = levels[len(levels) // 2]
        caps = [x for x in levels if x >= mid]
        floors = [x for x in levels if x <= mid]
    return {
        "levels": levels,
        "caps": caps,
        "floors": floors,
        "n_posts": len(posts),
        "n_waveish": waveish_n,
        "phrases": phrases,
        "levels_raw_n": len(set(raw)),
        "levels_kept_n": len(levels),
    }


def _infer_named_only(
    *,
    day: str,
    named: Dict[str, Any],
    ref_px: Optional[float],
) -> List[PathInfer]:
    """只推他點名位；沒有點名＝空推（隔日不計分）。不准擺盪補位、不准發明段號 5／9。"""
    paths: List[PathInfer] = []
    floors = list(named.get("floors") or [])
    caps = list(named.get("caps") or [])
    floor = None
    if floors:
        if ref_px:
            cands = [x for x in floors if x <= ref_px * 1.01]
            floor = min(cands, key=lambda x: abs(x - ref_px)) if cands else floors[-1]
        else:
            floor = floors[-1]
    cap = None
    if caps:
        if ref_px:
            cands = [x for x in caps if x >= ref_px * 0.99]
            cap = min(cands, key=lambda x: abs(x - ref_px)) if cands else caps[-1]
        else:
            cap = caps[-1]

    if floor is not None:
        p1 = PathInfer(
            id="P1_named_floor",
            status="推論／未定案",
            thesis_zh=f"{day} 近窗他點撐（labeled；無擺盪補）",
            segments_provisional=[
                {"label": "UNK_named_prior", "role": "他點前結構暫定"},
                {"label": "UNK_named_retest", "role": "回測他點撐", "level": float(floor)},
            ],
            levels={"floor": float(floor)},
            expect=[f"低點觸及或距 {floor:.0f} ≤2.0%"],
            invalidate=[f"不再靠近 {floor:.0f}"],
        )
        _require_segments(p1)
        paths.append(p1)

    if cap is not None and (floor is None or abs(cap - floor) / max(cap, 1) > 0.002):
        p2 = PathInfer(
            id="P2_named_cap",
            status="推論／未定案",
            thesis_zh=f"{day} 近窗他點壓（labeled；無擺盪補）",
            segments_provisional=[
                {"label": "UNK_named_cap", "role": "挑戰他點壓", "level": float(cap)},
            ],
            levels={"cap": float(cap)},
            expect=[f"高點觸及或距 {cap:.0f} ≤2.0%"],
            invalidate=[f"收盤站穩 {cap:.0f} 上方"],
        )
        _require_segments(p2)
        paths.append(p2)

    return paths


def _night_lead_note(
    *,
    txn: Optional[Dict[str, float]],
    levels: List[float],
) -> Optional[Dict[str, Any]]:
    """夜盤領先筆記：只記有沒有碰到他點；不進主分。"""
    if not txn or not levels:
        return None
    touched = []
    for lv in levels:
        if txn["l"] <= lv <= txn["h"]:
            touched.append(lv)
        else:
            dist = min(abs(txn["l"] - lv), abs(txn["h"] - lv), abs(txn["c"] - lv)) / lv
            if dist <= 0.01:
                touched.append(lv)
    return {
        "o": txn["o"],
        "h": txn["h"],
        "l": txn["l"],
        "c": txn["c"],
        "touched_named": touched[:12],
        "n_touched_named": len(touched),
        "role_zh": "夜盤領先筆記；主對質＝翌日／當日日盤柱",
        "scores_day_bar": False,
    }


def _adapt_paths_for_verify(paths: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """_verify_paths 只認 P1_retest_near_floor / P2_cap_overhead 當結構主分。"""
    out = []
    for p in paths:
        q = dict(p)
        pid = q.get("id")
        if pid == "P1_named_floor":
            q["id"] = "P1_retest_near_floor"
            q["labeled_id"] = "P1_named_floor"
        elif pid == "P2_named_cap":
            q["id"] = "P2_cap_overhead"
            q["labeled_id"] = "P2_named_cap"
        out.append(q)
    return out


def _stats(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    decided = [r for r in rows if (r.get("verify") or {}).get("scoreable")]
    hit = sum(1 for r in decided if r["verify"]["verdict"] == "對")
    miss = sum(1 for r in decided if r["verify"]["verdict"] == "偏")
    return {
        "rows": len(rows),
        "n_decided": len(decided),
        "hit": hit,
        "miss": miss,
        "hit_rate": (hit / len(decided)) if decided else None,
        "n_with_named": sum(1 for r in rows if (r.get("named") or {}).get("levels")),
        "n_night_touched": sum(
            1
            for r in rows
            if (r.get("night_lead") or {}).get("n_touched_named", 0) > 0
        ),
    }


def _load_loose_baseline() -> Dict[str, Any]:
    """Loose with_his baseline（decade replay）；優先 tight_vs 封印。"""
    if BASELINE_COMPARE.exists():
        data = json.loads(BASELINE_COMPARE.read_text(encoding="utf-8"))
        b = data.get("baseline_with_his") or {}
        return {
            "source": BASELINE_COMPARE.name,
            "rows": b.get("rows"),
            "n_decided": b.get("n_decided"),
            "hit": b.get("hit"),
            "miss": b.get("miss"),
            "hit_rate": b.get("hit_rate"),
            "tight_with_his": data.get("tight_with_his"),
            "prior_replace": data.get("replace"),
        }
    if BASELINE_SUMMARY.exists():
        data = json.loads(BASELINE_SUMMARY.read_text(encoding="utf-8"))
        ph = data.get("phase_with_his") or {}
        return {
            "source": BASELINE_SUMMARY.name,
            "rows": ph.get("rows"),
            "n_decided": ph.get("n_decided"),
            "hit": ph.get("hit"),
            "miss": ph.get("miss"),
            "hit_rate": ph.get("hit_rate"),
        }
    return {"source": None, "hit_rate": None, "n_decided": 0}


def _load_loose_daily_verdicts() -> Dict[str, str]:
    """decade loose daily：day → 對/偏（僅 scoreable）。"""
    path = OUT_DIR / "wave_decade_replay_daily.jsonl"
    out: Dict[str, str] = {}
    if not path.exists():
        return out
    with path.open(encoding="utf-8") as f:
        for line in f:
            try:
                r = json.loads(line)
            except json.JSONDecodeError:
                continue
            if r.get("phase") != "with_his":
                continue
            v = r.get("verify") or {}
            if not v.get("scoreable"):
                continue
            day = str(r.get("day") or "")
            verd = v.get("verdict")
            if day and verd in ("對", "偏"):
                out[day] = str(verd)
    return out


def _matched_day_compare(
    rows: List[Dict[str, Any]], loose_verdicts: Dict[str, str]
) -> Dict[str, Any]:
    """同一批 labeled 可裁判日上，loose 命中 vs labeled 命中（防選樣膨脹）。"""
    pairs: List[Tuple[str, str, str]] = []
    for r in rows:
        v = r.get("verify") or {}
        if not v.get("scoreable"):
            continue
        day = str(r.get("day") or "")
        lv = v.get("verdict")
        bv = loose_verdicts.get(day)
        if day and lv in ("對", "偏") and bv in ("對", "偏"):
            pairs.append((day, str(lv), str(bv)))
    n = len(pairs)
    lab_hit = sum(1 for _, lv, _ in pairs if lv == "對")
    loose_hit = sum(1 for _, _, bv in pairs if bv == "對")
    lab_hr = (lab_hit / n) if n else None
    loose_hr = (loose_hit / n) if n else None
    delta = (
        round(float(lab_hr) - float(loose_hr), 6)
        if lab_hr is not None and loose_hr is not None
        else None
    )
    return {
        "n_matched_decided": n,
        "labeled_hit": lab_hit,
        "loose_hit": loose_hit,
        "labeled_hit_rate": lab_hr,
        "loose_hit_rate": loose_hr,
        "delta_hit_rate_matched": delta,
        "note_zh": "同日對照：headline 高於 loose 全窗若只因放棄難日＝不誠實換閘",
    }


def _honest_flags(
    stats: Dict[str, Any],
    *,
    baseline_hr: Optional[float],
    matched: Optional[Dict[str, Any]] = None,
    min_delta: float = 0.02,
) -> List[str]:
    """誠實問題（會擋換閘）；樣本不足／未贏另記在 gate 欄。"""
    flags: List[str] = []
    hr = stats.get("hit_rate")
    if hr is not None and hr > 0.92:
        flags.append("hit_rate_suspiciously_high")
    if int(stats.get("n_with_named") or 0) == 0:
        flags.append("no_named_levels")
    # headline 贏全窗但同日對照未贏＝選樣膨脹
    if matched:
        md = matched.get("delta_hit_rate_matched")
        if md is not None and md < min_delta:
            flags.append("matched_day_not_clearly_better")
        if (
            hr is not None
            and baseline_hr is not None
            and hr >= (baseline_hr + min_delta)
            and md is not None
            and md < 0
        ):
            flags.append("headline_selection_bias_vs_matched")
    return flags


def _replace_gate(
    stats: Dict[str, Any],
    *,
    baseline_hr: Optional[float],
    honest: List[str],
    matched: Optional[Dict[str, Any]] = None,
    min_delta: float = 0.02,
    score_mode: str = "baseline",
) -> Dict[str, Any]:
    n = int(stats.get("n_decided") or 0)
    hr = stats.get("hit_rate")
    delta = None
    if hr is not None and baseline_hr is not None:
        delta = round(float(hr) - float(baseline_hr), 6)
    clearly_better = bool(
        hr is not None
        and baseline_hr is not None
        and delta is not None
        and delta >= min_delta
    )
    matched_better = False
    if matched and matched.get("delta_hit_rate_matched") is not None:
        matched_better = float(matched["delta_hit_rate_matched"]) >= min_delta
    gate_flags: List[str] = []
    if n < 20:
        gate_flags.append("n_lt_20")
    if hr is not None and baseline_hr is not None and not clearly_better:
        gate_flags.append("not_clearly_better_than_loose_baseline")
    if matched and not matched_better:
        gate_flags.append("matched_day_not_clearly_better")
    # 對 loose baseline（觸及計分）只允許同语义 labeled-baseline 換閘；
    # labeled_tight 是教具對照軌，不是 decade baseline 的 drop-in。
    drop_in_ok = str(score_mode or "baseline").strip().lower() == "baseline"
    if not drop_in_ok:
        gate_flags.append("cross_score_mode_not_drop_in_for_loose_baseline")
    # 換閘：同语义 且 全窗明顯更好 且 同日對照也明顯更好 且 無誠實旗標
    replace = bool(
        drop_in_ok and n >= 20 and clearly_better and matched_better and not honest
    )
    return {
        "n_decided": n,
        "gate_n20": n >= 20,
        "score_mode": score_mode,
        "drop_in_for_loose_baseline": drop_in_ok,
        "baseline_hit_rate": baseline_hr,
        "labeled_hit_rate": hr,
        "delta_hit_rate": delta,
        "matched_day": matched,
        "min_delta_clear": min_delta,
        "clearly_better": clearly_better,
        "matched_clearly_better": matched_better,
        "honest_flags": honest,
        "gate_flags": gate_flags,
        "replace": replace,
        "keep": "wave_decade_replay baseline score_mode" if not replace else None,
        "decision_zh": (
            "labeled 過閘且全窗＋同日對照皆明顯優於 loose → 可換（仍須另令合主）"
            if replace
            else (
                "tight／跨裁判語意只當教具對照，不換 loose baseline"
                if not drop_in_ok
                else "未過閘／同日未贏／選樣膨脹／不誠實 → 不換 decade baseline；labeled 當教具軌續收"
            )
        ),
    }


def run(
    *,
    start: Optional[str] = None,
    end: Optional[str] = None,
    near: int = NEAR_OPEN_DAYS,
    score_mode: str = "baseline",
    with_his_only: bool = True,
) -> Dict[str, Any]:
    from trading_calendar import is_tw_open_calendar_day

    start_d = _ymd(start) or HIS_POSTS_FROM
    if with_his_only and start_d < HIS_POSTS_FROM:
        start_d = HIS_POSTS_FROM
    end = _ymd(end) or datetime.now(TAIPEI).strftime("%Y%m%d")
    mode = (score_mode or "baseline").strip().lower() or "baseline"
    if mode not in ("baseline", "tight"):
        mode = "baseline"

    while end >= start_d and not is_tw_open_calendar_day(end):
        end = (datetime.strptime(end, "%Y%m%d") - timedelta(days=1)).strftime("%Y%m%d")
    while start_d <= end and not is_tw_open_calendar_day(start_d):
        start_d = (datetime.strptime(start_d, "%Y%m%d") + timedelta(days=1)).strftime(
            "%Y%m%d"
        )

    phase_windows = _load_timeline_phase_windows(TIMELINE_SEAL)
    open_days = _open_days(start_d, end)

    con = sqlite3.connect(f"file:{MARKET_DB}?mode=ro", uri=True)
    try:
        twii = _load_twii(con, start_d)
        tx_reg = _load_tx(con, start_d, "regular")
        tx_night = _load_tx(con, start_d, "night")
        posts_by = _load_posts(con, start_d, end)
    finally:
        con.close()

    rows: List[Dict[str, Any]] = []
    pending: Optional[Dict[str, Any]] = None
    recent_bars: List[Dict[str, float]] = []

    for i, day in enumerate(open_days):
        bar = twii.get(day)
        txd = tx_reg.get(day)
        txn = tx_night.get(day)
        ref_px = (bar or {}).get("c") if bar else (
            recent_bars[-1]["c"] if recent_bars else None
        )
        near_posts, near_days = _posts_near_window(
            posts_by, open_days, i, near=near
        )
        named = _named_levels_from_posts(near_posts, ref_px=ref_px)
        named["near_days"] = near_days
        named["same_day_posts"] = len(posts_by.get(day) or [])

        phase = _tag_phase(day, phase_windows)

        verify = {
            "verdict": "首日無前推",
            "scoreable": False,
            "path_results": [],
            "score_mode": mode,
            "day_bar_verdict": True,
        }
        if pending is not None:
            verify = _verify_paths(
                pending["paths"],
                bar=bar,
                tx_day=txd,
                prior_bars=list(recent_bars),
                score_mode=mode,
            )
            verify["inferred_on"] = pending["from_day"]
            verify["named_source_days"] = pending.get("near_days")
            verify["day_bar_verdict"] = True
            verify["night_lead_does_not_score"] = True

        night_note = _night_lead_note(txn=txn, levels=list(named.get("levels") or []))

        paths = _infer_named_only(day=day, named=named, ref_px=ref_px)
        path_dicts = [asdict(p) for p in paths]
        pending = {
            "from_day": day,
            "paths": _adapt_paths_for_verify(path_dicts),
            "near_days": near_days,
            "named_levels": list(named.get("levels") or []),
        }

        if bar:
            recent_bars.append(bar)
            recent_bars = recent_bars[-12:]

        rows.append(
            {
                "pot": POT,
                "track": "market_tw",
                "day": day,
                "phone_sync": PHONE_SYNC,
                "buy_signal": False,
                "WAVE_NEURONS_MATCH": False,
                "phase": "with_his",
                "timeline_phase": phase,
                "named": named,
                "bar_twii": bar,
                "bar_tx_day": txd,
                "night_lead": night_note,
                "verify": verify,
                "infer_for_next": path_dicts,
                "score_mode": mode,
                "labeled": True,
                "no_swing_fallback": True,
                "no_invent_wave_5_9": True,
                "not_buy_signal": True,
            }
        )

    overall = _stats(rows)
    by_phase: Dict[str, Any] = {}
    for r in rows:
        tag = ((r.get("timeline_phase") or {}).get("phase_tag")) or "outside_seal"
        by_phase.setdefault(tag, []).append(r)
    phase_stats = {k: _stats(v) for k, v in sorted(by_phase.items())}

    loose = _load_loose_baseline()
    baseline_hr = loose.get("hit_rate")
    matched = _matched_day_compare(rows, _load_loose_daily_verdicts())
    honest = _honest_flags(overall, baseline_hr=baseline_hr, matched=matched)
    gate = _replace_gate(
        overall,
        baseline_hr=baseline_hr,
        honest=honest,
        matched=matched,
        score_mode=mode,
    )

    # 相位內命中品質（教具窗）
    seal_rows = [r for r in rows if r.get("timeline_phase")]
    seal_stats = _stats(seal_rows)

    summary = {
        "as_of": _now(),
        "tz": "Asia/Taipei",
        "track": "market_tw",
        "pot": POT,
        "phone_sync": PHONE_SYNC,
        "buy_signal": False,
        "WAVE_NEURONS_MATCH": False,
        "purpose_zh": (
            "labeled teach pass：with_his 只評他近窗點名位／用語；"
            "夜盤領先與日盤主分分開；時間線封印相位打標；對照 loose baseline"
        ),
        "start": start_d,
        "end": end,
        "his_posts_from": HIS_POSTS_FROM,
        "near_open_days": near,
        "score_mode": mode,
        "teach_aid_lock": TEACH_AID_LOCK.name if TEACH_AID_LOCK.exists() else None,
        "timeline_seal": TIMELINE_SEAL.name if TIMELINE_SEAL.exists() else None,
        "phase_windows": {
            k: {
                "phase_tag": v["phase_tag"],
                "start": v["start"],
                "end": v["end"],
                "title_zh": v["title_zh"],
            }
            for k, v in phase_windows.items()
        },
        "labeled_with_his": overall,
        "labeled_in_timeline_seal": seal_stats,
        "by_timeline_phase": phase_stats,
        "loose_baseline_with_his": loose,
        "matched_day_vs_loose": matched,
        "comparison": gate,
        "replace": gate["replace"],
        "isolation_zh": "market_tw 專鍋；股票選股鍋不進；不改 leave_zero／海選",
        "not_buy_signal": True,
        "no_invent_wave_5_9": True,
        "note_zh": (
            "主分＝日盤柱對他點名位；夜盤只筆記。"
            "loose baseline 含擺盪補位；labeled 無補位。"
            "換閘必看同日對照，防放棄難日把 headline 抬高。"
        ),
    }

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    ART.mkdir(parents=True, exist_ok=True)
    prefix = "wave_teach_aid_labeled" + ("_tight" if mode == "tight" else "")
    jsonl = OUT_DIR / f"{prefix}_daily.jsonl"
    with jsonl.open("w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    text = json.dumps(summary, ensure_ascii=False, indent=2)
    (OUT_DIR / f"{prefix}_summary.json").write_text(text, encoding="utf-8")
    (OUT_DIR / f"{prefix}_latest.json").write_text(text, encoding="utf-8")
    (ART / f"{prefix}_summary.json").write_text(text, encoding="utf-8")

    # 對照封印（給話筒外 lab 讀）；baseline 軌寫主對照檔，tight 另寫
    compare_name = (
        "wave_teach_aid_labeled_vs_baseline.json"
        if mode == "baseline"
        else "wave_teach_aid_labeled_tight_vs_baseline.json"
    )
    compare_seal = {
        "as_of": summary["as_of"],
        "tz": "Asia/Taipei",
        "track": "market_tw",
        "pot": POT,
        "phone_sync": PHONE_SYNC,
        "buy_signal": False,
        "WAVE_NEURONS_MATCH": False,
        "purpose_zh": "labeled teach pass vs loose with_his baseline；未過閘不換",
        "labeled_with_his": overall,
        "labeled_in_timeline_seal": seal_stats,
        "by_timeline_phase": phase_stats,
        "loose_baseline_with_his": loose,
        "matched_day_vs_loose": matched,
        "delta_hit_rate_vs_loose": gate.get("delta_hit_rate"),
        "delta_hit_rate_matched": (matched or {}).get("delta_hit_rate_matched"),
        "decision_zh": gate.get("decision_zh"),
        "replace": gate["replace"],
        "keep": gate.get("keep"),
        "honest_flags": honest,
        "gate_flags": gate.get("gate_flags"),
        "score_mode": mode,
        "linked_seals": [
            TIMELINE_SEAL.name,
            TEACH_AID_LOCK.name,
            "wave8_14_overlap_resolved.json",
            "wave8_extension_rules_lock.json",
            "wave_tight_vs_baseline_with_his.json",
        ],
        "not_buy_signal": True,
        "no_invent_wave_5_9": True,
    }
    compare_text = json.dumps(compare_seal, ensure_ascii=False, indent=2)
    (OUT_DIR / compare_name).write_text(compare_text, encoding="utf-8")
    (ART / compare_name).write_text(compare_text, encoding="utf-8")

    print(
        "GATE",
        f"{prefix} {start_d}→{end} decided={overall['n_decided']} "
        f"hr={overall['hit_rate']} vs_loose={baseline_hr} "
        f"delta={gate.get('delta_hit_rate')} replace={gate['replace']} "
        f"phone_sync=blocked",
    )
    return summary


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="", help="YYYYMMDD (default=HIS_POSTS_FROM)")
    ap.add_argument("--end", default="", help="YYYYMMDD")
    ap.add_argument("--near", type=int, default=NEAR_OPEN_DAYS)
    ap.add_argument(
        "--score-mode",
        default="baseline",
        choices=("baseline", "tight"),
        help="labeled 位上的裁判：baseline=觸及；tight=連2收／假跌破",
    )
    args = ap.parse_args()
    run(
        start=args.start or None,
        end=args.end or None,
        near=args.near,
        score_mode=args.score_mode,
    )


if __name__ == "__main__":
    main()
