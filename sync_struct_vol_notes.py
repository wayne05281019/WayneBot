# -*- coding: utf-8 -*-
"""SYNC-STRUCT-VOL｜查股結構圖／大量撐壓圖註（輔助層・可開關・非買訊）。

浪則卡對應：
- ``WR-OPS-EFF-PIERCE`` 有效穿刺
- ``WR-OPS-FAKE-BREAK`` 假跌破
- ``WR-OPS-PRESS-TO-SUPPORT`` 壓轉撐
- ``WR-VOL-NO-STABILIZE`` 無量下跌≠止穩／沒爆量＝沒換籌碼

三鍋分標：他說／官方／試標推論。不准改黃金買點／leave_zero。
有他點名位才疊他位；沒有就不畫他價線。
"""
from __future__ import annotations

import os
from typing import Any, Dict, List, Mapping, MutableMapping, Optional, Sequence, Tuple

PHONE_WARNING_FIXED = "試標・推論／非他原文・非買訊・對質未過閘"

# 總開關：預設關（輔助層可開）；``WAYNE_STRUCT_VOL_NOTES=1`` 或 card 開。
# card["struct_vol_notes"]=True 強制開；False 強制關。
ENV_KEY = "WAYNE_STRUCT_VOL_NOTES"

RULE_EFF_PIERCE = "WR-OPS-EFF-PIERCE"
RULE_FAKE_BREAK = "WR-OPS-FAKE-BREAK"
RULE_PRESS_TO_SUP = "WR-OPS-PRESS-TO-SUPPORT"
RULE_VOL_NO_STAB = "WR-VOL-NO-STABILIZE"

POT_HIS = "他說"
POT_OFFICIAL = "官方"
POT_TRIAL = "試標推論"


def notes_enabled(card: Optional[Mapping[str, Any]] = None) -> bool:
    """可開關：環境變數＋card 覆寫。"""
    if isinstance(card, Mapping) and "struct_vol_notes" in card:
        return bool(card.get("struct_vol_notes"))
    raw = str(os.environ.get(ENV_KEY, "0") or "0").strip().lower()
    return raw in ("1", "true", "yes", "on")


def _px(val: Any) -> float:
    try:
        f = float(val)
    except (TypeError, ValueError):
        return 0.0
    if f != f:  # NaN
        return 0.0
    return f


def _ymd(raw: Any) -> str:
    s = str(raw or "").replace("-", "")[:8]
    return s if len(s) == 8 and s.isdigit() else ""


def _bar(row: Mapping[str, Any]) -> Dict[str, float]:
    return {
        "o": _px(row.get("open") or row.get("o")),
        "h": _px(row.get("high") or row.get("h")),
        "l": _px(row.get("low") or row.get("l")),
        "c": _px(row.get("close") or row.get("c")),
        "v": _px(row.get("volume") or row.get("v")),
    }


def _closes_beyond(
    bars: Sequence[Mapping[str, float]],
    level: float,
    *,
    side: str,
    n: int = 2,
) -> bool:
    """有效穿刺／有效突破：近 n 根收盤連續在位的同側。"""
    if level <= 0 or len(bars) < n:
        return False
    window = list(bars)[-n:]
    if side == "below":
        return all(_px(b.get("c")) < level for b in window)
    if side == "above":
        return all(_px(b.get("c")) > level for b in window)
    return False


def _fake_breakdown_candidate(
    bars: Sequence[Mapping[str, float]],
    floor: float,
) -> bool:
    """假跌破候選：近窗影線戳破 floor，最新收回到 floor 上方。"""
    if floor <= 0 or len(bars) < 2:
        return False
    last = bars[-1]
    pierced = any(_px(b.get("l")) < floor for b in list(bars)[-3:])
    return bool(pierced and _px(last.get("c")) > floor)


def _press_to_support(
    bars: Sequence[Mapping[str, float]],
    press: float,
) -> bool:
    """壓轉撐：他／區的第一道壓，近 2 收站穩其上。"""
    if press <= 0 or len(bars) < 3:
        return False
    if not _closes_beyond(bars, press, side="above", n=2):
        return False
    # 轉撐前近窗曾在壓下（收或高觸壓）
    prior = list(bars)[:-2]
    touched_under = any(
        _px(b.get("c")) <= press or _px(b.get("h")) >= press * 0.997
        for b in prior[-8:]
    )
    return bool(touched_under)


