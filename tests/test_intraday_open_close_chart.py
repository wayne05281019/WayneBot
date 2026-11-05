# -*- coding: utf-8 -*-
"""當天走勢圖（查股第 5 張）正式入口：市場解析／缺路徑不上假圖／接線存在。"""
from __future__ import annotations

import inspect
import os

from bot_servers import WayneTelegramBot, _LOOKUP_CHART_KINDS
from intraday_open_close_chart import (
    _CHART_LABEL_FS_SCALE,
    _GRID_FS_SCALE,
    _chart_label_fs,
    _grid_fs,
    _paint_smart_level_labels,
    _y_price_tick_band,
    prepare_lookup_intraday_series,
    resolve_intraday_asof_ymd,
    resolve_intraday_market,
    render_lookup_intraday_result,
)


def test_lookup_chart_kinds_include_intraday():
    assert "intraday" in _LOOKUP_CHART_KINDS


def test_send_card_wires_fifth_intraday():
    src = inspect.getsource(WayneTelegramBot._send_card_to_locked)
    assert "_intraday_item" in src
    assert "render_lookup_intraday_result" in src
    assert 'render_plan_kinds = ("card", "glance", "struct", "vol", "intraday")' in src
    # 第 5 張不掛 hub
    assert src.index("_intraday_item") > src.index("_vol_item")
    assert "當天走勢" in src


def test_progress_mentions_intraday():
    txt = WayneTelegramBot._chart_progress_text(
        12, sent=["card", "glance", "struct", "vol"], current="intraday"
    )
    assert "當天走勢" in txt


def test_resolve_market_from_hits_em():
    assert (
        resolve_intraday_market(
            "3595", hits=[{"stock_id": "3595", "market": "EM"}]
        )
        == "EM"
    )


def test_resolve_market_from_hits_two():
    assert (
        resolve_intraday_market(
            "6274", hits=[{"stock_id": "6274", "market": "TWO"}]
        )
        == "TWO"
    )


def test_resolve_asof_ymd_prefer():
    assert resolve_intraday_asof_ymd(prefer="2026-10-29") == "20261029"


def test_fetch_official_twse_matches_zero_padded_roc_day(monkeypatch):
    """證交所日列是 115/11/03；mmdd 必須零墊，1–9 日不准 miss 掉官方列。"""
    import requests

    import intraday_open_close_chart as ioc

    payload = {
        "stat": "OK",
        "data": [
            [
                "115/11/03",
                "1,000,000",
                "100,000,000",
                "100.00",
                "110.00",
                "99.00",
                "105.00",
                "+5.00",
                "1,000",
                "",
            ]
        ],
    }

    class _Resp:
        status_code = 200

        def json(self):
            return payload

    monkeypatch.setattr(requests, "get", lambda *a, **k: _Resp())
    monkeypatch.setattr(ioc, "_hist_stats", lambda *a, **k: (None, None, None))
    monkeypatch.setattr(ioc, "_prev_day_vol_turn_db", lambda *a, **k: (None, None))
    off = ioc.fetch_official_twse("2383", ymd="20261103", db_path="/tmp/x.db")
    assert off is not None
    assert float(off.close) == 105.0
    assert float(off.open) == 100.0


def test_render_lookup_empty_without_series(tmp_path):
    """無真官方／分時 → 回空，不准假圖。"""
    out = os.path.join(tmp_path, "x.png")
    path, cap = render_lookup_intraday_result(
        "0000",
        "無此檔",
        db_path=os.path.join(tmp_path, "missing.db"),
        save_path=out,
        market="TW",
        asof_ymd="20261029",
    )
    assert path == ""
    assert cap == ""
    assert not os.path.isfile(out)


def test_prefer_asof_does_not_fallback_previous_day(tmp_path, monkeypatch):
    """高低卡指定日缺路徑 → 回空；不准默默退前一開市日換成錯日戳。"""
    calls: list[str] = []

    def _fake_build(sid, name, mkt, db_path=None, ymd=None, live_quote=None, **_kw):
        calls.append(str(ymd or ""))
        return None

    monkeypatch.setattr(
        "intraday_open_close_chart.build_series", _fake_build
    )
    out = os.path.join(tmp_path, "prefer.png")
    path, cap = render_lookup_intraday_result(
        "8234",
        "新漢",
        db_path=os.path.join(tmp_path, "x.db"),
        save_path=out,
        market="TWO",
        asof_ymd="20261030",
        card={"latest_date": "20261030"},
    )
    assert path == ""
    assert cap == ""
    assert calls == ["20261030"]


