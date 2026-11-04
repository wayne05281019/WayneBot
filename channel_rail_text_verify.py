# -*- coding: utf-8 -*-
"""平行軌圖／文字準度・靜默對質（非買訊；face=false）。

量什麼（OHLC 可重算）：
  1. 現況句 pos 與 rail_now／base_now／收盤幾何是否一致（圖文同鍋）
  2. 分桶前瞻：靠近下軌／中段／靠近上軌 → h1／h3／h5 報酬與是否守住下軌
  3. 空通道誠實：推不出軌時腳註不准寫「雙線／淡灰藍虛線＝平行趨勢」

對照基線：無通道日（no_channel）。
硬規則：官方已收柱；盤中未收不當收；不准假數；不准改 leave_zero／
golden_buy／ma60_lower／海選；Asia/Taipei；勝率分軌不准混；
n≥20 獨立交易日且贏基線才談「文字準度旁註」上臉——買訊永遠不准從這軌升。
§13：現況 pos_geom 過關後再生下一版 pos_hold_tight（下軌±寬度 20%）。
"""
from __future__ import annotations

import os
import sqlite3
from typing import Any, Dict, List, Optional, Sequence, Tuple

from dongzhu_tape import OPTIMIZE_MIN_N, tape_store_path

KIND = "channel_rail_text"
TAG_NEAR_LO = "near_lower"  # 靠近上升軌／平行撐
TAG_MID = "mid_channel"
TAG_NEAR_HI = "near_upper"  # 靠近平行壓／下降壓
TAG_BROKEN = "broken_or_over"  # 破軌／過軌（alive=False 或過緣）
TAG_NONE = "no_channel"  # 基線：推不出合格平行軌
TAG_NEXT = "near_lower_tight"  # §13 下一版：更貼下軌
FACE_DEFAULT = False
PRODUCT_ENTRY = False  # 永遠不當買訊
FORWARD_H: Tuple[int, ...] = (1, 3, 5)
MIN_BARS = 40
LOOKBACK = 80
MIN_UNIQUE_DAYS = OPTIMIZE_MIN_N
MIN_DISTINCT_SIDS = 40
# 幾何一致率底線（同一公式重算）；低於此＝編碼／文案脫節
MIN_GEOM_HIT = 0.98
# 文字準度旁註候選：靠近下軌 h5 守軌率須贏無通道基線
MIN_HOLD_EDGE = 0.03


def _ymd(raw: Any) -> str:
    t = str(raw or "").replace("-", "")[:8]
    return t if len(t) == 8 and t.isdigit() else ""


def _num(val: Any, default: float = 0.0) -> float:
    try:
        if val is None or val == "":
            return default
        return float(val)
    except (TypeError, ValueError):
        return default


def ensure_tables(db_path: str) -> str:
    store = tape_store_path(db_path)
    os.makedirs(os.path.dirname(store) or ".", exist_ok=True)
    con = sqlite3.connect(store, timeout=8.0)
    try:
        con.executescript(
            """
            CREATE TABLE IF NOT EXISTS channel_rail_text_tape (
                kind TEXT NOT NULL,
                as_of TEXT NOT NULL,
                sid TEXT NOT NULL,
                tag TEXT NOT NULL,
                kind_ch TEXT DEFAULT '',
                pos TEXT DEFAULT '',
                geom_ok INTEGER NOT NULL DEFAULT 0,
                close REAL,
                rail REAL,
                base REAL,
                width REAL,
                PRIMARY KEY (kind, as_of, sid, tag)
            );
            CREATE TABLE IF NOT EXISTS channel_rail_text_score (
                kind TEXT NOT NULL,
                as_of TEXT NOT NULL,
                sid TEXT NOT NULL,
                tag TEXT NOT NULL,
                horizon INTEGER NOT NULL,
                check_as_of TEXT NOT NULL,
                entry REAL,
                exit REAL,
                ret_pct REAL,
                hold_rail INTEGER,
                verdict TEXT NOT NULL,
                PRIMARY KEY (kind, as_of, sid, tag, horizon)
            );
            CREATE TABLE IF NOT EXISTS channel_rail_text_rates (
                kind TEXT NOT NULL,
                tag TEXT NOT NULL,
                horizon INTEGER NOT NULL,
                n INTEGER NOT NULL,
                hit INTEGER NOT NULL,
                miss INTEGER NOT NULL,
                pending INTEGER NOT NULL,
                hold_rail INTEGER NOT NULL,
                avg_ret REAL,
                updated_at TEXT NOT NULL,
                PRIMARY KEY (kind, tag, horizon)
            );
            """
        )
        con.commit()
    finally:
        con.close()
    return store


