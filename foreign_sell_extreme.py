# -*- coding: utf-8 -*-
"""極端大賣日→D+1～D+5（確認層）｜只觀察，不是買訊。

錨＝收盤後四大賣 lit 之日 D；主評 D+1～D+5 續危（價回撤／續極端分標）。
與 Fear／escalate 勝率分開。不准改 leave_zero。單位：張。
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Dict, List, Optional, Sequence, Tuple

from foreign_sell_escalate import (
    GRID_CUM10_THR,
    GRID_LOTS_THR,
    LIQUID_MIN_TURNOVER_K,
    LIQUID_MIN_VOL_LOTS,
    QIANJIN_PX,
    UNIVERSE_LIQUID,
    UNIVERSE_QIANJIN,
    UNIVERSE_TOP500_VOL,
    cum_sell_lots,
    lit_dump_cum10,
    lit_dump_lots,
    lit_dump_share,
    lit_dump_streak,
    sell_lots,
    units_banner,
)
from fear_composite import _f, sell_share

KIND = "foreign_sell_extreme_dplus"
TAG_PRICE_DD = "cont_price_dd"  # D 後價再回撤
TAG_CONT_EXTREME = "cont_extreme"  # D+1～D+5 再 lit 極端

SHARE_THR_GRID: Tuple[float, ...] = (0.10, 0.15, 0.20, 0.30)
STREAK_GRID: Tuple[int, ...] = (3, 5)
K_AHEAD_GRID: Tuple[int, ...] = (1, 2, 3, 4, 5)
# 價回撤門檻（相對 D 收；負＝跌）
DD_THR_GRID: Tuple[float, ...] = (-0.03, -0.05, -0.08)


@dataclass(frozen=True)
class ExtremeTrack:
    """四大賣 lit 規格。"""

    track: str  # lots|share|streak|cum10
    thr: float

    def key(self) -> str:
        if self.track == "share":
            return f"share_th{self.thr:g}"
        if self.track == "streak":
            return f"streak_N{int(self.thr)}"
        if self.track == "cum10":
            return f"cum10_th{int(self.thr)}"
        return f"lots_th{int(self.thr)}"

    def as_dict(self) -> Dict[str, Any]:
        return asdict(self)


def iter_extreme_tracks() -> List[ExtremeTrack]:
    out: List[ExtremeTrack] = []
    for thr in GRID_LOTS_THR:
        out.append(ExtremeTrack("lots", float(thr)))
    for thr in SHARE_THR_GRID:
        out.append(ExtremeTrack("share", float(thr)))
    for n in STREAK_GRID:
        out.append(ExtremeTrack("streak", float(n)))
    for thr in GRID_CUM10_THR:
        out.append(ExtremeTrack("cum10", float(thr)))
    return out


def lit_extreme_day(
    track: ExtremeTrack,
    *,
    foreign_net: Any,
    volume: Any,
    foreign_nets_hist: Sequence[Any],
    foreign_nets_10: Sequence[Any],
) -> bool:
    t = track.track
    if t == "lots":
        return lit_dump_lots(foreign_net, track.thr)
    if t == "share":
        return lit_dump_share(foreign_net, volume, track.thr)
    if t == "streak":
        return lit_dump_streak(foreign_nets_hist, int(track.thr))
    if t == "cum10":
        return lit_dump_cum10(foreign_nets_10, track.thr)
    return False


def price_drawdown_from_anchor(
    anchor_close: Any, future_closes: Sequence[Any]
) -> Optional[float]:
    """相對錨收的最大回撤（負值＝跌）；無有效價→None。"""
    a = _f(anchor_close)
    if a is None or a <= 0:
        return None
    worst = 0.0
    any_ok = False
    for c in future_closes:
        v = _f(c)
        if v is None or v <= 0:
            continue
        any_ok = True
        dd = (v - a) / a
        if dd < worst:
            worst = dd
    return worst if any_ok else None


def hit_price_dd(
    anchor_close: Any,
    future_closes: Sequence[Any],
    *,
    k: int,
    thr_dd: float,
) -> Dict[str, Any]:
    """D+1～D+k 內最大回撤 ≤ thr_dd（thr 為負）＝命中續危。"""
    xs = list(future_closes)[: int(k)]
    if len(xs) < int(k):
        # 未滿窗：若已觸及仍可提前判 hit；否則 pending
        dd = price_drawdown_from_anchor(anchor_close, xs)
        if dd is not None and dd <= float(thr_dd):
            return {"hit": True, "dd": dd, "verdict": "hit", "tag": TAG_PRICE_DD}
        return {"hit": None, "dd": dd, "verdict": "pending", "tag": TAG_PRICE_DD}
    dd = price_drawdown_from_anchor(anchor_close, xs)
    if dd is None:
        return {"hit": None, "dd": None, "verdict": "pending", "tag": TAG_PRICE_DD}
    if dd <= float(thr_dd):
        return {"hit": True, "dd": dd, "verdict": "hit", "tag": TAG_PRICE_DD}
    return {"hit": False, "dd": dd, "verdict": "miss", "tag": TAG_PRICE_DD}


def hit_continue_extreme(
    future_lits: Sequence[Optional[bool]],
    *,
    k: int,
) -> Dict[str, Any]:
    """D+1～D+k 任一交易日再 lit 極端＝命中。"""
    xs = list(future_lits)[: int(k)]
    for i, lit in enumerate(xs):
        if lit is True:
            return {
                "hit": True,
                "hit_day_offset": i + 1,
                "verdict": "hit",
                "tag": TAG_CONT_EXTREME,
            }
        if lit is None:
            # 缺柱：整窗未滿或未知 → pending（若後面也沒 True）
            pass
    if len(xs) < int(k) or any(x is None for x in xs):
        if any(x is True for x in xs):
            return {"hit": True, "verdict": "hit", "tag": TAG_CONT_EXTREME}
        return {"hit": None, "verdict": "pending", "tag": TAG_CONT_EXTREME}
    return {"hit": False, "verdict": "miss", "tag": TAG_CONT_EXTREME}


def sync_same_day_crash(
    *,
    open_: Any,
    close: Any,
    thr_dd: float = -0.05,
) -> bool:
    """D 日開→收已大崩（Sync 自嗨標）；分表用，不進主命中混算。"""
    o = _f(open_)
    c = _f(close)
    if o is None or c is None or o <= 0:
        return False
    return (c - o) / o <= float(thr_dd)


__all__ = [
    "KIND",
    "TAG_PRICE_DD",
    "TAG_CONT_EXTREME",
    "SHARE_THR_GRID",
    "STREAK_GRID",
    "K_AHEAD_GRID",
    "DD_THR_GRID",
    "UNIVERSE_QIANJIN",
    "UNIVERSE_TOP500_VOL",
    "UNIVERSE_LIQUID",
    "QIANJIN_PX",
    "LIQUID_MIN_VOL_LOTS",
    "LIQUID_MIN_TURNOVER_K",
    "ExtremeTrack",
    "iter_extreme_tracks",
    "lit_extreme_day",
    "price_drawdown_from_anchor",
    "hit_price_dd",
    "hit_continue_extreme",
    "sync_same_day_crash",
    "units_banner",
    "sell_lots",
    "sell_share",
    "cum_sell_lots",
]
