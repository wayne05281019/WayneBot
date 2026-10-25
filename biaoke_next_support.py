# -*- coding: utf-8 -*-
"""破大量區撐／過壓 → 下一層（次大量區壓+撐）＋飆大原文絕對目標（非買訊）。

產品（2026-10-25 鎖／WB-27）：
- 下一層＝往更早 K 對照出的**次大量區間**（上緣壓＋下緣撐兩條一起）；
  不是單線平行撐、也不把原文目標叫「下一撐」。
- 收盤有效破主撐才標下一層；收盤有效過主壓對稱標下一層（下一壓）。
- 破撐≠立刻換主區（主區仍依 find_volume_zone 近窗爆大量重算）。
- 平行軌若結構圖仍畫，用通道自己的名，不准搶「下一撐／下一層」。
- 他寫死絕對價＝「飆大原文目標 {價}・非買訊」；檔別隔離。
Asia/Taipei；官方已收 OHLC＋量。
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence, Tuple

NONE_LABEL = "暫無下一層大量區"
WRITTEN_LABEL_TMPL = "飆大原文目標 {price}・非買訊"
NEXT_HOLD_LABEL_TMPL = "下一層撐 {price}"
NEXT_PRESS_LABEL_TMPL = "下一層壓 {price}"
NEXT_LAYER_SOURCE = "次大量區"

# 相容舊測試／靜默鍵顯示名
SOURCE_NEXT_VOL = "次大量區撐"
SOURCE_NEXT_VOL_PRESS = "次大量區壓"
SOURCE_WRITTEN = "原文目標"
# 舊來源名保留常數，但**不再**當下一層主候選（不准搶名）
SOURCE_CHANNEL = "平行撐"
SOURCE_CHANNEL_DASH = "通道下緣"
SOURCE_PIVOT = "近窗樞紐低"

# 他寫死的絕對價：每檔隔離。費半／大立光無絕對價 → 不補。
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

_DEFAULT_LOOKBACK = 40
_EARLIER_LOOKBACK = 80  # 近窗內次層已破 → 往更早 K 再找一檔


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


def _cjk_fp(size: float = 9.0, weight: str = "bold"):
    """與結構圖／大量區標籤同源 CJK 字型；缺字＝方塊亂碼。"""
    try:
        from wayne_navigator import _fp

        return _fp(float(size), weight)
    except Exception:
        return None


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


def next_hold_label(price: Any) -> str:
    return NEXT_HOLD_LABEL_TMPL.format(price=_fmt_price(price) or "—")


def next_press_label(price: Any) -> str:
    return NEXT_PRESS_LABEL_TMPL.format(price=_fmt_price(price) or "—")


def next_support_label(source: str, price: Any) -> str:
    """舊單線標籤相容；次大量區改走下一層撐文案。"""
    src = str(source or "").strip()
    if src in (SOURCE_NEXT_VOL, NEXT_LAYER_SOURCE, SOURCE_NEXT_VOL_PRESS):
        return next_hold_label(price)
    return f"下一撐：{src or '結構'} {_fmt_price(price) or '—'}"


def close_broke_vol_support(
    *,
    close: Any,
    support: Any,
) -> bool:
    """收盤有效跌破大量區撐；盤中刺穿不算（呼叫端須餵已收／臉柱收）。"""
    cl = _num(close)
    lo = _num(support)
    return bool(cl > 0 and lo > 0 and cl < lo)


def close_over_vol_pressure(
    *,
    close: Any,
    pressure: Any,
) -> bool:
    """收盤有效站上大量區壓；盤中刺穿不算。"""
    cl = _num(close)
    hi = _num(pressure)
    return bool(cl > 0 and hi > 0 and cl > hi)


def _window_rows(
    bars: Sequence[Dict[str, Any]],
    *,
    lookback: int,
) -> List[Dict[str, Any]]:
    rows = list(bars or [])
    if lookback > 0 and len(rows) > lookback:
        rows = rows[-int(lookback) :]
    # 不含末日（與 find_volume_zone 同尺：大量區＝過去參考）
    if len(rows) >= 2:
        return list(rows[:-1])
    return list(rows)


def find_secondary_vol_zone(
    bars: Sequence[Dict[str, Any]],
    *,
    direction: str = "below",
    ref_lo: float = 0.0,
    ref_hi: float = 0.0,
    exclude_date: str = "",
    lookback: int = _DEFAULT_LOOKBACK,
    close: Any = None,
    allow_earlier: bool = True,
) -> Optional[Dict[str, Any]]:
    """次大量區間（高低一對）。

    below（破撐後）：量次大且低 < 已破撐；若該撐已被收盤再破，往更低／更早串聯。
    above（過壓後）：量次大且高 > 已過壓；若該壓已被收盤再過，往更高／更早串聯。
    不准回填主區同一爆大量日。
    """
    rows = list(bars or [])
    if len(rows) < 4:
        return None
    excl = _ymd(exclude_date)
    cl = _num(close)
    direction = str(direction or "below").strip().lower() or "below"

    def _pick(lb: int) -> Optional[Dict[str, Any]]:
        cands = _window_rows(rows, lookback=lb)
        scored: List[Tuple[float, Dict[str, Any]]] = []
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
            if direction == "above":
                if ref_hi <= 0 or hi <= ref_hi + 1e-9:
                    continue
                # 已過這層壓 → 再往上找
                if cl > 0 and cl > hi + 1e-9:
                    continue
            else:
                if ref_lo <= 0 or lo >= ref_lo - 1e-9:
                    continue
                # 已破這層撐 → 再往下找
                if cl > 0 and cl < lo - 1e-9:
                    continue
            scored.append((v, r))
        if not scored:
            return None
        scored.sort(key=lambda t: -t[0])
        best = scored[0][1]
        lo = _num(best.get("low"))
        hi = _num(best.get("high"))
        return {
            "source": NEXT_LAYER_SOURCE,
            "price": lo if direction != "above" else hi,  # 主焦點價（相容 primary.price）
            "low": lo,
            "high": hi,
            "support": lo,
            "pressure": hi,
            "date": _ymd(best.get("date")),
            "volume": _num(best.get("volume")),
            "direction": direction,
            "label_hold": next_hold_label(lo),
            "label_press": next_press_label(hi),
            # 舊單線相容：破撐主標＝撐；過壓主標＝壓
            "label": (
                next_press_label(hi) if direction == "above" else next_hold_label(lo)
            ),
            "source_hold": SOURCE_NEXT_VOL,
            "source_press": SOURCE_NEXT_VOL_PRESS,
        }

    hit = _pick(int(lookback or _DEFAULT_LOOKBACK))
    if hit is None and allow_earlier and int(lookback or 0) < _EARLIER_LOOKBACK:
        hit = _pick(_EARLIER_LOOKBACK)
    return hit


def find_secondary_vol_zone_support(
    bars: Sequence[Dict[str, Any]],
    *,
    broken_lo: float,
    exclude_date: str = "",
    lookback: int = _DEFAULT_LOOKBACK,
    close: Any = None,
) -> Optional[Dict[str, Any]]:
    """相容舊 API：回次大量區撐列（含 high）。"""
    zone = find_secondary_vol_zone(
        bars,
        direction="below",
        ref_lo=broken_lo,
        exclude_date=exclude_date,
        lookback=lookback,
        close=close,
    )
    if not zone:
        return None
    # 舊欄位名
    zone = dict(zone)
    zone["source"] = SOURCE_NEXT_VOL
    zone["price"] = _num(zone.get("low") or zone.get("price"))
    zone["label"] = next_hold_label(zone["price"])
    return zone


def collect_next_support_candidates(
    bars: Sequence[Dict[str, Any]],
    *,
    sid: str = "",
    broken_lo: float,
    spike_date: str = "",
    channel: Optional[Dict[str, Any]] = None,
    close: Any = None,
) -> List[Dict[str, Any]]:
    """破撐後 NEXT 候選。產品主臉只認次大量區；原文另欄不搶「下一撐」名。

    channel 參數保留（呼叫端相容），但**不**再進下一層主候選。
    """
    del channel  # 平行撐不准搶下一撐名
    if broken_lo <= 0:
        return []
    cands: List[Dict[str, Any]] = []
    sec = find_secondary_vol_zone(
        bars,
        direction="below",
        ref_lo=broken_lo,
        exclude_date=spike_date,
        close=close,
    )
    if sec:
        # candidates 列：撐／壓各一列方便靜默；primary 用整區
        cands.append(
            {
                **sec,
                "source": SOURCE_NEXT_VOL,
                "price": _num(sec.get("low")),
                "label": next_hold_label(sec.get("low")),
                "role": "hold",
                "layer": sec,
            }
        )
        cands.append(
            {
                **sec,
                "source": SOURCE_NEXT_VOL_PRESS,
                "price": _num(sec.get("high")),
                "label": next_press_label(sec.get("high")),
                "role": "press",
                "layer": sec,
            }
        )
    # 原文目標只留在 written／face，不進「下一撐」候選搶名
    _ = sid
    return cands


def resolve_next_support(
    bars: Sequence[Dict[str, Any]],
    *,
    sid: str = "",
    close: Any = None,
    support: Any = None,
    pressure: Any = None,
    spike_date: str = "",
    channel: Optional[Dict[str, Any]] = None,
    under_support: Optional[bool] = None,
    over_pressure: Optional[bool] = None,
) -> Dict[str, Any]:
    """破撐／過壓時解析下一層（次大量區壓+撐）；未破未過＝不畫下一層。

    回傳：
      broke, over, layer, primary, primary_press, candidates,
      none_label, reason_line, written, written_lines
    破撐≠換主區（本函式不改主區錨）。
    """
    del channel
    rows = list(bars or [])
    broken_lo = _num(support)
    broken_hi = _num(pressure)
    cl = _num(close)
    if cl <= 0 and rows:
        cl = _num(rows[-1].get("close"))
    broke = (
        bool(under_support)
        if under_support is not None
        else close_broke_vol_support(close=cl, support=broken_lo)
    )
    over = (
        bool(over_pressure)
        if over_pressure is not None
        else (
            close_over_vol_pressure(close=cl, pressure=broken_hi)
            if broken_hi > 0
            else False
        )
    )
    # 同時破撐又過壓不合理；破撐優先（掉在撐下）
    if broke:
        over = False
    written = written_targets_for(sid)
    out: Dict[str, Any] = {
        "broke": bool(broke),
        "over": bool(over),
        "broken_lo": broken_lo if broke else 0.0,
        "broken_hi": broken_hi if over else 0.0,
        "close": cl,
        "sid": _sid(sid),
        "layer": None,
        "primary": None,
        "primary_press": None,
        "candidates": [],
        "none_label": "",
        "reason_line": "",
        "written": written,
        "written_lines": [w.get("label") for w in written if w.get("label")],
        "main_zone_unchanged": True,  # 破撐≠換主區
    }
    if not broke and not over:
        return out

    if broke:
        layer = find_secondary_vol_zone(
            rows,
            direction="below",
            ref_lo=broken_lo,
            exclude_date=spike_date,
            close=cl,
        )
        out["candidates"] = collect_next_support_candidates(
            rows,
            sid=sid,
            broken_lo=broken_lo,
            spike_date=spike_date,
            close=cl,
        )
    else:
        layer = find_secondary_vol_zone(
            rows,
            direction="above",
            ref_hi=broken_hi,
            exclude_date=spike_date,
            close=cl,
        )
        if layer:
            out["candidates"] = [
                {
                    **layer,
                    "source": SOURCE_NEXT_VOL_PRESS,
                    "price": _num(layer.get("high")),
                    "label": next_press_label(layer.get("high")),
                    "role": "press",
                    "layer": layer,
                },
                {
                    **layer,
                    "source": SOURCE_NEXT_VOL,
                    "price": _num(layer.get("low")),
                    "label": next_hold_label(layer.get("low")),
                    "role": "hold",
                    "layer": layer,
                },
            ]

    out["layer"] = layer
    if layer and _num(layer.get("low")) > 0 and _num(layer.get("high")) > 0:
        hold = {
            "source": SOURCE_NEXT_VOL,
            "price": _num(layer.get("low")),
            "high": _num(layer.get("high")),
            "low": _num(layer.get("low")),
            "date": layer.get("date"),
            "volume": layer.get("volume"),
            "label": next_hold_label(layer.get("low")),
            "layer": layer,
        }
        press = {
            "source": SOURCE_NEXT_VOL_PRESS,
            "price": _num(layer.get("high")),
            "high": _num(layer.get("high")),
            "low": _num(layer.get("low")),
            "date": layer.get("date"),
            "volume": layer.get("volume"),
            "label": next_press_label(layer.get("high")),
            "layer": layer,
        }
        out["primary"] = press if over else hold
        out["primary_press"] = press
        out["primary_hold"] = hold
        out["none_label"] = ""
    else:
        out["primary"] = None
        out["primary_press"] = None
        out["primary_hold"] = None
        out["none_label"] = NONE_LABEL

    out["reason_line"] = reason_next_support_line(
        broken_lo=broken_lo if broke else 0.0,
        broken_hi=broken_hi if over else 0.0,
        layer=layer,
        primary=out.get("primary"),
        none_label=out.get("none_label") or "",
        distribution=False,
        over=over,
    )
    return out


def reason_next_support_line(
    *,
    broken_lo: float = 0.0,
    broken_hi: float = 0.0,
    layer: Optional[Dict[str, Any]] = None,
    primary: Optional[Dict[str, Any]] = None,
    none_label: str = "",
    distribution: bool = False,
    over: bool = False,
) -> str:
    """破撐／過壓／出貨痕跡一句原因：點名下一層壓+撐；非買訊。"""
    if over:
        hi_s = _fmt_price(broken_hi) or "—"
        head = f"收過大量區壓 {hi_s}"
    else:
        lo_s = _fmt_price(broken_lo) or "—"
        head = (
            f"過壓後掉回撐下＝出貨痕跡，收破大量區撐 {lo_s}"
            if distribution
            else f"收破大量區撐 {lo_s}"
        )
    zone = dict(layer or {})
    if not zone and primary:
        zone = dict((primary or {}).get("layer") or primary or {})
    lo = _num(zone.get("low") or zone.get("support"))
    hi = _num(zone.get("high") or zone.get("pressure"))
    if lo > 0 and hi > 0:
        return (
            f"{head}，下一層＝次大量區壓 {_fmt_price(hi)}／"
            f"撐 {_fmt_price(lo)}（非買訊）"
        )
    if primary and _num(primary.get("price")) > 0:
        src = str(primary.get("source") or "").strip() or NEXT_LAYER_SOURCE
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
    """把下一層／原文目標掛進 analyze_structure 結果（原地＋回傳）。"""
    if not isinstance(info, dict):
        return {}
    rows = list(bars or [])
    if not rows:
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
    spike_hi = _num(st.get("spike_high") or info.get("spike_hi"))
    last = info.get("last_bar") or (rows[-1] if rows else {})
    close = _num(last.get("close"))
    if close <= 0 and info.get("closes"):
        close = _num(list(info.get("closes") or [])[-1])
    pack = resolve_next_support(
        rows,
        sid=sid or str(st.get("sid") or ""),
        close=close,
        support=spike_lo,
        pressure=spike_hi,
        spike_date=str(st.get("spike_date") or ""),
        under_support=bool(info.get("under_support") or info.get("distribution")),
        over_pressure=(
            bool(info.get("over_pressure") or info.get("over_press"))
            if ("over_pressure" in info or "over_press" in info)
            else None
        ),
    )
    info["next_support"] = pack
    if pack.get("broke") or pack.get("over"):
        line = reason_next_support_line(
            broken_lo=_num(pack.get("broken_lo") or spike_lo),
            broken_hi=_num(pack.get("broken_hi") or spike_hi),
            layer=pack.get("layer"),
            primary=pack.get("primary"),
            none_label=str(pack.get("none_label") or ""),
            distribution=bool(info.get("distribution")),
            over=bool(pack.get("over")),
        )
        pack["reason_line"] = line
        notes = list(info.get("notes") or [])
        if line and line not in notes:
            notes.append(line)
        info["notes"] = notes
        proj = dict(info.get("project") or {})
        key = str(proj.get("key") or "")
        layer = dict(pack.get("layer") or {})
        lo = _num(layer.get("low"))
        hi = _num(layer.get("high"))
        if key in ("abandon", "distribution") and pack.get("broke"):
            # 圖上不再畫「最可能＝…」橘虛線／標；演算句留 label，mark 清空
            if lo > 0 and hi > 0:
                if key == "distribution":
                    proj["label"] = (
                        f"出貨痕跡，收破撐 {_fmt_price(spike_lo)}，"
                        f"下一層壓 {_fmt_price(hi)}／撐 {_fmt_price(lo)}。"
                        "不是保證、非買訊。"
                    )
                    proj["target"] = lo
                else:
                    proj["label"] = (
                        f"收在撐 {_fmt_price(spike_lo)} 之下，"
                        f"下一層壓 {_fmt_price(hi)}／撐 {_fmt_price(lo)}；"
                        "不把反彈當最可能。不是保證。"
                    )
                    proj["target"] = lo
                proj["mark"] = ""
            elif pack.get("none_label"):
                if key == "abandon":
                    proj["label"] = (
                        f"收在撐 {_fmt_price(spike_lo)} 之下，{NONE_LABEL}；"
                        "這次量價先放棄，不把反彈當最可能。不是保證。"
                    )
                else:
                    proj["label"] = (
                        f"出貨痕跡，收破撐 {_fmt_price(spike_lo)}，{NONE_LABEL}。"
                        "不是保證、非買訊。"
                    )
                proj["mark"] = ""
            info["project"] = proj
    return info


def find_layer_bar_index(
    bars: Sequence[Dict[str, Any]],
    layer: Optional[Dict[str, Any]],
) -> int:
    """次大量參考日在可視 bars 的索引；找不到回 -1。"""
    d = _ymd((layer or {}).get("date"))
    if not d:
        return -1
    for i, r in enumerate(bars or []):
        if _ymd(r.get("date")) == d:
            return int(i)
    return -1


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
    color_next_press: str = "#ad1457",
    color_none: str = "#546e7a",
    color_band: str = "#9e9e9e",
    band_alpha: float = 0.14,
    ymin: Optional[float] = None,
    ymax: Optional[float] = None,
    tag_size: float = 10.0,
    layer_labels: str = "right",
    written_labels: str = "auto",
) -> List[float]:
    """原文目標水平線＋破撐／過壓下一層（次大量區淺灰底＋壓／撐兩線）。

    layer_labels：
      - \"left\"＝結構圖：下一層壓／撐偏左（比照大量區左側標）
      - \"right\"／\"notes\"＝右側或併入 right_notes
    written_labels：\"auto\"＝有 right_notes 走 notes，否則 right；也可強制 left／right／notes。
    標籤一律帶 CJK fontproperties。平行撐不搶「下一撐」名。
    """
    ys: List[float] = []
    pack = dict(next_pack or {})
    written = list(pack.get("written") or written_targets_for(sid))
    lx = float(label_x) if label_x is not None else float(xmax) - 0.4
    notes = right_notes if isinstance(right_notes, list) else None
    layer_mode = str(layer_labels or "right").strip().lower() or "right"
    written_mode = str(written_labels or "auto").strip().lower() or "auto"
    if written_mode == "auto":
        written_mode = "notes" if notes is not None else "right"
    fp = _cjk_fp(max(7.5, float(tag_size) - 1.5), "bold")
    fp_tag = _cjk_fp(max(8.5, float(tag_size) - 0.5), "bold")
    fp_none = _cjk_fp(8.2, "bold")
    _tag_box = dict(
        boxstyle="round,pad=0.28",
        facecolor="#ffffff",
        linewidth=1.1,
        alpha=0.94,
    )

    def _text(x, y, text, *, color, size=None, transform=None, ha="right", va="center", bbox=None):
        kw: Dict[str, Any] = {
            "ha": ha,
            "va": va,
            "color": color,
            "fontsize": float(size if size is not None else max(7.5, float(tag_size) - 1.5)),
            "zorder": 11,
            "clip_on": False,
        }
        use_fp = fp_tag if bbox is not None else fp
        if use_fp is not None:
            kw["fontproperties"] = (
                use_fp if size is None else _cjk_fp(float(size), "bold")
            )
            kw.pop("fontsize", None)
        if transform is not None:
            kw["transform"] = transform
        if bbox is not None:
            kw["bbox"] = bbox
        ax.text(x, y, text, **kw)

    def _label_y(raw_y: float, used: List[float]) -> float:
        """標籤 y 微避讓：原文與下一層壓太近不准互蓋。"""
        y = float(raw_y)
        try:
            y0, y1 = ax.get_ylim()
            span = max(abs(float(y1) - float(y0)), 1.0)
        except Exception:
            span = max(abs(y) * 0.2, 50.0)
        gap = span * 0.028
        for _ in range(8):
            if all(abs(y - u) >= gap for u in used):
                break
            above = sum(1 for u in used if u >= y)
            below = sum(1 for u in used if u < y)
            y = y - gap if above >= below else y + gap
        used.append(y)
        return y

    label_ys: List[float] = []

    for row in written:
        y = _num(row.get("price"))
        if y <= 0:
            continue
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
        lab_y = _label_y(y, label_ys)
        if written_mode == "notes" and notes is not None:
            notes.append(
                {
                    "x": lx,
                    "y": lab_y,
                    "text": label,
                    "color": color_written,
                    "size": tag_size,
                }
            )
        elif written_mode == "left":
            try:
                _text(
                    0.012,
                    lab_y,
                    label,
                    color=color_written,
                    transform=ax.get_yaxis_transform(),
                    ha="left",
                    va="center",
                    bbox={**_tag_box, "edgecolor": color_written},
                    size=max(8.5, float(tag_size) - 0.5),
                )
            except Exception:
                pass
        else:
            try:
                _text(
                    0.988,
                    lab_y,
                    label,
                    color=color_written,
                    transform=ax.get_yaxis_transform(),
                )
            except Exception:
                pass

    layer = dict(pack.get("layer") or {})
    if not layer and pack.get("primary"):
        layer = dict((pack.get("primary") or {}).get("layer") or {})

    show_layer = bool(pack.get("broke") or pack.get("over")) and bool(layer)
    if show_layer:
        lo = _num(layer.get("low") or layer.get("support"))
        hi = _num(layer.get("high") or layer.get("pressure"))
        if lo > 0 and hi > 0 and hi >= lo:
            # 淺灰底＝次大量區區間帶（不是平行撐細縫；與主區桃色分開）
            try:
                ax.axhspan(
                    lo,
                    hi,
                    facecolor=color_band,
                    edgecolor="none",
                    alpha=float(band_alpha),
                    zorder=1,
                )
            except Exception:
                pass
            for y, color, label in (
                (hi, color_next_press, str(layer.get("label_press") or next_press_label(hi))),
                (lo, color_next, str(layer.get("label_hold") or next_hold_label(lo))),
            ):
                same = any(abs(y - w) < 1e-6 for w in ys)
                if not same:
                    try:
                        ax.hlines(
                            y,
                            xmin=xmin,
                            xmax=xmax,
                            colors=color,
                            linestyles=(0, (2.2, 1.6)),
                            linewidth=1.15,
                            zorder=4,
                            alpha=0.9,
                        )
                    except Exception:
                        try:
                            ax.axhline(
                                y,
                                color=color,
                                linestyle=(0, (2.2, 1.6)),
                                linewidth=1.15,
                                zorder=4,
                                alpha=0.9,
                            )
                        except Exception:
                            pass
                    ys.append(y)
                lab_y = _label_y(y, label_ys)
                if layer_mode == "left":
                    try:
                        _text(
                            0.012,
                            lab_y,
                            label,
                            color=color,
                            transform=ax.get_yaxis_transform(),
                            ha="left",
                            va="center",
                            bbox={**_tag_box, "edgecolor": color},
                            size=max(9.0, float(tag_size) - 0.2),
                        )
                    except Exception:
                        pass
                elif layer_mode == "notes" and notes is not None:
                    notes.append(
                        {
                            "x": lx,
                            "y": lab_y,
                            "text": label,
                            "color": color,
                            "size": tag_size,
                        }
                    )
                else:
                    try:
                        _text(
                            0.988,
                            lab_y,
                            label,
                            color=color,
                            transform=ax.get_yaxis_transform(),
                        )
                    except Exception:
                        pass
    elif pack.get("broke") or pack.get("over"):
        if pack.get("none_label"):
            try:
                kw: Dict[str, Any] = {
                    "transform": ax.transAxes,
                    "ha": "right",
                    "va": "bottom",
                    "color": color_none,
                    "zorder": 11,
                    "clip_on": True,
                }
                if fp_none is not None:
                    kw["fontproperties"] = fp_none
                else:
                    kw["fontsize"] = 8.2
                ax.text(0.98, 0.04, str(pack.get("none_label") or NONE_LABEL), **kw)
            except Exception:
                pass
    return ys
