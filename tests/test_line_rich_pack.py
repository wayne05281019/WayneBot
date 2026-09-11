# -*- coding: utf-8 -*-
"""圖文包曾給 LINE 用；產品已拿掉傳 LINE，這裡只鎖不再走那條路。"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_line_rich_pack_not_wired_to_bot_or_http():
    bot = (ROOT / "bot_servers.py").read_text(encoding="utf-8")
    main = (ROOT / "main.py").read_text(encoding="utf-8")
    assert "from line_rich_pack import" not in bot
    assert "from line_rich_pack import" not in main
    assert "/line/rich" not in main
    assert "一鍵傳 LINE" not in bot
    assert not (ROOT / "line_hop.py").exists()
    assert not (ROOT / "line_rich_pack.py").exists()
