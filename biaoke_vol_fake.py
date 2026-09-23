# -*- coding: utf-8 -*-
"""量價結構：用官方開高低收＋量重述他已講過的，不發明指標、不進海選。

2026-09-23 16:50 樓下自回打成「量假結構」，正文是量價結構。
懂量價結構，久了就自然會將穩定性差的技術指標拿掉，
而且 K 棒更清楚，慢慢就會發現隱藏的主力意圖的細節。自行去挖掘體會。
同一串精神他 9/15 夜（裸K、三種形態不准混）、9/20（不看 KD／均線／分點）、
2024-07-08（洗盤 vs 出貨）、2024-04-15 協易機 4533 爆大量要整理、
2025-01-13 鴻海 2317 爆大量還要再跌、2026-08-31 金像電 2368 前波高長上影轉弱K
已經講過。個股不數 5／9。盤中未收不當官方收。不是買訊。
3167 是大量不是協易機。
"""
from __future__ import annotations

from typing import Any, Dict, Optional, Sequence, Tuple

# rows：舊→新；(date, high, low, close, volume)
Bar = Tuple[str, float, float, float, float]


def _volr(rows: Sequence[Bar]) -> float:
    if len(rows) < 6:
        return 0.0
    last = rows[-1][4]
    w20 = rows[-21:-1] if len(rows) >= 21 else rows[:-1]
    if not w20:
        return 0.0
    avg = sum(x[4] for x in w20) / float(len(w20))
    return (last / avg) if avg > 0 else 0.0


def _loc(high: float, low: float, close: float) -> Tuple[float, float]:
    span = float(high) - float(low)
    if span <= 1e-9:
        return 0.5, 0.0
    close_from_low = (float(close) - float(low)) / span
    up_shadow = (float(high) - float(close)) / span
    return close_from_low, up_shadow


def classify_volume_fake(rows: Sequence[Bar]) -> Dict[str, Any]:
    """最後一根官方柱的量價結構。

    dump：爆量＋長上影（金像電前波高轉弱K／出貨意圖）
    pause：爆量卻收在當日下半（協易機／鴻海：量大要整理或還要再跌，不是當日攻完）
    wash：破近期低但 1～3 日內已站回（假跌破／洗盤，證據不足升轉折）
    hold：爆量收在上半且還在近窗低之上（收撐候選，仍要價穩量縮，不是買訊）
    none：量沒起來，維持原本量縮／死水讀法
    """
    empty = {"kind": "none", "volr": 0.0, "close_from_low": 0.5, "up_shadow": 0.0}
    if len(rows) < 8:
        return dict(empty)
    last = rows[-1]
    volr = _volr(rows)
    close_from_low, up_shadow = _loc(last[1], last[2], last[3])
    stood_back = False
    for j in range(-3, 0):
        before = rows[:j]
        if len(before) < 5:
            continue
        bar = rows[j]
        plat = min(x[2] for x in before[-10:])
        if bar[2] < plat * 0.998 and last[3] >= plat:
            stood_back = True
            break
    out = {
        "kind": "none",
        "volr": volr,
        "close_from_low": close_from_low,
        "up_shadow": up_shadow,
    }
    if stood_back:
        out["kind"] = "wash"
        return out
    if volr < 1.5:
        return out
    # 沒開盤價時用收的位置拆。貼當日低＝協易機整理／鴻海還要再跌（pause），
    # 即使上影看起來很長也不當轉弱K。沒貼低的長上影＝金像電前波高 dump。
    if close_from_low <= 0.18:
        out["kind"] = "pause"
        return out
    if up_shadow >= 0.55:
        out["kind"] = "dump"
        return out
    if close_from_low <= 0.35:
        out["kind"] = "pause"
        return out
    if close_from_low >= 0.60:
        out["kind"] = "hold"
        return out
    return out


def is_fake_stir(st: Optional[Dict[str, Any]]) -> bool:
    """蠢蠢欲動的『量起來』若是轉弱／還要再跌的量價，不准當發動。"""
    kind = str((st or {}).get("vol_fake") or "")
    return kind in ("dump", "pause")


def fake_note(kind: str) -> str:
    return {
        "dump": "量價結構：爆量長上影，主力意圖偏出貨／轉弱K，不是發動。",
        "pause": "量價結構：爆量收在當日下半，要整理或還要再跌，不是當日攻完。",
        "wash": "破線後站回＝洗盤／假跌破候選，過幾天才能知道，不准升轉折K。",
        "hold": "爆量收在上半＝收撐候選，仍要價穩量縮，不是買訊。",
        "none": "",
    }.get(str(kind or ""), "")