def _vol_dry_decline(
    bars: Sequence[Mapping[str, float]],
    *,
    thin_ratio: float = 0.55,
) -> bool:
    """綠跌＋量縮 → 無量下跌≠止穩。"""
    if len(bars) < 6:
        return False
    last = bars[-1]
    prev = bars[-2]
    c0, c1 = _px(last.get("c")), _px(prev.get("c"))
    v0 = _px(last.get("v"))
    if c0 <= 0 or c1 <= 0 or v0 <= 0 or c0 >= c1:
        return False
    vols = [_px(b.get("v")) for b in list(bars)[-21:-1] if _px(b.get("v")) > 0]
    if len(vols) < 5:
        return False
    med = sorted(vols)[len(vols) // 2]
    return bool(med > 0 and v0 < med * thin_ratio)


def _broke_low_no_spike(
    bars: Sequence[Mapping[str, float]],
    floor: float,
    *,
    spike_mult: float = 1.8,
) -> bool:
    """破前低但量沒放＝沒爆量＝沒換籌碼。"""
    if floor <= 0 or len(bars) < 8:
        return False
    last = bars[-1]
    if not (_px(last.get("l")) < floor or _px(last.get("c")) < floor):
        return False
    vols = [_px(b.get("v")) for b in list(bars)[-21:-1] if _px(b.get("v")) > 0]
    if len(vols) < 5:
        return False
    med = sorted(vols)[len(vols) // 2]
    v0 = _px(last.get("v"))
    return bool(med > 0 and v0 < med * spike_mult)


def extract_his_named_levels(
    card: Optional[Mapping[str, Any]] = None,
    *,
    levels: Optional[Sequence[Mapping[str, Any]]] = None,
) -> List[Dict[str, Any]]:
    """只收他點名位。空＝不疊他價。試標位可收但必須標試標鍋。"""
    raw: List[Any] = []
    if levels:
        raw.extend(list(levels))
    if isinstance(card, Mapping):
        for key in ("his_named_levels", "biaoke_named_levels", "oral_levels"):
            blob = card.get(key)
            if isinstance(blob, (list, tuple)):
                raw.extend(list(blob))
    out: List[Dict[str, Any]] = []
    seen = set()
    for item in raw:
        if not isinstance(item, Mapping):
            continue
        price = _px(item.get("price") or item.get("level") or item.get("value"))
        if price <= 0:
            continue
        pot_raw = str(
            item.get("pot") or item.get("source_kind") or item.get("pot_his") or ""
        ).strip()
        flagged_his = bool(
            item.get("his")
            or item.get("oral")
            or str(item.get("kind") or "") in ("his", "oral", "biaoke")
        )
        if pot_raw in ("his_words", "他說", "oral", "biaoke"):
            pot = POT_HIS
        elif pot_raw in ("他圖",):
            pot = "他圖"
        elif pot_raw in ("trial_infer", "試標", "試標推論", "infer"):
            pot = POT_TRIAL
        elif flagged_his:
            pot = POT_HIS
        else:
            # 沒他點名／沒試標標籤＝略過（不准發明價）
            continue
        key = round(price, 4)
        if key in seen:
            continue
        seen.add(key)
        label = str(item.get("label") or item.get("tag") or item.get("name") or "").strip()
        out.append(
            {
                "price": price,
                "label": label or f"{price:g}",
                "pot": pot,
                "rule_id": str(item.get("rule_id") or ""),
            }
        )
    return out


def detect_struct_vol_notes(
    bars: Sequence[Mapping[str, Any]],
    *,
    press: float = 0.0,
    hold: float = 0.0,
    his_levels: Optional[Sequence[Mapping[str, Any]]] = None,
    card: Optional[Mapping[str, Any]] = None,
) -> List[Dict[str, Any]]:
    """從官方柱＋位偵測可標註記（非買訊）。回 list of note dict。"""
    if not notes_enabled(card):
        return []
    rows = [_bar(r) for r in bars or ()]
    rows = [r for r in rows if r["c"] > 0 and r["h"] > 0]
    if len(rows) < 3:
        return []

    notes: List[Dict[str, Any]] = []
    his = extract_his_named_levels(card, levels=his_levels)

    # 參考位：他點名優先；否則大量區／結構壓撐（官方層）
    floors: List[Tuple[float, str, str]] = []
    presses: List[Tuple[float, str, str]] = []
    for lv in his:
        p = float(lv["price"])
        lab = str(lv.get("label") or "")
        pot = str(lv.get("pot") or POT_HIS)
        # 他位可當壓或撐候選；偵測時兩邊都試
        floors.append((p, lab, pot))
        presses.append((p, lab, pot))
    if hold > 0:
        floors.append((float(hold), "撐", POT_OFFICIAL))
    if press > 0:
        presses.append((float(press), "壓", POT_OFFICIAL))

    # 假跌破／有效穿刺（對 floor）
    for floor, lab, pot in floors:
        if _fake_breakdown_candidate(rows, floor):
            notes.append(
                {
                    "kind": "fake_breakdown",
                    "rule_id": RULE_FAKE_BREAK,
                    "label_zh": "假跌破",
                    "text_zh": f"假跌破候選・{lab or f'{floor:g}'}（戳破後收回）",
                    "level": floor,
                    "pot": pot if pot != POT_OFFICIAL else POT_TRIAL,
                    "buy_signal": False,
                }
            )
        elif _closes_beyond(rows, floor, side="below", n=2):
            notes.append(
                {
                    "kind": "eff_pierce_down",
                    "rule_id": RULE_EFF_PIERCE,
                    "label_zh": "有效穿刺",
                    "text_zh": f"有效穿刺（連2收破）・{lab or f'{floor:g}'}",
                    "level": floor,
                    "pot": pot if pot != POT_OFFICIAL else POT_TRIAL,
                    "buy_signal": False,
                }
            )
        elif any(_px(b.get("l")) < floor <= _px(b.get("h")) for b in rows[-2:]):
            notes.append(
                {
                    "kind": "pierce_touch",
                    "rule_id": RULE_EFF_PIERCE,
                    "label_zh": "觸及未確認",
                    "text_zh": f"碰到{lab or f'{floor:g}'}・未確認有效穿刺",
                    "level": floor,
                    "pot": pot if pot != POT_OFFICIAL else POT_TRIAL,
                    "buy_signal": False,
                }
            )

    # 壓轉撐／向上有效穿刺
    for pr, lab, pot in presses:
        if _press_to_support(rows, pr):
            notes.append(
                {
                    "kind": "resist_to_support",
                    "rule_id": RULE_PRESS_TO_SUP,
                    "label_zh": "壓轉撐",
                    "text_zh": f"壓轉撐・{lab or f'{pr:g}'}（連2收站上）",
                    "level": pr,
                    "pot": pot if pot != POT_OFFICIAL else POT_TRIAL,
                    "buy_signal": False,
                }
            )
        elif _closes_beyond(rows, pr, side="above", n=2) and not any(
            n.get("kind") == "resist_to_support" and abs(n.get("level", 0) - pr) < 1e-9
            for n in notes
        ):
            notes.append(
                {
                    "kind": "eff_pierce_up",
                    "rule_id": RULE_EFF_PIERCE,
                    "label_zh": "有效穿刺",
                    "text_zh": f"有效穿刺（連2收過）・{lab or f'{pr:g}'}",
                    "level": pr,
                    "pot": pot if pot != POT_OFFICIAL else POT_TRIAL,
                    "buy_signal": False,
                }
            )

    # 量價句
    if _vol_dry_decline(rows):
        notes.append(
            {
                "kind": "vol_dry_decline",
                "rule_id": RULE_VOL_NO_STAB,
                "label_zh": "無量≠止穩",
                "text_zh": "無量下跌≠止穩（綠跌＋量縮）",
                "level": 0.0,
                "pot": POT_TRIAL,
                "buy_signal": False,
            }
        )
    ref_floor = hold if hold > 0 else (floors[0][0] if floors else 0.0)
    if ref_floor > 0 and _broke_low_no_spike(rows, ref_floor):
        notes.append(
            {
                "kind": "no_chip_exchange",
                "rule_id": RULE_VOL_NO_STAB,
                "label_zh": "沒爆量",
                "text_zh": "沒爆量＝沒換籌碼（破低量未放）",
                "level": float(ref_floor),
                "pot": POT_TRIAL,
                "buy_signal": False,
            }
        )

    # 去重：同 kind+level 只留一條
    dedup: List[Dict[str, Any]] = []
    seen_k = set()
    for n in notes:
        key = (n.get("kind"), round(float(n.get("level") or 0), 4))
        if key in seen_k:
            continue
        seen_k.add(key)
        n["warning"] = PHONE_WARNING_FIXED
        n["buy_signal"] = False
        dedup.append(n)
    return dedup


def format_notes_caption(
    notes: Sequence[Mapping[str, Any]],
    *,
    max_lines: int = 4,
    with_warning: bool = True,
) -> str:
    """圖說旁註：一行一件；結尾固定警語。"""
    if not notes:
        return ""
    lines: List[str] = []
    for n in list(notes)[: max(1, int(max_lines))]:
        pot = str(n.get("pot") or POT_TRIAL)
        text = str(n.get("text_zh") or n.get("label_zh") or "").strip()
        if not text:
            continue
        lines.append(f"〔{pot}〕{text}")
    if not lines:
        return ""
    if with_warning:
        lines.append(PHONE_WARNING_FIXED)
    return "\n".join(lines)


def append_notes_to_caption(
    caption: str,
    notes: Sequence[Mapping[str, Any]],
    *,
    card: Optional[Mapping[str, Any]] = None,
) -> str:
    if not notes_enabled(card):
        return caption or ""
    block = format_notes_caption(notes)
    if not block:
        return caption or ""
    base = str(caption or "").rstrip()
    if not base:
        return block
    # 避免重複堆警語
    if PHONE_WARNING_FIXED in base and block.endswith(PHONE_WARNING_FIXED):
        block = "\n".join(block.splitlines()[:-1])
    if not block:
        return base
    return f"{base}\n{block}"


def _note_font(size: float = 8.0, weight: str = "bold"):
    try:
        from wayne_navigator import _fp

        return _fp(size, weight)
    except Exception:
        return None


def paint_his_named_levels(
    ax,
    levels: Sequence[Mapping[str, Any]],
    *,
    xmin: float = 0.0,
    xmax: Optional[float] = None,
) -> int:
    """有他點名位才畫水平虛線＋短標；空 list＝0。"""
    if ax is None or not levels:
        return 0
    n_drawn = 0
    x1 = float(xmax) if xmax is not None else None
    fp = _note_font(7.5, "bold")
    for lv in levels:
        price = _px(lv.get("price"))
        if price <= 0:
            continue
        pot = str(lv.get("pot") or POT_HIS)
        color = "#6a1b9a" if pot in (POT_HIS, "他圖") else "#546e7a"
        try:
            if x1 is None:
                ax.axhline(
                    price,
                    color=color,
                    linestyle=(0, (3.0, 2.2)),
                    linewidth=1.05,
                    alpha=0.78,
                    zorder=6,
                )
            else:
                ax.plot(
                    [float(xmin), float(x1)],
                    [price, price],
                    color=color,
                    linestyle=(0, (3.0, 2.2)),
                    linewidth=1.05,
                    alpha=0.78,
                    zorder=6,
                    solid_capstyle="butt",
                )
            lab = str(lv.get("label") or f"{price:g}").strip()
            tag = f"{pot}・{lab}"
            kw = {
                "ha": "right",
                "va": "bottom",
                "color": color,
                "zorder": 7,
                "clip_on": False,
            }
            if fp is not None:
                kw["fontproperties"] = fp
            else:
                kw["fontsize"] = 7.5
            ax.text(0.995, price, tag, transform=ax.get_yaxis_transform(), **kw)
            n_drawn += 1
        except Exception:
            continue
    return n_drawn


def paint_note_chips(
    ax,
    notes: Sequence[Mapping[str, Any]],
    *,
    max_chips: int = 4,
) -> int:
    """左上角小標註記（輔助層）；不壓 K 數字為優先。"""
    if ax is None or not notes:
        return 0
    drawn = 0
    y = 0.98
    fp = _note_font(8.0, "bold")
    colors = {
        "fake_breakdown": "#c62828",
        "eff_pierce_down": "#ad1457",
        "eff_pierce_up": "#2e7d32",
        "resist_to_support": "#1565c0",
        "pierce_touch": "#6d4c41",
        "vol_dry_decline": "#455a64",
        "no_chip_exchange": "#455a64",
    }
    for n in list(notes)[: max(1, int(max_chips))]:
        kind = str(n.get("kind") or "")
        lab = str(n.get("label_zh") or n.get("text_zh") or "").strip()
        if not lab:
            continue
        try:
            kw = {
                "transform": ax.transAxes,
                "ha": "left",
                "va": "top",
                "color": colors.get(kind, "#37474f"),
                "zorder": 12,
                "bbox": {
                    "boxstyle": "round,pad=0.18",
                    "facecolor": "#ffffff",
                    "edgecolor": colors.get(kind, "#90a4ae"),
                    "linewidth": 0.8,
                    "alpha": 0.88,
                },
            }
            if fp is not None:
                kw["fontproperties"] = fp
            else:
                kw["fontsize"] = 8.0
            ax.text(0.01, y, lab, **kw)
            y -= 0.045
            drawn += 1
        except Exception:
            continue
    return drawn


def maybe_paint_struct_vol_notes(
    ax,
    bars: Optional[Sequence[Mapping[str, Any]]] = None,
    xs: Optional[Sequence[float]] = None,
    *,
    press: float = 0.0,
    hold: float = 0.0,
    card: Optional[Mapping[str, Any]] = None,
    his_levels: Optional[Sequence[Mapping[str, Any]]] = None,
    chart_kind: str = "",
    notes: Optional[Sequence[Mapping[str, Any]]] = None,
) -> Dict[str, Any]:
    """結構／大量圖掛鉤：旗標關＝no-op。回摘要 dict。"""
    _ = (xs, chart_kind)
    out: Dict[str, Any] = {
        "enabled": False,
        "n_notes": 0,
        "n_his_levels": 0,
        "notes": [],
        "buy_signal": False,
        "warning": PHONE_WARNING_FIXED,
    }
    if not notes_enabled(card):
        return out
    out["enabled"] = True
    his = extract_his_named_levels(card, levels=his_levels)
    out["n_his_levels"] = len(his)
    detected = list(notes) if notes is not None else detect_struct_vol_notes(
        bars or (),
        press=press,
        hold=hold,
        his_levels=his,
        card=card,
    )
    out["notes"] = detected
    out["n_notes"] = len(detected)
    if ax is not None:
        if his:
            xmax = None
            try:
                if xs is not None and len(xs) > 0:
                    xmax = float(xs[-1])
                elif bars is not None and len(bars) > 0:
                    xmax = float(len(bars) - 1)
            except Exception:
                xmax = None
            paint_his_named_levels(ax, his, xmin=0.0, xmax=xmax)
        if detected:
            paint_note_chips(ax, detected)
    return out


def attach_notes_to_card(
    card: MutableMapping[str, Any],
    notes: Sequence[Mapping[str, Any]],
) -> MutableMapping[str, Any]:
    """掛到決策卡旁路欄；不准當買訊。"""
    card["struct_vol_notes_hit"] = list(notes or [])
    card["struct_vol_notes_warning"] = PHONE_WARNING_FIXED
    card["struct_vol_notes_buy_signal"] = False
    return card


def notes_fingerprint(card: Optional[Mapping[str, Any]] = None) -> Tuple[Any, ...]:
    """進 memo 鍵：開關／他位變了不准互蓋舊圖。"""
    on = int(bool(notes_enabled(card)))
    his = extract_his_named_levels(card)
    his_fp = tuple(
        (round(float(x.get("price") or 0), 4), str(x.get("label") or ""), str(x.get("pot") or ""))
        for x in his[:12]
    )
    return ("sync-struct-vol-v1", on, his_fp)


__all__ = [
    "PHONE_WARNING_FIXED",
    "ENV_KEY",
    "RULE_EFF_PIERCE",
    "RULE_FAKE_BREAK",
    "RULE_PRESS_TO_SUP",
    "RULE_VOL_NO_STAB",
    "notes_enabled",
    "extract_his_named_levels",
    "detect_struct_vol_notes",
    "format_notes_caption",
    "append_notes_to_caption",
    "paint_his_named_levels",
    "paint_note_chips",
    "maybe_paint_struct_vol_notes",
    "attach_notes_to_card",
    "notes_fingerprint",
]
