# -*- coding: utf-8 -*-
"""我的波浪結構純規則（擴延 161.8%／前端傾斜 1–4 重疊）。

來源消化：D.C 直流變頻教學圖 → 變成 AI 自己的判斷工具（source=mine）。
單向：可參考同學／老師；輸出不准冒充飆大原文，也不准寫回黃金買點。

- detect_extension_1618：五浪群最長浪 ≥ 161.8% × 次長 → 推進擴延候選。
- check_w1_w4_overlap／leading_diagonal_flags：①④ 價區重疊（前端傾斜特徵之一）。

不是買訊；盤中未收柱呼叫端自己擋。
"""
from __future__ import annotations

from typing import Any, Dict, Mapping, Optional, Sequence, Tuple, Union

EXT_RATIO = 1.618

Number = Union[int, float]


def _f(x: Any) -> Optional[float]:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    if v != v:  # NaN
        return None
    return v


def wave_price_length(start: Number, end: Number) -> Optional[float]:
    """價距絕對值；缺數回 None。"""
    a, b = _f(start), _f(end)
    if a is None or b is None:
        return None
    return abs(b - a)


def detect_extension_1618(
    lengths: Mapping[str, Number],
    *,
    ratio: float = EXT_RATIO,
) -> Dict[str, Any]:
    """擴延波檢測：L_max ≥ ratio × L_second_max。

    ``lengths`` 典型鍵 ``\"1\"``／``\"3\"``／``\"5\"``（也可只傳有的浪）。
    回傳一律可 JSON 化；``pass``＝過核心閘。
    """
    cleaned: Dict[str, float] = {}
    for k, v in (lengths or {}).items():
        fv = _f(v)
        if fv is None or fv < 0:
            continue
        cleaned[str(k)] = float(fv)

    ordered = sorted(cleaned.items(), key=lambda kv: kv[1], reverse=True)
    if len(ordered) < 2:
        return {
            "pass": False,
            "ratio": None,
            "threshold": float(ratio),
            "longest": ordered[0][0] if ordered else None,
            "second": None,
            "lengths": cleaned,
            "variant": "insufficient_legs",
            "basis": "need≥2 motive legs",
        }

    (long_k, long_v), (sec_k, sec_v) = ordered[0], ordered[1]
    if sec_v <= 0:
        return {
            "pass": False,
            "ratio": None,
            "threshold": float(ratio),
            "longest": long_k,
            "second": sec_k,
            "lengths": cleaned,
            "variant": "zero_second",
            "basis": "second length≤0",
        }

    got = long_v / sec_v
    passed = got + 1e-12 >= float(ratio)
    variant: Optional[str] = None
    if not passed:
        # 例外標籤（digest §1）：僅提示，不自動升格為 pass
        l1 = cleaned.get("1")
        l3 = cleaned.get("3")
        l5 = cleaned.get("5")
        if long_k == "1" and l3 is not None and l1 is not None:
            variant = "rare_motive_variant_w1_longest"
        elif (
            l3 is not None
            and l1 is not None
            and l5 is not None
            and l3 >= l1
            and l3 >= l5
            and l3 < float(ratio) * l1
            and l5 < l3
        ):
            variant = "rare_ending_motive_variant"

    return {
        "pass": bool(passed),
        "ratio": float(got),
        "threshold": float(ratio),
        "longest": long_k,
        "second": sec_k,
        "lengths": cleaned,
        "variant": variant,
        "basis": f"L_max≥{ratio:g}×L_2nd",
    }


def price_ranges_overlap(
    a_lo: Number,
    a_hi: Number,
    b_lo: Number,
    b_hi: Number,
) -> Optional[bool]:
    """兩價區是否重疊（閉區間）。缺數→None。"""
    alo, ahi = _f(a_lo), _f(a_hi)
    blo, bhi = _f(b_lo), _f(b_hi)
    if None in (alo, ahi, blo, bhi):
        return None
    lo_a, hi_a = (alo, ahi) if alo <= ahi else (ahi, alo)
    lo_b, hi_b = (blo, bhi) if blo <= bhi else (bhi, blo)
    return not (hi_a < lo_b or hi_b < lo_a)


def check_w1_w4_overlap(
    w1_start: Number,
    w1_end: Number,
    w4_start: Number,
    w4_end: Number,
) -> Dict[str, Any]:
    """① 與 ④ 價區是否重疊（前端傾斜關鍵特徵；標準 impulse 禁止）。"""
    ov = price_ranges_overlap(w1_start, w1_end, w4_start, w4_end)
    return {
        "overlap": ov,
        "w1": {"start": _f(w1_start), "end": _f(w1_end)},
        "w4": {"start": _f(w4_start), "end": _f(w4_end)},
        "basis": "w1_w4_price_range_overlap",
    }


def leading_diagonal_flags(
    *,
    w1_w4_overlap: Optional[bool],
    position_ok: Optional[bool] = None,
    structure_53535: Optional[bool] = None,
) -> Dict[str, Any]:
    """前端傾斜旗標組裝（純規則；內部 5-3-5-3-5 由呼叫端先判再傳入）。

    implication=continuation（vs ending_diagonal=termination）。
    candidate＝重疊為真；confirmed 還要位置＋結構（缺則 False）。
    """
    overlap = None if w1_w4_overlap is None else bool(w1_w4_overlap)
    pos = None if position_ok is None else bool(position_ok)
    struct = None if structure_53535 is None else bool(structure_53535)
    candidate = overlap is True
    confirmed = candidate and pos is True and struct is True
    return {
        "candidate": candidate,
        "confirmed": confirmed,
        "w1_w4_overlap": overlap,
        "position_ok": pos,
        "structure_53535": struct,
        "implication": "continuation",
        "vs_ending": "ending_diagonal=termination",
        "basis": "leading_diagonal: overlap(+pos+5-3-5-3-5)",
    }


def lengths_from_pivots(
    pivots: Sequence[Tuple[Number, Number]],
) -> Dict[str, float]:
    """連續轉折點 (price, ...) 序列 → 浪價距。

    pivots 長度 n 產生 n-1 段；鍵 ``\"1\"``起編。只取絕對價距。
    """
    out: Dict[str, float] = {}
    pts = [_f(p[0]) if isinstance(p, (tuple, list)) else _f(p) for p in pivots]
    pts = [p for p in pts if p is not None]
    for i in range(len(pts) - 1):
        out[str(i + 1)] = abs(float(pts[i + 1]) - float(pts[i]))
    return out
