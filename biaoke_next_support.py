# -*- coding: utf-8 -*-
"""破大量區撐／過壓 → 下一層（次大量區壓+撐）＋飆大原文絕對目標（非買訊）。

產品（2026-10-25 鎖／WB-27；2026-10-29 話筒臉）：
- 下一層＝往更早 K 對照出的**次大量區間**（上緣壓＋下緣撐兩條一起）；
  不是單線平行撐、也不把原文目標叫「下一撐」。
- 收盤有效破主撐才標下一層；收盤有效過主壓對稱標下一層（下一壓）。
- **畫法（2026-10-29 鎖臉）**：次大量區間＝K 下**較深**淺灰價帶（α≈0.30）
  ＋下一層壓／撐虛線＋數字角標（使用者改口：虛線／數字要留）。
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
# v11：下一層壓／撐整組同一字級（結構＝大量區）；略縮輔助避擋，掃位優先。主壓撐／原文／量標不跟縮。
LAYER_TAG_PT = 8.5
LAYER_TAG_SIZE_DELTA = 1.35  # 相容舊測試／說明
LAYER_TAG_SIZE_FLOOR = 8.2
LAYER_TAG_PAD = 0.20

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
    # 無下一層：原因句只留破撐／過壓本身；不准附「暫無下一層大量區」佔位
    # （none_label 參數保留給呼叫端相容；圖／話筒靜默）
    _ = none_label
    return f"{head}"


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
                # 無下一層：靜默佔位字；演算句仍可講破撐／出貨，不准寫暫無下一層
                if key == "abandon":
                    proj["label"] = (
                        f"收在撐 {_fmt_price(spike_lo)} 之下；"
                        "這次量價先放棄，不把反彈當最可能。不是保證。"
                    )
                else:
                    proj["label"] = (
                        f"出貨痕跡，收破撐 {_fmt_price(spike_lo)}。"
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


def _approx_layer_tag_half_w(text: str, tag_size: float) -> float:
    """資料座標半寬粗估（沿 K 索引）；CJK 偏寬，略保守以免實畫仍壓柱。"""
    nchars = max(len(str(text or "")), 4)
    return max(3.6, 0.72 * float(nchars) * (max(float(tag_size), 8.0) / 10.0))



def _min_vertical_clearance(
    *,
    x0: float,
    x1: float,
    y: float,
    highs: Sequence[float],
    lows: Sequence[float],
) -> float:
    """盒內相對 K 的最小垂直距離；無柱則回大值。"""
    import math

    n = min(len(highs), len(lows))
    if n <= 0:
        return 1.0e9
    bar_hw = 0.42
    i0 = max(0, int(math.floor(float(x0) - bar_hw)))
    i1 = min(n - 1, int(math.ceil(float(x1) + bar_hw)))
    best = 1.0e9
    hit = False
    for i in range(i0, i1 + 1):
        if float(i) + bar_hw < float(x0) or float(i) - bar_hw > float(x1):
            continue
        try:
            hk = float(highs[i])
            lk = float(lows[i])
        except (TypeError, ValueError, IndexError):
            continue
        if hk <= 0 or lk <= 0:
            continue
        hit = True
        if lk <= float(y) <= hk:
            return 0.0
        if float(y) < lk:
            best = min(best, lk - float(y))
        else:
            best = min(best, float(y) - hk)
    return 1.0e9 if not hit else float(best)


def _layer_box_overlap_score(
    *,
    x0: float,
    x1: float,
    y: float,
    half_h: float,
    highs: Sequence[float],
    lows: Sequence[float],
    mas: Optional[Sequence[Sequence[float]]] = None,
    occupied: Optional[Sequence[Tuple[float, float, float, float]]] = None,
) -> float:
    """重疊 K／近距柱列／均線／已放標的代價；愈低愈好。"""
    score = 0.0
    n = min(len(highs), len(lows))
    if n <= 0:
        return score
    import math

    # K 柱資料座標半寬（與影線柱身對齊），避免右溝誤算末日柱
    bar_hw = 0.42
    i0 = max(0, int(math.floor(float(x0) - bar_hw)))
    i1 = min(n - 1, int(math.ceil(float(x1) + bar_hw)))
    y_lo = float(y) - float(half_h)
    y_hi = float(y) + float(half_h)
    soft_r = max(float(half_h) * 5.5, abs(float(y)) * 0.022, 28.0)
    recent_from = max(0, n - max(8, int(n * 0.12)))
    for i in range(i0, i1 + 1):
        bx0_i, bx1_i = float(i) - bar_hw, float(i) + bar_hw
        if bx1_i < float(x0) or bx0_i > float(x1):
            continue
        try:
            hk = float(highs[i])
            lk = float(lows[i])
        except (TypeError, ValueError, IndexError):
            continue
        if hk <= 0 or lk <= 0:
            continue
        if lk <= y_hi and hk >= y_lo:
            score += 2.5
            if lk <= float(y) <= hk:
                # 標壓在真 K 柱上＝重罰（使用者紅圈壞例）
                score += 8.0
                mid = 0.5 * (hk + lk)
                span = max(hk - lk, 1e-6)
                score += 2.5 * (1.0 - min(abs(float(y) - mid) / span, 1.0))
        else:
            # 同 x 柱列近距也擋讀＝軟罰，逼標離開密 K 帶
            if float(y) < lk:
                dist = lk - float(y)
            elif float(y) > hk:
                dist = float(y) - hk
            else:
                dist = 0.0
            if dist < soft_r:
                score += 2.2 * (1.0 - dist / soft_r)
            # 標在近端 K 正下方／上方＝再罰（右溝貼末日柱壞例）
            if i >= recent_from and dist < soft_r * 1.35:
                score += 3.2 * (1.0 - min(dist / (soft_r * 1.35), 1.0))
            # 線遠低於近端行情時，仍算「擋在 K 列下」——逼標稍離末日柱
            if i >= recent_from and float(y) < lk:
                score += 2.4 * min(1.0, 380.0 / max(lk - float(y), 50.0))
        if mas:
            for arr in mas:
                if arr is None or i >= len(arr):
                    continue
                try:
                    mv = float(arr[i])
                except (TypeError, ValueError, IndexError):
                    continue
                if mv > 0 and abs(mv - float(y)) <= float(half_h) * 1.25:
                    score += 1.15
    # 右緣無柱但仍在近端行情正下方（視感貼 K）＝罰，改搶線上中空窗
    if n > 0:
        import statistics

        recent_lows = []
        for j in range(recent_from, n):
            try:
                lv = float(lows[j])
            except (TypeError, ValueError, IndexError):
                continue
            if lv > 0:
                recent_lows.append(lv)
        if recent_lows:
            med = float(statistics.median(recent_lows))
            if float(y) < med - float(half_h):
                # 僅罰「貼末日柱」右溝；中段高淨空空窗不罰
                if float(x0) >= float(recent_from) - 0.5:
                    score += 26.0 + 0.35 * max(0.0, float(x1) - float(recent_from))
    for box in occupied or ():

        try:
            ox0, ox1, oy0, oy1 = (float(box[0]), float(box[1]), float(box[2]), float(box[3]))
        except (TypeError, ValueError, IndexError):
            continue
        ix0, ix1 = max(x0, ox0), min(x1, ox1)
        iy0, iy1 = max(y_lo, oy0), min(y_hi, oy1)
        if ix1 > ix0 and iy1 > iy0:
            score += 10.0 * (ix1 - ix0) * (iy1 - iy0) / max(half_h * 2.0, 1e-6)
    return float(score)


def pick_layer_label_along_line(
    *,
    y: float,
    text: str,
    xmin: float,
    xmax: float,
    highs: Sequence[float],
    lows: Sequence[float],
    mas: Optional[Sequence[Sequence[float]]] = None,
    occupied: Optional[Sequence[Tuple[float, float, float, float]]] = None,
    tag_size: float = 10.0,
    y_span: Optional[float] = None,
    prefer_x: Optional[float] = None,
    max_score: Optional[float] = 22.0,
    same_band_max: float = 10.0,
) -> Optional[Tuple[float, str, Tuple[float, float, float, float]]]:
    """沿水平線掃候選，取重疊代價最低的錨點（不准寫死左／右）。

    候選含左空白、線段中空窗、右溝；同代價偏好較空／較右，避開密 K。
    prefer_x：成對下一層壓／撐鎖同垂直帶。
    max_score：代價過高→回 None（略過，不准硬壓 K）。
    回傳 (x, ha, occupied_box) 或 None。
    """
    import math

    half_w = _approx_layer_tag_half_w(text, tag_size)
    try:
        span = float(y_span) if y_span and float(y_span) > 0 else 0.0
    except (TypeError, ValueError):
        span = 0.0
    if span <= 0:
        try:
            hs = [float(h) for h in highs if float(h) > 0]
            ls = [float(l) for l in lows if float(l) > 0]
            span = max(max(hs) - min(ls), 1.0) if hs and ls else max(abs(float(y)) * 0.2, 50.0)
        except Exception:
            span = max(abs(float(y)) * 0.2, 50.0)
    # 半高隨價窗縮放：絕對 floor=10 會讓 30～50 元股整盒蓋滿 K → 掃位全死、只能歪出右緣
    half_h = max(float(span) * 0.022, abs(float(y)) * 0.0035, 1.15)
    half_h = min(float(half_h), max(float(span) * 0.09, 2.8))
    x_lo = float(xmin) + half_w * 0.12
    x_hi = float(xmax) - half_w * 0.12
    if x_hi <= x_lo + 1.0:
        cx = 0.5 * (float(xmin) + float(xmax))
        box = (cx - half_w, cx + half_w, float(y) - half_h, float(y) + half_h)
        return cx, "center", box

    step = max(0.55, (x_hi - x_lo) / 64.0)
    best: Optional[Tuple[float, float, str, Tuple[float, float, float, float]]] = None
    trials: List[Tuple[float, str]] = []
    x = x_lo
    while x <= x_hi + 1e-9:
        trials.append((float(x), "center"))
        x += step
    trials.append((float(xmin) + half_w * 0.08, "left"))
    trials.append((float(xmax) - half_w * 0.08, "right"))
    n_bars = min(len(highs), len(lows))
    if n_bars > 0:
        last = float(n_bars - 1)
        # 右緣：ha=right 讓字往左長進圖內，不准 ha=left 把「下一層壓」裁出 figure
        trials.append((float(xmax) - 0.08, "right"))
        trials.append((min(float(xmax) - 0.05, last + 0.35), "right"))
        trials.append((max(float(xmin) + half_w * 0.2, last - half_w * 0.15), "right"))
        trials.append((max(float(xmin) + half_w, last - 1.2), "right"))
        # 左緣空白（含整盒在第一根左側）
        trials.append((max(float(xmin) + 0.05, -0.15), "left"))
        trials.append((float(xmin) + half_w * 0.9, "right"))
        trials.append((min(float(xmin) + 0.35, -0.05), "right"))
        # 整盒完全離開第 0 根（bar_hw=0.42）
        trials.append((float(xmin) - 0.25, "right"))
        trials.append((-0.55, "right"))

    # 可見左欄（資料座標，整盒進界）
    trials.append((float(xmin) + half_w * 1.05, "left"))
    trials.append((float(xmin) + half_w * 1.05 + half_w, "center"))
    # 已放標兩側空窗（常見：原文目標左／右）
    for ob in occupied or ():
        try:
            ox0, ox1 = float(ob[0]), float(ob[1])
        except (TypeError, ValueError, IndexError):
            continue
        trials.append((ox0 - half_w * 1.05, "right"))
        trials.append((ox1 + half_w * 0.15, "left"))
        trials.append((0.5 * (ox0 + ox1), "center"))
    # 空窗中心：連續不穿線的段，取中點當候選
    if n_bars > 0:
        y_lo = float(y) - half_h
        y_hi = float(y) + half_h
        clear: List[int] = []
        for i in range(n_bars):
            try:
                hk = float(highs[i])
                lk = float(lows[i])
            except (TypeError, ValueError, IndexError):
                clear.append(i)
                continue
            if hk <= 0 or lk <= 0 or not (lk <= y_hi and hk >= y_lo):
                clear.append(i)
        if clear:
            run_s = clear[0]
            prev = clear[0]
            for idx in clear[1:] + [clear[-1] + 2]:
                if idx == prev + 1:
                    prev = idx
                    continue
                run_e = prev
                if run_e - run_s + 1 >= 3:
                    mid = 0.5 * (run_s + run_e)
                    trials.append((float(mid), "center"))
                run_s = idx
                prev = idx

    # 成對同帶：優先在 prefer_x 附近加候選
    if prefer_x is not None:
        px = float(prefer_x)
        for dlt in (0.0, -2.0, 2.0, -4.0, 4.0, -6.0, 6.0, -8.0, 8.0):
            trials.append((px + dlt, "center"))
            trials.append((px + dlt, "left"))
            trials.append((px + dlt, "right"))

    for cx, ha in trials:
        if ha == "left":
            bx0, bx1 = float(cx), float(cx) + 2.0 * half_w
        elif ha == "right":
            bx0, bx1 = float(cx) - 2.0 * half_w, float(cx)
        else:
            bx0, bx1 = float(cx) - half_w, float(cx) + half_w
        if float(cx) < float(xmin) - 1.2 or float(cx) > float(xmax) + 0.8:
            continue
        if bx1 < float(xmin) - 1.2 or bx0 > float(xmax) + 0.8:
            continue
        # 硬拒：整盒超出資料右／左界＝話筒必裁（1605／3033／6443「下一層壓」右緣）
        if float(bx1) > float(xmax) + 0.05:
            continue
        if float(bx0) < float(xmin) - 0.55:
            continue
        # 成對：拉開同帶硬拒
        if prefer_x is not None and abs(float(cx) - float(prefer_x)) > float(same_band_max):
            continue
        sc = _layer_box_overlap_score(
            x0=bx0,
            x1=bx1,
            y=float(y),
            half_h=half_h,
            highs=highs,
            lows=lows,
            mas=mas,
            occupied=occupied,
        )
        # 硬拒：盒蓋到任何 K（與 smart_label_metrics k_hit 對齊）
        _k_hits = 0
        if n_bars > 0:
            import math as _math

            _i0 = max(0, int(_math.floor(float(bx0) - 0.42)))
            _i1 = min(n_bars - 1, int(_math.ceil(float(bx1) + 0.42)))
            _y_lo = float(y) - half_h
            _y_hi = float(y) + half_h
            for _i in range(_i0, _i1 + 1):
                try:
                    _hk = float(highs[_i])
                    _lk = float(lows[_i])
                except (TypeError, ValueError, IndexError):
                    continue
                if _hk <= 0 or _lk <= 0:
                    continue
                if _lk <= _y_hi and _hk >= _y_lo:
                    _k_hits += 1
            if _k_hits > 0:
                continue
        # 出界／半截＝不可用
        if bx1 < float(xmin) + 1.0:
            sc += 28.0
        if bx0 < float(xmin):
            sc += 14.0 * min(1.0, (float(xmin) - bx0) / max(half_w, 1.0))
        if bx0 > float(xmax) - 0.8:
            sc += 6.0
        # 貼右緣仍微罰，逼回圖內空窗
        if bx1 > float(xmax) - 0.35:
            sc += 9.0 * min(1.0, (bx1 - (float(xmax) - 0.35)) / max(half_w, 1.0))
        clear = _min_vertical_clearance(
            x0=bx0, x1=bx1, y=float(y), highs=highs, lows=lows
        )
        # 淨空太小＝視感貼 K（即使沒穿線）
        if clear < max(half_h * 3.0, 100.0):
            sc += 12.0 * (1.0 - min(clear / max(half_h * 3.0, 100.0), 1.0))
        # 高淨空＋中後段：加分；左 42% 內即使高淨空也微罰（少停上升初段）
        if n_bars > 0:
            if clear >= max(half_h * 6.0, 280.0) and bx0 >= float(n_bars) * 0.42:
                sc -= 11.0
            if bx1 <= float(n_bars) * 0.42:
                sc += 7.5
        recent_pen = 0.0
        if n_bars > 0 and bx1 > float(n_bars - 1) - max(6.0, n_bars * 0.10):
            recent_pen = 1.15
        band_pen = 0.0
        if prefer_x is not None:
            band_pen = abs(float(cx) - float(prefer_x)) * 0.08
        tie = -min(clear, 1200.0) * 1.2e-3 - bx1 * 1e-6
        key = sc + recent_pen + band_pen + tie
        box = (bx0, bx1, float(y) - half_h, float(y) + half_h)
        if best is None or key < best[0]:
            best = (key, float(cx), ha, box)

    if best is None:
        return None
    if max_score is not None and float(best[0]) > float(max_score):
        return None
    return best[1], best[2], best[3]


def _flush_smart_layer_pixel_gate(ax, queue, occupied_boxes) -> None:
    """成對下一層標：整批只 draw 一次再做像素裁切／nudge（結構＋大量少 Agg）。"""
    if not queue:
        return
    try:
        ax.figure.canvas.draw()
        ren = ax.figure.canvas.get_renderer()
    except Exception:
        return
    fbb = ax.figure.bbox
    for item in queue:
        art = item.get("art")
        if art is None:
            continue
        cx = float(item["cx"])
        ha = item["ha"]
        box = item["box"]
        label = item["label"]
        lab_y = item["lab_y"]
        color = item["color"]
        xmin = float(item["xmin"])
        _text = item["_text_fn"]
        _layer_tag_box = item["_layer_tag_box"]
        _layer_tag_size = item["_layer_tag_size"]
        try:
            for _nudge in range(8):
                bb = art.get_window_extent(renderer=ren)
                if not (
                    bb.x0 < fbb.x0 - 1
                    or bb.x1 > fbb.x1 - 1
                    or bb.y0 < fbb.y0 - 1
                    or bb.y1 > fbb.y1 - 1
                ):
                    break
                try:
                    art.remove()
                except Exception:
                    pass
                cx = float(cx) - 1.2
                ha = "right"
                _hw = max(0.5 * (float(box[1]) - float(box[0])), 1.0)
                box = (
                    cx - 2.0 * _hw,
                    cx,
                    float(box[2]),
                    float(box[3]),
                )
                if float(box[0]) < float(xmin) - 0.55:
                    art = None
                    break
                art = _text(
                    float(cx),
                    lab_y,
                    label,
                    color=color,
                    ha=ha,
                    va="center",
                    bbox={**_layer_tag_box, "edgecolor": color},
                    size=float(_layer_tag_size),
                )
                ax.figure.canvas.draw()
                ren = ax.figure.canvas.get_renderer()
            if art is None:
                try:
                    occupied_boxes.pop()
                except Exception:
                    pass
                continue
            bb = art.get_window_extent(renderer=ren)
            if (
                bb.x0 < fbb.x0 - 1
                or bb.x1 > fbb.x1 - 1
                or bb.y0 < fbb.y0 - 1
                or bb.y1 > fbb.y1 - 1
            ):
                try:
                    art.remove()
                except Exception:
                    pass
                try:
                    occupied_boxes.pop()
                except Exception:
                    pass
                continue
            occupied_boxes[-1] = box
            try:
                from smart_label_metrics import record_smart_label

                record_smart_label(
                    ax,
                    kind="layer",
                    text=str(label),
                    x0=float(box[0]),
                    x1=float(box[1]),
                    y0=float(box[2]),
                    y1=float(box[3]),
                    rail_y=float(lab_y),
                    clipped=False,
                )
            except Exception:
                pass
        except Exception:
            pass


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
    color_next: str = "#062e70",  # 下一層撐：再加深（縮圖可讀）
    color_next_press: str = "#ad1457",
    color_none: str = "#546e7a",
    color_band: str = "#78909c",
    band_alpha: float = 0.30,
    ymin: Optional[float] = None,
    ymax: Optional[float] = None,
    tag_size: float = 10.0,
    layer_labels: str = "right",
    written_labels: str = "auto",
    layer_marks: str = "both",
    busy_ys: Optional[Sequence[float]] = None,
    highs: Optional[Sequence[float]] = None,
    lows: Optional[Sequence[float]] = None,
    mas: Optional[Sequence[Sequence[float]]] = None,
    occupied: Optional[Sequence[Tuple[float, float, float, float]]] = None,
) -> List[float]:
    """原文目標水平線＋破撐／過壓下一層（次大量區深灰價帶＋壓／撐虛線標）。

    layer_marks（2026-10-29 鎖臉）：
      - \"both\"＝深灰價帶＋虛線＋角標（產品預設；對齊建議A濃度）
      - \"band\"＝只畫 K 下灰帶（無虛線／無標）
      - \"lines\"＝舊虛線＋角標（無灰帶）
    layer_labels：
      - \"smart\"／\"auto\"＝沿該水平線掃位，取擋 K／均線最少（有 highs／lows 時）
      - \"left\"＝偏左固定欄
      - \"right\"／\"notes\"＝右側或併入 right_notes
    written_labels：\"auto\"＝有 right_notes 走 notes，否則 right；也可強制 left／right／notes。
    busy_ys：已佔用價位（如大量區壓／撐），標籤 y 微避讓不准互蓋。
    occupied：已放標盒（主區壓撐／通道），下一層掃位須避讓不准互壓。
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
    hi_arr = list(highs) if highs is not None else []
    lo_arr = list(lows) if lows is not None else []
    if layer_mode in ("auto", "smart"):
        layer_mode = "smart" if (hi_arr and lo_arr) else ("notes" if notes is not None else "left")
    occupied_boxes: List[Tuple[float, float, float, float]] = []
    for ob in occupied or ():
        try:
            occupied_boxes.append(
                (float(ob[0]), float(ob[1]), float(ob[2]), float(ob[3]))
            )
        except (TypeError, ValueError, IndexError):
            continue
    try:
        y_span_for_pick = (
            abs(float(ymax) - float(ymin))
            if ymin is not None and ymax is not None
            else 0.0
        )
    except (TypeError, ValueError):
        y_span_for_pick = 0.0
    fp = _cjk_fp(max(7.5, float(tag_size) - 1.5), "bold")
    fp_tag = _cjk_fp(max(8.5, float(tag_size) - 0.5), "bold")
    fp_none = _cjk_fp(8.2, "bold")
    # v9：關鍵標白底不透明＋高 z，不准被 K／箭頭／均線壓住
    _tag_box = dict(
        boxstyle="round,pad=0.28",
        facecolor="#ffffff",
        linewidth=1.1,
        alpha=1.0,
    )
    # 下一層壓／撐：結構＝大量區同一絕對字級；兩條一樣大（略縮輔助避擋）
    _layer_tag_size = max(float(LAYER_TAG_SIZE_FLOOR), float(LAYER_TAG_PT))
    _layer_tag_box = dict(
        boxstyle=f"round,pad={float(LAYER_TAG_PAD):.2f}",
        facecolor="#ffffff",
        linewidth=1.0,
        alpha=1.0,
    )
    # 略高於大量區壓／撐角標（22），同欄近價時仍以白底可讀為先
    _TAG_Z = 23

    def _text(x, y, text, *, color, size=None, transform=None, ha="right", va="center", bbox=None):
        kw: Dict[str, Any] = {
            "ha": ha,
            "va": va,
            "color": color,
            "fontsize": float(size if size is not None else max(7.5, float(tag_size) - 1.5)),
            "zorder": int(_TAG_Z),
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
        return ax.text(x, y, text, **kw)

    def _label_y(raw_y: float, used: List[float]) -> float:
        """標籤 y 微避讓：原文與下一層壓太近不准互蓋。"""
        y = float(raw_y)
        try:
            y0, y1 = ax.get_ylim()
            span = max(abs(float(y1) - float(y0)), 1.0)
        except Exception:
            span = max(abs(y) * 0.2, 50.0)
        # 原文目標／下一層價很近時加大縫，避免白底互疊
        gap = span * 0.045
        for _ in range(10):
            if all(abs(y - u) >= gap for u in used):
                break
            above = sum(1 for u in used if u >= y)
            below = sum(1 for u in used if u < y)
            y = y - gap if above >= below else y + gap
        used.append(y)
        return y

    def _left_tag_x(raw_y: float, used: Sequence[float]) -> float:
        """近價互壓時改走第二欄 x，Y 仍釘線上。"""
        try:
            y0, y1 = ax.get_ylim()
            span = max(abs(float(y1) - float(y0)), 1.0)
        except Exception:
            span = max(abs(float(raw_y)) * 0.2, 50.0)
        gap = span * 0.055
        if any(abs(float(raw_y) - float(u)) < gap for u in used):
            return 0.22
        return 0.012

    label_ys: List[float] = []
    for _by in list(busy_ys or []):
        try:
            _bf = float(_by or 0)
        except (TypeError, ValueError):
            _bf = 0.0
        if _bf > 0:
            label_ys.append(_bf)

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
                # 近主區／下一層改第二欄；白底高 z，線仍對得到
                _wx = _left_tag_x(float(y), label_ys[:-1] if label_ys else [])
                _text(
                    float(_wx),
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
                # 大量區右緣：長標「飆大原文目標…非買訊」再左，整段可見、不壓軸刻度（v8／v10 位）
                _text(
                    0.78,
                    lab_y,
                    label,
                    color=color_written,
                    transform=ax.get_yaxis_transform(),
                    ha="right",
                    va="center",
                    bbox={**_tag_box, "edgecolor": color_written},
                    size=max(8.5, float(tag_size) - 0.5),
                )
                # 佔位給下一層 smart 掃位避讓
                try:
                    _xl0, _xl1 = ax.get_xlim()
                    _edge = float(_xl0) + 0.78 * (float(_xl1) - float(_xl0))
                    _hw = _approx_layer_tag_half_w(label, max(8.5, float(tag_size) - 0.5))
                    _hh = max(abs(float(lab_y)) * 0.004, 8.0)
                    if y_span_for_pick > 0:
                        _hh = max(_hh, float(y_span_for_pick) * 0.016)
                    # 佔位：價很近時加大 y 盒，逼下一層標錯開 x，避免白底互疊
                    _y_pad = _hh * 1.65
                    occupied_boxes.append(
                        (
                            _edge - 1.55 * _hw,
                            _edge + 0.35 * _hw,
                            float(lab_y) - _y_pad,
                            float(lab_y) + _y_pad,
                        )
                    )
                except Exception:
                    pass
            except Exception:
                pass

    layer = dict(pack.get("layer") or {})
    if not layer and pack.get("primary"):
        layer = dict((pack.get("primary") or {}).get("layer") or {})

    show_layer = bool(pack.get("broke") or pack.get("over")) and bool(layer)
    marks = str(layer_marks or "both").strip().lower() or "both"
    if marks not in ("band", "lines", "both"):
        marks = "both"
    draw_band = marks in ("band", "both")
    draw_layer_lines = marks in ("lines", "both")
    if show_layer:
        lo = _num(layer.get("low") or layer.get("support"))
        hi = _num(layer.get("high") or layer.get("pressure"))
        if lo > 0 and hi > 0 and hi >= lo:
            # 淺灰價帶＝次大量區（K／影線 z≥3 之上不准蓋；桃色主區 z=0 之下／旁）
            if draw_band:
                try:
                    ax.axhspan(
                        lo,
                        hi,
                        facecolor=color_band,
                        edgecolor="none",
                        alpha=float(band_alpha),
                        zorder=0.5,
                        clip_on=True,
                    )
                except Exception:
                    pass
                ys.append(float(lo))
                ys.append(float(hi))
            _layer_pair_anchor = False
            _layer_prefer_x: Optional[float] = None
            _smart_layer_pixel_queue: List[Dict[str, Any]] = []
            if draw_layer_lines:
                for y, color, label in (
                    (
                        hi,
                        color_next_press,
                        str(layer.get("label_press") or next_press_label(hi)),
                    ),
                    (
                        lo,
                        color_next,
                        str(layer.get("label_hold") or next_hold_label(lo)),
                    ),
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
                    if layer_mode == "smart" and hi_arr and lo_arr:
                        # v12：成對壓／撐同垂直帶；代價過高略過（不准硬壓 K）
                        lab_y = float(y)
                        label_ys.append(lab_y)
                        picked = pick_layer_label_along_line(
                            y=lab_y,
                            text=label,
                            xmin=float(xmin),
                            xmax=float(xmax),
                            highs=hi_arr,
                            lows=lo_arr,
                            mas=mas,
                            occupied=occupied_boxes,
                            tag_size=float(_layer_tag_size),
                            y_span=y_span_for_pick or None,
                            prefer_x=_layer_prefer_x,
                        )
                        # OPTIONAL：無淨空可略過。第二趟放寬代價但仍硬拒壓 K／超 xmax
                        if picked is None:
                            picked = pick_layer_label_along_line(
                                y=lab_y,
                                text=label,
                                xmin=float(xmin),
                                xmax=float(xmax),
                                highs=hi_arr,
                                lows=lo_arr,
                                mas=mas,
                                occupied=occupied_boxes,
                                tag_size=float(_layer_tag_size),
                                y_span=y_span_for_pick or None,
                                prefer_x=_layer_prefer_x,
                                max_score=60.0,
                            )
                        if picked is None:
                            continue
                        cx, ha, box = picked
                        # 雙保險：盒右緣仍超 xmax → 改 ha=right 釘在 xmax 內
                        if float(box[1]) > float(xmax) + 0.05:
                            _hw = max(0.5 * (float(box[1]) - float(box[0])), 1.0)
                            cx = float(xmax) - 0.08
                            ha = "right"
                            box = (
                                cx - 2.0 * _hw,
                                cx,
                                float(box[2]),
                                float(box[3]),
                            )
                            if float(box[0]) < float(xmin) - 0.55:
                                continue
                        occupied_boxes.append(box)
                        if _layer_prefer_x is None:
                            _layer_prefer_x = float(cx)
                            _layer_pair_anchor = True
                        try:
                            art = _text(
                                float(cx),
                                lab_y,
                                label,
                                color=color,
                                ha=ha,
                                va="center",
                                bbox={**_layer_tag_box, "edgecolor": color},
                                size=float(_layer_tag_size),
                            )
                            _smart_layer_pixel_queue.append(
                                {
                                    "art": art,
                                    "cx": cx,
                                    "ha": ha,
                                    "box": box,
                                    "label": label,
                                    "lab_y": lab_y,
                                    "color": color,
                                    "xmin": float(xmin),
                                    "_text_fn": _text,
                                    "_layer_tag_box": _layer_tag_box,
                                    "_layer_tag_size": _layer_tag_size,
                                }
                            )
                        except Exception:
                            pass
                    elif layer_mode == "left":
                        # 舊固定左欄；近主區壓撐改第二欄
                        lab_y = float(y)
                        lx_left = _left_tag_x(lab_y, label_ys)
                        label_ys.append(lab_y)
                        try:
                            _text(
                                float(lx_left),
                                lab_y,
                                label,
                                color=color,
                                transform=ax.get_yaxis_transform(),
                                ha="left",
                                va="center",
                                bbox={**_layer_tag_box, "edgecolor": color},
                                size=float(_layer_tag_size),
                            )
                        except Exception:
                            pass
                    elif layer_mode == "notes" and notes is not None:
                        lab_y = _label_y(y, label_ys)
                        notes.append(
                            {
                                "x": lx,
                                "y": lab_y,
                                "text": label,
                                "color": color,
                                "size": float(_layer_tag_size),
                                "pad": float(LAYER_TAG_PAD),
                            }
                        )
                    else:
                        lab_y = _label_y(y, label_ys)
                        try:
                            # v9：右緣下一層標也帶白底，不准被 K／箭頭切字
                            _text(
                                0.988,
                                lab_y,
                                label,
                                color=color,
                                transform=ax.get_yaxis_transform(),
                                ha="right",
                                va="center",
                                bbox={**_layer_tag_box, "edgecolor": color},
                                size=float(_layer_tag_size),
                            )
                        except Exception:
                            pass
                _flush_smart_layer_pixel_gate(
                    ax, _smart_layer_pixel_queue, occupied_boxes
                )
    elif pack.get("broke") or pack.get("over"):
        # 2026-10-27：無下一層＝靜默，不准畫「暫無下一層大量區」佔位
        pass
    return ys
