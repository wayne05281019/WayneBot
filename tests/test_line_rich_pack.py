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


def test_render_line_rich_share_html_has_album_and_line():
    from line_hop import render_line_rich_share_html

    page = render_line_rich_share_html(
        {
            "title": "起漲",
            "count": 2,
            "line_text": "WayneBot 測試\n1. 台積電 (2330)",
            "album_url": "https://example.com/line/rich/leave_zero/20260901/album.png",
            "stocks": [
                {
                    "rank": 1,
                    "stock_id": "2330",
                    "stock_name": "台積電",
                    "strip_url": "https://example.com/x.png",
                    "industry_plain": "半導體業景氣…",
                }
            ],
        }
    )
    assert "line://msg/text/" in page
    assert "album.png" in page
    assert "全區長圖" in page


def test_line_rich_hop_url():
    from line_rich_pack import line_rich_hop_url

    assert line_rich_hop_url("leave_zero", "https://example.com") == "https://example.com/line/rich/leave_zero"
