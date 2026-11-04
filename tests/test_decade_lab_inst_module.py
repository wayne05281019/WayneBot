# -*- coding: utf-8 -*-
from scripts.decade_lab_inst_module import parse_bfi82u, load_inst_votes


def test_parse_bfi82u_sample():
    payload = {
        "stat": "OK",
        "data": [
            ["自營商(自行買賣)", "1", "2", "-100000000"],
            ["自營商(避險)", "1", "2", "-200000000"],
            ["投信", "1", "2", "300000000"],
            ["外資及陸資(不含外資自營商)", "1", "2", "-400000000"],
            ["合計", "1", "2", "-400000000"],
        ],
    }
    row = parse_bfi82u(payload)
    assert row is not None
    assert row["trust_net_yi"] == 3.0
    assert row["foreign_net_yi"] == -4.0
    assert row["dealer_net_yi"] == -3.0
    assert row["three_net_yi"] == -4.0


def test_load_inst_votes_file_optional():
    # 檔可能存在；函式不准炸
    votes = load_inst_votes()
    assert isinstance(votes, dict)
