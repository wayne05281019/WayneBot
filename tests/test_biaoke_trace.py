# -*- coding: utf-8 -*-
"""飆大時間線：連線對官方日 K；手機不寫「語料」。"""
import pytest

from biaoke_brain import answer_biaoke
from biaoke_trace import format_trace, verify_level_holds, verify_low_rail


def test_phone_text_does_not_say_yuliao(tmp_path):
    from tests.test_biaoke_brain import _db

    db = _db(tmp_path)
    html = answer_biaoke(db, "藝舍-KY")
    assert "語料" not in html
    assert "資料庫從頭到尾沒點名" in html
    html2 = answer_biaoke(":memory:", "連線怎麼看大盤")
    assert "語料" not in html2
    assert "9/3" in html2
    assert "11/24" in html2
    assert "1145" in html2


def test_rails_named_dates_and_verified_break():
    text = format_trace("台積電 9/3 連到 11/24 那條上升軌")
    assert "上升軌" in text
    assert "下降壓" in text
    assert "1145" in text
    assert "1375" in text
    assert "語料" not in text


def test_fancheng_timeline_not_a_lecture():
    html = answer_biaoke(":memory:", "汎銓為什麼會大漲")
    assert "語料" not in html
    assert "6830" in html or "泛銓" in html
    assert "新聞變多" in html
    assert "這不是買訊" in html


@pytest.mark.production_db
def test_verify_tsmc_rail_on_production_db():
    from tests.conftest import require_production_db

    db = require_production_db()
    chk = verify_low_rail(db, sid="2330", d1="20250903", d2="20251124", at="20251216")
    assert chk.get("ok")
    assert chk["p1_low"] == 1145
    assert chk["p2_low"] == 1375
    assert chk["close"] == 1435
    assert chk["broke_close"] is True
    tw = verify_low_rail(db, sid="TWII", d1="20250903", d2="20251121", at="20251216")
    assert tw.get("ok")
    assert tw["broke_close"] is False


def test_wave_question_uses_sep11_levels():
    text = format_trace("目前大盤是屬於哪個位階 以波浪來看的話")
    assert "45839" in text
    assert "46506" in text
    assert "48218" in text
    assert "17200" not in text
    assert "語料" not in text
    text = format_trace("45839 有沒有守住")
    assert "45839" in text
    assert "右肩" in text
    assert "1145" not in text
    assert "語料" not in text
    html = answer_biaoke(":memory:", "右肩型態 45839")
    assert "45839" in html
    assert "這不是買訊" in html
    assert "語料" not in html


@pytest.mark.production_db
def test_verify_45839_holds_through_sep10():
    from tests.conftest import require_production_db

    db = require_production_db()
    chk = verify_level_holds(db, sid="TWII", ymd="20260903")
    assert chk.get("ok")
    assert abs(float(chk["level"]) - 45839.36) < 0.02
    assert chk["held"] is True
    assert float(chk["nearest_later_low"]) > 45839
    text = format_trace("45839 有沒有守住", db)
    assert "還沒破" in text