def recompute_pos(
    *,
    kind: str,
    last: float,
    rail_now: float,
    base_now: float,
    width: float,
    span: float,
) -> Tuple[str, bool]:
    """與 biaoke_chart.infer_parallel_channel 同一套現況句／alive。"""
    w = max(float(width), 1e-9)
    sp = max(float(span), 1.0)
    last = float(last)
    rail = float(rail_now)
    base = float(base_now)
    if kind == "desc":
        if last > rail + sp * 0.02:
            return "過下降壓", False
        if last < base - sp * 0.02:
            return "破平行撐", True
        if last >= base + w * 0.66:
            return "靠近下降壓", True
        if last <= base + w * 0.34:
            return "靠近平行撐", True
        return "下降通道中段", True
    if last < base - sp * 0.02:
        return "破上升軌", False
    if last > rail + sp * 0.02:
        return "過平行壓", True
    if last >= base + w * 0.66:
        return "靠近平行壓", True
    if last <= base + w * 0.34:
        return "靠近上升軌", True
    return "上升通道中段", True


def pos_tag(pos: str, *, alive: bool) -> str:
    p = str(pos or "")
    if (not alive) or ("破" in p) or p.startswith("過"):
        return TAG_BROKEN
    if "中段" in p:
        return TAG_MID
    if any(k in p for k in ("平行撐", "上升軌")):
        return TAG_NEAR_LO
    if any(k in p for k in ("平行壓", "下降壓")):
        return TAG_NEAR_HI
    return TAG_MID


def near_lower_tight(
    *,
    last: float,
    rail_now: float,
    base_now: float,
    width: float,
) -> bool:
    """下一版：收在下軌起算寬度 20% 內（更貼下軌）。"""
    w = max(float(width), 1e-9)
    base = float(base_now)
    last = float(last)
    return base - w * 0.02 <= last <= base + w * 0.20


def classify_channel_day(ch: Dict[str, Any], *, last: float, span: float) -> Dict[str, Any]:
    """單日：幾何對質＋分桶標籤。空通道→ no_channel。"""
    from vol_zone_chart import channel_has_drawable_rails

    if not channel_has_drawable_rails(ch):
        return {
            "tag": TAG_NONE,
            "geom_ok": True,
            "pos": "",
            "kind_ch": "",
            "alive": False,
            "rail": 0.0,
            "base": 0.0,
            "width": 0.0,
            "tight": False,
        }
    kind = str(ch.get("kind") or "")
    rail = _num(ch.get("rail_now"))
    base = _num(ch.get("base_now"))
    width = _num(ch.get("width"), abs(rail - base))
    stated = str(ch.get("pos") or "")
    alive_stated = bool(ch.get("alive"))
    pos2, alive2 = recompute_pos(
        kind=kind,
        last=float(last),
        rail_now=rail,
        base_now=base,
        width=width,
        span=float(span),
    )
    geom_ok = (pos2 == stated) and (alive2 == alive_stated)
    tag = pos_tag(stated or pos2, alive=alive_stated if stated else alive2)
    tight = near_lower_tight(
        last=float(last), rail_now=rail, base_now=base, width=width
    )
    return {
        "tag": tag,
        "geom_ok": geom_ok,
        "pos": stated or pos2,
        "kind_ch": kind,
        "alive": alive_stated if stated else alive2,
        "rail": rail,
        "base": base,
        "width": width,
        "tight": tight,
        "pos_recompute": pos2,
    }


def load_bars(db_path: str, sid: str, *, need: int = LOOKBACK) -> List[Dict[str, Any]]:
    con = sqlite3.connect(db_path, timeout=8.0)
    try:
        rows = con.execute(
            "SELECT date, open, high, low, close, volume FROM daily_quotes "
            "WHERE stock_id=? ORDER BY date DESC LIMIT ?",
            (str(sid), int(need)),
        ).fetchall()
    finally:
        con.close()
    out = [
        {
            "date": _ymd(d),
            "open": _num(o),
            "high": _num(h),
            "low": _num(l),
            "close": _num(c),
            "volume": _num(v),
        }
        for d, o, h, l, c, v in reversed(rows)
        if _ymd(d)
    ]
    return out