def test_send_card_passes_card_asof_to_intraday():
    src = inspect.getsource(WayneTelegramBot._send_card_to_locked)
    assert "latest_date" in src
    assert "asof_ymd=asof or None" in src
    assert "prepare_lookup_intraday_series" in src
    assert "intrad_prep_task" in src
    assert "series is None and not prefer" in inspect.getsource(
        prepare_lookup_intraday_series
    )


def test_intraday_caption_stamps_real_ymd():
    """第 5 張 caption 要標真日戳，不准只寫「當天」讓人猜。"""
    src = inspect.getsource(render_lookup_intraday_result)
    assert "day_lab" in src
    assert "開→收・{day_lab}" in src


def test_render_intraday_accepts_prepare_tuple(monkeypatch, tmp_path):
    """series= 若誤傳 prepare 整包 (series,ymd,mkt)，要拆開渲，不准 AttributeError 缺圖。"""
    calls = {"n": 0}

    class _FakeSeries:
        official = object()

    def _fake_prepare(*_a, **_k):
        raise AssertionError("不應再 prepare")

    def _fake_render_path(series, out, db_path=None):
        calls["n"] += 1
        assert series is fake
        open(out, "wb").write(b"x" * 100)
        return out, {"pass": True}

    fake = _FakeSeries()
    monkeypatch.setattr(
        "intraday_open_close_chart.prepare_lookup_intraday_series", _fake_prepare
    )
    monkeypatch.setattr("intraday_open_close_chart.render_path", _fake_render_path)
    out = str(tmp_path / "t.jpg")
    path, cap = render_lookup_intraday_result(
        "2330",
        "台積電",
        save_path=out,
        series=(fake, "20261030", "TW"),
    )
    assert path == out and calls["n"] == 1
    assert "2026-10-30" in cap


def test_grid_a_chart_label_b_scales():
    """十二宮格 A(+30%)；走勢圖智能標 B(+50%)；頭欄不准吃這兩條。"""
    assert abs(_GRID_FS_SCALE - 1.30) < 1e-9
    assert abs(_CHART_LABEL_FS_SCALE - 1.50) < 1e-9
    assert abs(_grid_fs(10) - 13.0) < 1e-9
    assert abs(_chart_label_fs(10) - 15.0) < 1e-9
    src = inspect.getsource(_paint_smart_level_labels)
    assert "_y_price_tick_band" in src
    assert "tick_band" in src
    assert "tick_clear_x" in src
    assert "_chart_label_fs" in src
    # #735：同側同角空白座＋虛線不准交錯；合 main 後仍要留著
    assert "prefer_side_up" in src
    assert "_connector_crosses_any" in src
    assert "used_connectors" in src
    assert "_grid_fs(9.5)" in inspect.getsource(
        __import__("intraday_open_close_chart", fromlist=["_paint_quote_grid"])._paint_quote_grid
    )


def test_y_price_tick_band_covers_left_gutter():
    class _Ax:
        def get_xlim(self):
            return (-13.0, 270.0)

        def get_ylim(self):
            return (58.0, 61.5)

    band = _y_price_tick_band(_Ax(), x_span=283.0, y_span=3.5)
    assert band[0] == -13.0
    # 禁區蓋左 gutter，右緣貼近開盤，不准再吃進大半圖
    assert -13.0 < band[1] <= 8.0
    assert band[2] == 58.0
    assert band[3] == 61.5


def test_x_label_pad_keeps_open_near_price_ticks():
    """股價刻度完整在外框內；左 gutter 約 5.5%，不准 12% 大空白、不准框線切字。"""
    import inspect as _ins

    src = _ins.getsource(
        __import__("intraday_open_close_chart", fromlist=["render_path"]).render_path
    )
    assert "* 0.06" in src.split("x_label_pad", 1)[-1][:160]
    assert "0.125" not in src.split("x_label_pad", 1)[-1][:160]
    assert "tick_x" in src
    assert 'ha="left"' in src
    assert "clip_on=False" in src


