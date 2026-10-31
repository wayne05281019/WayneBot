#!/usr/bin/env python3
"""本機預覽入口：轉呼叫正式模組 ``intraday_open_close_chart``（v20 臉）。

查股第 5 張正式路徑走 ``render_lookup_intraday_result``；此腳本只給本機試渲。
"""
from __future__ import annotations

import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from intraday_open_close_chart import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
