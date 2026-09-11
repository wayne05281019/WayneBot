# -*- coding: utf-8 -*-
"""話筒一千角：二十個面 × 五十種鏡頭，名字不重複。"""
from __future__ import annotations

from phone_angles import (
    ANGLE_N,
    FEATURES,
    LENSES,
    build_angles,
    format_angles,
    summarize_angles,
)


def test_phone_angles_are_one_thousand_distinct():
    assert len(FEATURES) * len(LENSES) == ANGLE_N == 1000
    rows = build_angles()
    assert len(rows) == 1000
    names = [r["name"] for r in rows]
    assert len(set(names)) == 1000
    assert names[0] == f"{FEATURES[0]}/{LENSES[0]}"
    assert "飆大/對價" not in names
    assert any(n.startswith("精簡六顆/") for n in names)
    assert any(n.startswith("查股兩張圖/") for n in names)


def test_phone_angles_all_pass():
    rows = build_angles()
    s = summarize_angles(rows)
    assert s["n"] == 1000
    assert s["failed"] == 0, s["fail_names"][:12]
    text = format_angles(rows)
    assert f"{s['passed']}/{s['n']}" in text
    assert s["passed"] == 1000
