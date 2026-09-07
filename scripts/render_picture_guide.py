#!/usr/bin/env python3
"""本機把圖文說明 9 頁渲出來，方便對排版。"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from picture_guide import render_picture_guide  # noqa: E402


def main() -> int:
    dest = sys.argv[1] if len(sys.argv) > 1 else None
    paths = render_picture_guide(dest, force=True)
    for p in paths:
        print(p, os.path.getsize(p))
    print("n", len(paths))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
