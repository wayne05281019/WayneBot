# -*- coding: utf-8 -*-
"""海選大盤狀況末段的細項輪動說明。

海選／籌碼主功能不准 import biaoke_* overlay。佔比走中性
sector_flow（洞燭／飆大共用讀），這裡只轉口，語料不進海選桶。
"""
from __future__ import annotations

from typing import Optional


def rotation_screen_block(db_path: str, *, spoken: Optional[str] = None) -> str:
    from sector_flow import rotation_screen_block as _block

    return _block(db_path, spoken=spoken)
