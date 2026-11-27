#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""飆大量規則多軌觀察：產業龍頭面板＋狀態機（觀察／對質，非買訊）。

硬邊界：
- Asia/Taipei；官方日 K；未收不當收
- phone_sync blocked；不准改 leave_zero
- 分軌對質，勝率不准混
"""
from __future__ import annotations

import argparse
import json
import sqlite3
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple
from zoneinfo import ZoneInfo

from scripts.biaoke_bottom_vol_observe_screen import (
    YEAR_LOOKBACK,
    latest_full_asof,
    load_bars,
    year_grade_floor as near_year_vol_floor,  # 程式鍵名；中文禁稱「一年級」→近一年前巨量
)

TAIPEI = ZoneInfo("Asia/Taipei")
ROOT = Path(__file__).resolve().parents[1]
LAB = ROOT / "docs" / "expert_notes" / "飆客" / "decade_lab"
DB_DEFAULT = ROOT / "data" / "wayne_market.db"
SPEC_PATH = LAB / "biaoke_vol_tracks_spec_20261127.json"

# 風向／龍頭面板（他點名＋taught 對照；光學＝待驗證獨立軌）
PANELS: List[Dict[str, Any]] = [
    # 2330＝市場沉澱錨，不併入產業同相票（單檔永不 vane_on）
    {"industry": "晶圓代工", "leaders": ["2330"], "role": "market_anchor"},
    {"industry": "PCB", "leaders": ["2383"], "role": "problem_vol"},
    {"industry": "光通訊", "leaders": ["6442", "2345", "3081"], "role": "vane"},
    {"industry": "ASIC", "leaders": ["3443", "5274", "3661"], "role": "vane"},
    {"industry": "散熱", "leaders": ["3017", "2059", "3653"], "role": "vane"},
    {"industry": "ABF", "leaders": ["3037"], "role": "contrast"},
    {"industry": "被動元件", "leaders": ["2327"], "role": "rebound_contrast"},
    {"industry": "光學", "leaders": ["3008"], "role": "pending_verify"},
]

LOW_ZONE_PCT = 12.0
HIGH_ZONE_PCT = 8.0
SEDIMENT_LOOKBACK = 15
CONSEC_WINDOW = 5


@dataclass
class PhaseSnap:
    stock_id: str
    stock_name: str
    industry: str
    role: str
    as_of: str
    close: float
    phase: str  # quiet|low_explode|high_explode|sediment
    flags: List[str]
    near_year_vol_floor: float
    vol_today: float
    vol_year_max: float
    consec_near_year_vol: int
    dist_to_low60_pct: float
    dist_to_high120_pct: float
    rs_5_vs_twii_pct: Optional[float]
    note_zh: str


def _ymd(raw: Any) -> str:
    t = str(raw or "").replace("-", "")[:8]
    return t if len(t) == 8 and t.isdigit() else ""


def _num(x: Any) -> float:
    try:
        return float(x)
    except (TypeError, ValueError):
        return 0.0


def load_twii(con: sqlite3.Connection) -> Dict[str, float]:
    rows = con.execute(
        "SELECT date, close FROM index_daily WHERE symbol='TWII' ORDER BY date"
    ).fetchall()
    return {_ymd(d): _num(c) for d, c in rows if _ymd(d) and _num(c) > 0}


def stock_name(con: sqlite3.Connection, sid: str) -> str:
    row = con.execute(
        "SELECT stock_name FROM stock_directory WHERE stock_id=? LIMIT 1", (sid,)
    ).fetchone()
    return str(row[0] or sid).strip() if row else sid


def _is_yg(v: float, floor: float) -> bool:
    return floor > 0 and v >= floor - 1e-9


def classify_phase(bars: Sequence[Dict[str, float]]) -> Tuple[str, List[str], Dict[str, float]]:
    """回傳 (phase, flags, metrics)。sediment 優先於 explode。"""
    flags: List[str] = []
    empty = {
        "floor": 0.0,
        "ymax": 0.0,
        "consec": 0.0,
        "dist_lo": 0.0,
        "dist_hi": 0.0,
        "vol": 0.0,
    }
    if len(bars) < 120:
        return "quiet", flags, empty
    year = list(bars[-YEAR_LOOKBACK:]) if len(bars) >= YEAR_LOOKBACK else list(bars)
    win60 = list(bars[-60:])
    win120 = list(bars[-120:])
    last = bars[-1]
    floor, ymax = near_year_vol_floor([b["volume"] for b in year])
    if floor <= 0:
        return "quiet", flags, empty
    low60 = min(b["low"] for b in win60 if b["low"] > 0)
    high120 = max(b["high"] for b in win120 if b["high"] > 0)
    close = last["close"]
    if close <= 0 or low60 <= 0 or high120 <= 0:
        return "quiet", flags, empty
    dist_lo = (close - low60) / low60 * 100.0
    dist_hi = (high120 - close) / high120 * 100.0

    recent5 = list(bars[-CONSEC_WINDOW:])
    yg5 = [1 if _is_yg(b["volume"], floor) else 0 for b in recent5]
    consec = 0
    run = 0
    for f in yg5:
        if f:
            run += 1
            consec = max(consec, run)
        else:
            run = 0

    # 近窗近一年前巨量根的高低位歸類
    look = list(bars[-SEDIMENT_LOOKBACK:])
    low_yg = False
    high_yg = False
    peak_yg = 0.0
    for b in look:
        if not _is_yg(b["volume"], floor):
            continue
        peak_yg = max(peak_yg, b["volume"])
        if b["low"] > 0 and (b["low"] - low60) / low60 * 100.0 <= LOW_ZONE_PCT:
            low_yg = True
            flags.append("low_near_year_vol")
        if b["high"] > 0 and (high120 - b["high"]) / high120 * 100.0 <= HIGH_ZONE_PCT:
            high_yg = True
            flags.append("high_near_year_vol")

    med60_vols = sorted(b["volume"] for b in win60 if b["volume"] > 0)
    med60 = med60_vols[len(med60_vols) // 2] if med60_vols else 0.0
    sediment = False
    if low_yg and peak_yg > 0 and med60 > 0:
        if med60 * 0.5 <= last["volume"] < peak_yg * 0.65:
            sediment = True
            flags.append("sediment_ok")

    if consec >= 2 and low_yg:
        flags.append("consec_low_explode")

    metrics = {
        "floor": floor,
        "ymax": ymax,
        "consec": float(consec),
        "dist_lo": dist_lo,
        "dist_hi": dist_hi,
        "vol": last["volume"],
    }

    if sediment:
        return "sediment", sorted(set(flags)), metrics
    if consec >= 2 and low_yg:
        return "low_explode", sorted(set(flags)), metrics
    if sum(yg5) >= 1 and low_yg:
        flags.append("single_low_explode")
        return "low_explode", sorted(set(flags)), metrics
    if high_yg and sum(yg5) >= 1:
        return "high_explode", sorted(set(flags)), metrics
    return "quiet", sorted(set(flags)), metrics


def rs_vs_twii(
    bars: Sequence[Dict[str, float]], twii: Dict[str, float], *, days: int = 5
) -> Optional[float]:
    if len(bars) < days + 1:
        return None
    d1 = bars[-(days + 1)]["date"]
    d0 = bars[-1]["date"]
    c1, c0 = bars[-(days + 1)]["close"], bars[-1]["close"]
    t1, t0 = twii.get(d1), twii.get(d0)
    if not (c1 and c0 and t1 and t0):
        return None
    stock_r = (c0 / c1 - 1.0) * 100.0
    twii_r = (t0 / t1 - 1.0) * 100.0
    return round(stock_r - twii_r, 3)


def snap_leader(
    con: sqlite3.Connection,
    *,
    sid: str,
    industry: str,
    role: str,
    as_of: str,
    twii: Dict[str, float],
) -> Optional[PhaseSnap]:
    bars = load_bars(con, sid)
    if not bars or bars[-1]["date"] != as_of:
        return None
    phase, flags, m = classify_phase(bars)
    note = (
        f"相={phase}；距60低{m['dist_lo']:.1f}%；距120高剩餘{m['dist_hi']:.1f}%；"
        f"近一年前巨量門檻={m['floor']:.0f}（年最大{m['ymax']:.0f}）；"
        f"近{CONSEC_WINDOW}連={int(m['consec'])}；flags={','.join(flags) or '—'}"
    )
    return PhaseSnap(
        stock_id=sid,
        stock_name=stock_name(con, sid),
        industry=industry,
        role=role,
        as_of=as_of,
        close=bars[-1]["close"],
        phase=phase,
        flags=flags,
        near_year_vol_floor=round(m["floor"], 1),
        vol_today=m["vol"],
        vol_year_max=m["ymax"],
        consec_near_year_vol=int(m["consec"]),
        dist_to_low60_pct=round(m["dist_lo"], 2),
        dist_to_high120_pct=round(m["dist_hi"], 2),
        rs_5_vs_twii_pct=rs_vs_twii(bars, twii, days=5),
        note_zh=note,
    )


def industry_vane(snaps: Sequence[PhaseSnap]) -> Dict[str, Any]:
    """產業量轉：有效指標≥2 且同相（low_explode／sediment）≥2。

    單檔面板（台積／台光電等）只標 anchor_active，永不 vane_on——
    避免把個股事件誤當產業風向。
    """
    active = [s for s in snaps if s.phase in ("low_explode", "sediment")]
    n = len(snaps)
    need = 2
    on = n >= 2 and len(active) >= need
    anchor_active = n < 2 and len(active) >= 1
    return {
        "vane_on": on,
        "anchor_active": anchor_active,
        "active_n": len(active),
        "need_n": need if n >= 2 else None,
        "phases": {s.stock_id: s.phase for s in snaps},
        "active_ids": [s.stock_id for s in active],
    }


def forward_slice(
    con: sqlite3.Connection,
    sid: str,
    as_of: str,
    horizons: Sequence[int] = (5, 10, 20),
) -> Dict[str, Optional[float]]:
    """簡易往前報酬（開市日根數）；不夠長＝None。對質用，非買訊。"""
    bars = load_bars(con, sid, lookback=400)
    idx = next((i for i, b in enumerate(bars) if b["date"] == as_of), -1)
    out: Dict[str, Optional[float]] = {}
    if idx < 0:
        return {f"fwd_{h}": None for h in horizons}
    c0 = bars[idx]["close"]
    for h in horizons:
        j = idx + int(h)
        if j >= len(bars) or c0 <= 0:
            out[f"fwd_{h}"] = None
        else:
            out[f"fwd_{h}"] = round((bars[j]["close"] / c0 - 1.0) * 100.0, 3)
    return out


def screen(db_path: str, *, as_of: str = "") -> Dict[str, Any]:
    con = sqlite3.connect(db_path)
    try:
        asof = _ymd(as_of) or latest_full_asof(con)
        if not asof:
            return {"ok": False, "reason": "no_full_asof"}
        twii = load_twii(con)
        leaders: List[Dict[str, Any]] = []
        by_ind: Dict[str, List[PhaseSnap]] = {}
        for panel in PANELS:
            ind = str(panel["industry"])
            role = str(panel.get("role") or "")
            snaps: List[PhaseSnap] = []
            for sid in panel["leaders"]:
                snap = snap_leader(
                    con, sid=str(sid), industry=ind, role=role, as_of=asof, twii=twii
                )
                if not snap:
                    leaders.append(
                        {
                            "stock_id": sid,
                            "industry": ind,
                            "role": role,
                            "as_of": asof,
                            "phase": "no_bar",
                            "note_zh": "當日無完整官方柱",
                        }
                    )
                    continue
                snaps.append(snap)
                row = asdict(snap)
                # 当日无法算未来；保留栏位给回扫
                row["forward"] = {f"fwd_{h}": None for h in (5, 10, 20)}
                leaders.append(row)
            by_ind[ind] = snaps

        vanes = []
        for ind, snaps in by_ind.items():
            if not snaps:
                continue
            v = industry_vane(snaps)
            vanes.append({"industry": ind, **v})

        # 分軌當日計數（討論用現況，不是勝率）
        phase_counts: Dict[str, int] = {}
        for row in leaders:
            p = str(row.get("phase") or "")
            phase_counts[p] = phase_counts.get(p, 0) + 1

        return {
            "ok": True,
            "as_of": asof,
            "phone_sync": "blocked",
            "buy_signal": False,
            "not_buy_signal": True,
            "tracks": ["T1_low_explode", "T2_sediment", "T3_hi_lo_split", "T4_vol_leads_price", "T5_industry_vane", "T6_leader_peer_lag"],
            "discuss_order_zh": [
                "先對齊 T3 高低異義與 T2 沉澱定義",
                "再看 T1／T5 當日面板",
                "T4／T6 要較長窗回掃",
            ],
            "phase_counts": phase_counts,
            "n_leaders": len(leaders),
            "leaders": leaders,
            "industry_vanes": vanes,
            "vane_on_industries": [v["industry"] for v in vanes if v.get("vane_on")],
            "anchor_active_industries": [
                v["industry"] for v in vanes if v.get("anchor_active")
            ],
            "written_at": datetime.now(TAIPEI).strftime("%Y-%m-%dT%H:%M:%S%z"),
            "spec": str(SPEC_PATH.relative_to(ROOT)),
        }
    finally:
        con.close()


def backfill_hi_lo_split(
    db_path: str,
    *,
    as_of: str = "",
    lookback_days: int = 120,
    sample_sids: Optional[Sequence[str]] = None,
) -> Dict[str, Any]:
    """T3 高低位爆量異義：掃面板股近窗近一年前巨量日，分 low/high 區統計（觀察）。"""
    con = sqlite3.connect(db_path)
    try:
        asof = _ymd(as_of) or latest_full_asof(con)
        sids = list(sample_sids or [])
        if not sids:
            for p in PANELS:
                sids.extend(str(x) for x in p["leaders"])
        low_events = 0
        high_events = 0
        both = 0
        detail: List[Dict[str, Any]] = []
        for sid in sorted(set(sids)):
            bars = load_bars(con, sid, lookback=YEAR_LOOKBACK + lookback_days)
            if len(bars) < 120:
                continue
            # truncate to asof
            bars = [b for b in bars if b["date"] <= asof]
            if len(bars) < 120:
                continue
            year = bars[-YEAR_LOOKBACK:]
            floor, ymax = near_year_vol_floor([b["volume"] for b in year])
            if floor <= 0:
                continue
            win = bars[-lookback_days:] if len(bars) >= lookback_days else bars
            for i, b in enumerate(win):
                if not _is_yg(b["volume"], floor):
                    continue
                # local 60/120 ending at i within full bars
                abs_i = len(bars) - len(win) + i
                w60 = bars[max(0, abs_i - 59) : abs_i + 1]
                w120 = bars[max(0, abs_i - 119) : abs_i + 1]
                low60 = min(x["low"] for x in w60 if x["low"] > 0)
                high120 = max(x["high"] for x in w120 if x["high"] > 0)
                if low60 <= 0 or high120 <= 0:
                    continue
                lo = (b["low"] - low60) / low60 * 100.0
                hi = (high120 - b["high"]) / high120 * 100.0
                is_lo = lo <= LOW_ZONE_PCT
                is_hi = hi <= HIGH_ZONE_PCT
                if is_lo and is_hi:
                    both += 1
                    zone = "both"
                elif is_lo:
                    low_events += 1
                    zone = "low"
                elif is_hi:
                    high_events += 1
                    zone = "high"
                else:
                    zone = "mid"
                detail.append(
                    {
                        "stock_id": sid,
                        "date": b["date"],
                        "zone": zone,
                        "vol": b["volume"],
                        "floor": round(floor, 1),
                        "ymax": ymax,
                    }
                )
        return {
            "ok": True,
            "track": "T3_hi_lo_split",
            "as_of": asof,
            "lookback_days": lookback_days,
            "n_low": low_events,
            "n_high": high_events,
            "n_both": both,
            "n_mid_or_other": sum(1 for d in detail if d["zone"] == "mid"),
            "n_events": len(detail),
            "phone_sync": "blocked",
            "buy_signal": False,
            "note_zh": "只計事件分區樣本；fwd 對質另開長窗回掃。空事件不算有記。",
            "sample_tail": detail[-30:],
        }
    finally:
        con.close()


def main() -> int:
    ap = argparse.ArgumentParser(description="量規則多軌龍頭觀察（非買訊）")
    ap.add_argument("--db", default=str(DB_DEFAULT))
    ap.add_argument("--as-of", default="")
    ap.add_argument("--t3-only", action="store_true")
    ap.add_argument(
        "--out",
        default="",
        help="寫出 JSON；預設 decade_lab/biaoke_leader_vol_tracks_{asof}.json",
    )
    args = ap.parse_args()
    if args.t3_only:
        out = backfill_hi_lo_split(args.db, as_of=args.as_of)
    else:
        out = screen(args.db, as_of=args.as_of)
        t3 = backfill_hi_lo_split(args.db, as_of=out.get("as_of") or args.as_of)
        out["t3_hi_lo_split"] = {
            k: t3.get(k)
            for k in (
                "n_low",
                "n_high",
                "n_both",
                "n_mid_or_other",
                "n_events",
                "lookback_days",
                "note_zh",
            )
        }
    asof = str(out.get("as_of") or "unknown")
    path = Path(args.out) if args.out else LAB / f"biaoke_leader_vol_tracks_{asof}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    latest = LAB / "biaoke_leader_vol_tracks_latest.json"
    latest.write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
    print(json.dumps({"ok": out.get("ok"), "as_of": asof, "out": str(path)}, ensure_ascii=False))
    return 0 if out.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
