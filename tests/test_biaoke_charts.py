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
    pick_charts,
)


def assert_snip_owned(sid, snip, note_bits, not_sids):
    """歸屬＝charts_for 全表。排名會被新盤中圖挤掉，歸屬不會。"""
    bits = (note_bits,) if isinstance(note_bits, str) else tuple(note_bits or ())
    rows = charts_for(sid)
    hit = [r for r in rows if snip in str(r.get("url") or "")]
    assert hit
    note = str(hit[0].get("note") or "")
    for bit in bits:
        assert bit in note
    for other in not_sids:
        assert not any(snip in str(r.get("url") or "") for r in charts_for(other))
        assert not any(
            snip in str(r.get("url") or "")
            for r in pick_charts(other, limit=32, public_only=True)
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


def test_pick_charts_skips_chart_that_is_not_this_stock():
    from biaoke_charts import charts_for, pick_charts

    rows = pick_charts("2357", limit=8, public_only=True)
    blob = " ".join(str(r.get("note") or "") + str(r.get("url") or "") for r in rows)
    assert "圖不是華碩" not in blob
    assert "046492e4-cc55-460f-a081-5f1aa9a04bf7" not in blob
    assert any("華碩" in str(r.get("note") or "") for r in rows)
    owned = charts_for("2357")
    assert any("046492e4-cc55-460f-a081-5f1aa9a04bf7" in str(r.get("url") or "") for r in owned)
    tong = pick_charts("8011", limit=8, public_only=True)
    assert all("圖不是個股" not in str(r.get("note") or "") for r in tong)


def test_intraday_snip_notes_overlay_not_daily_k():
    from biaoke_charts import pick_charts

    gs = pick_charts("6442", limit=8, public_only=True)
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
    qt = charts_for("2382")
    assert any("9a56b8cc-9e24-4397-a5cb-68d6df19c5a5" in str(r.get("url") or "") for r in qt)
    assert any("c3095408-726b-4dde-b71f-7cebd42ae8b5" in str(r.get("url") or "") for r in qt)
    assert any("d9ca1bdc-42f3-444b-87fc-6852e905a126" in str(r.get("url") or "") for r in qt)
    assert any("26d9c950-b806-47d5-959b-7cd66855e460" in str(r.get("url") or "") for r in qt)
    assert any("821625f8-5d5f-426d-8a50-6f5c953706bc" in str(r.get("url") or "") for r in qt)
    assert any("b8455d0f-0bc8-42d9-838a-7a13256a54af" in str(r.get("url") or "") for r in qt)
    assert any("487f0e8b-4cbf-432e-a0c6-bb2d9e504eb4" in str(r.get("url") or "") for r in qt)
    assert any("a2ca173c-8a8e-4bb9-81bc-7277983f9a82" in str(r.get("url") or "") for r in qt)
    assert any("9749924c-a3e0-43b8-acd0-5db50dae7fe4" in str(r.get("url") or "") for r in qt)
    assert any("廣達盤中走勢" in str(r.get("note") or "") and "不是日K" in str(r.get("note") or "") for r in qt)
    assert any("不是鴻海日K" in str(r.get("note") or "") for r in qt)
    assert any("下星期上半週" in str(r.get("note") or "") for r in qt)
    assert any("多空分界" in str(r.get("note") or "") for r in qt)
    assert any("多方最低標準282" in str(r.get("note") or "") for r in qt)
    assert any("挑戰前高298" in str(r.get("note") or "") for r in qt)
    en = pick_charts("6414", limit=8, public_only=True)
    assert any("3e6b15a5-a550-4e9e-a9ea-9d4e20405a82" in str(r.get("url") or "") for r in en)
    assert any("3d8bf14c-9c2f-4feb-ac93-8c56755b79af" in str(r.get("url") or "") for r in en)
    assert any("d841fc6b-6dbd-47cc-9b2e-d6c1bf900da8" in str(r.get("url") or "") for r in en)
    assert any("df0553e6-4348-4cd8-ab64-09a179b9d6e1" in str(r.get("url") or "") for r in en)
    assert any("ead7aa97-2233-4df3-a6d2-4016a6b6fb01" in str(r.get("url") or "") for r in en)
    assert any("5e0d0c26-161f-4a5b-946f-94c6ca086382" in str(r.get("url") or "") for r in en)
    assert any("0f2edc9a-0fb0-460c-b4e2-0deb3042b5f9" in str(r.get("url") or "") for r in en)
    assert any("90440d1d-dfb5-4562-bd28-71be2bb2607c" in str(r.get("url") or "") for r in en)
    assert any("樺漢盤中走勢" in str(r.get("note") or "") for r in en)
    assert any("必過400" in str(r.get("note") or "") and "不是周K" in str(r.get("note") or "") for r in en)
    assert any("長下引線" in str(r.get("note") or "") for r in en)
    assert any("350守得住" in str(r.get("note") or "") or "回測365" in str(r.get("note") or "") for r in en)
    hon = pick_charts("2317", limit=5, public_only=True)
    assert not any("3e6b15a5-a550-4e9e-a9ea-9d4e20405a82" in str(r.get("url") or "") for r in hon)
    assert not any("ead7aa97-2233-4df3-a6d2-4016a6b6fb01" in str(r.get("url") or "") for r in hon)
    assert not any("d9ca1bdc-42f3-444b-87fc-6852e905a126" in str(r.get("url") or "") for r in hon)
    assert not any("26d9c950-b806-47d5-959b-7cd66855e460" in str(r.get("url") or "") for r in hon)
    food = pick_charts("1231", limit=5, public_only=True)
    assert not any("d841fc6b-6dbd-47cc-9b2e-d6c1bf900da8" in str(r.get("url") or "") for r in food)
    fd = pick_charts("3004", limit=4, public_only=True)
    assert any("195e7491-0a99-4b9d-aedd-a3815e9f84ee" in str(r.get("url") or "") for r in fd)
    assert any("959f8ed1-4de2-4852-8f41-986cc63ea4c4" in str(r.get("url") or "") for r in fd)
    assert any("豐達科盤中走勢" in str(r.get("note") or "") and "不是日K" in str(r.get("note") or "") for r in fd)
    assert any("114-114.5" in str(r.get("note") or "") for r in fd)
    iei = pick_charts("6117", limit=4, public_only=True)
    assert any("909aaff2-51bc-4393-8a6f-ca014f7ac88f" in str(r.get("url") or "") for r in iei)
    assert any("迎廣盤中走勢" in str(r.get("note") or "") and "不是日K" in str(r.get("note") or "") for r in iei)
    skip6416 = pick_charts("6416", limit=5, public_only=True)
    assert not any("909aaff2-51bc-4393-8a6f-ca014f7ac88f" in str(r.get("url") or "") for r in skip6416)
    assert_snip_owned(
        "2330",
        "e25bcfc1-8852-431b-b463-cf05f9577ab0",
        ("台積電盤中走勢", "不是日K"),
        ("6416", "5310"),
    )


def test_twentyseventh_pick_charts_thunder_chenming_not_jianding():
    from biaoke_charts import pick_charts

    tt = pick_charts("8033", limit=4, public_only=True)
    assert any("3129a0d0-1538-4578-8064-47897b3c3025" in str(r.get("url") or "") for r in tt)
    assert any("雷虎盤中走勢" in str(r.get("note") or "") and "不是日K" in str(r.get("note") or "") for r in tt)
    assert not any("7482636f-fcb7-478d-b199-84184302a5e5" in str(r.get("url") or "") for r in tt)
    cm = pick_charts("3013", limit=4, public_only=True)
    assert any("7482636f-fcb7-478d-b199-84184302a5e5" in str(r.get("url") or "") for r in cm)
    assert any("晟銘電盤中走勢" in str(r.get("note") or "") and "不是日K" in str(r.get("note") or "") for r in cm)
    assert not any("3129a0d0-1538-4578-8064-47897b3c3025" in str(r.get("url") or "") for r in cm)
    jd = pick_charts("3044", limit=5, public_only=True)
    assert not any("3129a0d0-1538-4578-8064-47897b3c3025" in str(r.get("url") or "") for r in jd)
    assert not any("7482636f-fcb7-478d-b199-84184302a5e5" in str(r.get("url") or "") for r in jd)
    skip6416 = pick_charts("6416", limit=5, public_only=True)
    assert not any("3129a0d0-1538-4578-8064-47897b3c3025" in str(r.get("url") or "") for r in skip6416)
    assert not any("7482636f-fcb7-478d-b199-84184302a5e5" in str(r.get("url") or "") for r in skip6416)


def test_twentyeighth_pick_charts_lasertek_not_5310():
    from biaoke_charts import pick_charts

    lk = pick_charts("6207", limit=8, public_only=True)
    assert any("a078f516-26c5-49f8-b7de-f7dfe14959cb" in str(r.get("url") or "") for r in lk)
    assert any("雷科盤中走勢" in str(r.get("note") or "") and "不是日K" in str(r.get("note") or "") for r in lk)
    zs = pick_charts("2467", limit=2, public_only=True)
    assert any("d1fb2f19-5bac-4d15-8d8b-5b30b9654f59" in str(r.get("url") or "") for r in zs)
    assert any("志聖盤中走勢" in str(r.get("note") or "") and "不是日K" in str(r.get("note") or "") for r in zs)
    jh = pick_charts("5443", limit=2, public_only=True)
    assert any("c81d96de-10f0-4de6-b971-45ddb33d511f" in str(r.get("url") or "") for r in jh)
    assert any("均豪盤中走勢" in str(r.get("note") or "") and "不是日K" in str(r.get("note") or "") for r in jh)
    skip5310 = pick_charts("5310", limit=5, public_only=True)
    assert not any("a078f516-26c5-49f8-b7de-f7dfe14959cb" in str(r.get("url") or "") for r in skip5310)
    assert not any("d1fb2f19-5bac-4d15-8d8b-5b30b9654f59" in str(r.get("url") or "") for r in skip5310)
    assert not any("c81d96de-10f0-4de6-b971-45ddb33d511f" in str(r.get("url") or "") for r in skip5310)
    skip6416 = pick_charts("6416", limit=5, public_only=True)
    assert not any("a078f516-26c5-49f8-b7de-f7dfe14959cb" in str(r.get("url") or "") for r in skip6416)


def test_twentyninth_pick_charts_iei_chenming_not_6416():
    from biaoke_charts import pick_charts

    y = pick_charts("6117", limit=4, public_only=True)
    assert any("40be401e-c52c-4114-8a9d-605cb5b37f21" in str(r.get("url") or "") for r in y)
    assert any("最佳上車" in str(r.get("note") or "") and "不是日K" in str(r.get("note") or "") for r in y)
    cm = pick_charts("3013", limit=4, public_only=True)
    assert any("6f617165-51b9-4396-b3b4-3d436947bea7" in str(r.get("url") or "") for r in cm)
    assert any("強勢反彈" in str(r.get("note") or "") and "不是日K" in str(r.get("note") or "") for r in cm)
    skip6416 = pick_charts("6416", limit=5, public_only=True)
    assert not any("40be401e-c52c-4114-8a9d-605cb5b37f21" in str(r.get("url") or "") for r in skip6416)
    assert not any("6f617165-51b9-4396-b3b4-3d436947bea7" in str(r.get("url") or "") for r in skip6416)


def test_thirtieth_pick_charts_compare_not_6416():
    from biaoke_charts import pick_charts

    y = pick_charts("6117", limit=5, public_only=True)
    assert any("3e28b3b3-ae1a-4ebc-9f27-404450609327" in str(r.get("url") or "") for r in y)
    assert any("波動更大" in str(r.get("note") or "") and "不是日K" in str(r.get("note") or "") for r in y)
    cm = pick_charts("3013", limit=4, public_only=True)
    assert any("8760c259-e431-4c9a-99cc-8d1061413ad2" in str(r.get("url") or "") for r in cm)
    assert any("比較強" in str(r.get("note") or "") and "不是日K" in str(r.get("note") or "") for r in cm)
    skip6416 = pick_charts("6416", limit=5, public_only=True)
    assert not any("3e28b3b3-ae1a-4ebc-9f27-404450609327" in str(r.get("url") or "") for r in skip6416)
    assert not any("8760c259-e431-4c9a-99cc-8d1061413ad2" in str(r.get("url") or "") for r in skip6416)


def test_thirtyfirst_pick_charts_ma5_not_6416():
    from biaoke_charts import pick_charts

    y = pick_charts("6117", limit=5, public_only=True)
    assert any("886911b5-d689-4033-b8f3-a9b2d0cf0eeb" in str(r.get("url") or "") for r in y)
    assert any("跌破5日均線看10日" in str(r.get("note") or "") and "不是日K" in str(r.get("note") or "") for r in y)
    cm = pick_charts("3013", limit=5, public_only=True)
    assert any("237c5965-cc4c-4126-bc0f-f185c2a95603" in str(r.get("url") or "") for r in cm)
    assert any("支撐沿5日均線比較強" in str(r.get("note") or "") and "不是日K" in str(r.get("note") or "") for r in cm)
    skip6416 = pick_charts("6416", limit=5, public_only=True)
    assert not any("886911b5-d689-4033-b8f3-a9b2d0cf0eeb" in str(r.get("url") or "") for r in skip6416)
    assert not any("237c5965-cc4c-4126-bc0f-f185c2a95603" in str(r.get("url") or "") for r in skip6416)


def test_thirtysecond_pick_charts_canon_sehi_not_6416():
    from biaoke_charts import pick_charts

    cn = pick_charts("2374", limit=4, public_only=True)
    assert any("56a489b6-ca84-40d8-a131-ba1e42ff9978" in str(r.get("url") or "") for r in cn)
    assert any("佳能盤中走勢" in str(r.get("note") or "") and "不是日K" in str(r.get("note") or "") for r in cn)
    se = pick_charts("4533", limit=3, public_only=True)
    assert any("ef4a177b-7a37-4712-9c70-2d5c138f9fb0" in str(r.get("url") or "") for r in se)
    assert any("協易機盤中走勢" in str(r.get("note") or "") and "不是日K" in str(r.get("note") or "") for r in se)
    skip6416 = pick_charts("6416", limit=5, public_only=True)
    assert not any("56a489b6-ca84-40d8-a131-ba1e42ff9978" in str(r.get("url") or "") for r in skip6416)
    assert not any("ef4a177b-7a37-4712-9c70-2d5c138f9fb0" in str(r.get("url") or "") for r in skip6416)
    skip3013 = pick_charts("3013", limit=6, public_only=True)
    assert not any("56a489b6-ca84-40d8-a131-ba1e42ff9978" in str(r.get("url") or "") for r in skip3013)
    assert not any("ef4a177b-7a37-4712-9c70-2d5c138f9fb0" in str(r.get("url") or "") for r in skip3013)
    skip6117 = pick_charts("6117", limit=6, public_only=True)
    assert not any("56a489b6-ca84-40d8-a131-ba1e42ff9978" in str(r.get("url") or "") for r in skip6117)
    assert not any("ef4a177b-7a37-4712-9c70-2d5c138f9fb0" in str(r.get("url") or "") for r in skip6117)


def test_thirtythird_pick_charts_lasertek_stage2_not_6416():
    from biaoke_charts import pick_charts

    lk = pick_charts("6207", limit=8, public_only=True)
    assert any("5945f017-f1e1-407a-abe8-19fe2b06c6fe" in str(r.get("url") or "") for r in lk)
    assert any("第二階段型態目標" in str(r.get("note") or "") and "不是日K" in str(r.get("note") or "") for r in lk)
    skip6416 = pick_charts("6416", limit=5, public_only=True)
    assert not any("5945f017-f1e1-407a-abe8-19fe2b06c6fe" in str(r.get("url") or "") for r in skip6416)
    skip5310 = pick_charts("5310", limit=5, public_only=True)
    assert not any("5945f017-f1e1-407a-abe8-19fe2b06c6fe" in str(r.get("url") or "") for r in skip5310)
    zs = pick_charts("2467", limit=4, public_only=True)
    assert not any("5945f017-f1e1-407a-abe8-19fe2b06c6fe" in str(r.get("url") or "") for r in zs)
    hs = pick_charts("3131", limit=4, public_only=True)
    assert not any("5945f017-f1e1-407a-abe8-19fe2b06c6fe" in str(r.get("url") or "") for r in hs)
    wr = pick_charts("6187", limit=4, public_only=True)
    assert not any("5945f017-f1e1-407a-abe8-19fe2b06c6fe" in str(r.get("url") or "") for r in wr)


def test_thirtyfourth_pick_charts_quanta_273_not_tsmc():
    assert_snip_owned(
        "2382",
        "ada1f9ba-cced-4a3f-8213-6a21cf775572",
        "支撐273不是282",
        ("2330", "6416", "5310"),
    )


def test_thirtyfifth_pick_charts_thunder_entry_not_6416():
    from biaoke_charts import pick_charts

    tt = pick_charts("8033", limit=4, public_only=True)
    assert any("bc7d90d8-fdd4-47d0-a861-4d091ae87b61" in str(r.get("url") or "") for r in tt)
    assert any("上車最佳時機" in str(r.get("note") or "") and "不是日K" in str(r.get("note") or "") for r in tt)
    skip6416 = pick_charts("6416", limit=5, public_only=True)
    assert not any("bc7d90d8-fdd4-47d0-a861-4d091ae87b61" in str(r.get("url") or "") for r in skip6416)
    skip5310 = pick_charts("5310", limit=5, public_only=True)
    assert not any("bc7d90d8-fdd4-47d0-a861-4d091ae87b61" in str(r.get("url") or "") for r in skip5310)


def test_thirtysixth_pick_charts_thunder_85_not_6416():
    from biaoke_charts import pick_charts

    tt = pick_charts("8033", limit=4, public_only=True)
    assert any("b297cbc0-0e9c-426b-a0d4-0031be1da493" in str(r.get("url") or "") for r in tt)
    assert any("挑戰歷史高點85.2" in str(r.get("note") or "") and "不是日K" in str(r.get("note") or "") for r in tt)
    skip6416 = pick_charts("6416", limit=5, public_only=True)
    assert not any("b297cbc0-0e9c-426b-a0d4-0031be1da493" in str(r.get("url") or "") for r in skip6416)
    skip5310 = pick_charts("5310", limit=5, public_only=True)
    assert not any("b297cbc0-0e9c-426b-a0d4-0031be1da493" in str(r.get("url") or "") for r in skip5310)


def test_thirtyseventh_pick_charts_lasertek_5ma_not_6416():
    from biaoke_charts import pick_charts

    lk = pick_charts("6207", limit=8, public_only=True)
    assert any("0b1449bb-43f1-4115-84c3-8b4b243660de" in str(r.get("url") or "") for r in lk)
    assert any("回測5MA支撐線" in str(r.get("note") or "") and "不是日K" in str(r.get("note") or "") for r in lk)
    skip6416 = pick_charts("6416", limit=5, public_only=True)
    assert not any("0b1449bb-43f1-4115-84c3-8b4b243660de" in str(r.get("url") or "") for r in skip6416)
    skip5310 = pick_charts("5310", limit=5, public_only=True)
    assert not any("0b1449bb-43f1-4115-84c3-8b4b243660de" in str(r.get("url") or "") for r in skip5310)


def test_thirtyeighth_pick_charts_lock_not_3167():
    from biaoke_charts import pick_charts

    cn = pick_charts("2374", limit=4, public_only=True)
    assert any("b5a3d066-a5d9-46e6-98b0-f7783b9fec02" in str(r.get("url") or "") for r in cn)
    assert any("鎖股40.1" in str(r.get("note") or "") and "不是日K" in str(r.get("note") or "") for r in cn)
    se = pick_charts("4533", limit=3, public_only=True)
    assert any("7cbc1625-37b5-42c6-be61-0338ba837fc3" in str(r.get("url") or "") for r in se)
    assert any("爆大量已賣" in str(r.get("note") or "") and "不是日K" in str(r.get("note") or "") for r in se)
    hk = pick_charts("3402", limit=2, public_only=True)
    assert any("a7f487e1-297e-45d5-afc2-3b91158ae8c2" in str(r.get("url") or "") for r in hk)
    assert any("鎖股119" in str(r.get("note") or "") and "不是日K" in str(r.get("note") or "") for r in hk)
    skip3167 = pick_charts("3167", limit=5, public_only=True)
    assert not any("b5a3d066-a5d9-46e6-98b0-f7783b9fec02" in str(r.get("url") or "") for r in skip3167)
    assert not any("7cbc1625-37b5-42c6-be61-0338ba837fc3" in str(r.get("url") or "") for r in skip3167)
    assert not any("a7f487e1-297e-45d5-afc2-3b91158ae8c2" in str(r.get("url") or "") for r in skip3167)
    skip6416 = pick_charts("6416", limit=5, public_only=True)
    assert not any("b5a3d066-a5d9-46e6-98b0-f7783b9fec02" in str(r.get("url") or "") for r in skip6416)
    skip5310 = pick_charts("5310", limit=5, public_only=True)
    assert not any("a7f487e1-297e-45d5-afc2-3b91158ae8c2" in str(r.get("url") or "") for r in skip5310)


def test_thirtyninth_pick_charts_canon_374_not_6416():
    from biaoke_charts import pick_charts

    cn = pick_charts("2374", limit=4, public_only=True)
    assert any("d9f126f0-5318-4e29-be3b-966a1cb1f8de" in str(r.get("url") or "") for r in cn)
    assert any("早盤37.4先買一半" in str(r.get("note") or "") and "不是日K" in str(r.get("note") or "") for r in cn)
    skip6416 = pick_charts("6416", limit=5, public_only=True)
    assert not any("d9f126f0-5318-4e29-be3b-966a1cb1f8de" in str(r.get("url") or "") for r in skip6416)
    skip5310 = pick_charts("5310", limit=5, public_only=True)
    assert not any("d9f126f0-5318-4e29-be3b-966a1cb1f8de" in str(r.get("url") or "") for r in skip5310)


def test_fortieth_pick_charts_hank_117_not_6416():
    from biaoke_charts import pick_charts

    hk = pick_charts("3402", limit=3, public_only=True)
    assert any("b57e4c6f-34b8-4bc0-b6fc-033e9b51cba6" in str(r.get("url") or "") for r in hk)
    assert any("先掛117-117.5" in str(r.get("note") or "") and "不是日K" in str(r.get("note") or "") for r in hk)
    skip6416 = pick_charts("6416", limit=5, public_only=True)
    assert not any("b57e4c6f-34b8-4bc0-b6fc-033e9b51cba6" in str(r.get("url") or "") for r in skip6416)
    skip5310 = pick_charts("5310", limit=5, public_only=True)
    assert not any("b57e4c6f-34b8-4bc0-b6fc-033e9b51cba6" in str(r.get("url") or "") for r in skip5310)
    skip2374 = pick_charts("2374", limit=5, public_only=True)
    assert not any("b57e4c6f-34b8-4bc0-b6fc-033e9b51cba6" in str(r.get("url") or "") for r in skip2374)


def test_fortyfirst_pick_charts_leike_neck_not_6416():
    from biaoke_charts import pick_charts

    lk = pick_charts("6207", limit=8, public_only=True)
    assert any("6820b93c-0852-47bd-868e-9c07421125a4" in str(r.get("url") or "") for r in lk)
    assert any("打到頸線56.5" in str(r.get("note") or "") and "不是日K" in str(r.get("note") or "") for r in lk)
    skip6416 = pick_charts("6416", limit=5, public_only=True)
    assert not any("6820b93c-0852-47bd-868e-9c07421125a4" in str(r.get("url") or "") for r in skip6416)
    skip5310 = pick_charts("5310", limit=5, public_only=True)
    assert not any("6820b93c-0852-47bd-868e-9c07421125a4" in str(r.get("url") or "") for r in skip5310)
    skip3402 = pick_charts("3402", limit=5, public_only=True)
    assert not any("6820b93c-0852-47bd-868e-9c07421125a4" in str(r.get("url") or "") for r in skip3402)


def test_fortysecond_pick_charts_tsmc_not_canon_etf():
    from biaoke_charts import pick_charts

    snip = "f233c076-a0d5-4be2-8cd5-f6f6946abb12"
    assert_snip_owned("2330", snip, "法說前786", ("2374", "0050", "6416", "5310"))
    skip2374 = pick_charts("2374", limit=8, public_only=True)
    assert not any("7ad20984-9c2f-4119-811e-a49f4656e7c0" in str(r.get("url") or "") for r in skip2374)
    skip0050 = pick_charts("0050", limit=8, public_only=True)
    assert not any("721c2c75-3ca9-4401-879a-c84164150a11" in str(r.get("url") or "") for r in skip0050)


def test_fortythird_pick_charts_index_not_tsmc_hank_canon():
    from biaoke_charts import pick_charts

    skip2330 = pick_charts("2330", limit=8, public_only=True)
    assert not any("8cd5d5c2-72cf-4b8f-8409-19037d427f95" in str(r.get("url") or "") for r in skip2330)
    skip3402 = pick_charts("3402", limit=8, public_only=True)
    assert not any("f26afa9e-f9c8-4b04-a861-065073c91b6c" in str(r.get("url") or "") for r in skip3402)
    skip2374 = pick_charts("2374", limit=8, public_only=True)
    assert not any("ac9395fb-1692-4640-a2ec-c81638b9cbe6" in str(r.get("url") or "") for r in skip2374)


def test_fortyfourth_pick_charts_honso_leike_not_each_other():
    from biaoke_charts import pick_charts

    hs = pick_charts("3131", limit=5, public_only=True)
    assert any("acb86ccf-ea62-404a-9a48-c6240e370891" in str(r.get("url") or "") for r in hs)
    assert any("漲停過前高1110" in str(r.get("note") or "") and "不是日K" in str(r.get("note") or "") for r in hs)
    assert not any("7913362a-11b8-4286-beee-d3c4c593ccb4" in str(r.get("url") or "") for r in hs)
    lk = pick_charts("6207", limit=8, public_only=True)
    assert any("7913362a-11b8-4286-beee-d3c4c593ccb4" in str(r.get("url") or "") for r in lk)
    assert any("也會過前高64.5" in str(r.get("note") or "") and "不是日K" in str(r.get("note") or "") for r in lk)
    assert not any("acb86ccf-ea62-404a-9a48-c6240e370891" in str(r.get("url") or "") for r in lk)
    skip6416 = pick_charts("6416", limit=5, public_only=True)
    assert not any("acb86ccf-ea62-404a-9a48-c6240e370891" in str(r.get("url") or "") for r in skip6416)
    assert not any("7913362a-11b8-4286-beee-d3c4c593ccb4" in str(r.get("url") or "") for r in skip6416)
    skip5310 = pick_charts("5310", limit=5, public_only=True)
    assert not any("acb86ccf-ea62-404a-9a48-c6240e370891" in str(r.get("url") or "") for r in skip5310)
    assert not any("7913362a-11b8-4286-beee-d3c4c593ccb4" in str(r.get("url") or "") for r in skip5310)


def test_fortyfifth_pick_charts_tx_not_tsmc_hank_canon():
    from biaoke_charts import pick_charts

    skip2330 = pick_charts("2330", limit=8, public_only=True)
    assert not any("ffa9234a-1de5-48b4-9f81-aa7ba9a60e8c" in str(r.get("url") or "") for r in skip2330)
    skip3402 = pick_charts("3402", limit=8, public_only=True)
    assert not any("eadff9cf-d2dd-4e94-9ea4-7c82df1c4ccd" in str(r.get("url") or "") for r in skip3402)
    skip2374 = pick_charts("2374", limit=8, public_only=True)
    assert not any("a9e194fd-ba63-432c-8366-88f688d244c5" in str(r.get("url") or "") for r in skip2374)
    tx = charts_for("TX")
    assert any("ffa9234a-1de5-48b4-9f81-aa7ba9a60e8c" in str(r.get("url") or "") for r in tx)
    assert any("台指期夜盤19650" in str(r.get("note") or "") and "不對圖" in str(r.get("note") or "") for r in tx)


def test_fortysixth_pick_charts_twii_not_stocks():
    assert_snip_owned(
        "TWII",
        "120a18bc-51be-460b-9d01-9b39e46abe87",
        "18752-19012",
        ("2330", "6416", "5310"),
    )
    assert_snip_owned(
        "TWII",
        "5d2ca298-069f-44c9-adb9-c0a07bb715a2",
        (),
        ("2330", "6416", "5310"),
    )


def test_fortyseventh_pick_charts_wistron_not_quanta_gold_emc():
    from biaoke_charts import pick_charts

    snip = "28244ab1-8764-4f52-8417-79798406448f"
    w = pick_charts("3231", limit=8, public_only=True)
    assert any(snip in str(r.get("url") or "") for r in w)
    assert any("小時線還沒站上119" in str(r.get("note") or "") and "不是日K" in str(r.get("note") or "") for r in w)
    for sid in ("2382", "2368", "2383", "3017", "6416", "5310"):
        rows = pick_charts(sid, limit=8, public_only=True)
        assert not any(snip in str(r.get("url") or "") for r in rows)


def test_fortyeighth_pick_charts_quanta_wiwynn_ennoconn_not_emc():
    from biaoke_charts import pick_charts

    q = pick_charts("2382", limit=32, public_only=True)
    assert any("493f2e88-231c-48b2-ab73-035291c94c8b" in str(r.get("url") or "") for r in q)
    assert any("伺服器漲勢確認" in str(r.get("note") or "") and "不是日K" in str(r.get("note") or "") for r in q)
    y = pick_charts("6669", limit=8, public_only=True)
    assert any("f46970b1-fe3b-4937-b354-95761405af6c" in str(r.get("url") or "") for r in y)
    assert any("比較看好" in str(r.get("note") or "") and "不是日K" in str(r.get("note") or "") for r in y)
    c = pick_charts("8210", limit=8, public_only=True)
    assert any("848aa61c-5fb5-4719-8a62-2c4c0c61da1a" in str(r.get("url") or "") for r in c)
    assert any("持續看好可跌再進" in str(r.get("note") or "") and "不是日K" in str(r.get("note") or "") for r in c)
    skip_snips = (
        "848aa61c-5fb5-4719-8a62-2c4c0c61da1a",
        "493f2e88-231c-48b2-ab73-035291c94c8b",
        "f46970b1-fe3b-4937-b354-95761405af6c",
    )
    for sid in ("2383", "3231", "3035", "6416", "5310"):
        rows = pick_charts(sid, limit=8, public_only=True)
        for snip in skip_snips:
            assert not any(snip in str(r.get("url") or "") for r in rows)


def test_fortyninth_pick_charts_ennoconn_289_not_others():
    from biaoke_charts import pick_charts

    snip = "b459a4ea-2d0d-4a99-ab03-c6686c5f11a5"
    rows = charts_for("8210")
    assert any(snip in str(r.get("url") or "") for r in rows)
    assert any("站上289頭肩底" in str(r.get("note") or "") and "不是日K" in str(r.get("note") or "") for r in rows)
    for sid in ("2382", "6669", "3231", "3035", "6416", "5310"):
        rows = pick_charts(sid, limit=8, public_only=True)
        assert not any(snip in str(r.get("url") or "") for r in rows)


def test_fiftieth_pick_charts_gigalight_not_others():
    from biaoke_charts import pick_charts

    snip = "7700b8ea-640f-43f5-b5be-778b1c37eea8"
    g = pick_charts("3234", limit=8, public_only=True)
    assert any(snip in str(r.get("url") or "") for r in g)
    assert any("行進中短線買點" in str(r.get("note") or "") and "不是日K" in str(r.get("note") or "") for r in g)
    for sid in ("8210", "2382", "6442", "6416", "5310"):
        rows = pick_charts(sid, limit=8, public_only=True)
        assert not any(snip in str(r.get("url") or "") for r in rows)


def test_fiftyfirst_pick_charts_gigalight_gs_not_others():
    from biaoke_charts import pick_charts

    g = pick_charts("3234", limit=8, public_only=True)
    assert any("dfc3e6d9-d626-4189-b2bc-57aa6cbcee15" in str(r.get("url") or "") for r in g)
    assert any("被處置往下打" in str(r.get("note") or "") and "不是日K" in str(r.get("note") or "") for r in g)
    gs = pick_charts("6442", limit=8, public_only=True)
    assert any("6e00e8dc-c2e8-45d7-bd9a-4af5c867236d" in str(r.get("url") or "") for r in gs)
    assert any("確認不是假突破" in str(r.get("note") or "") and "不是日K" in str(r.get("note") or "") for r in gs)
    assert not any("dfc3e6d9-d626-4189-b2bc-57aa6cbcee15" in str(r.get("url") or "") for r in gs)
    skip6416 = pick_charts("6416", limit=5, public_only=True)
    assert not any("6e00e8dc-c2e8-45d7-bd9a-4af5c867236d" in str(r.get("url") or "") for r in skip6416)
    skip5310 = pick_charts("5310", limit=5, public_only=True)
    assert not any("dfc3e6d9-d626-4189-b2bc-57aa6cbcee15" in str(r.get("url") or "") for r in skip5310)


def test_fiftysecond_pick_charts_quanta_not_others():
    snip = "37db3808-6362-474f-ab88-348ce95e3cec"
    assert_snip_owned(
        "2382",
        snip,
        ("13:30約256.5", "不是日K"),
        ("2330", "2454", "1459", "3234", "6442", "6416", "5310"),
    )


def test_fiftythird_pick_charts_quanta_min_target_not_others():
    snip = "5efc30e4-a857-49d0-a8ff-13a007847d8d"
    assert_snip_owned(
        "2382",
        snip,
        ("09:42約272.5", "不是日K"),
        ("3231", "6669", "3234", "6442", "6416", "5310"),
    )


def test_fiftyfourth_pick_charts_emc_right_shoulder_not_others():
    snip = "2b13c5f0-d84b-4deb-ac02-c13f4893a4ff"
    assert_snip_owned(
        "2383",
        snip,
        ("09:30約412.5", "不是日K"),
        ("2382", "3231", "8210", "6416", "5310"),
    )


def test_fiftyfifth_pick_charts_alchip_not_others():
    from biaoke_charts import pick_charts

    snip = "171f0639-5819-4329-bbb5-96d4e7e8e3fe"
    a = pick_charts("3661", limit=8, public_only=True)
    assert any(snip in str(r.get("url") or "") for r in a)
    assert any(
        "13:30約2760" in str(r.get("note") or "") and "不是日K" in str(r.get("note") or "")
        for r in a
    )
    for sid in ("2382", "3035", "2383", "6416", "5310"):
        rows = pick_charts(sid, limit=8, public_only=True)
        assert not any(snip in str(r.get("url") or "") for r in rows)


def test_fiftysixth_pick_charts_quanta_not_dingtian():
    snip = "f867e1ab-7301-4cff-9385-2430f8217ad7"
    assert_snip_owned(
        "2382",
        snip,
        ("09:15約274.5", "不是日K"),
        ("3306", "6188", "6669", "2317", "6416", "5310"),
    )


def test_fiftyseventh_pick_charts_asus_not_quanta():
    snip = "9759bcbb-623d-4f16-bc7c-b616edebbb7b"
    assert_snip_owned(
        "2357",
        snip,
        ("09:54約478", "不是日K"),
        ("2382", "2317", "3661", "6416", "5310"),
    )


def test_fiftyeighth_pick_charts_alchip_not_funai():
    from biaoke_charts import pick_charts

    snip = "f67e2dfe-1bc5-4e20-8d4f-f20f7f54f02b"
    a = pick_charts("3661", limit=8, public_only=True)
    assert any(snip in str(r.get("url") or "") for r in a)
    assert any(
        "10:22約2520" in str(r.get("note") or "") and "不是日K" in str(r.get("note") or "")
        for r in a
    )
    for sid in ("2736", "2357", "2382", "6416", "5310"):
        rows = pick_charts(sid, limit=8, public_only=True)
        assert not any(snip in str(r.get("url") or "") for r in rows)


def test_fiftyninth_pick_charts_ennoconn_emc_not_leader():
    snip_e = "23219170-a90a-4d45-a3bc-4896dc578cef"
    snip_t = "5b5ed874-9577-4296-98e6-1eb759affb15"
    assert_snip_owned("8210", snip_e, (), ("6669", "2382", "3231", "6416", "5310"))
    assert_snip_owned("2383", snip_t, (), ("6669", "2382", "3231", "6416", "5310"))


def test_sixtieth_pick_charts_right_shoulder_intraday():
    snip_e = "e54e963e-5576-4058-9e80-761a7d453640"
    snip_t = "651f4c31-2e20-4429-b317-2d78e36dcbdf"
    assert_snip_owned(
        "8210",
        snip_e,
        "11:31約275.5",
        ("6669", "2382", "3231", "6416", "5310"),
    )
    assert_snip_owned(
        "2383",
        snip_t,
        "11:30約416.5",
        ("6669", "2382", "3231", "6416", "5310"),
    )


def test_sixtyfirst_pick_charts_asus_not_shipping():
    snip = "5e96754a-7f28-452d-b6a8-bc7f7720aad0"
    assert_snip_owned(
        "2357",
        snip,
        "13:05約471",
        ("2609", "2615", "2382", "6416", "5310"),
    )


def test_sixtysecond_pick_charts_quanta_wiwynn_not_tsmc():
    snip_q = "87acb739-5f83-4c24-9641-52b150feba26"
    snip_w = "f414adc8-792d-4af0-8b51-1c31d31808cd"
    assert_snip_owned(
        "2382",
        snip_q,
        "13:21約274.5",
        ("2330", "2357", "2609", "2615", "3231", "6416", "5310"),
    )
    assert_snip_owned(
        "6669",
        snip_w,
        "13:21約2405",
        ("2330", "2357", "2609", "2615", "3231", "6416", "5310"),
    )


def test_sixtythird_pick_charts_quanta_hold_273():
    snip = "3c6619ac-f707-4062-b495-5282e17ccb91"
    assert_snip_owned("2382", snip, "10:26約276", ("6669", "2330", "6416", "5310"))


def test_sixtyfourth_pick_charts_quanta_282_290():
    snip = "d45ebe1b-59ab-48dc-b778-5b02fad3502d"
    assert_snip_owned("2382", snip, "09:41約288", ("6669", "2330", "6416", "5310"))


def test_sixtyfifth_pick_charts_shipping_not_tsmc():
    snip_w = "8089d63a-9bc7-4676-8200-f081a8ac92f2"
    snip_y = "082fe1e0-9a33-4a03-a871-614e2ab2afdf"
    snip_e = "b1e9f107-4112-44b7-8073-c84ed0138a0a"
    assert_snip_owned("2615", snip_w, "10:21約70.4", ("2330", "3162", "2382", "6416", "5310"))
    assert_snip_owned("2609", snip_y, "10:20約71.4", ("2330", "3162", "2382", "6416", "5310"))
    assert_snip_owned("2603", snip_e, "10:20約206.5", ("2330", "3162", "2382", "6416", "5310"))


def test_sixtysixth_pick_charts_emc_dark_before_dawn():
    snip = "bf1db5dc-a2de-4b60-b121-645c32838250"
    assert_snip_owned("2383", snip, "10:45約421", ("2382", "2330", "6416", "5310"))


def test_sixtyseventh_pick_charts_asus_clevo_not_mixed():
    snip_c = "109304d1-ce6c-457f-9900-3bf52e91b411"
    snip_a = "53d75100-477f-4dc0-bfe7-2219a1d3bc68"
    assert_snip_owned("2362", snip_c, (), ("2357", "2382", "6416", "5310"))
    assert_snip_owned("2357", snip_a, (), ("2362", "2382", "6416", "5310"))


def test_sixtyeighth_pick_charts_eps_313_is_quanta_not_number():
    snip = "eada4ea7-5ce9-4dad-bde2-dd88315619eb"
    assert_snip_owned(
        "2382",
        snip,
        ("13:30約287", "不是數字"),
        ("5287", "2330", "6416", "5310"),
    )


def test_sixtyninth_pick_charts_asus_far_from_target_not_quanta():
    snip = "4fd7bb2d-76a2-4b14-a675-0ac8643ff395"
    assert_snip_owned("2357", snip, "12:18約513", ("2382", "2383", "6416", "5310"))


def test_seventieth_pick_charts_quanta_attack_cost_not_daily_k():
    snip = "c6dac0ec-b44c-49ae-9e5b-0fe7d8efba71"
    assert_snip_owned(
        "2382",
        snip,
        "09:23約286.5",
        ("2357", "2383", "6416", "5310"),
    )


def test_seventyfirst_pick_charts_asus_last_entry_not_quanta():
    snip = "e5c2ddd7-9252-4296-9ddf-9d5decd178e3"
    assert_snip_owned(
        "2357",
        snip,
        "10:20約508",
        ("2382", "2383", "6416", "5310"),
    )


def test_seventysecond_pick_charts_emc_three_soldiers_not_3167():
    snip = "fc2da086-1a6d-4ca4-bd09-0690a67dab80"
    assert_snip_owned(
        "2383",
        snip,
        "11:35約447.5",
        ("3167", "2382", "6416", "5310"),
    )


def test_seventythird_pick_charts_index_21100_not_tsmc():
    snip = "1fa3e9ae-a32c-4ccf-95cd-eff57ded0189"
    assert_snip_owned(
        "TWII",
        snip,
        "主文大盤21100",
        ("2330", "2382", "6416", "5310"),
    )


def test_seventyfourth_pick_charts_index_wedge_not_tsmc():
    snip = "7bdf5e68-2755-4e51-bc46-db0ef8c07e29"
    assert_snip_owned(
        "TWII",
        snip,
        "主文大盤下降楔形",
        ("2330", "2382", "6416", "5310"),
    )


def test_seventyfifth_pick_charts_quanta_group_not_mixed():
    assert_snip_owned(
        "3306",
        "7176c3a5-cb62-4fb8-b2ee-d9f657c67f78",
        "12:22約58.3",
        ("2382", "6188", "6416", "5310"),
    )
    assert_snip_owned(
        "2382",
        "8850edce-5e37-4337-bd9b-665b194463bf",
        "12:26約282.5",
        ("3306", "6188", "6416", "5310"),
    )
    assert_snip_owned(
        "6188",
        "d19a4996-49ff-4716-94da-e2b4ffd1e319",
        "12:23約105",
        ("2382", "3306", "6416", "5310"),
    )


def test_chart_stamp_locks_text_stock_not_wrong_picture():
    from biaoke_charts import (
        chart_matches_text,
        keep_charts_for_text,
        official_for_text_at_stamp,
        parse_chart_stamp,
    )

    honhai_text = "鴻海機器人概念股今天站上型態頸線，待回測 327 再買完。"
    hanyun = (
        "https://image.cmoney.tw/attachment/message/1710000000/"
        "3e6b15a5-a550-4e9e-a9ea-9d4e20405a82.jpg"
    )
    hank_text = "漢科先掛117-117.5兩個價位，先買1/3"
    hank = (
        "https://image.cmoney.tw/attachment/message/1713196800/"
        "b57e4c6f-34b8-4bc0-b6fc-033e9b51cba6.jpg"
    )
    assert parse_chart_stamp("2024/04/16 10:25") == ("2024-04-16", "10:25")
    assert chart_matches_text(honhai_text, hanyun) is False
    assert chart_matches_text(hank_text, hank) is True
    assert keep_charts_for_text(honhai_text, [hanyun, hank]) == []
    assert hank in keep_charts_for_text(hank_text, [hank, hanyun])
    hit = official_for_text_at_stamp(
        "data/wayne_market.db",
        "2317",
        "2024/03/20 10:24",
        chart_sids=["6414"],
    )
    assert hit["mismatch"] is True
    assert hit["use_chart"] is False
    assert hit["stamp_date"] == "2024-03-20"
    assert hit["stamp_time"] == "10:24"
    assert hit["sid"] == "2317"
    bar = hit["official"]
    assert bar == {} or abs(float(bar["close"]) - 138) < 0.01


@pytest.mark.production_db
def test_2383_redbox_matches_official_day():
    from tests.conftest import require_production_db
    from biaoke_charts import format_charts_vs_official

    db = require_production_db()
    text = format_charts_vs_official("2383", db, hold=False, limit=3)
    assert "1265" in text
    assert "1275" in text
    assert "官方收1275" in text
