# -*- coding: utf-8 -*-
"""smoke／render／slow 分類自測（本身必須落在 smoke 桶）。"""
from __future__ import annotations

from smoke_classify import is_render_module, is_slow_module, smoke_bucket


def test_py311_syntax_stays_smoke():
    assert smoke_bucket("test_render_py311_syntax") == "smoke"
    assert not is_render_module("test_render_py311_syntax")


def test_png_and_market_are_render():
    assert is_render_module("test_png_layout")
    assert is_render_module("test_market_teach_trio")
    assert is_render_module("test_vol_zone_chart")
    assert smoke_bucket("test_biaoke_chart") == "render"


def test_stress_and_biaoke_are_slow():
    assert is_slow_module("test_two_user_long_stress")
    assert is_slow_module("test_full_spectrum_300")
    assert is_slow_module("test_biaoke_ingest")
    assert is_slow_module("test_decade_lab_hsiao_lab")
    assert smoke_bucket("test_market_menu_e2e") in {"render", "slow"}


def test_core_unit_is_smoke():
    assert smoke_bucket("test_bot_menu") == "smoke"
    assert smoke_bucket("test_tw_holidays") == "smoke"
    assert smoke_bucket("test_db_migrations") == "smoke"
    assert smoke_bucket("test_smoke_classify") == "smoke"
