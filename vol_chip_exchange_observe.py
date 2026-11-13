# -*- coding: utf-8 -*-
"""查股當下：近 1～2 周「爆大量＋換手」觀察（不是買訊）。

只用官方日 K 開高低收＋量；有三大法人張數就當換手輔助。
不准寫新主力／幹大事／漲幅空間。
"""
from __future__ import annotations

import sqlite3
from typing import Any, Dict, List, Optional, Sequence, Tuple

NOTE_ZH = "近兩周爆量換手觀察（不是買訊）"
BADGE_ZH = "近兩周爆量換手"


def _ymd(raw: Any) -> str:
    t = str(raw or "").replace("-", "")[:8]
    return t if len(t) == 8 and t.isdigit() else ""


def _load_bars(
    db_path: str, stock_id: str, *, limit: int = 80
) -> List[Dict[str, Any]]:
    sid = str(stock_id or "").strip()
    if not sid or not db_path:
        return []
    conn = sqlite3.connect(db_path)
    try:
        rows = conn.execute(
            "SELECT date, open, high, low, close, volume, "
            "foreign_net, trust_net, dealer_net "
            "FROM daily_quotes WHERE stock_id=? ORDER BY date DESC LIMIT ?",
            (sid, int(limit)),
        ).fetchall()
    finally:
        conn.close()
    out: List[Dict[str, Any]] = []
    for r in reversed(rows or []):
        d = _ymd(r[0])
        if not d:
            continue
        try:
            o, h, l, c = float(r[1]), float(r[2]), float(r[3]), float(r[4])
            v = float(r[5] or 0)
        except (TypeError, ValueError):
            continue
        if c <= 0 or v < 0:
            continue
        fn = tn = dn = None
        try:
            if r[6] is not None:
                fn = float(r[6])
            if r[7] is not None:
                tn = float(r[7])
            if r[8] is not None:
                dn = float(r[8])
        except (TypeError, ValueError):
            pass
        out.append(
            {
                "date": d,
                "open": o,
                "high": h,
                "low": l,
                "close": c,
                "volume": v,
                "foreign_net": fn,
                "trust_net": tn,
                "dealer_net": dn,
            }
        )
    return out


def _vol_ranks(volumes: Sequence[float]) -> List[int]:
    n = len(volumes)
    order = sorted(range(n), key=lambda i: (-float(volumes[i]), i))
    ranks = [0] * n
    for r, i in enumerate(order, start=1):
        ranks[i] = r
    return ranks


