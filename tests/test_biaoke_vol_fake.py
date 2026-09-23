# -*- coding: utf-8 -*-
"""量假結構：官方柱重述他已講過的，不發明指標、不進海選。"""
from biaoke_field_scan import _stirring
from biaoke_mind import method_body, views_for_neuron
from biaoke_neurons import classify_spoken
from biaoke_vol_fake import classify_volume_fake, is_fake_stir
from biaoke_why import lookup


def _bars(last_h, last_l, last_c, last_v, n=25, base_v=100.0):
    rows = []
    for i in range(n - 1):
        rows.append((f"202609{i+1:02d}"[:8] if i < 9 else f"202609{i+1:02d}", 100.0, 90.0, 95.0, base_v))
    rows.append(("20260930", last_h, last_l, last_c, last_v))
    return rows


def test_dump_pause_hold_from_named_shapes():
    """金像電型長上影＝dump；協易機／鴻海型收在下半＝pause；收撐＝hold。"""
    dump = classify_volume_fake(_bars(120, 100, 108, 300))
    assert dump["kind"] == "dump"
    pause = classify_volume_fake(_bars(110, 90, 93, 300))
    assert pause["kind"] == "pause"
    hold = classify_volume_fake(_bars(110, 90, 108, 300))
    assert hold["kind"] == "hold"
    quiet = classify_volume_fake(_bars(110, 90, 108, 80))
    assert quiet["kind"] == "none"


def test_wash_break_then_stand_back():
    rows = []
    for i in range(12):
        rows.append((f"d{i:02d}", 100.0, 90.0, 95.0, 100.0))
    rows.append(("brk", 92.0, 80.0, 82.0, 250.0))
    rows.append(("back", 98.0, 88.0, 94.0, 120.0))
    got = classify_volume_fake(rows)
    assert got["kind"] == "wash"


def test_fake_volume_not_stirring_for_dongzhu():
    st = {
        "vs20": -2.0,
        "vs60": -12.0,
        "volr": 2.0,
        "broke": False,
        "vol_fake": "dump",
    }
    assert is_fake_stir(st)
    assert _stirring(st) is False
    st["vol_fake"] = "none"
    assert _stirring(st) is True


def test_quote_files_to_tape_neuron():
    hits = classify_spoken(
        "懂量假結構，久了就自然會將穩定性差的技術指標拿掉，而且K棒更清楚，"
        "慢慢就會發現隱藏的主力意圖的細節"
    )
    assert any(h["neuron"] == "tape" for h in hits)


def test_mind_and_why_carry_sep23_quote():
    body = method_body("量先價行")
    assert "量假結構" in body
    assert "主力意圖" in body
    assert "協易機" in body or "鴻海" in body
    wash = method_body("洗盤還是出貨")
    assert "量假結構" in wash
    five = method_body("真正有用的五件")
    assert "量假結構" in five
    tape = views_for_neuron("tape")
    assert any("量假結構" in b for _t, b in tape)
    why = lookup("量假結構是什麼")
    assert "16:50" in why
    assert "不進海選" in why
    assert "黃金買點" in why
