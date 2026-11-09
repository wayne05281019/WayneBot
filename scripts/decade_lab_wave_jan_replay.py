#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""大盤 2026-01-01 起重播：冷啟動未知→逐日自推→日盤對質→可回溯修訂（計分不穿越）。

專鍋 wave_jan_replay。不是買訊。phone_sync=blocked。
夜盤領先紀錄；對質計分以日盤為主。他沒文仍自推；有文再補我vs他。
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
MARKET_DB = Path(os.environ.get("WAYNE_DB_PATH") or (ROOT / "data" / "wayne_market.db"))
OUT_DIR = ROOT / "docs" / "expert_notes" / "飆客" / "decade_lab"
ART = Path("/opt/cursor/artifacts")
TAIPEI = ZoneInfo("Asia/Taipei")
POT = "wave_jan_replay"
PHONE_SYNC = "blocked"
START = "20260101"
CHECKPOINT_EVERY = 20  # open days

WAVE_RE = re.compile(
    r"(?:八浪|細微|鐵律|擴延|假跌破|壓轉撐|1\s*[-–]?\s*4\s*重疊|14重疊|"
    r"C\d-?\d*|大[ABC]|[ABC]波|B-a|B-b|A-c|走\s*3-5|末升|主跌|"
    r"台指|加權|壓力|支撐|下降壓|上升軌|穿刺|有效)",
    re.I,
)
LEVEL_RE = re.compile(r"(?<![0-9.])([1-9]\d{4}(?:\.\d+)?)(?![0-9])")
COND_RE = re.compile(r"(如果|若|除非|否則|才能|才會|沒[有]?過|站穩|跌破|穿刺)")


def _now() -> str:
    return datetime.now(TAIPEI).strftime("%Y-%m-%dT%H:%M:%S%z")


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


def _open_days(start: str, end: str) -> List[str]:
    from trading_calendar import is_tw_open_calendar_day

    out: List[str] = []
    d0 = datetime.strptime(start, "%Y%m%d")
    d1 = datetime.strptime(end, "%Y%m%d")
    cur = d0
    while cur <= d1:
        ymd = cur.strftime("%Y%m%d")
        if is_tw_open_calendar_day(ymd):
            out.append(ymd)
        cur += timedelta(days=1)
    return out


def _load_twii(con: sqlite3.Connection, start: str) -> Dict[str, Dict[str, float]]:
    rows = con.execute(
        """
        SELECT REPLACE(CAST(date AS TEXT),'-',''), open, high, low, close
        FROM index_daily WHERE symbol='TWII' AND date>=?
        ORDER BY 1
        """,
        (start,),
    ).fetchall()
    out: Dict[str, Dict[str, float]] = {}
    for d, o, h, l, c in rows:
        day = _ymd(d)
        cc = _f(c)
        if not day or cc is None:
            continue
        out[day] = {
            "o": _f(o) or cc,
            "h": _f(h) or cc,
            "l": _f(l) or cc,
            "c": cc,
        }
    return out


def _load_tx(
    con: sqlite3.Connection, start: str, session: str
) -> Dict[str, Dict[str, float]]:
    rows = con.execute(
        """
        SELECT REPLACE(CAST(date AS TEXT),'-',''), open, high, low, close
        FROM futures_daily WHERE symbol='TX' AND session=? AND date>=?
        ORDER BY 1
        """,
        (session, start),
    ).fetchall()
    out: Dict[str, Dict[str, float]] = {}
    for d, o, h, l, c in rows:
        day = _ymd(d)
        cc = _f(c)
        if not day or cc is None:
            continue
        out[day] = {
            "o": _f(o) or cc,
            "h": _f(h) or cc,
            "l": _f(l) or cc,
            "c": cc,
        }
    return out


