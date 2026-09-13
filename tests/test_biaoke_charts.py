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

    gs = pick_charts("6442", limit=4, public_only=True)
    assert any("47b69e0f-de57-44d9-a9ec-4e809202ca13" in str(r.get("url") or "") for r in gs)
    assert any("b0b38f9c-6ac5-4260-8f9d-0206f1167367" in str(r.get("url") or "") for r in gs)
    assert any("a23ff8ba-c9f6-4086-89a8-b4b7e2d68168" in str(r.get("url") or "") for r in gs)
    assert any("d6a36765-2022-4e9e-a780-29c96479a294" in str(r.get("url") or "") for r in gs)
    assert any(
        "盤中走勢" in str(r.get("note") or "") and "不是日K" in str(r.get("note") or "")
        for r in gs
    )
    assert any("整理半年" in str(r.get("note") or "") for r in gs)
    qb = pick_charts("6147", limit=3, public_only=True)
    assert any("925ae6d3-392a-4e43-8cf7-6ef7c03a7406" in str(r.get("url") or "") for r in qb)
    assert any("頎邦盤中走勢" in str(r.get("note") or "") for r in qb)
    qt = pick_charts("2382", limit=7, public_only=True)
    assert any("9a56b8cc-9e24-4397-a5cb-68d6df19c5a5" in str(r.get("url") or "") for r in qt)
    assert any("c3095408-726b-4dde-b71f-7cebd42ae8b5" in str(r.get("url") or "") for r in qt)
    assert any("d9ca1bdc-42f3-444b-87fc-6852e905a126" in str(r.get("url") or "") for r in qt)
    assert any("26d9c950-b806-47d5-959b-7cd66855e460" in str(r.get("url") or "") for r in qt)
    assert any("821625f8-5d5f-426d-8a50-6f5c953706bc" in str(r.get("url") or "") for r in qt)
    assert any("廣達盤中走勢" in str(r.get("note") or "") and "不是日K" in str(r.get("note") or "") for r in qt)
    assert any("不是鴻海日K" in str(r.get("note") or "") for r in qt)
    assert any("下星期上半週" in str(r.get("note") or "") for r in qt)
    en = pick_charts("6414", limit=7, public_only=True)
    assert any("3e6b15a5-a550-4e9e-a9ea-9d4e20405a82" in str(r.get("url") or "") for r in en)
    assert any("3d8bf14c-9c2f-4feb-ac93-8c56755b79af" in str(r.get("url") or "") for r in en)
    assert any("d841fc6b-6dbd-47cc-9b2e-d6c1bf900da8" in str(r.get("url") or "") for r in en)
    assert any("df0553e6-4348-4cd8-ab64-09a179b9d6e1" in str(r.get("url") or "") for r in en)
    assert any("ead7aa97-2233-4df3-a6d2-4016a6b6fb01" in str(r.get("url") or "") for r in en)
    assert any("5e0d0c26-161f-4a5b-946f-94c6ca086382" in str(r.get("url") or "") for r in en)
    assert any("0f2edc9a-0fb0-460c-b4e2-0deb3042b5f9" in str(r.get("url") or "") for r in en)
    assert any("樺漢盤中走勢" in str(r.get("note") or "") for r in en)
    assert any("必過400" in str(r.get("note") or "") and "不是周K" in str(r.get("note") or "") for r in en)
    assert any("長下引線" in str(r.get("note") or "") for r in en)
    hon = pick_charts("2317", limit=5, public_only=True)
    assert not any("3e6b15a5-a550-4e9e-a9ea-9d4e20405a82" in str(r.get("url") or "") for r in hon)
    assert not any("ead7aa97-2233-4df3-a6d2-4016a6b6fb01" in str(r.get("url") or "") for r in hon)
    assert not any("d9ca1bdc-42f3-444b-87fc-6852e905a126" in str(r.get("url") or "") for r in hon)
    assert not any("26d9c950-b806-47d5-959b-7cd66855e460" in str(r.get("url") or "") for r in hon)
    food = pick_charts("1231", limit=5, public_only=True)
    assert not any("d841fc6b-6dbd-47cc-9b2e-d6c1bf900da8" in str(r.get("url") or "") for r in food)


@pytest.mark.production_db
def test_2383_redbox_matches_official_day():
    from tests.conftest import require_production_db
    from biaoke_charts import format_charts_vs_official

    db = require_production_db()
    text = format_charts_vs_official("2383", db, hold=False, limit=3)
    assert "1265" in text
    assert "1275" in text
    assert "官方收1275" in text