def list_stock_ids(db_path: str, *, limit: int = 80) -> List[str]:
    con = sqlite3.connect(db_path, timeout=8.0)
    try:
        rows = con.execute(
            "SELECT stock_id FROM stock_universe "
            "WHERE COALESCE(is_active,1)=1 AND COALESCE(asset_type,'STOCK')='STOCK' "
            "ORDER BY stock_id LIMIT ?",
            (int(limit),),
        ).fetchall()
    except sqlite3.Error:
        rows = con.execute(
            "SELECT DISTINCT stock_id FROM daily_quotes ORDER BY stock_id LIMIT ?",
            (int(limit),),
        ).fetchall()
    finally:
        con.close()
    return [str(r[0]) for r in rows if r and r[0]]


def score_forward(
    bars: Sequence[Dict[str, Any]],
    *,
    i: int,
    base: float,
    tag: str,
) -> List[Dict[str, Any]]:
    """前瞻報酬＋是否守住下軌（期間最低 ≥ base − 2%·幅）。"""
    entry = _num(bars[i].get("close"))
    if entry <= 0:
        return []
    as_of = _ymd(bars[i].get("date"))
    span = max(
        max(_num(b.get("high")) for b in bars[max(0, i - 20) : i + 1])
        - min(
            (_num(b.get("low")) for b in bars[max(0, i - 20) : i + 1] if _num(b.get("low")) > 0),
            default=entry,
        ),
        1.0,
    )
    floor = float(base) - span * 0.02 if base > 0 else 0.0
    out: List[Dict[str, Any]] = []
    for h in FORWARD_H:
        j = i + int(h)
        if j >= len(bars):
            out.append(
                {
                    "as_of": as_of,
                    "tag": tag,
                    "horizon": int(h),
                    "check_as_of": "",
                    "entry": entry,
                    "exit": None,
                    "ret_pct": None,
                    "hold_rail": None,
                    "verdict": "pending",
                }
            )
            continue
        ex = _num(bars[j].get("close"))
        mn = min(_num(bars[k].get("low")) for k in range(i + 1, j + 1))
        hold = 1 if (floor <= 0 or mn >= floor) else 0
        ret = (ex / entry - 1.0) * 100.0 if entry else 0.0
        out.append(
            {
                "as_of": as_of,
                "tag": tag,
                "horizon": int(h),
                "check_as_of": _ymd(bars[j].get("date")),
                "entry": entry,
                "exit": ex,
                "ret_pct": ret,
                "hold_rail": hold,
                "verdict": "hit" if ret > 0 else "miss",
            }
        )
    return out


def scan_stock_history(
    db_path: str,
    sid: str,
    *,
    bars: Optional[Sequence[Dict[str, Any]]] = None,
    max_events: int = 30,
    persist: bool = True,
) -> Dict[str, Any]:
    from biaoke_chart import infer_parallel_channel

    rows = list(bars) if bars is not None else load_bars(db_path, sid, need=LOOKBACK + 40)
    if len(rows) < MIN_BARS:
        return {"sid": sid, "n": 0, "events": []}
    store = ensure_tables(db_path) if persist else ""
    events: List[Dict[str, Any]] = []
    scores: List[Dict[str, Any]] = []
    # 每隔 3 根採樣，避免同窗重複
    step = 3
    start = MIN_BARS
    for i in range(start, len(rows) - max(FORWARD_H), step):
        if len(events) >= int(max_events):
            break
        window = rows[max(0, i + 1 - LOOKBACK) : i + 1]
        ch = infer_parallel_channel(window) or {}
        last = _num(rows[i].get("close"))
        highs = [_num(b.get("high")) for b in window]
        lows = [_num(b.get("low")) for b in window if _num(b.get("low")) > 0]
        span = max(max(highs) - min(lows or [last]), 1.0)
        pack = classify_channel_day(ch, last=last, span=span)
        as_of = _ymd(rows[i].get("date"))
        tags = [str(pack["tag"])]
        if pack.get("tight") and pack["tag"] == TAG_NEAR_LO:
            tags.append(TAG_NEXT)
        for tag in tags:
            ev = {
                "kind": KIND,
                "as_of": as_of,
                "sid": str(sid),
                "tag": tag,
                "kind_ch": pack.get("kind_ch") or "",
                "pos": pack.get("pos") or "",
                "geom_ok": 1 if pack.get("geom_ok") else 0,
                "close": last,
                "rail": pack.get("rail") or 0.0,
                "base": pack.get("base") or 0.0,
                "width": pack.get("width") or 0.0,
            }
            events.append(ev)
            for sc in score_forward(
                rows, i=i, base=_num(pack.get("base")), tag=tag
            ):
                scores.append({**sc, "sid": str(sid), "kind": KIND})
    if persist and store and events:
        con = sqlite3.connect(store, timeout=8.0)
        try:
            con.executemany(
                "INSERT OR REPLACE INTO channel_rail_text_tape("
                "kind,as_of,sid,tag,kind_ch,pos,geom_ok,close,rail,base,width"
                ") VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                [
                    (
                        e["kind"],
                        e["as_of"],
                        e["sid"],
                        e["tag"],
                        e["kind_ch"],
                        e["pos"],
                        e["geom_ok"],
                        e["close"],
                        e["rail"],
                        e["base"],
                        e["width"],
                    )
                    for e in events
                ],
            )
            con.executemany(
                "INSERT OR REPLACE INTO channel_rail_text_score("
                "kind,as_of,sid,tag,horizon,check_as_of,entry,exit,ret_pct,hold_rail,verdict"
                ") VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                [
                    (
                        s["kind"],
                        s["as_of"],
                        s["sid"],
                        s["tag"],
                        s["horizon"],
                        s["check_as_of"],
                        s["entry"],
                        s["exit"],
                        s["ret_pct"],
                        s["hold_rail"],
                        s["verdict"],
                    )
                    for s in scores
                ],
            )
            con.commit()
        finally:
            con.close()
    return {"sid": sid, "n": len(events), "events": events, "scores": scores}


