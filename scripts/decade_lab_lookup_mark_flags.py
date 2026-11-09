# -*- coding: utf-8 -*-
"""查股五張圖實驗室記號旗標（LAB-ONLY；預設全關）。

意圖記號（尚未上話筒、未過閘不准畫）：
- ``LAB_BUY_W3_START``：波浪起漲買（主 W3／均衡核）；glyph 預留，不發明 5／9
- ``REL_HIGH_SELL``：相對高點賣（首碰 20高／浪頂）；glyph 預留

硬規則：
- ``LOOKUP_LAB_MARKS_ENABLED=False`` 預設；生產路徑預設永不開
- ``phone_sync`` 維持 ``blocked``；過閘 JSON 才准 ``promote_to_lookup_display``
- 不准改 leave_zero 公式；不准把未確認浪號寫進話筒
- 掛鉤點見 ``docs/expert_notes/飆客/decade_lab/phone_lookup_mark_hook_map.md``
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

PHONE_SYNC = "blocked"
NOT_BUY_SIGNAL = True

# 總開關：預設 False。唯有明確 True **且** gate JSON promote 才准畫新記號。
LOOKUP_LAB_MARKS_ENABLED = False

# 意圖 glyph 名（文件／對質用；本模組不畫、不發明浪號）
LAB_BUY_W3_START = "LAB_BUY_W3_START"
REL_HIGH_SELL = "REL_HIGH_SELL"

ROOT = Path(__file__).resolve().parents[1]
DOC = ROOT / "docs" / "expert_notes" / "飆客" / "decade_lab"
ART = Path("/opt/cursor/artifacts")

GATE_JSON_CANDIDATES = (
    ART / "phone_curriculum_merged_decision.json",
    DOC / "phone_curriculum_merged_decision.json",
    ART / "hsiao_promote_lookup_decision.json",
    DOC / "hsiao_promote_lookup_decision.json",
    ART / "phone_lookup_mark_promote_gate.json",
    DOC / "phone_lookup_mark_promote_gate.json",
)


def _read_gate() -> Dict[str, Any]:
    for p in GATE_JSON_CANDIDATES:
        try:
            if p.is_file():
                data = json.loads(p.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    return data
        except Exception:
            continue
    return {}


def lab_marks_allowed() -> bool:
    """生產 paint 路徑呼叫：預設永不開。

    必須同時：
    1. ``LOOKUP_LAB_MARKS_ENABLED is True``（顯式打開）
    2. gate JSON ``promote_to_lookup_display is True``
    3. 模組／gate 的 ``phone_sync`` 不是 ``blocked``

    現況：``PHONE_SYNC=blocked`` + 旗標 False → 永遠 False。
    """
    if not LOOKUP_LAB_MARKS_ENABLED:
        return False
    gate = _read_gate()
    sync = str(gate.get("phone_sync") or PHONE_SYNC or "blocked").strip().lower()
    if sync == "blocked":
        return False
    return bool(gate.get("promote_to_lookup_display") is True)


def paint_lab_buy_indices(*_a, **_k) -> List[int]:
    """Stub：過閘前 no-op。回空 list，不改現況藍▲。"""
    if not lab_marks_allowed():
        return []
    return []


def paint_lab_sell_indices(*_a, **_k) -> List[int]:
    """Stub：過閘前 no-op。回空 list，不改現況橙▼／如何賣。"""
    if not lab_marks_allowed():
        return []
    return []


def maybe_paint_lab_lookup_marks(
    ax=None,
    work=None,
    xs: Optional[Sequence[float]] = None,
    *,
    chart_kind: str = "",
    card: Optional[dict] = None,
    **_kwargs,
) -> bool:
    """查股五張／導航共用延伸點：旗標關＝直接 False，不碰 axes。

    chart_kind 約定：``card`` / ``glance`` / ``nav`` / ``vol`` / ``struct`` / ``intraday``。
    過閘後才在此畫 ``LAB_BUY_W3_START``／``REL_HIGH_SELL``；現在永不畫。
    """
    if not lab_marks_allowed():
        return False
    # 未來：讀 paint_lab_buy_indices／paint_lab_sell_indices 再上 glyph
    _ = (ax, work, xs, chart_kind, card)
    return False


__all__ = [
    "PHONE_SYNC",
    "NOT_BUY_SIGNAL",
    "LOOKUP_LAB_MARKS_ENABLED",
    "LAB_BUY_W3_START",
    "REL_HIGH_SELL",
    "lab_marks_allowed",
    "paint_lab_buy_indices",
    "paint_lab_sell_indices",
    "maybe_paint_lab_lookup_marks",
]
