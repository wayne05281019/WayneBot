# -*- coding: utf-8 -*-
"""洞燭／飆大佔比走中性 sector_flow，海選不直接 import biaoke_*。"""
import inspect

import dongzhu_screen
import sector_flow


def test_dongzhu_screen_imports_sector_flow():
    src = inspect.getsource(dongzhu_screen)
    assert "sector_flow" in src
    assert "biaoke_field_scan" not in src


def test_sector_flow_reexports_rotation():
    assert callable(sector_flow.rotation_screen_block)
    assert callable(sector_flow.format_share_cross)
    assert callable(sector_flow.want_share_cross)
