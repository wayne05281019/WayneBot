# -*- coding: utf-8 -*-
"""WB-67 剩餘真怪：期貨比現貨／日K時段／失效升軌／站撐句（輕測、不渲圖）。"""
from __future__ import annotations

import inspect
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

_TP = ZoneInfo("Asia/Taipei")


def test_basis_uses_card_spot_not_fuse_prev():
    """期貨比現貨％必須對卡上加權現價／收；不准對 fuse 昨收（0.03% 假貼平）。"""
    from taiwan_market import compute_basis_pct, format_taiwan_market_page_html

    # 昨收 46096、今收／現價 47035、期 46990 → 應對今約 -0.10%，不是對昨 ~+1.9%
    assert compute_basis_pct(46096.0, 46990.0) == pytest.approx(1.94, abs=0.02)
    assert compute_basis_pct(47035.0, 46990.0) == pytest.approx(-0.10, abs=0.02)

    src = inspect.getsource(format_taiwan_market_page_html)
    assert "spot_for_basis" in src
    assert "compute_basis_pct(spot_for_basis" in src
    assert "load_futures_daily(db_path, spot_day)" in src


def test_index_kline_header_no_intraday_after_close():
    """日K 圖頭時段與收盤一致：已收不准因 live_px 殘價再寫盤中。"""
    from index_kline_chart import render_index_kline_png

    src = inspect.getsource(render_index_kline_png)
    assert "tw_cash_session_open" in src
    assert "live_px > 0 and cash_open" in src


def test_fmtqik_volume_force_on_sync_and_kline():
    """日K 量與主卡全日量同源：sync／日K 路徑可 FMTQIK 覆寫近窗。"""
    from index_kline_chart import build_market_kline_chart
    from taiwan_market import _backfill_zero_index_volumes, sync_index_daily

    assert "force_recent" in inspect.signature(_backfill_zero_index_volumes).parameters
    ssrc = inspect.getsource(sync_index_daily)
    assert "force_recent=True" in ssrc
    ksrc = inspect.getsource(build_market_kline_chart)
    assert "force_recent=True" in ksrc
    msrc = inspect.getsource(
        __import__("taiwan_market", fromlist=["_merge_index_closes"])._merge_index_closes
    )
    assert '"volume": 0.0' in msrc or "'volume': 0.0" in msrc


def test_broken_asc_demote_or_say_not_drawn():
    """失效升軌：降權灰或明說未畫下降壓（對齊 WB-28）。"""
    import vol_zone_chart as vz

    from biaoke_chart import _paint_parallel_channel, channel_prefer_named_rising_or_infer
    from vol_zone_chart import paint_vol_zone_parallel_channel

    nsrc = inspect.getsource(channel_prefer_named_rising_or_infer)
    assert "未改畫下降壓" in nsrc or "未畫下降壓" in nsrc
    assert 'out["alive"] = False' in nsrc
    psrc = inspect.getsource(_paint_parallel_channel)
    assert 'color = "#90a4ae"' in psrc
    vsrc = inspect.getsource(paint_vol_zone_parallel_channel)
    assert "ch_alive" in vsrc
    assert "#90a4ae" in vsrc
    mod = inspect.getsource(vz)
    assert "未畫下降壓" in mod


def test_hold_wording_stand_and_pierce_recover():
    """站撐句：過撐歧義改站上撐；今低破撐收站回要講清楚。"""
    from vol_zone_chart import vol_zone_day_path_label, vol_zone_position_line

    press, hold = 3255.0, 2940.0
    today = {
        "date": "20261006",
        "open": 3000,
        "high": 3055,
        "low": 2915,
        "close": 2920,
        "volume": 3260,
    }
    line = vol_zone_day_path_label(press, hold, today, bars=[today], zone_date="20260826")
    assert "收盤未站上撐" in line
    assert "過撐" not in line

    recover = {
        "date": "20261028",
        "open": 46400,
        "high": 47100,
        "low": 46200,
        "close": 47036,
        "volume": 1,
    }
    zone = {"high": 49970, "low": 46450, "date": "20261015", "volume": 1}
    # 今低 46200 < 撐 46450，收 47036 站回
    pos = vol_zone_position_line(zone, recover, bars=[recover])
    assert "刺穿" in pos and "站回" in pos
    assert "過撐" not in pos

    stand = {
        "date": "20261028",
        "open": 46500,
        "high": 47100,
        "low": 46480,
        "close": 47036,
        "volume": 1,
    }
    path = vol_zone_day_path_label(49970, 46450, stand, bars=[stand])
    assert "收盤站上撐" in path
    assert "過撐" not in path


def test_merge_official_day_zeros_yahoo_volume():
    """有官方收的日子 merge 量歸零，交給 FMTQIK，避免 Yahoo 量進日K。"""
    import pandas as pd

    from taiwan_market import _merge_index_closes

    yahoo = pd.DataFrame(
        [
            {
                "date": "20261027",
                "open": 46200.0,
                "high": 46500.0,
                "low": 45600.0,
                "close": 46096.0,
                "volume": 8_978_000.0,
                "pct_change": 0.5,
            }
        ]
    )
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(
            "taiwan_market._fetch_twse_index_close",
            lambda d: {"close": 46096.23, "pct_change": 0.5},
        )
        out, _alerts = _merge_index_closes(yahoo)
    assert float(out.iloc[0]["volume"]) == 0.0
    assert float(out.iloc[0]["close"]) == pytest.approx(46096.23)