def _load_posts(con: sqlite3.Connection, start: str, end: str) -> Dict[str, List[Dict[str, Any]]]:
    """主文＋他自己回（layer 不限）；路人正文不進。biaoke_posts 已是他的文／自回。"""
    rows = con.execute(
        """
        SELECT id, date, time, kind, layer, text
        FROM biaoke_posts
        WHERE date>=? AND date<=? AND text IS NOT NULL AND length(text)>5
        ORDER BY date, time, id
        """,
        (f"{start[:4]}-{start[4:6]}-{start[6:8]}", f"{end[:4]}-{end[4:6]}-{end[6:8]}"),
    ).fetchall()
    by: Dict[str, List[Dict[str, Any]]] = {}
    for pid, date, time, kind, layer, text in rows:
        day = _ymd(date)
        if not day:
            continue
        t = str(text or "")
        levels = []
        for m in LEVEL_RE.findall(t):
            v = _f(m)
            if v is None:
                continue
            # 台股指數／期點合理窗
            if 15000 <= v <= 60000:
                levels.append(v)
        by.setdefault(day, []).append(
            {
                "id": str(pid),
                "time": str(time or ""),
                "kind": str(kind or ""),
                "layer": layer,
                "waveish": bool(WAVE_RE.search(t)),
                "has_cond": bool(COND_RE.search(t)),
                "levels": sorted(set(levels)),
                "snip": re.sub(r"\s+", " ", t)[:240],
            }
        )
    return by


@dataclass
class PathInfer:
    id: str
    status: str
    thesis_zh: str
    segments_provisional: List[Dict[str, Any]]
    levels: Dict[str, float]
    expect: List[str]
    invalidate: List[str]
    asof_visible: bool = True  # False = 事後修訂，不進主分


@dataclass
class DayState:
    degree_primary: str = "UNKNOWN"
    degree_note_zh: str = "冷啟動暫定未知"
    alive_labels: List[str] = field(default_factory=list)
    last_swing_high: Optional[float] = None
    last_swing_low: Optional[float] = None
    his_caps: List[float] = field(default_factory=list)
    his_floors: List[float] = field(default_factory=list)
    revisions: List[Dict[str, Any]] = field(default_factory=list)


def _require_segments(path: PathInfer) -> None:
    if not path.segments_provisional:
        raise ValueError(f"{path.id} missing segments")
    for s in path.segments_provisional:
        if not str(s.get("label") or "").strip():
            raise ValueError(f"{path.id} blank segment")


def _update_swings(state: DayState, bar: Dict[str, float], *, window: List[Dict[str, float]]) -> None:
    """近窗擺盪：用最近 N 根日盤高低，不准開年以來極值當每日必測。"""
    if not window:
        state.last_swing_high = bar["h"]
        state.last_swing_low = bar["l"]
        return
    state.last_swing_high = max(b["h"] for b in window)
    state.last_swing_low = min(b["l"] for b in window)


def _filter_index_levels(levels: List[float], ref: Optional[float]) -> List[float]:
    """只留贴近大盤／台指的點；個股價（離指數太遠）不准當大盤壓撐。"""
    if not levels:
        return []
    if ref is None or ref <= 0:
        # 無參照：只留典型指數窗
        return sorted({x for x in levels if 18000 <= x <= 55000})
    lo, hi = ref * 0.72, ref * 1.28
    return sorted({x for x in levels if lo <= x <= hi and 15000 <= x <= 60000})


