# -*- coding: utf-8 -*-
from scripts.decade_lab_wave8_dual import (
    _biaoke_bias,
    _iron_abc,
    _iron_motive,
    _judge_dir,
)


def test_biaoke_bias_mapping():
    assert _biaoke_bias("down_done", "A波低") == "up"
    assert _biaoke_bias("retest", "第五波測底") == "up"
    assert _biaoke_bias("down", "逃命波C-2") == "down"
    assert _biaoke_bias("up", "主升段") == "up"
    assert _biaoke_bias("side", "位階四") == "range"


def test_iron_and_judge():
    # 人工上漲 1-2-3-4-5 端點（L H L H L H）
    pts = [
        {"px": 100, "kind": "L"},
        {"px": 110, "kind": "H"},
        {"px": 105, "kind": "L"},
        {"px": 125, "kind": "H"},
        {"px": 115, "kind": "L"},
        {"px": 130, "kind": "H"},
    ]
    m = _iron_motive(pts)
    assert "lens" in m
    assert _judge_dir("up", "up") == "對"
    assert _judge_dir("up", "down") == "偏"
    assert _judge_dir("range", "up") == "觀望不計分"
    a = _iron_abc(pts[:4])
    assert "kind" in a
