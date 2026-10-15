# -*- coding: utf-8 -*-
"""小賣→大賣升級（P1b）｜只觀察，不是買訊。

單位鎖：``daily_quotes.volume``／``foreign_net``＝**張**（1 張＝1000 股）；
``sell_share``＝(−foreign_net張)/volume張。不准張股混用。

升級型 A：近 N 日連賣＋sell_share 爬升、尚未達極端分位 θ → escalate_pre；
其後 K 日內達 θ＝命中。Lead＝極端日前亮；Sync＝極端日當天才亮。
勝率與 FearComposite 分開。不准改 leave_zero。
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Dict, List, Optional, Sequence, Tuple

from fear_composite import (
    FOREIGN_NET_UNIT,
    LOTS_PER_SHARE,
    SELL_SHARE_UNIT,
    VOLUME_UNIT,
    _f,
    _ymd,
    sell_share,
    unit_consistency_report,
)

KIND = "foreign_sell_escalate"
TAG_PRE_A = "escalate_pre_A"
TAG_PRE_B = "escalate_pre_B"
TAG_MKT_C = "escalate_mkt_C"

# 起點「大賣」分軌標籤（與升級主訊號分開記勝率）
TAG_DUMP_LOTS = "dump_lots"  # 單日賣超張數
TAG_DUMP_SHARE = "dump_share"  # 超比％
TAG_DUMP_STREAK = "dump_streak"  # 連續 N 日賣超
TAG_DUMP_CUM10 = "dump_cum10"  # 10 日累賣超張數

# 母體（討論起點三組並行）
UNIVERSE_QIANJIN = "qianjin"  # 收≥1000
UNIVERSE_TOP500_VOL = "top500_vol"  # 近半年日均量(張) Top500
UNIVERSE_LIQUID = "liquid_tw"  # 上市櫃流動對照

DEFAULT_THETA_PCTL = 90.0
DEFAULT_N = 3
DEFAULT_K = 3
GRID_N: Tuple[int, ...] = (3, 5)
GRID_K: Tuple[int, ...] = (1, 2, 3)
GRID_THETA: Tuple[float, ...] = (90.0,)
# 單日賣超張數／10日累門檻網格（張；離線掃描鎖）
GRID_LOTS_THR: Tuple[int, ...] = (1000, 3000, 5000, 10000)
GRID_CUM10_THR: Tuple[int, ...] = (5000, 10000, 20000, 50000)
# 分位爬坡 B：從中位帶進入極端
B_BAND_LO = 50.0
B_BAND_HI = 70.0
B_WINDOW = 5
QIANJIN_PX = 1000.0
# 流動對照（對齊海選第一層流動：日量張＋日額千元）
LIQUID_MIN_VOL_LOTS = 1000
LIQUID_MIN_TURNOVER_K = 30_000.0  # 3000 萬＝30000 千元


@dataclass(frozen=True)
class EscalateParams:
    n_days: int = DEFAULT_N
    k_ahead: int = DEFAULT_K
    theta_pctl: float = DEFAULT_THETA_PCTL
    min_upgrades: int = 2  # sell_share 至少上修次數

    def key(self) -> str:
        return f"n{self.n_days}_k{self.k_ahead}_th{self.theta_pctl:g}_u{self.min_upgrades}"

    def as_dict(self) -> Dict[str, Any]:
        return asdict(self)


def iter_escalate_param_grid() -> List[EscalateParams]:
    out: List[EscalateParams] = []
    for n in GRID_N:
        for k in GRID_K:
            for th in GRID_THETA:
                out.append(EscalateParams(n_days=int(n), k_ahead=int(k), theta_pctl=float(th)))
    return out


def units_banner() -> Dict[str, Any]:
    return {
        "lots_per_share": LOTS_PER_SHARE,
        "volume_unit": VOLUME_UNIT,
        "foreign_net_unit": FOREIGN_NET_UNIT,
        "sell_share_unit": SELL_SHARE_UNIT,
    }


def cross_sectional_percentile(values: Sequence[float], x: float) -> float:
    """同日同宇宙分位（0–100）。"""
    xs = [float(v) for v in values if v is not None]
    if not xs:
        return 0.0
    less = sum(1 for v in xs if v < x)
    eq = sum(1 for v in xs if v == x)
    return (less + 0.5 * eq) / len(xs) * 100.0


def count_upgrades(shares: Sequence[float]) -> int:
    """相鄰日 sell_share 上修次數。"""
    n = 0
    for i in range(1, len(shares)):
        if shares[i] > shares[i - 1]:
            n += 1
    return n


def is_nondecreasing(shares: Sequence[float]) -> bool:
    for i in range(1, len(shares)):
        if shares[i] + 1e-15 < shares[i - 1]:
            return False
    return True


def evaluate_escalate_A(
    *,
    foreign_nets: Sequence[Optional[float]],
    volumes: Sequence[Optional[float]],
    pctls: Sequence[Optional[float]],
    params: Optional[EscalateParams] = None,
) -> Dict[str, Any]:
    """序列末端＝今日。foreign_nets／volumes 長度≥N；單位皆張。

    回傳 lit／reason；不預測未來（命中由後驗窗算）。
    """
    p = params or EscalateParams()
    n = int(p.n_days)
    if len(foreign_nets) < n or len(volumes) < n or len(pctls) < n:
        return {"lit": False, "reason": "序列不足", "pctl": None, "sell_share": None}
    fns = list(foreign_nets[-n:])
    vols = list(volumes[-n:])
    ps = list(pctls[-n:])
    shares: List[float] = []
    for fn, vol in zip(fns, vols):
        if fn is None or vol is None or vol <= 0:
            return {"lit": False, "reason": "缺量或法人", "pctl": None, "sell_share": None}
        if fn >= 0:
            return {"lit": False, "reason": "非連賣", "pctl": None, "sell_share": None}
        ss = sell_share(fn, vol)
        if ss is None:
            return {"lit": False, "reason": "sell_share 無法算", "pctl": None, "sell_share": None}
        shares.append(float(ss))
    today_p = ps[-1]
    if today_p is None:
        return {"lit": False, "reason": "缺分位", "pctl": None, "sell_share": shares[-1]}
    if float(today_p) >= float(p.theta_pctl):
        return {
            "lit": False,
            "reason": "已達極端（非 pre）",
            "pctl": float(today_p),
            "sell_share": shares[-1],
            "already_extreme": True,
        }
    mono = is_nondecreasing(shares)
    ups = count_upgrades(shares)
    if not (mono or ups >= int(p.min_upgrades)):
        return {
            "lit": False,
            "reason": f"未爬升 mono={mono} ups={ups}",
            "pctl": float(today_p),
            "sell_share": shares[-1],
        }
    return {
        "lit": True,
        "reason": f"連賣{n}日爬升 ups={ups} mono={int(mono)}",
        "pctl": float(today_p),
        "sell_share": shares[-1],
        "tag": TAG_PRE_A,
    }


def evaluate_escalate_B(
    *,
    pctls: Sequence[Optional[float]],
    window: int = B_WINDOW,
    band_lo: float = B_BAND_LO,
    band_hi: float = B_BAND_HI,
    theta_pctl: float = DEFAULT_THETA_PCTL,
) -> Dict[str, Any]:
    """分位爬坡：近 window 內曾落在 [lo,hi]、今日仍 <θ、且今日分位 > 窗內最早。"""
    w = int(window)
    if len(pctls) < w:
        return {"lit": False, "reason": "序列不足", "pctl": None}
    seq = list(pctls[-w:])
    if any(x is None for x in seq):
        return {"lit": False, "reason": "缺分位", "pctl": None}
    nums = [float(x) for x in seq]
    today = nums[-1]
    if today >= float(theta_pctl):
        return {"lit": False, "reason": "已達極端", "pctl": today, "already_extreme": True}
    in_band = any(band_lo <= x <= band_hi for x in nums[:-1])
    climbed = today > nums[0] and today > min(nums[:-1])
    if in_band and climbed:
        return {
            "lit": True,
            "reason": f"分位自中帶爬升→{today:.1f}",
            "pctl": today,
            "tag": TAG_PRE_B,
        }
    return {"lit": False, "reason": "未爬坡", "pctl": today}


def classify_lead_sync_vs_extreme(
    lit: bool, *, extreme_today: bool
) -> str:
    """Lead＝pre 且今日未極端；Sync＝今日已極端才標（A 規則通常不亮）。"""
    if not lit:
        return ""
    if extreme_today:
        return "sync"
    return "lead"


def hit_within_k(
    future_pctls: Sequence[Optional[float]],
    *,
    k: int,
    theta_pctl: float,
) -> Dict[str, Any]:
    """後驗：未來 K 個交易日內是否出現 P≥θ。"""
    kk = int(k)
    for i, p in enumerate(list(future_pctls)[:kk]):
        if p is not None and float(p) >= float(theta_pctl):
            return {"hit": True, "hit_day_offset": i + 1, "hit_pctl": float(p)}
    pending = len([x for x in list(future_pctls)[:kk] if x is None]) > 0 or len(future_pctls) < kk
    if pending and len(future_pctls) < kk:
        return {"hit": None, "verdict": "pending"}
    return {"hit": False, "hit_day_offset": None, "hit_pctl": None}


def sell_lots(foreign_net: Any) -> Optional[float]:
    """單日外資賣超張數＝max(0, −foreign_net)；單位張。"""
    fn = _f(foreign_net)
    if fn is None:
        return None
    return max(0.0, -fn)


def cum_sell_lots(foreign_nets: Sequence[Any]) -> Optional[float]:
    """多日累計賣超張數（只加賣超日）；單位張。"""
    total = 0.0
    any_ok = False
    for raw in foreign_nets:
        fn = _f(raw)
        if fn is None:
            continue
        any_ok = True
        if fn < 0:
            total += -fn
    return total if any_ok else None


def streak_sell_days(foreign_nets: Sequence[Any]) -> int:
    """自序列末端往回連續 foreign_net<0 的日數。"""
    n = 0
    for fn in reversed(list(foreign_nets)):
        v = _f(fn)
        if v is None or v >= 0:
            break
        n += 1
    return n


def lit_dump_lots(foreign_net: Any, thr_lots: float) -> bool:
    s = sell_lots(foreign_net)
    return s is not None and s >= float(thr_lots)


def lit_dump_share(foreign_net: Any, volume: Any, thr_share: float) -> bool:
    ss = sell_share(foreign_net, volume)
    return ss is not None and ss >= float(thr_share)


def lit_dump_streak(foreign_nets: Sequence[Any], n: int) -> bool:
    return streak_sell_days(foreign_nets) >= int(n)


def lit_dump_cum10(foreign_nets_10: Sequence[Any], thr_lots: float) -> bool:
    c = cum_sell_lots(foreign_nets_10)
    return c is not None and c >= float(thr_lots)


__all__ = [
    "KIND",
    "TAG_PRE_A",
    "TAG_PRE_B",
    "TAG_MKT_C",
    "TAG_DUMP_LOTS",
    "TAG_DUMP_SHARE",
    "TAG_DUMP_STREAK",
    "TAG_DUMP_CUM10",
    "UNIVERSE_QIANJIN",
    "UNIVERSE_TOP500_VOL",
    "UNIVERSE_LIQUID",
    "QIANJIN_PX",
    "LIQUID_MIN_VOL_LOTS",
    "LIQUID_MIN_TURNOVER_K",
    "GRID_LOTS_THR",
    "GRID_CUM10_THR",
    "EscalateParams",
    "iter_escalate_param_grid",
    "units_banner",
    "cross_sectional_percentile",
    "evaluate_escalate_A",
    "evaluate_escalate_B",
    "classify_lead_sync_vs_extreme",
    "hit_within_k",
    "sell_share",
    "sell_lots",
    "cum_sell_lots",
    "streak_sell_days",
    "lit_dump_lots",
    "lit_dump_share",
    "lit_dump_streak",
    "lit_dump_cum10",
    "unit_consistency_report",
]