def detect_recent_vol_chip_exchange(
    db_path: str,
    stock_id: str,
    *,
    recent_days: int = 10,
    lookback: int = 40,
    top_rank: int = 8,
    min_top_days: int = 2,
    strong_rank: int = 3,
    range_pct: float = 4.0,
    min_wide_days: int = 2,
) -> Dict[str, Any]:
    """近 recent_days（最多約兩周交易日）相對 lookback 窗是否爆量換手。

    爆大量：近窗內 ≥min_top_days 日量排名≤top_rank，或至少一日排名≤strong_rank。
    換手：那些大量日中 ≥min_wide_days 日振幅≥range_pct%；
         若有法人張數，近窗 |淨額| 加總 ≥ 前段中位日的 1.5 倍也算過。
    """
    sid = str(stock_id or "").strip()
    out: Dict[str, Any] = {
        "stock_id": sid,
        "hit": False,
        "buy_signal": False,
        "note_zh": "",
        "badge_zh": "",
        "spike_dates": [],
        "wide_dates": [],
        "n_top": 0,
        "best_rank": None,
        "recent_days": int(recent_days),
        "lookback": int(lookback),
        "reason": "",
    }
    recent = max(5, min(10, int(recent_days or 10)))  # 一週～兩週
    lb = max(recent + 5, int(lookback or 40))
    bars = _load_bars(db_path, sid, limit=lb + 5)
    if len(bars) < lb:
        out["reason"] = "bars_short"
        return out
    win = bars[-lb:]
    vols = [float(b["volume"]) for b in win]
    ranks = _vol_ranks(vols)
    recent_slice = list(range(lb - recent, lb))
    top_idxs = [i for i in recent_slice if ranks[i] <= int(top_rank)]
    best = min((ranks[i] for i in recent_slice), default=None)
    vol_hit = len(top_idxs) >= int(min_top_days) or (
        best is not None and int(best) <= int(strong_rank)
    )
    out["n_top"] = len(top_idxs)
    out["best_rank"] = int(best) if best is not None else None
    out["spike_dates"] = [win[i]["date"] for i in top_idxs]
    if not vol_hit:
        out["reason"] = "no_volume_spike"
        return out

    wide: List[str] = []
    for i in top_idxs:
        b = win[i]
        c = float(b["close"]) or 1.0
        rng = (float(b["high"]) - float(b["low"])) / c * 100.0
        if rng >= float(range_pct):
            wide.append(b["date"])
    out["wide_dates"] = wide
    range_hit = len(wide) >= int(min_wide_days) or (
        len(top_idxs) == 1 and len(wide) == 1 and best is not None and int(best) <= int(strong_rank)
    )

    chip_hit = False
    abs_recent = 0.0
    abs_prior_med = 0.0
    daily_abs: List[float] = []
    for b in win:
        parts = []
        for k in ("foreign_net", "trust_net", "dealer_net"):
            if b.get(k) is not None:
                parts.append(abs(float(b[k])))
        daily_abs.append(sum(parts) if parts else 0.0)
    if any(daily_abs):
        abs_recent = float(sum(daily_abs[lb - recent : lb]))
        prior = daily_abs[: lb - recent] or daily_abs
        prior_sorted = sorted(prior)
        mid = prior_sorted[len(prior_sorted) // 2]
        abs_prior_med = float(mid) * float(recent)
        if abs_prior_med > 0 and abs_recent >= abs_prior_med * 1.5:
            chip_hit = True
    out["abs_inst_recent"] = round(abs_recent, 1)
    out["abs_inst_prior_med_window"] = round(abs_prior_med, 1)

    exchange_hit = bool(range_hit or chip_hit)
    if not exchange_hit:
        out["reason"] = "spike_but_no_exchange_proxy"
        return out

    out["hit"] = True
    out["buy_signal"] = False
    out["note_zh"] = NOTE_ZH
    out["badge_zh"] = BADGE_ZH
    out["reason"] = "vol_spike_and_exchange"
    return out


def attach_vol_chip_exchange_observe(
    card: Optional[dict], db_path: str, stock_id: str = ""
) -> Optional[Dict[str, Any]]:
    """寫進決策卡：hit 才掛徽章與 observe 欄；永遠 buy_signal=False。

    hit 當日默默落檔（kind=vol_chip_exchange），供後續對質；不上話筒報過程。
    """
    if not isinstance(card, dict) or card.get("error"):
        return None
    sid = str(stock_id or card.get("stock_id") or "").strip()
    hit = detect_recent_vol_chip_exchange(db_path, sid)
    card["vol_chip_exchange"] = hit
    if not hit.get("hit"):
        return hit
    badge = str(hit.get("badge_zh") or BADGE_ZH)
    badges = list(card.get("badges") or [])
    if badge not in badges:
        badges.insert(0, badge)
    card["badges"] = badges
    try:
        from judge_tape import remember_rows

        spikes = hit.get("spike_dates") or []
        remember_rows(
            db_path,
            "vol_chip_exchange",
            [
                {
                    "stock_id": sid,
                    "stock_name": str(card.get("stock_name") or ""),
                    "close": card.get("close"),
                    "profit_pct": card.get("gain_pct"),
                    "why": (
                        f"n_top={hit.get('n_top')} best={hit.get('best_rank')} "
                        f"spikes={','.join(str(x) for x in spikes[:6])}"
                    ),
                    "src": "lookup",
                }
            ],
            as_of=str(card.get("latest_date") or card.get("as_of") or ""),
            pick="observe",
            src="lookup",
        )
    except Exception:
        pass
    return hit
