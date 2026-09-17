# -*- coding: utf-8 -*-
"""T86 股→張：對官方列、對齊籌碼K線四捨五入。"""
from chips import _shares_to_lots, parse_twse_t86

_T86_FIELDS = [
    "證券代號",
    "證券名稱",
    "外陸資買進股數(不含外資自營商)",
    "外陸資賣出股數(不含外資自營商)",
    "外陸資買賣超股數(不含外資自營商)",
    "外資自營商買進股數",
    "外資自營商賣出股數",
    "外資自營商買賣超股數",
    "投信買進股數",
    "投信賣出股數",
    "投信買賣超股數",
    "自營商買賣超股數",
    "自營商買進股數(自行買賣)",
    "自營商賣出股數(自行買賣)",
    "自營商買賣超股數(自行買賣)",
    "自營商買進股數(避險)",
    "自營商賣出股數(避險)",
    "自營商買賣超股數(避險)",
    "三大法人買賣超股數",
]


def test_shares_to_lots_rounds_t86_shares():
    assert _shares_to_lots(-65) == 0
    assert _shares_to_lots(-402) == 0
    assert _shares_to_lots(218964) == 219
    assert _shares_to_lots(-221000) == -221
    assert _shares_to_lots(90185) == 90
    assert _shares_to_lots(-2885) == -3
    assert _shares_to_lots(3955) == 4
    assert _shares_to_lots(4839) == 5
    assert _shares_to_lots(99951) == 100
    assert _shares_to_lots(-1680) == -2
    assert _shares_to_lots(0) == 0


def test_parse_twse_t86_6526_20260917_dealer_is_zero_lots():
    """官方 6526 20260917：自營合計 -65 股＝0 張，三大法人 90,185 股＝90 張。"""
    payload = {
        "fields": _T86_FIELDS,
        "data": [
            [
                "6526",
                "達發",
                "239,282",
                "149,032",
                "90,250",
                "0",
                "0",
                "0",
                "0",
                "0",
                "0",
                "-65",
                "2,210",
                "0",
                "2,210",
                "3,497",
                "5,772",
                "-2,275",
                "90,185",
            ]
        ],
    }
    got = parse_twse_t86(payload)["6526"]
    assert got["foreign_net"] == 90
    assert got["trust_net"] == 0
    assert got["dealer_net"] == 0
    assert got["three_net"] == 90


def test_parse_twse_t86_6526_20260908_dealer_not_minus_402_lots():
    """官方自營合計 -402 股＝0 張，不是 -402 張。"""
    payload = {
        "fields": _T86_FIELDS,
        "data": [
            [
                "6526",
                "達發",
                "0",
                "0",
                "67,332",
                "0",
                "0",
                "0",
                "0",
                "0",
                "0",
                "-402",
                "0",
                "2,100",
                "-2,100",
                "1,698",
                "0",
                "1,698",
                "66,930",
            ]
        ],
    }
    got = parse_twse_t86(payload)["6526"]
    assert got["foreign_net"] == 67
    assert got["trust_net"] == 0
    assert got["dealer_net"] == 0
    assert got["three_net"] == 67
