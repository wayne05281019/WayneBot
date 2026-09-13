# -*- coding: utf-8 -*-
"""附圖索引：341 張、三來源、頭像不算、F10 排名在、問 2383 有圖。"""
from __future__ import annotations

import pytest

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


def test_pick_charts_public_only_and_vs_official():
    from biaoke_charts import format_charts_vs_official, pick_charts

    rows = pick_charts("2383", limit=3, public_only=True)
    assert rows
    assert all(r.get("src") == "public1709" for r in rows)
    notes = " ".join(str(r.get("note") or "") for r in rows)
    assert "平台依賴" in notes
    assert "1265" in notes
    assert "漢唐" not in notes
    assert any("516b26b0-786e-494d-bf8f-1897b6f7dd7f" in str(r.get("url") or "") for r in rows)
    hold_rows = pick_charts("2383", limit=2, public_only=True, hold=True)
    assert hold_rows
    assert any("平台依賴" in str(r.get("note") or "") or "護城河" in str(r.get("note") or "") or "紅框" in str(r.get("note") or "") for r in hold_rows)
    text = format_charts_vs_official("2383", "", hold=False, limit=3)
    assert "他的附圖對官方日K" in text
    assert "不准編" in text
    assert pick_charts("0000") == []


def test_intraday_snip_notes_overlay_not_daily_k():
    from biaoke_charts import pick_charts

    gs = pick_charts("6442", limit=3, public_only=True)
    assert any("47b69e0f-de57-44d9-a9ec-4e809202ca13" in str(r.get("url") or "") for r in gs)
    assert any(
        "盤中走勢" in str(r.get("note") or "") and "不是日K" in str(r.get("note") or "")
        for r in gs
    )
    qb = pick_charts("6147", limit=3, public_only=True)
    assert any("925ae6d3-392a-4e43-8cf7-6ef7c03a7406" in str(r.get("url") or "") for r in qb)
    assert any("頎邦盤中走勢" in str(r.get("note") or "") for r in qb)


@pytest.mark.production_db
def test_2383_redbox_matches_official_day():
    from tests.conftest import require_production_db
    from biaoke_charts import format_charts_vs_official

    db = require_production_db()
    text = format_charts_vs_official("2383", db, hold=False, limit=3)
    assert "1265" in text
    assert "1275" in text
    assert "官方收1275" in text
