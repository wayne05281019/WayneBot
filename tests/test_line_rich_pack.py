def test_render_line_share_pack_empty_db_returns_error(tmp_path):
    from line_rich_pack import render_line_share_pack

    out = render_line_share_pack("0000", db_path=":memory:", charts_dir=str(tmp_path))
    assert out.get("error") or out.get("stock_id") == "0000"


def test_bucket_title_leave_zero():
    from line_rich_pack import bucket_title

    assert bucket_title("leave_zero") == "起漲"
