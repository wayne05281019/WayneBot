# -*- coding: utf-8 -*-
"""Calm／小買→大買（佈局環境）｜只觀察，不是買訊。

Calm：FearComposite₀ 邊數下降或熄滅。
Buy escalate：連買＋買超比爬升、尚未達買方極端 → 後 K 日達極端。
與 Fear／escalate／extreme 勝率分開。不准改 leave_zero。單位：張。
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Dict, List, Optional, Sequence, Tuple

from fear_composite import _f, sell_share
from foreign_sell_escalate import (
    DEFAULT_K,
    DEFAULT_N,
    DEFAULT_THETA_PCTL,
    GRID_K,
    GRID_N,
    GRID_THETA,
    UNIVERSE_LIQUID,
    UNIVERSE_QIANJIN,
    UNIVERSE_TOP500_VOL,
    count_upgrades,
    cross_sectional_percentile,
    units_banner,
)

KIND = "foreign_sell_calm_env"
TAG_CALM = "calm_fear_fade"
TAG_BUY_ESC = "buy_escalate_A"


@dataclass(frozen=True)
class BuyEscalateParams:
    n_days: int = DEFAULT_N
    k_ahead: int = DEFAULT_K
    theta_pctl: float = DEFAULT_THETA_PCTL
    min_upgrades: int = 2

    def key(self) -> str:
        return f"buy_n{self.n_days}_k{self.k_ahead}_th{self.theta_pctl:g}_u{self.min_upgrades}"

    def as_dict(self) -> Dict[str, Any]:
        return asdict(self)


def iter_buy_param_grid() -> List[BuyEscalateParams]:
    out: List[BuyEscalateParams] = []
    for n in GRID_N:
        for k in GRID_K:
            for th in GRID_THETA:
                out.append(BuyEscalateParams(n_days=int(n), k_ahead=int(k), theta_pctl=float(th)))
    return out


def current_buy_params() -> BuyEscalateParams:
    """現況靜默（測試；橘六角買升級仍不亮）。"""
    return BuyEscalateParams()


def next_silent_buy_params() -> BuyEscalateParams:
    """下一版靜默候選 buy_n5；只落檔，未過閘不上橘六角。"""
    from foreign_sell_escalate import NEXT_K, NEXT_N

    return BuyEscalateParams(
        n_days=int(NEXT_N),
        k_ahead=int(NEXT_K),
        theta_pctl=float(DEFAULT_THETA_PCTL),
        min_upgrades=2,
    )


def buy_lots(foreign_net: Any) -> Optional[float]:
    """單日外資買超張數＝max(0, foreign_net)；單位張。"""
    fn = _f(foreign_net)
    if fn is None:
        return None
    return max(0.0, fn)


def buy_share(foreign_net: Any, volume: Any) -> Optional[float]:
    """買超佔量＝buy_lots/volume（張/張）。"""
    b = buy_lots(foreign_net)
    vol = _f(volume)
    if b is None or vol is None or vol <= 0:
        return None
    return b / vol


def evaluate_buy_escalate_A(
    *,
    foreign_nets: Sequence[Any],
    volumes: Sequence[Any],
    pctls: Sequence[Optional[float]],
    params: BuyEscalateParams,
) -> Dict[str, Any]:
    """連買＋買超比爬升、尚未達買方極端分位。"""
    n = int(params.n_days)
    if len(foreign_nets) < n or len(volumes) < n or len(pctls) < n:
        return {"lit": False, "reason": "窗不足"}
    fns = list(foreign_nets)[-n:]
    vols = list(volumes)[-n:]
    ps = list(pctls)[-n:]
    # 全日買超
    for fn in fns:
        v = _f(fn)
        if v is None or v <= 0:
            return {"lit": False, "reason": "非連買"}
    shares = []
    for fn, vol in zip(fns, vols):
        ss = buy_share(fn, vol)
        if ss is None:
            return {"lit": False, "reason": "無買超比"}
        shares.append(ss)
    if count_upgrades(shares) < int(params.min_upgrades):
        return {"lit": False, "reason": "買超比未爬升", "buy_share": shares[-1]}
    today = ps[-1]
    if today is None:
        return {"lit": False, "reason": "無分位"}
    if float(today) >= float(params.theta_pctl):
        return {
            "lit": False,
            "reason": "已達買方極端",
            "pctl": float(today),
            "already_extreme": True,
        }
    return {
        "lit": True,
        "reason": "連買＋爬升未極端",
        "pctl": float(today),
        "buy_share": shares[-1],
        "tag": TAG_BUY_ESC,
    }


def evaluate_calm_fear_fade(
    *,
    fear_edges_today: Optional[int],
    fear_edges_yest: Optional[int],
    lit_today: Optional[bool],
    lit_yest: Optional[bool],
) -> Dict[str, Any]:
    """Fear 邊數下降或由亮轉熄＝Calm 環境。"""
    if lit_yest is True and lit_today is False:
        return {"lit": True, "reason": "恐懼由亮轉熄", "tag": TAG_CALM}
    if (
        fear_edges_today is not None
        and fear_edges_yest is not None
        and fear_edges_today < fear_edges_yest
        and fear_edges_yest >= 2
    ):
        return {
            "lit": True,
            "reason": f"恐懼邊 {fear_edges_yest}→{fear_edges_today}",
            "tag": TAG_CALM,
            "edges_today": fear_edges_today,
            "edges_yest": fear_edges_yest,
        }
    return {"lit": False, "reason": "未降溫"}


def hit_buy_within_k(
    future_pctls: Sequence[Optional[float]],
    *,
    k: int,
    theta_pctl: float,
) -> Dict[str, Any]:
    kk = int(k)
    for i, p in enumerate(list(future_pctls)[:kk]):
        if p is not None and float(p) >= float(theta_pctl):
            return {"hit": True, "hit_day_offset": i + 1, "hit_pctl": float(p)}
    if len(future_pctls) < kk or any(
        x is None for x in list(future_pctls)[:kk]
    ):
        return {"hit": None, "verdict": "pending"}
    return {"hit": False, "hit_day_offset": None, "hit_pctl": None}


__all__ = [
    "KIND",
    "TAG_CALM",
    "TAG_BUY_ESC",
    "UNIVERSE_QIANJIN",
    "UNIVERSE_TOP500_VOL",
    "UNIVERSE_LIQUID",
    "BuyEscalateParams",
    "iter_buy_param_grid",
    "buy_lots",
    "buy_share",
    "evaluate_buy_escalate_A",
    "evaluate_calm_fear_fade",
    "hit_buy_within_k",
    "units_banner",
    "cross_sectional_percentile",
]
