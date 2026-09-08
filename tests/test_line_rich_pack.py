def test_compose_vertical_images(tmp_path):
    from PIL import Image

    from line_rich_pack import compose_vertical_images

    p1 = tmp_path / "a.png"
    p2 = tmp_path / "b.png"
    Image.new("RGB", (100, 50), (255, 0, 0)).save(p1)
    Image.new("RGB", (100, 60), (0, 255, 0)).save(p2)
    out = tmp_path / "album.png"
    path = compose_vertical_images([str(p1), str(p2)], str(out))
    assert path == str(out)
    assert out.is_file()
    with Image.open(out) as im:
        assert im.height > 100


def test_selected_line_text_keeps_only_checked_stocks():
    from line_hop import selected_line_text

    manifest = {
        "title": "黃金買點",
        "bucket_key": "leave_zero",
        "as_of": "20260904",
        "line_text": "WayneBot 海選　2026/09/04\n＝＝黃金買點＝＝\n共 2 檔\n1. 台積電 (2330)\n────────────\n2. 聯發科 (2454)",
        "stocks": [
            {
                "stock_id": "2330",
                "stock_name": "台積電",
                "text_block": "1. 台積電 (2330)\n格局：黃金買點",
            },
            {
                "stock_id": "2454",
                "stock_name": "聯發科",
                "text_block": "2. 聯發科 (2454)\n格局：黃金買點",
            },
        ],
    }
    all_text = selected_line_text(manifest, None)
    assert all_text == manifest["line_text"]
    one = selected_line_text(manifest, ["2454"])
    assert "聯發科" in one
    assert "台積電" not in one
    assert "共 1 檔" in one
    assert selected_line_text(manifest, ["9999"]) == ""


def test_render_line_rich_share_html_has_album_and_line():
    from line_hop import render_line_rich_share_html

    page = render_line_rich_share_html(
        {
            "title": "黃金買點",
            "count": 2,
            "line_text": "WayneBot 測試\n1. 台積電 (2330)\n產業\n半導體業景氣…",
            "album_url": "https://example.com/line/rich/leave_zero/20260901/album.png",
            "stocks": [
                {
                    "rank": 1,
                    "stock_id": "2330",
                    "stock_name": "台積電",
                    "text_block": "1. 台積電 (2330)\n格局：站上月線\n收　100　+2.5%\n產業\n半導體業景氣…",
                    "glance_url": "https://example.com/g.png",
                    "card_url": "https://example.com/c.png",
                    "strip_url": "https://example.com/x.png",
                    "industry_plain": "半導體業景氣…",
                }
            ],
        }
    )
    assert "選聯絡人" in page
    assert "只轉 Keep" not in page
    assert "album.png" in page
    assert "格局：站上月線" in page
    assert "半導體業景氣" in page
    assert "color:#c41e3a" in page
    assert "g.png" in page
    assert "奇摩" in page
    assert "/y/2330" in page
    assert "tw.stock.yahoo.com" not in page
    assert "max-width:390px" in page
    assert "max-height:168px" in page
    assert 'class="stock-pick"' in page
    assert 'value="2330"' in page
    assert "勾要傳的檔" in page
    assert "開 LINE 選聯絡人" in page
    assert "傳勾選的圖到 LINE" in page
    assert "複製勾選名單到 LINE" not in page
    assert "請開 LINE → 選聯絡人 → 長按貼上" not in page
    assert "分享全區長圖" in page
    assert 'id="pickAll"' in page
    assert 'id="pickNone"' in page
    assert 'id="pickPayload"' in page
    assert "<details open>" not in page


def test_text_font_uses_bundled_noto():
    from line_rich_pack import text_font_path

    path = text_font_path().replace("\\", "/")
    assert "NotoSansTC" in path


def test_compose_stock_section_starts_with_glance(tmp_path):
    from PIL import Image

    from line_rich_pack import compose_stock_section

    glance = tmp_path / "g.png"
    card = tmp_path / "c.png"
    Image.new("RGB", (100, 80), (255, 0, 0)).save(glance)
    Image.new("RGB", (100, 90), (0, 255, 0)).save(card)
    out = tmp_path / "strip.png"
    path = compose_stock_section(
        "1. 台積電 (2330)\n格局：多頭",
        {"glance": str(glance), "card": str(card)},
        str(out),
        str(tmp_path / "w"),
    )
    assert path == str(out)
    with Image.open(out) as im:
        px = im.getpixel((50, 12))
        assert px[0] > 200 and px[1] < 40


def test_wrap_plain_lines():
    from line_share_format import _wrap_plain_lines

    lines = _wrap_plain_lines("半導體業近期營收轉強，法人買超持續增加中", width=10)
    assert len(lines) >= 2


def test_render_text_panel_png(tmp_path):
    from PIL import Image

    from line_rich_pack import render_text_panel_png
    from line_share_format import STANCE_RED_RGB, format_line_stock_block

    out = tmp_path / "t.png"
    block = format_line_stock_block(
        {
            "stock_id": "2330",
            "stock_name": "台積電",
            "close": 100.0,
            "pct_change": 2.5,
            "volume": 8000,
            "profit": 45.0,
            "hl": "20高",
        },
        1,
    )
    path = render_text_panel_png(block, str(out))
    assert path == str(out)
    assert out.is_file()
    assert "漲多了，今天別追" in block
    geju = next(ln for ln in block.split("\n") if ln.startswith("格局"))
    assert "漲多了，今天別追" in geju
    with Image.open(out) as im:
        reds = [
            px
            for y in range(im.height)
            for x in range(0, im.width, 2)
            if (px := im.getpixel((x, y)))[0] > 150 and px[1] < 90 and px[2] < 110
        ]
        assert reds, "黃金買點旁邊的態度應畫成紅字"
        hit = reds[len(reds) // 2]
        assert abs(hit[0] - STANCE_RED_RGB[0]) < 40


def test_line_rich_hop_url():
    from line_rich_pack import line_rich_hop_url

    assert line_rich_hop_url("leave_zero", "https://example.com") == "https://example.com/line/rich/leave_zero"


def test_rich_manifest_db_roundtrip(tmp_path):
    from screen_sessions import load_bucket_rich_manifest, save_bucket_rich_manifest

    db = str(tmp_path / "t.db")
    manifest = {
        "bucket_key": "leave_zero",
        "as_of": "20260901",
        "title": "黃金買點",
        "count": 1,
        "line_text": "WayneBot 測試\n1. 台積電",
        "album_url": "",
        "stocks": [],
    }
    save_bucket_rich_manifest(db, manifest)
    hit = load_bucket_rich_manifest(db, "leave_zero")
    assert hit.get("line_text") == manifest["line_text"]


def test_rebuild_manifest_from_line_pack(tmp_path):
    from line_rich_pack import rebuild_manifest_from_line_pack
    from screen_sessions import upsert_line_pack

    db = str(tmp_path / "t.db")
    upsert_line_pack(
        db,
        "20260901",
        {"id": "leave_zero", "title": "傳 黃金買點", "label": "開 LINE", "text": "WayneBot 測試\n1. 華航"},
    )
    hit = rebuild_manifest_from_line_pack(db, "leave_zero")
    assert hit.get("text_only") is True
    assert "華航" in hit.get("line_text", "")


def test_long_line_text_still_opens_line():
    from line_hop import render_line_redirect_html

    long_text = "測" * 3000
    page = render_line_redirect_html(long_text)
    assert "開 LINE 選聯絡人" in page
    assert "line://msg/text/" in page
    assert "line.me/R/share" in page
    assert "手動" not in page
