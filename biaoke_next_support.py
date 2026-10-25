# -*- coding: utf-8 -*-
"""破大量區撐 → 下一撐候選＋飆大原文絕對目標線（非買訊）。

產品缺口 D4／D5-T1：
- 收盤跌破近窗大量區撐（盤中刺穿不算）→ 必須標 NEXT support 來源＋價；
  無候選就明示「暫無下一官方結構撐」，不准假價。
- 他寫死的絕對價（聯亞 2000、奇鋐 3000／2700…）可畫水平
  「飆大原文目標 {價}・非買訊」；檔別隔離，不准串到他沒點的檔。
- 原因句可綁 NEXT；仍非買訊、不准寫回黃金買點／海選。
Asia/Taipei；官方已收 OHLC＋量。
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence, Tuple

NONE_LABEL = "暫無下一官方結構撐"
WRITTEN_LABEL_TMPL = "飆大原文目標 {price}・非買訊"
NEXT_LABEL_TMPL = "下一撐：{source} {price}"

# 來源顯示名（對齊概念清單 §F）
SOURCE_CHANNEL = "平行撐"
SOURCE_CHANNEL_DASH = "通道下緣"
SOURCE_NEXT_VOL = "次大量區撐"
SOURCE_WRITTEN = "原文目標"
SOURCE_PIVOT = "近窗樞紐低"

# 他寫死的絕對價：每檔隔離。費半／大立光無絕對價 → 不補。
# role=down：下檔目標（觸及＝已收低 ≤ 價）
WRITTEN_ABSOLUTE_TARGETS: Dict[str, Tuple[Dict[str, Any], ...]] = {
    "3081": (  # 聯亞：第二段下殺，目標先看頸線 2000
        {
            "price": 2000.0,
            "note": "第二段下殺頸線",
            "role": "down",
            "as_of": "20261025",
        },
    ),
    "3017": (  # 奇鋐：先測 3000 → 守不住再測 2700
        {
            "price": 3000.0,
            "note": "先測",
            "role": "down",
            "as_of": "20261025",
        },
        {
            "price": 2700.0,
            "note": "守不住頭部確認再測",
            "role": "down",
            "as_of": "20261025",
        },
    ),
}

# 候選優先：通道平行撐 → 次大量區 → 原文目標 → 近窗樞紐低
_SOURCE_RANK = {
    SOURCE_CHANNEL: 0,
    SOURCE_CHANNEL_DASH: 0,
    SOURCE_NEXT_VOL: 1,
    SOURCE_WRITTEN: 2,
    SOURCE_PIVOT: 3,
}


def _sid(raw: Any) -> str:
    return str(raw or "").strip().upper()


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


def _fmt_price(val: Any) -> str:
    """與話筒／圖標同源小數位；失敗退字串。"""
    try:
        from wayne_navigator import _fmt_price as _fp

        return str(_fp(val))
    except Exception:
        v = _num(val)
        if v <= 0:
            return ""
        if abs(v - round(v)) < 1e-9:
            return f"{int(round(v)):,}"
        return f"{v:,.2f}".rstrip("0").rstrip(".")


def written_targets_for(sid: str) -> List[Dict[str, Any]]:
    """該檔他寫死的絕對目標；沒寫＝空。檔別隔離。"""
    key = _sid(sid)
    if not key:
        return []
    rows = WRITTEN_ABSOLUTE_TARGETS.get(key) or ()
    out: List[Dict[str, Any]] = []
    for row in rows:
        px = _num(row.get("price"))
        if px <= 0:
            continue
        out.append(
            {
                "price": px,
                "note": str(row.get("note") or "").strip(),
                "role": str(row.get("role") or "down").strip() or "down",
                "as_of": _ymd(row.get("as_of")),
                "sid": key,
                "source": SOURCE_WRITTEN,
                "label": written_target_label(px),
            }
        )
    return out


def written_target_label(price: Any) -> str:
    px = _fmt_price(price)
    return WRITTEN_LABEL_TMPL.format(price=px or "—")


def next_support_label(source: str, price: Any) -> str:
    return NEXT_LABEL_TMPL.format(source=str(source or "").strip() or "結構", price=_fmt_price(price) or "—")


def close_broke_vol_support(
    *,
    close: Any,
    support: Any,
) -> bool:
    """收盤有效跌破大量區撐；盤中刺穿不算（呼叫端須餵已收／臉柱收）。"""
    cl = _num(close)
    lo = _num(support)
    return bool(cl > 0 and lo > 0 and cl < lo)


def find_secondary_vol_zone_support(
    bars: Sequence[Dict[str, Any]],
    *,
    broken_lo: float,
    exclude_date: str = "",
    lookback: int = 40,
) -> Optional[Dict[str, Any]]:
    """次一大量區撐：近窗（不含末日）量次大／量大且低 < 已破撐。

    與 find_volume_zone／volume_first_price 同尺：官方日 K 原柱；
    排除已破那根爆大量日；撐＝該日低。無合格候選回 None。
    """
    rows = list(bars or [])
    if len(rows) < 4 or broken_lo <= 0:
        return None
    window = rows[-int(lookback) :] if lookback > 0 else rows
    if len(window) < 3:
        return None
    cands = list(window[:-1]) if len(window) >= 2 else list(window)
    excl = _ymd(exclude_date)
    best: Optional[Dict[str, Any]] = None
    best_v = -1.0
    for r in cands:
        if excl and _ymd(r.get("date")) == excl:
            continue
        v = _num(r.get("volume"))
        if v <= 0:
            continue
        hi = _num(r.get("high"))
        lo = _num(r.get("low"))
        if hi <= 0 or lo <= 0 or hi < lo:
            continue
        # 必須低於已破撐，才算「下一」撐（不准回填同一區）
        if lo >= broken_lo - 1e-9:
            continue
        if v > best_v:
            best_v = v
            best = r
    if best is None:
        return None
    lo = _num(best.get("low"))
    return {
        "source": SOURCE_NEXT_VOL,
        "price": lo,
        "date": _ymd(best.get("date")),
        "high": _num(best.get("high")),
        "volume": _num(best.get("volume")),
        "label": next_support_label(SOURCE_NEXT_VOL, lo),
    }


def _channel_next_support(
    channel: Optional[Dict[str, Any]],
    *,
    broken_lo: float,
) -> Optional[Dict[str, Any]]:
    """平行／通道下緣：現價軌 base_now 低於已破大量區撐才認。"""
    ch = dict(channel or {})
    if not ch.get("kind"):
        return None
    base = _num(ch.get("base_now"))
    if base <= 0 or base >= broken_lo - 1e-9:
        return None
    kind = str(ch.get("kind") or "")
    # desc＝下降通道平行撐；asc＝上升軌本身（破後下緣仍可能是參考）
    src = SOURCE_CHANNEL if kind in ("desc", "asc") else SOURCE_CHANNEL_DASH
    pos = str(ch.get("pos") or "")
    if "破平行撐" in pos or kind == "desc":
        src = SOURCE_CHANNEL
    return {
        "source": src,
        "price": base,
        "kind": kind,
        "pos": pos,
        "label": next_support_label(src, base),
    }


def _pivot_next_support(
    bars: Sequence[Dict[str, Any]],
    *,
    broken_lo: float,
) -> Optional[Dict[str, Any]]:
    """近窗樞紐低：低於已破撐的最近／最高樞紐低。"""
    rows = list(bars or [])
    if len(rows) < 16 or broken_lo <= 0:
        return None
    try:
        from biaoke_chart import _pivots
    except Exception:
        return None
    highs = [_num(r.get("high")) for r in rows]
    lows = [_num(r.get("low")) for r in rows]
    _hi_p, lo_p = _pivots(highs, lows, left=3)
    best_i = -1
    best_lo = -1.0
    for i in lo_p:
        if i < 0 or i >= len(lows):
            continue
        lo = lows[i]
        if lo <= 0 or lo >= broken_lo - 1e-9:
            continue
        # 取最靠近已破撐（最高）的下一樞紐低
        if lo > best_lo:
            best_lo = lo
            best_i = int(i)
    if best_i < 0 or best_lo <= 0:
        return None
    return {
        "source": SOURCE_PIVOT,
        "price": best_lo,
        "date": _ymd(rows[best_i].get("date")),
        "i": best_i,
        "label": next_support_label(SOURCE_PIVOT, best_lo),
    }


def _written_next_candidates(
    sid: str,
    *,
    broken_lo: float,
) -> List[Dict[str, Any]]:
    """原文絕對目標中，低於已破撐者（由近到遠）。"""
    out: List[Dict[str, Any]] = []
    for row in written_targets_for(sid):
        px = _num(row.get("price"))
        if px <= 0 or px >= broken_lo - 1e-9:
            continue
        out.append(
            {
                "source": SOURCE_WRITTEN,
                "price": px,
                "note": row.get("note") or "",
                "role": row.get("role") or "down",
                "label": next_support_label(SOURCE_WRITTEN, px),
                "face_label": row.get("label") or written_target_label(px),
            }
        )
    out.sort(key=lambda r: -_num(r.get("price")))
    return out


def collect_next_support_candidates(
    bars: Sequence[Dict[str, Any]],
    *,
    sid: str = "",
    broken_lo: float,
    spike_date: str = "",
    channel: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    """破撐後全部 NEXT 候選（去重價）；來源標籤保留。不准發明價。"""
    if broken_lo <= 0:
        return []
    cands: List[Dict[str, Any]] = []
    ch = _channel_next_support(channel, broken_lo=broken_lo)
    if ch:
        cands.append(ch)
    sec = find_secondary_vol_zone_support(
        bars, broken_lo=broken_lo, exclude_date=spike_date
    )
    if sec:
        cands.append(sec)
    cands.extend(_written_next_candidates(sid, broken_lo=broken_lo))
    piv = _pivot_next_support(bars, broken_lo=broken_lo)
    if piv:
        cands.append(piv)
    # 價位去重：同價保留優先序較高來源
    by_px: Dict[float, Dict[str, Any]] = {}
    for row in cands:
        px = round(_num(row.get("price")), 4)
        if px <= 0:
            continue
        prev = by_px.get(px)
        if prev is None:
            by_px[px] = row
            continue
        rk_new = _SOURCE_RANK.get(str(row.get("source") or ""), 99)
        rk_old = _SOURCE_RANK.get(str(prev.get("source") or ""), 99)
        if rk_new < rk_old:
            by_px[px] = row
    ranked = sorted(
        by_px.values(),
        key=lambda r: (
            _SOURCE_RANK.get(str(r.get("source") or ""), 99),
            -_num(r.get("price")),
        ),
    )
    return ranked


def resolve_next_support(
    bars: Sequence[Dict[str, Any]],
    *,
    sid: str = "",
    close: Any = None,
    support: Any = None,
    spike_date: str = "",
    channel: Optional[Dict[str, Any]] = None,
    under_support: Optional[bool] = None,
) -> Dict[str, Any]:
    """破大量區撐時解析 NEXT；未破＝空（不畫下一撐）。

    回傳：
      broke, primary, candidates, none_label, reason_line, written_lines
    """
    rows = list(bars or [])
    broken_lo = _num(support)
    cl = _num(close)
    if cl <= 0 and rows:
        cl = _num(rows[-1].get("close"))
    broke = bool(under_support) if under_support is not None else close_broke_vol_support(
        close=cl, support=broken_lo
    )
    written = written_targets_for(sid)
    out: Dict[str, Any] = {
        "broke": bool(broke),
        "broken_lo": broken_lo if broke else 0.0,
        "close": cl,
        "sid": _sid(sid),
        "primary": None,
        "candidates": [],
        "none_label": "",
        "reason_line": "",
        "written": written,
        "written_lines": [w.get("label") for w in written if w.get("label")],
    }
    if not broke or broken_lo <= 0:
        return out
    cands = collect_next_support_candidates(
        rows,
        sid=sid,
        broken_lo=broken_lo,
        spike_date=spike_date,
        channel=channel,
    )
    out["candidates"] = cands
    if cands:
        out["primary"] = cands[0]
        out["none_label"] = ""
    else:
        out["primary"] = None
        out["none_label"] = NONE_LABEL
    out["reason_line"] = reason_next_support_line(
        broken_lo=broken_lo,
        primary=out.get("primary"),
        none_label=out.get("none_label") or "",
        distribution=False,
    )
    return out


def reason_next_support_line(
    *,
    broken_lo: float,
    primary: Optional[Dict[str, Any]] = None,
    none_label: str = "",
    distribution: bool = False,
) -> str:
    """破撐／出貨痕跡一句原因：點名 NEXT；非買訊。"""
    lo_s = _fmt_price(broken_lo) or "—"
    head = (
        f"過壓後掉回撐下＝出貨痕跡，收破大量區撐 {lo_s}"
        if distribution
        else f"收破大量區撐 {lo_s}"
    )
    if primary and _num(primary.get("price")) > 0:
        src = str(primary.get("source") or "").strip() or "結構"
        px = _fmt_price(primary.get("price")) or "—"
        return f"{head}，朝{src} {px}（非買訊）"
    label = str(none_label or NONE_LABEL).strip() or NONE_LABEL
    return f"{head}，{label}"


def attach_next_support(
    info: Dict[str, Any],
    *,
    sid: str = "",
    bars: Optional[Sequence[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """把 NEXT／原文目標掛進 analyze_structure 結果（原地＋回傳）。"""
    if not isinstance(info, dict):
        return {}
    rows = list(bars or [])
    if not rows:
        # 從 info 還原粗列（僅 OHLC；量可缺）
        highs = list(info.get("highs") or [])
        lows = list(info.get("lows") or [])
        closes = list(info.get("closes") or [])
        vols = list(info.get("vols") or [])
        n = min(len(highs), len(lows), len(closes))
        for i in range(n):
            rows.append(
                {
                    "high": highs[i],
                    "low": lows[i],
                    "close": closes[i],
                    "volume": vols[i] if i < len(vols) else 0,
                    "date": "",
                }
            )
    st = dict(info.get("struct") or {})
    spike_lo = _num(st.get("spike_low") or info.get("spike_lo"))
    last = info.get("last_bar") or (rows[-1] if rows else {})
    close = _num(last.get("close"))
    if close <= 0 and info.get("closes"):
        close = _num(list(info.get("closes") or [])[-1])
    channel = dict(info.get("channel") or {})
    pack = resolve_next_support(
        rows,
        sid=sid or str(st.get("sid") or ""),
        close=close,
        support=spike_lo,
        spike_date=str(st.get("spike_date") or ""),
        channel=channel,
        under_support=bool(info.get("under_support") or info.get("distribution")),
    )
    info["next_support"] = pack
    # 破撐／出貨 notes：補一句 NEXT（不重複堆）
    if pack.get("broke"):
        line = reason_next_support_line(
            broken_lo=_num(pack.get("broken_lo") or spike_lo),
            primary=pack.get("primary"),
            none_label=str(pack.get("none_label") or ""),
            distribution=bool(info.get("distribution")),
        )
        pack["reason_line"] = line
        notes = list(info.get("notes") or [])
        if line and line not in notes:
            notes.append(line)
        info["notes"] = notes
        # 改寫 abandon／distribution 演算標／最可能標，點名 NEXT（仍非保證）
        proj = dict(info.get("project") or {})
        key = str(proj.get("key") or "")
        if key in ("abandon", "distribution"):
            if pack.get("primary") and _num((pack.get("primary") or {}).get("price")) > 0:
                prim = pack["primary"]
                src = str(prim.get("source") or "")
                px = _fmt_price(prim.get("price"))
                nxt = _num(prim.get("price"))
                if key == "distribution":
                    proj["label"] = (
                        f"出貨痕跡，收破撐 {_fmt_price(spike_lo)}，"
                        f"朝{src} {px}。不是保證、非買訊。"
                    )
                    proj["target"] = nxt
                    proj["mark"] = f"最可能＝朝{src} {px}"
                else:
                    proj["label"] = (
                        f"收在撐 {_fmt_price(spike_lo)} 之下，"
                        f"下一撐：{src} {px}；不把反彈當最可能。不是保證。"
                    )
                    proj["target"] = nxt
                    proj["mark"] = f"最可能＝下一撐 {px}"
            elif pack.get("none_label"):
                if key == "abandon":
                    proj["label"] = (
                        f"收在撐 {_fmt_price(spike_lo)} 之下，{NONE_LABEL}；"
                        "這次量價先放棄，不把反彈當最可能。不是保證。"
                    )
                    proj["mark"] = "最可能＝先放棄"
                else:
                    proj["label"] = (
                        f"出貨痕跡，收破撐 {_fmt_price(spike_lo)}，{NONE_LABEL}。"
                        "不是保證、非買訊。"
                    )
                    proj["mark"] = f"最可能＝往撐 {_fmt_price(spike_lo)}"
            info["project"] = proj
    return info


def paint_written_and_next_levels(
    ax,
    *,
    sid: str,
    next_pack: Optional[Dict[str, Any]] = None,
    xmin: float = -0.55,
    xmax: float = 0.0,
    right_notes: Optional[List[Dict[str, Any]]] = None,
    label_x: Optional[float] = None,
    color_written: str = "#6a1b9a",
    color_next: str = "#1565c0",
    color_none: str = "#546e7a",
    ymin: Optional[float] = None,
    ymax: Optional[float] = None,
    tag_size: float = 10.0,
) -> List[float]:
    """在結構／大量區圖畫原文目標水平線＋破撐 NEXT（或暫無字）。

    回傳畫過的 y 價（呼叫端可併入 ylim／avoid）。
    """
    ys: List[float] = []
    pack = dict(next_pack or {})
    written = list(pack.get("written") or written_targets_for(sid))
    lx = float(label_x) if label_x is not None else float(xmax) - 0.4
    notes = right_notes if isinstance(right_notes, list) else None

    for row in written:
        y = _num(row.get("price"))
        if y <= 0:
            continue
        if ymin is not None and ymax is not None:
            if y < float(ymin) - 1e-9 or y > float(ymax) + 1e-9:
                # 仍畫線；ylim 由呼叫端先吃
                pass
        try:
            ax.hlines(
                y,
                xmin=xmin,
                xmax=xmax,
                colors=color_written,
                linestyles=(0, (4.0, 2.4)),
                linewidth=1.05,
                zorder=4,
                alpha=0.88,
            )
        except Exception:
            try:
                ax.axhline(
                    y,
                    color=color_written,
                    linestyle=(0, (4.0, 2.4)),
                    linewidth=1.05,
                    zorder=4,
                    alpha=0.88,
                )
            except Exception:
                continue
        ys.append(y)
        label = str(row.get("label") or written_target_label(y))
        if notes is not None:
            notes.append(
                {
                    "x": lx,
                    "y": y,
                    "text": label,
                    "color": color_written,
                    "size": tag_size,
                }
            )
        else:
            try:
                ax.text(
                    0.988,
                    y,
                    label,
                    transform=ax.get_yaxis_transform(),
                    ha="right",
                    va="center",
                    color=color_written,
                    fontsize=max(7.5, float(tag_size) - 1.5),
                    zorder=11,
                    clip_on=False,
                )
            except Exception:
                pass

    if pack.get("broke"):
        prim = pack.get("primary")
        if prim and _num(prim.get("price")) > 0:
            y = _num(prim.get("price"))
            # 若與原文目標同價，不重複畫線；標籤用下一撐
            same = any(abs(y - w) < 1e-6 for w in ys)
            if not same:
                try:
                    ax.hlines(
                        y,
                        xmin=xmin,
                        xmax=xmax,
                        colors=color_next,
                        linestyles=(0, (2.2, 1.6)),
                        linewidth=1.15,
                        zorder=4,
                        alpha=0.9,
                    )
                except Exception:
                    try:
                        ax.axhline(
                            y,
                            color=color_next,
                            linestyle=(0, (2.2, 1.6)),
                            linewidth=1.15,
                            zorder=4,
                            alpha=0.9,
                        )
                    except Exception:
                        pass
                ys.append(y)
            label = str(prim.get("label") or next_support_label(str(prim.get("source") or ""), y))
            if notes is not None:
                notes.append(
                    {
                        "x": lx,
                        "y": y,
                        "text": label,
                        "color": color_next,
                        "size": tag_size,
                    }
                )
            else:
                try:
                    ax.text(
                        0.988,
                        y,
                        label,
                        transform=ax.get_yaxis_transform(),
                        ha="right",
                        va="center",
                        color=color_next,
                        fontsize=max(7.5, float(tag_size) - 1.5),
                        zorder=11,
                        clip_on=False,
                    )
                except Exception:
                    pass
        elif pack.get("none_label"):
            # 明示暫無；掛在軸內下緣，不准發明價線
            try:
                ax.text(
                    0.98,
                    0.04,
                    str(pack.get("none_label") or NONE_LABEL),
                    transform=ax.transAxes,
                    ha="right",
                    va="bottom",
                    color=color_none,
                    fontsize=8.2,
                    zorder=11,
                    clip_on=True,
                )
            except Exception:
                pass
    return ys
