# -*- coding: utf-8 -*-
"""卡面稽核的距高驗算要跟決策卡同口徑（÷高），不准把正確值報成錯。"""
from tests.card_face_audit import card_issues


def test_dist_from_high_oracle_divides_by_high():
    card = {
        "stock_id": "2383",
        "close": 4215.0,
        "h60": 6350.0,
        "dist_h60": round((4215.0 - 6350.0) / 6350.0 * 100.0, 1),
    }
    assert card["dist_h60"] == -33.6
    assert not [x for x in card_issues(card) if "距高" in x]
    card["dist_h60"] = -50.7
    assert any("h60 距高" in x for x in card_issues(card))
