# -*- coding: utf-8 -*-
"""四路對質：分類與證人，不打外網。"""
from biaoke_mind import format_methods_html
from biaoke_witness import classify_post, follow_twii, format_witness_html, tsmc_witness


def _bar(day: str, close: float, low: float, vol: float, high: float = 0.0) -> dict:
    return {
        "date": day.replace("-", ""),
        "open": close,
        "high": high or close + 1,
        "low": low,
        "close": close,
        "volume": vol,
    }


def test_classify_confirm_vs_prelim():
    assert (
        classify_post(
            "波浪理論沒辦法 100% 確認 7/29 39384 為 A 波低；"
            "但台積電＋某金融商品的量價結構已經 100% 確認。第一次抄底那天就是 A 波低。"
        )
        == "confirm"
    )
    assert (
        classify_post(
            "夜盤 15 分細微波走了 5 段，下降軌道已破壞＝初步止訊號；"
            "夜盤至少要穿越 46506。無法判斷是 5 段或 9 段。"
        )
        == "prelim"
    )


def test_tsmc_volume_and_close_eq_low():
    bars = [_bar(f"202607{i:02d}", 100 + i, 99 + i, 1000) for i in range(1, 21)]
    bars.append(_bar("20260721", 90, 89.8, 4000))  # 爆量、收近低
    w = tsmc_witness(bars, "20260721")
    assert w["fire"]
    assert w["close_eq_low"]
    assert w["vol_ratio"] >= 1.6


def test_follow_twii_hold():
    ser = [_bar(f"202606{i:02d}", 100 + i, 90 + i, 1) for i in range(1, 28)]
    held = follow_twii(ser, "20260605", n=5)
    assert held["hold"] is True
    assert held["n"] == 5


def test_methods_html_mentions_four_way():
    html = format_methods_html("現在確認了沒四路對質")
    assert "四路" in html or "台積電" in html
    body = format_witness_html("現在確認了沒")
    assert "不是買訊" in body


def test_why_witness_uses_fetched_rates():
    from biaoke_why import lookup

    body = lookup("現在確認了沒四路對質")
    assert "52.9" in body or "輔助" in body
    assert "台指期" in body
    assert "不是買訊" in body
