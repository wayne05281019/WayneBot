# -*- coding: utf-8 -*-
"""海選桶中文唯一對照：leave_zero＝買、golden_buy＝還在零只觀察。"""
from screen_buckets import (
    BUCKET_TITLE,
    bucket_key_from_label,
    bucket_title,
)


def test_leave_zero_is_buy_label():
    assert BUCKET_TITLE["leave_zero"] == "黃金買點"
    assert bucket_title("leave_zero") == "黃金買點"


def test_golden_buy_is_watch_only_label():
    assert BUCKET_TITLE["golden_buy"] == "還在零"
    assert bucket_title("golden_buy") == "還在零"
    # 舊名只認不寫
    assert bucket_key_from_label("重點觀察") == "golden_buy"
    assert bucket_title("重點觀察") == "還在零"


def test_no_module_writes_zhongdian_as_canonical():
    assert "重點觀察" not in BUCKET_TITLE.values()
