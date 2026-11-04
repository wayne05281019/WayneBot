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
    assert _biaoke_bias("up", "末升段") == "down"  # 末端→預期修正
    assert _biaoke_bias("up", "邪惡第五波") == "down"
    assert _biaoke_bias("side", "位階四") == "range"


def test_iron_and_judge():
    from scripts.decade_lab_wave8_dual import _phase_from_pivots

    # 人工上漲 1-2-3-4-5（最長／次長 ≥1.618）
    pts = [
        {"px": 100, "kind": "L"},
        {"px": 110, "kind": "H"},  # w1=10
        {"px": 105, "kind": "L"},  # w2=5
        {"px": 145, "kind": "H"},  # w3=40（≥1.618×w5）
        {"px": 130, "kind": "L"},  # w4=15；不重疊 w1[100,110]
        {"px": 150, "kind": "H"},  # w5=20
    ]
    m = _iron_motive(pts)
    assert "lens" in m
    assert m.get("ok") and m.get("ext_pass")
    # 凑滿推進＝預期反向進修正（不上漲續抱）
    ph = _phase_from_pivots(pts)
    assert ph["phase"] == "impulse_12345"
    assert ph["bias"] == "down"
    assert _judge_dir("up", "up") == "對"
    assert _judge_dir("up", "down") == "偏"
    assert _judge_dir("range", "up") == "觀望不計分"
    a = _iron_abc(pts[:4])
    assert "kind" in a
