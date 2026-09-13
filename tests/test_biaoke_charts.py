# -*- coding: utf-8 -*-
"""附圖索引：341 張、三來源、頭像不算、F10 排名在、問 2383 有圖。"""
from __future__ import annotations

from biaoke_archive import load_bundled_archive, load_bundled_club
from biaoke_charts import (
    AVATAR_NEEDLE,
    build_chart_index,
    charts_for,
    extract_tickers,
    load_chart_index,
)


def test_avatar_never_indexed():
    blob = build_chart_index(
        [
            {
                "src": "public1709",
                "date": "2023-12-19",
                "aid": "1",
                "url": "https://image.cmoney.tw/profile/member/1725033600/51cbb11b-a890-422e-b84b-3c09e4b364b9.jpg",
                "kind": "other",
                "ocr": "頭像",
            }
        ]
    )
    assert blob["n"] == 0
    assert blob["charts"] == []


def test_extract_skips_years_keeps_known_f10():
    ids = extract_tickers(
        "2025 2383 1265",
        "台光電",
        url="https://image.cmoney.tw/attachment/post/1784217600/516b26b0-786e-494d-bf8f-1897b6f7dd7f.png",
        valid_ids=["2383", "2330", "2059", "3017", "2308", "6223", "6515", "2368", "8210", "3081", "2454", "7769"],
    )
    assert "2025" not in ids
    assert "1265" not in ids
    assert "2383" in ids
    assert "6223" in ids


def test_bundled_chart_index_has_341_three_sources_and_f10():
    blob = load_chart_index()
    charts = list(blob.get("charts") or [])
    assert int(blob.get("n") or 0) == 341
    assert len(charts) == 341
    srcs = {str(c.get("src") or "") for c in charts}
    assert "public1709" in srcs
    assert "club72" in srcs
    assert "club20" in srcs
    assert sum(1 for c in charts if c.get("src") == "public1709") == 327
    assert sum(1 for c in charts if c.get("src") == "club72") == 12
    assert sum(1 for c in charts if c.get("src") == "club20") == 2
    urls = [str(c.get("url") or "") for c in charts]
    assert all(AVATAR_NEEDLE not in u for u in urls)
    assert any("516b26b0-786e-494d-bf8f-1897b6f7dd7f" in u for u in urls)
    assert any("ocr" in c for c in charts) is False
    hit = charts_for("2383")
    assert hit
    assert any("516b26b0-786e-494d-bf8f-1897b6f7dd7f" in str(c.get("url") or "") for c in hit)
    assert charts_for("6223")
    assert not charts_for("0000")


def test_public_archive_has_fsv_and_club_stays_out():
    pub = load_bundled_archive()
    texts = " ".join(str(p.get("text") or "") for p in pub.get("posts") or [])
    assert "fsv.cmoney.tw/cmstatic" in texts
    assert AVATAR_NEEDLE not in texts
    club = load_bundled_club()
    club_texts = " ".join(str(p.get("text") or "") for p in club.get("posts") or [])
    assert "fsv.cmoney.tw/cmstatic" in club_texts
    assert int(club.get("n") or 0) >= 92
    assert club.get("club") is True
    pub_ids = {p["id"] for p in pub["posts"] if (p.get("kind") or "post") != "reply"}
    assert "171407503" not in pub_ids
    assert "171400455" not in pub_ids
