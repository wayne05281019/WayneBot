# -*- coding: utf-8 -*-
"""產業／細項法人買超佔比：洞燭與飆大共用讀取層。

按鈕功能仍分開（洞燭鈕／飆大對話／海選大盤末段說明）。
演算實作目前在 biaoke_field_scan；這裡當中性入口，海選主桶不准
直接 import biaoke_* overlay，改走本模組或 dongzhu_screen。
語料不進海選桶、不改黃金買點。
"""
from __future__ import annotations

from typing import Any, Optional


def rotation_screen_block(db_path: str, *, spoken: Optional[str] = None) -> str:
    from biaoke_field_scan import rotation_screen_block as _block

    return _block(db_path, spoken=spoken)


def format_share_cross(db_path: str) -> str:
    from biaoke_field_scan import format_share_cross as _fmt

    return _fmt(db_path)


def want_share_cross(ask: str) -> bool:
    from biaoke_field_scan import want_share_cross as _want

    return bool(_want(ask))


def refresh_dongzhu_judgment(db_path: str, cap: str = "") -> Any:
    """盤後洞燭走查。給融合排程；失敗由呼叫端處理。"""
    import os
    import sys

    root = os.path.dirname(os.path.abspath(__file__))
    scripts = os.path.join(root, "scripts")
    for p in (root, scripts):
        if p not in sys.path:
            sys.path.insert(0, p)
    from dongzhu_precursor import refresh_dongzhu_judgment as _run

    return _run(db_path, cap)
