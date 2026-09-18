# -*- coding: utf-8 -*-
"""盤後官方收齊後重跑洞燭走查。海選不准 import biaoke_*；這裡只給融合排程用。"""
from __future__ import annotations

import os
import sys
from typing import Any, Dict


def refresh_dongzhu_judgment(db_path: str, cap: str = "") -> Dict[str, Any]:
    root = os.path.dirname(os.path.abspath(__file__))
    scripts = os.path.join(root, "scripts")
    for p in (root, scripts):
        if p not in sys.path:
            sys.path.insert(0, p)
    from dongzhu_precursor import refresh_dongzhu_judgment as _run

    return _run(db_path, cap)
