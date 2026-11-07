# -*- coding: utf-8 -*-
"""查股五張圖實驗室記號旗標（預設全關；過閘 JSON 才准開）。

意圖記號（尚未上話筒）：
- LAB_BUY_W3_START／均衡核：起漲買
- REL_HIGH_SELL：相對高點賣（20高／浪頂）

硬規則：不准改 leave_zero 公式；phone_sync 預設 blocked。
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

PHONE_SYNC = "blocked"
NOT_BUY_SIGNAL = True

# 總開關：預設 False。唯有明確 True 且 gate JSON promote 才准畫新記號。
LOOKUP_LAB_MARKS_ENABLED = False

GATE_JSON_CANDIDATES = (
    Path("/opt/cursor/artifacts/phone_curriculum_merged_decision.json"),
    Path("docs/expert_notes/飆客/decade_lab/phone_curriculum_merged_decision.json"),
    Path("/opt/cursor/artifacts/hsiao_promote_lookup_decision.json"),
)


def _read_gate() -> Dict[str, Any]:
    for p in GATE_JSON_CANDIDATES:
        try:
            if p.is_file():
                import json

                return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            continue
    return {}


def lab_marks_allowed() -> bool:
    """生產路徑呼叫：預設永不開。"""
    if not LOOKUP_LAB_MARKS_ENABLED:
        return False
    if PHONE_SYNC != "allowed":
        return False
    gate = _read_gate()
    return bool(gate.get("promote_to_lookup_display") is True)


def paint_lab_buy_indices(*_a, **_k):
    """Stub：過閘前 no-op。掛鉤點見 phone_lookup_mark_hook_map.md。"""
    if not lab_marks_allowed():
        return []
    return []


def paint_lab_sell_indices(*_a, **_k):
    """Stub：過閘前 no-op。"""
    if not lab_marks_allowed():
        return []
    return []


__all__ = [
    "PHONE_SYNC",
    "NOT_BUY_SIGNAL",
    "LOOKUP_LAB_MARKS_ENABLED",
    "lab_marks_allowed",
    "paint_lab_buy_indices",
    "paint_lab_sell_indices",
]