def test_emerging_intraday_roundtrip_keeps_afternoon(tmp_path):
    """興櫃午後分時要落庫；隔日讀回仍有 13:30 後點，不准只剩 1m 切到 13:29。"""
    from datetime import datetime
    from zoneinfo import ZoneInfo

    import intraday_open_close_chart as ioc

    db = os.path.join(tmp_path, "em.db")
    TP = ZoneInfo("Asia/Taipei")
    ymd = "20261102"
    times = []
    closes = []
    for hm in list(range(900, 1330)) + list(range(1331, 1501)):
        h, m = divmod(hm, 100)
        if m >= 60:
            continue
        times.append(datetime(2026, 11, 2, h, m, tzinfo=TP))
        closes.append(700.0 + (hm % 17))
    n = len(times)
    path = {
        "times": times,
        "opens": list(closes),
        "highs": [c + 1 for c in closes],
        "lows": [c - 1 for c in closes],
        "closes": closes,
        "volumes_lots": [1.0] * n,
        "source": "yahoo:priceByTimes:1m:3595.TWO",
        "n_after_1330": sum(1 for t in times if t.hour * 100 + t.minute > 1330),
    }
    written = ioc.save_emerging_intraday_1m(db, "3595", ymd, path)
    assert written >= 100
    loaded = ioc.load_emerging_intraday_1m(db, "3595", ymd)
    assert loaded is not None
    assert int(loaded.get("n_after_1330") or 0) > 0
    assert loaded["times"][-1].hour * 100 + loaded["times"][-1].minute >= 1500


def test_fetch_intraday_em_prefers_db_afternoon(tmp_path, monkeypatch):
    """Yahoo 隔日吐不出該日 → 走落庫午後，不准 silent 退 1m。"""
    from datetime import datetime
    from zoneinfo import ZoneInfo

    import intraday_open_close_chart as ioc

    db = os.path.join(tmp_path, "em2.db")
    TP = ZoneInfo("Asia/Taipei")
    ymd = "20261102"
    times = [
        datetime(2026, 11, 2, 10, 0, tzinfo=TP),
        datetime(2026, 11, 2, 14, 0, tzinfo=TP),
        datetime(2026, 11, 2, 15, 0, tzinfo=TP),
    ]
    closes = [700.0, 750.0, 754.0]
    path = {
        "times": times,
        "opens": closes,
        "highs": closes,
        "lows": closes,
        "closes": closes,
        "volumes_lots": [1.0, 2.0, 1.0],
        "source": "yahoo:priceByTimes:1m:3595.TWO",
        "n_after_1330": 2,
    }
    assert ioc.save_emerging_intraday_1m(db, "3595", ymd, path) == 3

    monkeypatch.setattr(ioc, "fetch_yahoo_price_by_times", lambda *a, **k: None)

    def _boom(*_a, **_k):
        raise AssertionError("不准退 Yahoo 1m chart")

    monkeypatch.setattr(ioc, "fetch_yahoo_1m_path", _boom)
    got = ioc.fetch_intraday_path("3595", "EM", db_path=db, ymd=ymd)
    assert got is not None
    assert int(got.get("n_after_1330") or 0) >= 2
    assert got["times"][-1].hour >= 15


def test_sync_emerging_triggers_intraday_snapshot():
    import inspect

    from main_runner import MainRunner

    src = inspect.getsource(MainRunner._sync_emerging_required)
    assert "snapshot_emerging_intraday_day" in src


