# -*- coding: utf-8 -*-
"""盤後官方收齊後重跑洞燭走查。海選不准 import biaoke_*；這裡只給融合排程用。"""
from __future__ import annotations

from typing import Any, Dict


def refresh_dongzhu_judgment(db_path: str, cap: str = "") -> Dict[str, Any]:
    from sector_flow import refresh_dongzhu_judgment as _run

    return _run(db_path, cap)
