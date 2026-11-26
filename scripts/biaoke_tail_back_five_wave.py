#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""由尾回推五波（觀察用，非買訊；不准當話筒浪號認證）。

使用者教法（2026-11-26）：
1. 先抓出大量（一年級）股票
2. 浪由尾畫回去
3. 今天若上漲 → 連回前幾天低點＝「新的開始」
4. 由該低點往回畫，看能不能畫出五波（前一段下跌）

硬邊界：phone_sync blocked；不改 leave_zero／ma60_lower。
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple


@dataclass
class Pivot:
    i: int
    price: float
    kind: str  # H / L
    date: str = ""


@dataclass
class TailBackFive:
    ok_new_start: bool
    ok_five: bool
    today_up: bool
    new_start: Optional[Pivot] = None
    prior_high: Optional[Pivot] = None
    five_points: List[Pivot] = field(default_factory=list)  # 0..5：高起→五波低終
    fail_reason_zh: str = ""
    note_zh: str = ""

    def as_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        return d


def _is_up_day(o: float, c: float, prev_c: float | None = None) -> bool:
    if c > o + 1e-12:
        return True
    if prev_c is not None and c > prev_c + 1e-12:
        return True
    return False


def find_new_start_low(
    bars: Sequence[Dict[str, float]],
    *,
    lookback_days: int = 8,
) -> Optional[Pivot]:
    """今日上漲時：前幾日（含今日）最低點＝新開始。"""
    if len(bars) < 3:
        return None
    last = bars[-1]
    prev_c = float(bars[-2]["close"]) if len(bars) >= 2 else None
    if not _is_up_day(float(last["open"]), float(last["close"]), prev_c):
        return None
    win = list(bars[-max(2, lookback_days) :])
    # 取窗內最低 low；若多根同低取最早那根（起漲錨）
    best_i_local = 0
    best_low = float(win[0]["low"])
    for j, b in enumerate(win):
        lo = float(b["low"])
        if lo < best_low - 1e-12:
            best_low = lo
            best_i_local = j
    abs_i = len(bars) - len(win) + best_i_local
    return Pivot(
        i=abs_i,
        price=best_low,
        kind="L",
        date=str(bars[abs_i].get("date") or ""),
    )


def _fractal_pivots(
    highs: Sequence[float],
    lows: Sequence[float],
    *,
    left: int = 2,
) -> List[Pivot]:
    n = len(highs)
    raw: List[Pivot] = []
    if n < left * 2 + 1:
        return raw
    for i in range(left, n - left):
        if highs[i] >= max(highs[i - left : i + left + 1]) - 1e-12:
            raw.append(Pivot(i=i, price=float(highs[i]), kind="H"))
        if lows[i] <= min(lows[i - left : i + left + 1]) + 1e-12:
            raw.append(Pivot(i=i, price=float(lows[i]), kind="L"))
    raw.sort(key=lambda p: p.i)
    out: List[Pivot] = []
    for p in raw:
        if not out:
            out.append(p)
            continue
        if p.kind == out[-1].kind:
            if p.kind == "H" and p.price >= out[-1].price:
                out[-1] = p
            elif p.kind == "L" and p.price <= out[-1].price:
                out[-1] = p
        else:
            out.append(p)
    return out


def _filter_degree(
    piv: Sequence[Pivot],
    *,
    min_bars: int = 2,
    min_pct: float = 0.015,
) -> List[Pivot]:
    out: List[Pivot] = []
    for p in piv:
        if not out:
            out.append(p)
            continue
        if p.kind == out[-1].kind:
            if p.kind == "H" and p.price >= out[-1].price:
                out[-1] = p
            elif p.kind == "L" and p.price <= out[-1].price:
                out[-1] = p
            continue
        bars = p.i - out[-1].i
        amp = abs(p.price - out[-1].price) / max(out[-1].price, 1e-9)
        if bars < min_bars or amp < min_pct:
            continue
        out.append(p)
    return out


