# -*- coding: utf-8 -*-
"""1-4 重疊≠1-4 浪；費半對表不進海選。"""
from __future__ import annotations

from biaoke_archive import load_bundled_archive
from biaoke_brain import DISCLAIMER, answer_biaoke
from biaoke_sox import (
    OVERLAP_RE,
    claim_posts,
    follow_low,
    format_sox_html,
    is_overlap_text,
    is_sox_query,
    run_sox_14,
    summarize_sox,
)


def test_overlap_regex_skips_wave4_and_price():
    assert is_overlap_text("費城半導體已經確認 1 4重疊")
    assert is_overlap_text("費半、那斯達科指數早就　１４重疊")
    assert not is_overlap_text("回測1-4浪83.6")
    assert not is_overlap_text("今天是在回測114-114.5")
    assert not OVERLAP_RE.search("461-462")


def test_claim_posts_from_archive_only_real_overlap():
    blob = load_bundled_archive()
    rows = claim_posts(blob.get("posts") or [])
    ov = [r for r in rows if r.get("overlap")]
    assert ov
    dates = {r["date"] for r in ov}
    assert "2026-06-15" in dates
    assert "2025-05-09" in dates
    assert "2024-07-19" not in dates


def test_follow_low_and_html():
    ser = [(f"202606{i:02d}", 100 + i, 90 + i, 100 + i) for i in range(1, 28)]
    held = follow_low(ser, "2026-06-05", n=20)
    assert held["broke"] is False
    assert held["ret"] is not None
    brk_ser = list(ser)
    brk_ser[10] = (brk_ser[10][0], 80, 50, 70)
    broke = follow_low(brk_ser, "2026-06-05", n=20)
    assert broke["broke"] is True
    snap = summarize_sox(
        [{"overlap": True, "sox": True, "twii20": held, "sox20": held}]
    )
    html = format_sox_html(snap)
    assert "不是買訊" in html
    assert "不進海選" in html
    assert is_sox_query("費半 1-4 重疊")
    ans = answer_biaoke(":memory:", "1-4 重疊代表什麼")
    assert "這不是買訊" in ans
    assert DISCLAIMER.split("。")[0] in ans or "買訊" in ans


def test_run_sox_injected_bars():
    posts = [
        {
            "id": "1",
            "kind": "post",
            "date": "2026-06-15",
            "text": "週五的費城半導體指數已經確認 1 4重疊",
        }
    ]
    sox = [(f"202606{i:02d}", 7000, 6900, 6950) for i in range(1, 28)]
    snap = run_sox_14(posts, db_path="", sox_bars=sox)
    assert snap["n_overlap"] == 1
    assert snap["overlap_sox20"]["n"] == 1
    assert snap["overlap_sox20"]["hold"] == 100.0
