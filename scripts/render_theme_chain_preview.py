#!/usr/bin/env python3
"""本機預覽：主題鏈「加層、不換底」樣張（HTML→PNG）。不上話筒。"""
from __future__ import annotations

import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from theme_chain_preview import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
