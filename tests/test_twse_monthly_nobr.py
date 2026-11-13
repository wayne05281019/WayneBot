# -*- coding: utf-8 -*-
"""證交所月營收 OpenAPI：Accept-Encoding 不准帶 br（解碼會炸、最新月寫不進庫）。"""
from __future__ import annotations

from fundamentals import HEADERS


def test_fundamentals_headers_reject_brotli():
    ae = str(HEADERS.get("Accept-Encoding") or "")
    assert ae, "月營收抓取必須顯式鎖 Accept-Encoding"
    assert "br" not in ae.split(",")
    assert "gzip" in ae
