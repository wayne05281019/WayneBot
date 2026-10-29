"""興櫃完整日不准被上市櫃半套 as_of 卡死（3595 20261029）。"""
from __future__ import annotations

import inspect


def test_latest_complete_emerging_date_helper_exists():
    from import_health import MIN_EM, latest_complete_emerging_date

    assert int(MIN_EM) >= 300
    assert callable(latest_complete_emerging_date)


def test_load_official_ohlc_uses_emerging_complete_cap():
    from vol_zone_chart import load_official_ohlc

    src = inspect.getsource(load_official_ohlc)
    assert "latest_complete_emerging_date" in src
    assert "emerging_quotes" in src
    assert "不准把已收興櫃卡死" in src or "em_cap" in src