def try_five_wave_back_from_low(
    bars: Sequence[Dict[str, float]],
    new_start: Pivot,
    *,
    search_back: int = 120,
) -> TailBackFive:
    """由新開始低點往回，試畫前一段下跌的五波（0高→1低→2高→3低→4高→5低）。"""
    today_up = True
    if new_start is None:
        return TailBackFive(
            ok_new_start=False,
            ok_five=False,
            today_up=False,
            fail_reason_zh="無新開始低點",
        )

    n = len(bars)
    i5 = int(new_start.i)
    if i5 <= 10 or i5 >= n:
        return TailBackFive(
            ok_new_start=True,
            ok_five=False,
            today_up=today_up,
            new_start=new_start,
            fail_reason_zh="新開始位置太靠前／無效",
            note_zh="低點已定，但往回空間不足",
        )

    start_i = max(0, i5 - int(search_back))
    seg_highs = [float(b["high"]) for b in bars[start_i : i5 + 1]]
    seg_lows = [float(b["low"]) for b in bars[start_i : i5 + 1]]
    # 段內最高＝波段起點候選
    local_peak_j = max(range(len(seg_highs)), key=lambda j: seg_highs[j])
    peak_abs = start_i + local_peak_j
    prior_high = Pivot(
        i=peak_abs,
        price=float(bars[peak_abs]["high"]),
        kind="H",
        date=str(bars[peak_abs].get("date") or ""),
    )

    if peak_abs >= i5 - 4:
        return TailBackFive(
            ok_new_start=True,
            ok_five=False,
            today_up=today_up,
            new_start=new_start,
            prior_high=prior_high,
            fail_reason_zh="高點太靠近低點，不像完整下跌段",
        )

    # 只在「波段高 → 新開始低」這一段上找轉折
    sub_h = [float(b["high"]) for b in bars[peak_abs : i5 + 1]]
    sub_l = [float(b["low"]) for b in bars[peak_abs : i5 + 1]]
    raw = _fractal_pivots(sub_h, sub_l, left=2)
    # 映射回絕對 index
    for p in raw:
        p.i = peak_abs + p.i
        p.date = str(bars[p.i].get("date") or "")

    # 強制端點：起點高、終點低
    piv = _filter_degree(raw, min_bars=2, min_pct=0.012)
    # 清掉端點外、並確保起高終低
    piv = [p for p in piv if peak_abs <= p.i <= i5]
    if not piv or piv[0].kind != "H" or piv[0].i != peak_abs:
        piv = [prior_high] + [p for p in piv if p.i > peak_abs]
    if piv[-1].kind != "L" or piv[-1].i != i5:
        piv = [p for p in piv if p.i < i5] + [
            Pivot(i=i5, price=float(new_start.price), kind="L", date=new_start.date)
        ]
    # 再交替清理
    alt: List[Pivot] = []
    for p in piv:
        if not alt:
            alt.append(p)
            continue
        if p.kind == alt[-1].kind:
            if p.kind == "H" and p.price >= alt[-1].price:
                alt[-1] = p
            elif p.kind == "L" and p.price <= alt[-1].price:
                alt[-1] = p
        else:
            alt.append(p)
    piv = alt

    # 目標結構：H L H L H L ＝ 6 個點（浪0～浪5）
    # 若點數 > 6，抽稀到最顯著的 5 浪（保留端點，中間選幅度大的）
    five = _thin_to_five_down(piv)
    ok = len(five) == 6 and five[0].kind == "H" and five[-1].kind == "L"
    ok = ok and all(five[k].kind == ("H" if k % 2 == 0 else "L") for k in range(6))

    reason = ""
    note = ""
    if ok:
        # 軟規則：第3浪（點2→點3）跌幅不應是 1/3/5 最短（常見檢核）
        legs = [
            abs(five[1].price - five[0].price),
            abs(five[3].price - five[2].price),
            abs(five[5].price - five[4].price),
        ]
        if legs[1] + 1e-9 < min(legs[0], legs[2]):
            ok = False
            reason = "第3段是1/3/5中最短（五波檢核未過）"
        else:
            note = (
                f"由尾回推五波可定義：高{five[0].price:.0f}→低{five[5].price:.0f}；"
                f"今日連回新開始低{new_start.price:.0f}"
            )
    else:
        reason = reason or f"轉折點數={len(piv)}，抽稀後={len(five)}，無法穩定定義五波"

    return TailBackFive(
        ok_new_start=True,
        ok_five=bool(ok),
        today_up=today_up,
        new_start=new_start,
        prior_high=prior_high,
        five_points=five if five else piv,
        fail_reason_zh=reason,
        note_zh=note or ("五波未過關，僅標新開始與波段高" if not ok else note),
    )


def _thin_to_five_down(piv: Sequence[Pivot]) -> List[Pivot]:
    """把 H-L 交替序列抽成 6 點（五波下跌）。"""
    if len(piv) < 6:
        return list(piv)
    if len(piv) == 6:
        return list(piv)
    # 保留首尾；中間要 4 點（L H L H），從候選裡依段落幅度挑
    head, tail = piv[0], piv[-1]
    mid = list(piv[1:-1])
    # 需要剛好 HLHL（若 mid 過多，反覆合併最弱擺動）
    while len(mid) > 4:
        # 找相鄰三點中「中間擺動」幅度最小者合併
        best_k = 1
        best_amp = 1e99
        for k in range(1, len(mid) - 1):
            amp = abs(mid[k].price - mid[k - 1].price) + abs(mid[k + 1].price - mid[k].price)
            if amp < best_amp:
                best_amp = amp
                best_k = k
        # 刪掉 best_k，並修交替
        del mid[best_k]
        fixed: List[Pivot] = []
        for p in mid:
            if not fixed:
                fixed.append(p)
                continue
            if p.kind == fixed[-1].kind:
                if p.kind == "H" and p.price >= fixed[-1].price:
                    fixed[-1] = p
                elif p.kind == "L" and p.price <= fixed[-1].price:
                    fixed[-1] = p
            else:
                fixed.append(p)
        mid = fixed
    out = [head] + mid + [tail]
    # 再保證交替
    alt: List[Pivot] = []
    for p in out:
        if not alt:
            alt.append(p)
            continue
        if p.kind == alt[-1].kind:
            if p.kind == "H" and p.price >= alt[-1].price:
                alt[-1] = p
            elif p.kind == "L" and p.price <= alt[-1].price:
                alt[-1] = p
        else:
            alt.append(p)
    return alt


def analyze_bars(bars: Sequence[Dict[str, float]]) -> TailBackFive:
    """完整：今日漲？→新開始→往回五波。"""
    if len(bars) < 30:
        return TailBackFive(
            ok_new_start=False,
            ok_five=False,
            today_up=False,
            fail_reason_zh="K棒不足",
        )
    last = bars[-1]
    prev_c = float(bars[-2]["close"])
    today_up = _is_up_day(float(last["open"]), float(last["close"]), prev_c)
    if not today_up:
        return TailBackFive(
            ok_new_start=False,
            ok_five=False,
            today_up=False,
            fail_reason_zh="今日非上漲，先不定義新開始",
            note_zh="規則：今日上漲才連回前低當新開始",
        )
    ns = find_new_start_low(bars, lookback_days=8)
    if ns is None:
        return TailBackFive(
            ok_new_start=False,
            ok_five=False,
            today_up=True,
            fail_reason_zh="找不到前幾日低點",
        )
    return try_five_wave_back_from_low(bars, ns)
