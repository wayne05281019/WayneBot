# -*- coding: utf-8 -*-
"""三尺時間：早報／查股藍▲／剛脫離零為何可不一致。

公式同源 leave_zero；時間尺＋流動性閘不同。不准改黃金買點／leave_zero 公式。
話筒氣泡約 18 全形字寬；能一行就一行。
"""
from __future__ import annotations

from typing import List, Sequence

# 短行（各 ≤18 全形）——三處話筒同一套，偉權／哥哥功能全同
SANCHI_LINE_MORNING = "早報＝昨收掃描＋量≥1000張。"
SANCHI_LINE_LOOKUP = "查股藍▲＝現在查（可含盤中）。"
SANCHI_LINE_LEAVE_ZERO = "剛脫離零＝全市場雷達。"
SANCHI_LINE_WHY = "三尺不同，圖有箭≠早報必有。"

SANCHI_LINES: Sequence[str] = (
    SANCHI_LINE_MORNING,
    SANCHI_LINE_LOOKUP,
    SANCHI_LINE_LEAVE_ZERO,
    SANCHI_LINE_WHY,
)


def sanchi_note_lines(*, plain: bool = False) -> List[str]:
    """完整三尺說明（短行列表）。plain=True 不加 HTML。"""
    del plain
    return [str(x) for x in SANCHI_LINES]


def sanchi_note_html() -> str:
    """早報頭／剛脫離零副標用：斜體短行。"""
    from html import escape as html_escape

    return "\n".join(f"<i>{html_escape(x)}</i>" for x in SANCHI_LINES)


def sanchi_note_plain() -> str:
    """圖說／純文字：換行短句。"""
    return "\n".join(SANCHI_LINES)


def sanchi_lookup_buy_arrow_lines() -> List[str]:
    """查股有藍▲紅框時附上：強調現在查可含盤中＋為何早報可不列。"""
    return [
        SANCHI_LINE_LOOKUP,
        SANCHI_LINE_MORNING,
        SANCHI_LINE_WHY,
    ]


def card_lights_buy_arrow(card: dict | None) -> bool:
    """高低卡／大量區會畫買點藍▲紅框時為 True（不是紅箭頭買訊）。"""
    if not isinstance(card, dict):
        return False
    verdict = str(card.get("buy_verdict") or "").strip().lower()
    stage = str(card.get("entry_stage") or "").strip().lower()
    rel = str(card.get("relative_buy_kind") or "").strip().lower()
    if stage == "watch":
        return False
    if verdict in ("watch", "no"):
        return False
    if verdict == "buy":
        return True
    if rel == "just_left":
        return True
    return False


def append_sanchi_to_caption(caption: str, card: dict | None) -> str:
    """查股圖說：有藍▲才附三尺短句，避免每檔都塞。"""
    cap = str(caption or "").strip()
    if not card_lights_buy_arrow(card):
        return cap
    note = "\n".join(sanchi_lookup_buy_arrow_lines())
    if not note:
        return cap
    if note in cap:
        return cap
    return f"{cap}\n{note}" if cap else note