def _rates_from_scores(scores: Sequence[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    buckets: Dict[Tuple[str, int], Dict[str, Any]] = {}
    for s in scores:
        key = (str(s.get("tag")), int(s.get("horizon") or 0))
        b = buckets.setdefault(
            key,
            {
                "n": 0,
                "hit": 0,
                "miss": 0,
                "pending": 0,
                "hold_rail": 0,
                "rets": [],
            },
        )
        if s.get("verdict") == "pending" or s.get("ret_pct") is None:
            b["pending"] += 1
            continue
        b["n"] += 1
        if s.get("verdict") == "hit":
            b["hit"] += 1
        else:
            b["miss"] += 1
        if int(s.get("hold_rail") or 0) == 1:
            b["hold_rail"] += 1
        b["rets"].append(float(s["ret_pct"]))
    out: Dict[str, Dict[str, Any]] = {}
    for (tag, h), b in buckets.items():
        n = int(b["n"])
        avg = (sum(b["rets"]) / n) if n else None
        out[f"{tag}:h{h}"] = {
            "tag": tag,
            "horizon": h,
            "n": n,
            "hit": b["hit"],
            "miss": b["miss"],
            "pending": b["pending"],
            "hold_rail": b["hold_rail"],
            "hold_rate": (b["hold_rail"] / n) if n else None,
            "hit_rate": (b["hit"] / n) if n else None,
            "avg_ret": avg,
        }
    return out


def geom_consistency(events: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    ch_ev = [e for e in events if str(e.get("tag")) != TAG_NONE]
    n = len(ch_ev)
    ok = sum(1 for e in ch_ev if int(e.get("geom_ok") or 0) == 1)
    rate = (ok / n) if n else 1.0
    return {"n": n, "ok": ok, "rate": rate, "pass": rate >= MIN_GEOM_HIT}


def gate_status(
    db_path: str,
    *,
    scores: Optional[Sequence[Dict[str, Any]]] = None,
    events: Optional[Sequence[Dict[str, Any]]] = None,
    horizon: int = 5,
) -> Dict[str, Any]:
    """文字準度閘：幾何一致＋靠近下軌守軌贏無通道；永遠 PRODUCT_ENTRY=False。"""
    if scores is None or events is None:
        store = tape_store_path(db_path)
        events = events or []
        scores = scores or []
        if os.path.isfile(store):
            con = sqlite3.connect(store, timeout=8.0)
            try:
                if not events:
                    events = [
                        {
                            "tag": r[0],
                            "as_of": r[1],
                            "sid": r[2],
                            "geom_ok": r[3],
                        }
                        for r in con.execute(
                            "SELECT tag, as_of, sid, geom_ok FROM channel_rail_text_tape "
                            "WHERE kind=?",
                            (KIND,),
                        )
                    ]
                if not scores:
                    scores = [
                        {
                            "tag": r[0],
                            "as_of": r[1],
                            "sid": r[2],
                            "horizon": r[3],
                            "ret_pct": r[4],
                            "hold_rail": r[5],
                            "verdict": r[6],
                        }
                        for r in con.execute(
                            "SELECT tag, as_of, sid, horizon, ret_pct, hold_rail, verdict "
                            "FROM channel_rail_text_score WHERE kind=?",
                            (KIND,),
                        )
                    ]
            finally:
                con.close()
    geom = geom_consistency(events or [])
    rates = _rates_from_scores(scores or [])
    near = rates.get(f"{TAG_NEAR_LO}:h{horizon}") or {}
    none = rates.get(f"{TAG_NONE}:h{horizon}") or {}
    days = {str(e.get("as_of")) for e in (events or []) if e.get("as_of")}
    sids = {str(e.get("sid")) for e in (events or []) if e.get("sid")}
    n_days = len(days)
    n_sids = len(sids)
    n_ok = n_days >= MIN_UNIQUE_DAYS and n_sids >= MIN_DISTINCT_SIDS
    near_hold = near.get("hold_rate")
    none_hold = none.get("hold_rate")
    beats = (
        near_hold is not None
        and none_hold is not None
        and float(near_hold) >= float(none_hold) + MIN_HOLD_EDGE
        and int(near.get("n") or 0) >= 10
        and int(none.get("n") or 0) >= 10
    )
    text_promote = bool(geom.get("pass") and n_ok and beats)
    return {
        "kind": KIND,
        "face": FACE_DEFAULT,
        "product_entry": PRODUCT_ENTRY,
        "promote_ready": False,  # 買訊閘永遠關
        "text_promote_ready": text_promote,  # 僅腳註／旁註誠實候選
        "geom": geom,
        "n_unique_days": n_days,
        "n_sids": n_sids,
        "n_ok": n_ok,
        "near_lower": near,
        "no_channel": none,
        "near_beats_none_hold": beats,
        "next_candidate": TAG_NEXT,
        "rates": rates,
    }


def run_skeleton(
    db_path: str,
    *,
    stock_ids: Optional[Sequence[str]] = None,
    limit_stocks: int = 40,
    max_events: int = 20,
) -> Dict[str, Any]:
    ensure_tables(db_path)
    sids = list(stock_ids) if stock_ids else list_stock_ids(db_path, limit=limit_stocks)
    prefer = ["3081", "3017", "3653", "2454", "2368", "2330"]
    ordered: List[str] = []
    for p in prefer:
        if p in sids and p not in ordered:
            ordered.append(p)
    for s in sids:
        if s not in ordered:
            ordered.append(s)
    if limit_stocks > 0:
        ordered = ordered[: int(limit_stocks)]
    all_events: List[Dict[str, Any]] = []
    all_scores: List[Dict[str, Any]] = []
    for sid in ordered:
        pack = scan_stock_history(
            db_path, sid, max_events=max_events, persist=True
        )
        all_events.extend(pack.get("events") or [])
        all_scores.extend(pack.get("scores") or [])
    gate = gate_status(db_path, scores=all_scores, events=all_events)
    return {
        "ok": True,
        "face": FACE_DEFAULT,
        "product_entry": PRODUCT_ENTRY,
        "stocks": len(ordered),
        "events": len(all_events),
        "gate": gate,
        "definition": {
            "geom": "pos／alive 與 rail／base／收重算一致",
            "near_lower": "靠近上升軌／平行撐 → 前瞻守下軌",
            "baseline": "no_channel",
            "next": TAG_NEXT,
            "buy": "永遠不准升成買訊",
        },
    }


def empty_channel_foot_honest(
    *,
    with_parallel_channel: bool,
    with_nav_signals: bool,
    channel: Optional[Dict[str, Any]],
) -> bool:
    """安全修對質：無軌時腳註不准寫雙線／淡灰藍＝平行趨勢。"""
    from vol_zone_chart import vol_zone_parallel_rail_foot_bits

    bits = vol_zone_parallel_rail_foot_bits(
        with_parallel_channel=with_parallel_channel,
        with_nav_signals=with_nav_signals,
        channel=channel,
    )
    blob = f"{bits.get('quiet_bit') or ''}{bits.get('foot2') or ''}"
    has = bool(bits.get("has_rails"))
    if has:
        return "雙線＝可重算" in blob or "淡灰藍虛線＝平行趨勢" in blob
    bad = ("雙線＝可重算" in blob) or (
        "淡灰藍虛線＝平行趨勢" in blob and "推不出" not in blob
    )
    return (not bad) and ("推不出合格平行軌" in blob or not with_parallel_channel)