def test_overlay_live_replaces_stale_tpex_yesterday_close():
    """上櫃日收 API 盤中仍吐昨列時，現價／開高低要改吃 live（6274）。"""
    from intraday_open_close_chart import (
        OfficialDay,
        apply_live_quote_to_series,
        overlay_official_day_with_live,
    )
    from dataclasses import replace
    from datetime import datetime
    from zoneinfo import ZoneInfo

    from intraday_open_close_chart import PathSeries

    stale = OfficialDay(
        stock_id="6274",
        open=1130.0,
        high=1145.0,
        low=1010.0,
        close=1115.0,
        prev_close=1090.0,
        volume_lots=19039.0,
        turnover_k=20724863.0,
        avg_price=1088.51,
        pct_change=2.29,
        change=25.0,
        amplitude_pct=12.39,
        q_avg_vol_lots=8300.0,
        w52_high=1920.0,
        w52_low=374.0,
        source="tpex:mainboard_daily_close",
        close_label="收盤",
        prev_volume_lots=11140.0,
        prev_turnover_k=12624605.0,
    )
    live = {
        "stock_id": "6274",
        "open": 1030.0,
        "high": 1045.0,
        "low": 1005.0,
        "close": 1005.0,
        "volume": 9983.0,
        "pct_change": -9.87,
        "change": -110.0,
        "yesterday_close": 1115.0,
        "update_time": "11:55:53",
        "is_realtime": True,
    }
    got = overlay_official_day_with_live(stale, live, path_last=1005.0)
    assert got.close == 1005.0
    assert got.open == 1030.0
    assert got.high == 1045.0
    assert got.low == 1005.0
    assert got.prev_close == 1115.0
    assert got.change == -110.0
    assert abs(got.pct_change + 9.87) < 0.02
    assert got.prev_volume_lots == 19039.0  # 昨列量升成昨量
    assert "+live" in got.source
    assert got.close_label == "現價"

    TP = ZoneInfo("Asia/Taipei")
    series = PathSeries(
        stock_id="6274",
        name="台燿",
        market="TWO",
        times=[datetime(2026, 11, 5, 9, 0, tzinfo=TP), datetime(2026, 11, 5, 11, 37, tzinfo=TP)],
        closes=[1045.0, 1005.0],
        volumes_lots=[10.0, 20.0],
        opens=[1045.0, 1005.0],
        highs=[1045.0, 1005.0],
        lows=[1045.0, 1005.0],
        path_source="test",
        path_end=datetime(2026, 11, 5, 11, 37, tzinfo=TP),
        gap_after=None,
        official=stale,
    )
    out = apply_live_quote_to_series(series, live)
    assert out is not None
    assert out.official.close == 1005.0
    assert out.official.close_label == "現價"


def test_render_lookup_intraday_applies_live_quote():
    src = inspect.getsource(render_lookup_intraday_result)
    assert "apply_live_quote_to_series" in src
    assert "live_quote" in src


def test_resolve_session_official_uses_prev_plus_live_when_today_missing(monkeypatch):
    """上市盤中 STOCK_DAY 尚無今日列（6442）→ 上一日＋live，不准整張沒圖。"""
    from datetime import datetime
    from zoneinfo import ZoneInfo

    import intraday_open_close_chart as ioc

    today = "20261105"
    yest = "20261104"
    scaffold = ioc.OfficialDay(
        stock_id="6442",
        open=1155.0,
        high=1160.0,
        low=1045.0,
        close=1130.0,
        prev_close=1140.0,
        volume_lots=2863.0,
        turnover_k=3171848.0,
        avg_price=1107.0,
        pct_change=-0.88,
        change=-10.0,
        amplitude_pct=10.0,
        q_avg_vol_lots=2500.0,
        w52_high=2540.0,
        w52_low=857.0,
        source="twse:STOCK_DAY",
        close_label="收盤",
        prev_volume_lots=2143.0,
        prev_turnover_k=2526456.0,
    )
    live = {
        "stock_id": "6442",
        "open": 1110.0,
        "high": 1150.0,
        "low": 1040.0,
        "close": 1097.5,
        "volume": 1517.0,
        "pct_change": -2.88,
        "change": -32.5,
        "yesterday_close": 1130.0,
        "update_time": "12:01:56",
        "is_realtime": True,
    }

    def _fake_fetch(sid, market, *, ymd, db_path):
        if ymd == today:
            return None
        if ymd == yest:
            return scaffold
        return None

    monkeypatch.setattr(ioc, "fetch_official", _fake_fetch)
    monkeypatch.setattr(
        "tw_holidays.previous_tw_trading_day", lambda ymd, *_a, **_k: yest
    )
    got = ioc.resolve_session_official_day(
        "6442", "TW", ymd=today, db_path=":memory:", live_quote=live
    )
    assert got is not None
    assert got.close == 1097.5
    assert got.open == 1110.0
    assert got.prev_close == 1130.0
    assert got.close_label == "現價"
    assert "+live" in got.source or got.source == "live_quote"


def test_prepare_lookup_accepts_live_quote_kw():
    src = inspect.getsource(prepare_lookup_intraday_series)
    assert "live_quote" in src
    assert "build_series" in src
