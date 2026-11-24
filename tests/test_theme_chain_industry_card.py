"""查股產業卡：主題鏈加層不換底。"""
from __future__ import annotations

from industry_brief import (
    attach_fine_industry,
    format_industry_html,
    industry_card_spec,
    industry_snapshot,
    theme_chain_layer_text,
)
from tests.test_industry_chain_peers import _seed


def test_theme_chain_layer_text_empty_without_taught():
    assert theme_chain_layer_text([]) == ""
    assert theme_chain_layer_text(None) == ""


def test_theme_chain_layer_text_taught_format():
    assert theme_chain_layer_text(["散熱"]) == "散熱（已教過★）"
    assert theme_chain_layer_text(["光通訊", "低軌衛星"]) == "光通訊／低軌衛星（已教過★）"


def test_industry_card_taught_shows_theme_keeps_base_chain(tmp_path):
    db = str(tmp_path / "cool.db")
    _seed(
        db,
        [
            ("3017", "奇鋐", "電腦及週邊設備業", "TW", "電子中游-NB與手機零組件", 10.0, 2365.0, 5.0),
            ("3653", "健策", "電子零組件業", "TW", "電子中游-其他", 8.0, 3685.0, 4.0),
            ("3324", "雙鴻", "電子零組件業", "TWO", "電子中游-其他", 6.0, 777.0, 3.0),
        ],
    )
    snap = attach_fine_industry(industry_snapshot(db, "3017"), db, allow_fetch=False)
    spec = industry_card_spec(snap)
    assert spec["chain"] == "電子中游-NB與手機零組件"
    assert spec["theme_layer"] == "散熱（已教過★）"
    assert "散熱" in spec["extras"]

    html = format_industry_html("3017", db, allow_fetch=False)
    assert "產業鏈" in html
    assert "電子中游-NB與手機零組件" in html
    assert "主題鏈" in html
    assert "散熱（已教過★）" in html
    assert "跨族" not in html  # 臉改主題鏈，不再用跨族欄位名

    from industry_card import render_industry_png
    from PIL import Image

    out = str(tmp_path / "3017_industry.png")
    path = render_industry_png("3017", db, out, allow_fetch=False)
    im = Image.open(path)
    assert im.size[0] > 100 and im.size[1] > 100


def test_industry_card_untaught_no_theme_layer(tmp_path):
    db = str(tmp_path / "plain.db")
    _seed(
        db,
        [
            ("2002", "中鋼", "鋼鐵工業", "TW", "原物料-鋼鐵", 1.0, 16.85, 0.5),
            ("2006", "東和鋼鐵", "鋼鐵工業", "TW", "原物料-鋼鐵", 2.0, 40.0, 1.0),
        ],
    )
    # 中鋼不在 TAUGHT_GROUPS → 只顯示底標，不加主題鏈層
    snap = attach_fine_industry(industry_snapshot(db, "2002"), db, allow_fetch=False)
    spec = industry_card_spec(snap)
    assert spec["chain"] == "原物料-鋼鐵"
    assert spec["theme_layer"] == ""
    assert spec["extras"] == []

    html = format_industry_html("2002", db, allow_fetch=False)
    assert "原物料-鋼鐵" in html
    # 說明文案可提「主題鏈」二字；卡面 kv 加層（已教過★）不准出現
    assert "已教過★" not in html
    assert "主題鏈　" not in html and "主題鏈:" not in html and "主題鏈：" not in html