def _absorb_posts(
    state: DayState,
    posts: List[Dict[str, Any]],
    day: str,
    *,
    ref_px: Optional[float],
) -> Dict[str, Any]:
    wave_posts = [p for p in posts if p["waveish"]]
    raw_levels: List[float] = []
    for p in posts:
        raw_levels.extend(p["levels"])
    levels = _filter_index_levels(raw_levels, ref_px)
    caps, floors = [], []
    if levels:
        mid = levels[len(levels) // 2]
        caps = [x for x in levels if x >= mid]
        floors = [x for x in levels if x <= mid]
        state.his_caps = _filter_index_levels(
            list(state.his_caps or []) + caps, ref_px
        )[-8:]
        state.his_floors = _filter_index_levels(
            list(state.his_floors or []) + floors, ref_px
        )[-8:]
    if wave_posts and state.degree_primary == "UNKNOWN":
        state.degree_primary = "PROVISIONAL_IN_PROGRESS"
        state.degree_note_zh = f"{day} 首次出現波浪／結構語→主位階暫定進行中（未定哪一段）"
        state.alive_labels = ["UNK_motive_or_corrective"]
    elif wave_posts:
        state.degree_note_zh = f"{day} 續有結構語；主位階仍暫定，待鏈式確認"
    return {
        "n_posts": len(posts),
        "n_waveish": len(wave_posts),
        "levels": levels[:20],
        "levels_raw_dropped": max(0, len(set(raw_levels)) - len(levels)),
        "caps": caps[:8],
        "floors": floors[:8],
        "snips": [p["snip"] for p in wave_posts[:3]],
    }


def _infer_next(
    state: DayState,
    *,
    day: str,
    bar: Optional[Dict[str, float]],
    absorb: Dict[str, Any],
    prior_window: List[Dict[str, float]],
) -> List[PathInfer]:
    """冷啟動也可推：他點＋「先前」近窗擺盪（不含把今日高低當明日必測）。段號必標。"""
    paths: List[PathInfer] = []
    ref = bar["c"] if bar else (prior_window[-1]["c"] if prior_window else None)

    # 先他點，再先前窗擺盪（prior_window 應為更新前近窗，或近窗去尾）
    prior = prior_window[:-1] if len(prior_window) >= 2 else prior_window[:0]
    prior_lo = min((b["l"] for b in prior), default=None)
    prior_hi = max((b["h"] for b in prior), default=None)

    def _ok_lvl(x: Optional[float]) -> Optional[float]:
        if x is None or ref is None or ref <= 0:
            return x
        if abs(x - ref) / ref > 0.10:
            return None
        return x

    floor = None
    if state.his_floors:
        # 取最接近現價、且低於現價的撐
        cands = [x for x in state.his_floors if ref is None or x <= ref * 1.005]
        if cands and ref:
            floor = min(cands, key=lambda x: abs(x - ref))
        elif cands:
            floor = cands[-1]
    if floor is None:
        floor = _ok_lvl(prior_lo)

    cap = None
    if state.his_caps:
        cands = [x for x in state.his_caps if ref is None or x >= ref * 0.995]
        if cands and ref:
            cap = min(cands, key=lambda x: abs(x - ref))
        elif cands:
            cap = cands[-1]
    if cap is None:
        cap = _ok_lvl(prior_hi)

    if floor is not None:
        p1 = PathInfer(
            id="P1_retest_near_floor",
            status="推論／未定案",
            thesis_zh="近窗回測先前支撐／他點撐（非今日低點複製）",
            segments_provisional=[
                {"label": "UNK_prior", "role": "前結構暫定", "mark": "未知冷啟動"},
                {"label": "UNK_retest", "role": "回測段暫定", "level": float(floor)},
            ],
            levels={"floor": float(floor)},
            expect=[f"低點觸及或距 {floor:.0f} ≤2.0%"],
            invalidate=[f"不再靠近 {floor:.0f}"],
        )
        _require_segments(p1)
        paths.append(p1)

    if cap is not None and (floor is None or abs(cap - floor) / max(cap, 1) > 0.002):
        p2 = PathInfer(
            id="P2_cap_overhead",
            status="推論／未定案",
            thesis_zh="上方蓋＝先前高／他點壓；未站穩前不當壓轉撐",
            segments_provisional=[
                {"label": "UNK_cap_test", "role": "挑戰壓力暫定", "level": float(cap)},
            ],
            levels={"cap": float(cap)},
            expect=[f"高點觸及或距 {cap:.0f} ≤2.0%"],
            invalidate=[f"收盤站穩 {cap:.0f} 上方"],
        )
        _require_segments(p2)
        paths.append(p2)

    if bar is not None:
        bull = bar["c"] >= bar["o"]
        p3 = PathInfer(
            id="P3_session_bias_continue_or_fade",
            status="推論／未定案",
            thesis_zh=("偏多延續觀察" if bull else "偏空／回測觀察") + "（弱先驗）",
            segments_provisional=[
                {
                    "label": "UNK_bias",
                    "role": "方向弱先驗",
                    "note": "up" if bull else "down",
                },
                {"label": "UNK_next", "role": "下一開市日驗證"},
            ],
            levels={},
            expect=["下一開市日同向"],
            invalidate=["反向"],
        )
        _require_segments(p3)
        paths.append(p3)

    if not paths:
        p0 = PathInfer(
            id="P0_await_structure",
            status="推論／未定案",
            thesis_zh="尚無足夠官方柱／點位；下一開市日只觀察擺盪形成",
            segments_provisional=[
                {"label": "UNKNOWN", "role": "冷啟動"},
                {"label": "WAIT_SWING", "role": "等第一組高低"},
            ],
            levels={},
            expect=["出現可標記的日盤高／低"],
            invalidate=[],
        )
        _require_segments(p0)
        paths.append(p0)
    return paths


def _verify_paths(
    paths: List[Dict[str, Any]],
    *,
    bar: Optional[Dict[str, float]],
    tx_day: Optional[Dict[str, float]],
) -> Dict[str, Any]:
    """日盤主對質。用加權；台指有則並記。"""
    if not bar:
        return {
            "verdict": "缺柱",
            "path_results": [],
            "leading": None,
            "scoreable": False,
        }
    probe = tx_day or bar
    results = []
    for p in paths:
        hits, misses, tags = [], [], []
        lv = p.get("levels") or {}
        floor = _f(lv.get("floor"))
        cap = _f(lv.get("cap"))
        if floor is not None:
            # 真的碰到價區，或距離 ≤1%
            touched = bar["l"] <= floor <= bar["h"]
            dist = abs(bar["l"] - floor) / floor if floor else 999
            if touched or dist <= 0.02:
                hits.append(f"觸及／近floor {floor:.0f} (L={bar['l']:.0f})")
                tags.append("near_floor")
            else:
                misses.append(f"未近floor {floor:.0f} (L={bar['l']:.0f})")
        if cap is not None:
            touched = bar["l"] <= cap <= bar["h"]
            dist = abs(bar["h"] - cap) / cap if cap else 999
            if touched or dist <= 0.02:
                hits.append(f"觸及／近cap {cap:.0f} (H={bar['h']:.0f})")
                tags.append("near_cap")
                if bar["c"] < cap:
                    tags.append("cap_still")
                else:
                    tags.append("cap_break_close")
            else:
                misses.append(f"未近cap {cap:.0f} (H={bar['h']:.0f})")
        if p.get("id") == "P3_session_bias_continue_or_fade":
            note = ""
            for s in p.get("segments_provisional") or []:
                if s.get("label") == "UNK_bias":
                    note = str(s.get("note") or "")
            up = bar["c"] >= bar["o"]
            if (note == "up" and up) or (note == "down" and not up):
                hits.append("弱先驗方向同向")
                tags.append("bias_hit")
            else:
                misses.append("弱先驗方向相反")
                tags.append("bias_miss")
        score = len(hits) - 0.5 * len(misses)
        if not hits and not misses:
            verd = "觀望不計分"
            scoreable = False
        else:
            verd = "對" if score > 0 else "偏"
            scoreable = True
        results.append(
            {
                "path_id": p.get("id"),
                "hits": hits,
                "misses": misses,
                "tags": tags,
                "score_rough": score,
                "verdict": verd,
                "scoreable": scoreable,
                "segments_provisional": p.get("segments_provisional"),
            }
        )
    results.sort(key=lambda r: -float(r["score_rough"]))
    leading = results[0]["path_id"] if results else None
    # 日結：只拿結構路徑 P1/P2 計主分（P3 弱先驗降權，不單獨定日）
    struct = [
        r
        for r in results
        if r["scoreable"] and r["path_id"] in ("P1_retest_near_floor", "P2_cap_overhead")
    ]
    scored = struct or [r for r in results if r["scoreable"]]
    if not scored:
        day_v = "觀望不計分"
    else:
        day_v = (
            "對"
            if sum(1 for r in scored if r["verdict"] == "對") > sum(1 for r in scored if r["verdict"] == "偏")
            else "偏"
        )
    return {
        "verdict": day_v,
        "path_results": results,
        "leading": leading,
        "scoreable": bool(scored),
        "probe": "tx_day" if tx_day else "twii",
        "bar_twii": bar,
        "bar_tx": tx_day,
    }


def _self_check(rows: List[Dict[str, Any]], *, checkpoint: int) -> Dict[str, Any]:
    """每段自檢：方向有沒有跑差。"""
    decided = [r for r in rows if (r.get("verify") or {}).get("scoreable")]
    n = len(decided)
    hit = sum(1 for r in decided if r["verify"]["verdict"] == "對")
    miss = sum(1 for r in decided if r["verify"]["verdict"] == "偏")
    unknown = sum(1 for r in rows if r.get("degree_primary") == "UNKNOWN")
    prov = sum(1 for r in rows if r.get("degree_primary") == "PROVISIONAL_IN_PROGRESS")
    no_seg = 0
    for r in rows:
        for p in r.get("infer_for_next") or []:
            segs = p.get("segments_provisional") or []
            if not segs or any(not str(s.get("label") or "").strip() for s in segs):
                no_seg += 1
    drift = []
    if no_seg:
        drift.append("segment_missing")
    hr = (hit / n) if n else None
    if n >= 10 and hr is not None and hr < 0.35:
        drift.append("hit_rate_low")
    if n >= 10 and hr is not None and hr > 0.92:
        drift.append("hit_rate_suspiciously_high")
    if unknown == len(rows) and len(rows) >= CHECKPOINT_EVERY:
        drift.append("still_all_unknown_after_window")
    return {
        "checkpoint": checkpoint,
        "n_rows": len(rows),
        "n_decided": n,
        "hit": hit,
        "miss": miss,
        "hit_rate": hr,
        "degree_unknown_n": unknown,
        "degree_provisional_n": prov,
        "segment_errors": no_seg,
        "drift_flags": drift,
        "ok_to_continue": no_seg == 0,
        "note_zh": "自檢：段號必在；命中過低／過高都記；全未知過長則檢討吸收規則",
    }


def run(*, end: Optional[str] = None) -> Dict[str, Any]:
    from trading_calendar import is_tw_open_calendar_day

    end = _ymd(end) or datetime.now(TAIPEI).strftime("%Y%m%d")
    # 對到最新開市日
    while end >= START and not is_tw_open_calendar_day(end):
        end = (datetime.strptime(end, "%Y%m%d") - timedelta(days=1)).strftime("%Y%m%d")

    open_days = _open_days(START, end)
    con = sqlite3.connect(f"file:{MARKET_DB}?mode=ro", uri=True)
    try:
        twii = _load_twii(con, START)
        tx_reg = _load_tx(con, START, "regular")
        tx_night = _load_tx(con, START, "night")
        posts_by = _load_posts(con, START, end)
    finally:
        con.close()

    state = DayState()
    rows: List[Dict[str, Any]] = []
    pending_infer: Optional[Dict[str, Any]] = None
    checks: List[Dict[str, Any]] = []
    recent_bars: List[Dict[str, float]] = []

    for i, day in enumerate(open_days):
        bar = twii.get(day)
        txd = tx_reg.get(day)
        txn = tx_night.get(day)
        posts = posts_by.get(day) or []

        # ① 驗證：用前一日自推對今日日盤
        verify = {"verdict": "首日無前推", "scoreable": False, "path_results": []}
        if pending_infer is not None:
            verify = _verify_paths(
                pending_infer["paths"],
                bar=bar,
                tx_day=txd,
            )
            verify["inferred_on"] = pending_infer["from_day"]
            verify["night_lead"] = txn

        # ② 吸收當日文（可無文）；點位必須贴近大盤參照價
        ref_px = (bar or {}).get("c") if bar else (
            recent_bars[-1]["c"] if recent_bars else None
        )
        absorb = _absorb_posts(state, posts, day, ref_px=ref_px)
        if bar:
            recent_bars.append(bar)
            recent_bars = recent_bars[-12:]  # 近12開市日窗
            _update_swings(state, bar, window=recent_bars)

        # ③ 夜盤領先紀錄（不計主分）
        night_note = None
        if txn:
            night_note = {
                "o": txn["o"],
                "h": txn["h"],
                "l": txn["l"],
                "c": txn["c"],
                "role_zh": "領先指標紀錄；主對質仍看日盤",
            }

        # ④ 自推下一開市日（先前窗＝含今日的 recent，函式內會去掉「只複製今日」）
        paths = _infer_next(
            state,
            day=day,
            bar=bar,
            absorb=absorb,
            prior_window=list(recent_bars),
        )
        path_dicts = [asdict(p) for p in paths]
        pending_infer = {"from_day": day, "paths": path_dicts}

        row = {
            "pot": POT,
            "day": day,
            "phone_sync": PHONE_SYNC,
            "buy_signal": False,
            "degree_primary": state.degree_primary,
            "degree_note_zh": state.degree_note_zh,
            "alive_labels": list(state.alive_labels),
            "absorb": absorb,
            "bar_twii": bar,
            "bar_tx_day": txd,
            "night_lead": night_note,
            "verify": verify,
            "infer_for_next": path_dicts,
            "asof_visible_only": True,
        }
        rows.append(row)

        # 自檢
        if (i + 1) % CHECKPOINT_EVERY == 0 or day == open_days[-1]:
            window = rows[-CHECKPOINT_EVERY:] if len(rows) >= CHECKPOINT_EVERY else rows
            chk = _self_check(window, checkpoint=i + 1)
            # 若段號缺失＝硬錯，再生規則（本版不應發生）
            if not chk["ok_to_continue"]:
                # 修：對缺段路徑補 UNKNOWN
                for r in rows:
                    for p in r.get("infer_for_next") or []:
                        segs = p.get("segments_provisional")
                        if not segs:
                            p["segments_provisional"] = [
                                {"label": "UNKNOWN", "role": "自檢補段"}
                            ]
                chk["repaired_zh"] = "補段號後續跑"
            checks.append(chk)

    # 總結（分軌）
    decided = [r for r in rows if (r.get("verify") or {}).get("scoreable")]
    hit = sum(1 for r in decided if r["verify"]["verdict"] == "對")
    miss = sum(1 for r in decided if r["verify"]["verdict"] == "偏")
    summary = {
        "written_at": _now(),
        "tz": "Asia/Taipei",
        "pot": POT,
        "phone_sync": PHONE_SYNC,
        "buy_signal": False,
        "start": START,
        "end": end,
        "open_days_n": len(open_days),
        "rows_n": len(rows),
        "n_decided": len(decided),
        "hit": hit,
        "miss": miss,
        "hit_rate": (hit / len(decided)) if decided else None,
        "gate_n20": len(decided) >= 20,
        "degree_end": state.degree_primary,
        "checkpoints": checks,
        "isolation_zh": "專鍋；不混海選／黃金買點／洞燭／AI倉／個股",
        "not_buy_signal": True,
        "WAVE_NEURONS_MATCH": False,
        "note_zh": "冷啟動重播完成至最新開市日；段號暫定；主分＝自推對日盤。不上話筒。",
    }

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    ART.mkdir(parents=True, exist_ok=True)
    jsonl = OUT_DIR / "wave_jan_replay_daily.jsonl"
    with jsonl.open("w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    # 摘要不塞滿每日正文
    sum_path = OUT_DIR / "wave_jan_replay_summary.json"
    sum_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    (OUT_DIR / "wave_jan_replay_latest.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (ART / "wave_jan_replay_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    # 精簡 jsonl 到 artifacts 太大可能；只放 summary + 最後 5 日
    tail = {"tail_days": rows[-5:], "summary": summary}
    (ART / "wave_jan_replay_tail.json").write_text(
        json.dumps(tail, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(
        "GATE",
        f"wave_jan_replay {START}→{end} days={len(open_days)} decided={len(decided)} "
        f"hit_rate={summary['hit_rate']} phone_sync=blocked",
    )
    return summary


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--end", default="", help="YYYYMMDD latest open day cap")
    args = ap.parse_args()
    run(end=args.end or None)


if __name__ == "__main__":
    main()
