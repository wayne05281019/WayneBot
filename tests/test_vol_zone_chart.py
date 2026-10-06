# -*- coding: utf-8 -*-
"""大量區專圖：不改導航，查股第三張；只認官方原柱。"""
from __future__ import annotations

import os
import sqlite3
import tempfile

import pandas as pd
import pytest

from config import get_db_path

pytestmark = pytest.mark.production_db


def test_find_volume_zone_prefers_active_overhead():
    from vol_zone_chart import find_volume_zone

    work = pd.DataFrame(
        [
            {
                "date": "20260806",
                "open": 1405,
                "high": 1530,
                "low": 1365,
                "close": 1530,
                "volume": 16305,
                "is_halt": False,
            },
            {
                "date": "20260917",
                "open": 1445,
                "high": 1460,
                "low": 1275,
                "close": 1320,
                "volume": 21653,
                "is_halt": False,
            },
            {
                "date": "20260924",
                "open": 1485,
                "high": 1530,
                "low": 1475,
                "close": 1495,
                "volume": 10047,
                "is_halt": False,
            },
        ]
    )
    zone = find_volume_zone(work, lookback=40)
    assert zone["date"] == "20260806"
    assert zone["high"] == 1530
    assert zone["low"] == 1365
    assert zone["active"] is True


def test_find_volume_zone_excludes_last_bar():
    """最後一根即使量最大也不當大量區參考日。"""
    from vol_zone_chart import find_volume_zone

    work = pd.DataFrame(
        [
            {
                "date": "20260901",
                "open": 100,
                "high": 120,
                "low": 90,
                "close": 110,
                "volume": 5000,
                "is_halt": False,
            },
            {
                "date": "20260902",
                "open": 110,
                "high": 115,
                "low": 105,
                "close": 112,
                "volume": 90000,
                "is_halt": False,
            },
        ]
    )
    zone = find_volume_zone(work, lookback=40)
    assert zone["date"] == "20260901"
    assert zone["volume"] == 5000


def test_render_volume_zone_png_6274():
    from vol_zone_chart import find_volume_zone, load_official_ohlc, official_work, render_volume_zone_png

    db = get_db_path()
    work = official_work(load_official_ohlc("6274", db, 180))
    zone = find_volume_zone(work)
    # 爆大量日隨近窗／新收滾動，只鎖結構：有區、高低合理、對得上該根官方柱
    assert zone and str(zone["date"]).isdigit() and len(str(zone["date"])) == 8
    assert float(zone["high"]) > float(zone["low"]) > 0
    zi = int(zone["i"])
    assert 0 <= zi < len(work)
    assert str(work["date"].iloc[zi])[:8] == str(zone["date"])[:8]
    assert abs(float(work["high"].iloc[zi]) - float(zone["high"])) < 1e-6
    assert abs(float(work["low"].iloc[zi]) - float(zone["low"])) < 1e-6
    last = work.iloc[-1]
    assert str(last["date"])[:8] >= "20260924"
    assert float(last["close"]) > 0
    assert float(last["high"]) >= float(last["close"])
    with tempfile.TemporaryDirectory() as tmp:
        out = os.path.join(tmp, "6274_vz.png")
        path = render_volume_zone_png("6274", "台燿", db, out)
        assert path and os.path.isfile(path)
        assert os.path.getsize(path) > 20000


def test_lookup_sends_four_photos_card_glance_struct_vol():
    import inspect

    from bot_servers import WayneTelegramBot

    src = inspect.getsource(WayneTelegramBot._send_card_to_locked)
    assert "render_lookup_structure_result" in src
    assert "render_lookup_vol_result" in src
    assert "render_three_in_one_result" not in src
    # 順序：高低溫度卡 → 介紹圖 → 結構圖 → 大量撐壓；一次一張、好了就送
    assert "create_task(_struct_item())" in src
    assert "create_task(_vol_item())" in src
    assert "_bump_progress" in src
    assert src.find("glance_task = asyncio.create_task") < src.find(
        "card_item = await card_render_task"
    )
    assert src.find('current"] = "card"') < src.find("create_task(_struct_item())")
    assert src.find("create_task(_struct_item())") < src.find(
        'await _bump_progress("struct")'
    )
    assert src.find('await _bump_progress("struct")') < src.find(
        "create_task(_vol_item())"
    )
    assert "kind=kind" in src
    # 不准把決策卡還原 ohlc 當撐壓柱
    assert "already_normalized=True" not in src
    assert "③壓力不准盤中假柱" in src or "只吃官方原柱" in src
    # 興櫃與上市櫃同一條；is_em 只給鍵盤／標籤
    assert "is_em = self._hit_is_emerging" in src
    assert "if is_em:\n                return None" not in src
    assert "merge_live=True" in src
    assert "merge_live=not is_em" not in src
    nav = open("wayne_navigator.py", encoding="utf-8").read()
    assert "_paint_nav_volume_zone" not in nav
    assert "大量區壓" not in nav
    tio = open("three_in_one_chart.py", encoding="utf-8").read()
    assert "with_nav_signals=True" in tio
    assert "LOCK_KEY" in tio and "T0118" in tio
    vz = open("vol_zone_chart.py", encoding="utf-8").read()
    assert "with_nav_signals=True" in vz
    assert "render_lookup_vol_result" in vz


def test_lookup_structure_uses_vol_zone_view():
    """結構日K＝大量撐壓同一套官方 view，停牌灰K；橫式滿版對齊範本五。"""
    import inspect

    from three_in_one_chart import _bars_from_official, render_lookup_structure_result

    src = inspect.getsource(render_lookup_structure_result)
    assert "prepare_volume_zone" in src
    assert 'pack["view"]' in src
    assert "_STRUCTURE_LOOKUP_FIG" in src
    assert "VOL_ZONE_FIG_H_NAV" not in src
    bars = inspect.getsource(_bars_from_official)
    assert '"is_halt": halt' in bars


def test_vol_zone_http_not_inside_mpl_lock():
    import inspect

    from vol_zone_chart import prepare_volume_zone, render_volume_zone_png, render_volume_zone_result

    prep = inspect.getsource(prepare_volume_zone)
    assert "hydrate_official_ex_for_gaps" in prep
    assert "load_official_ohlc" in prep
    assert "mpl_render" not in prep
    res = inspect.getsource(render_volume_zone_result)
    assert res.find("prepare_volume_zone") < res.find("mpl_render")
    assert "_paint_volume_zone" in inspect.getsource(render_volume_zone_png) + res


def test_vol_zone_ignores_adjusted_card_ohlc():
    """有 db 時即使塞入除權還原假價，仍畫官方原柱高低。"""
    from vol_zone_chart import find_volume_zone, load_official_ohlc, official_work, render_volume_zone_png

    db = get_db_path()
    work = official_work(load_official_ohlc("2330", db, 180))
    zone = find_volume_zone(work)
    assert zone and str(zone["date"]).isdigit()
    z_date = str(zone["date"])[:8]
    z_hi, z_lo = float(zone["high"]), float(zone["low"])
    assert z_hi > z_lo > 0
    # 假還原價：把爆大量日高低改成非整數
    fake = work.copy()
    fake.loc[fake["date"].astype(str).str.replace("-", "").str[:8] == z_date, "high"] = z_hi - 7.363
    fake.loc[fake["date"].astype(str).str.replace("-", "").str[:8] == z_date, "low"] = z_lo - 7.231
    with tempfile.TemporaryDirectory() as tmp:
        out = os.path.join(tmp, "2330_vz.png")
        path = render_volume_zone_png("2330", "台積電", db, out, fake)
        assert path and os.path.isfile(path)
    # 選區仍以官方為準（不吃假還原）
    z2 = find_volume_zone(official_work(load_official_ohlc("2330", db, 180)))
    assert str(z2["date"])[:8] == z_date
    assert abs(float(z2["high"]) - z_hi) < 1e-6
    assert abs(float(z2["low"]) - z_lo) < 1e-6


def test_vol_zone_bars_match_db_exactly():
    """畫面用的每一根開高低收量＝庫內官方列，不准漂浮小數還原價。"""
    from vol_zone_chart import load_official_ohlc, official_work

    db = get_db_path()
    con = sqlite3.connect(db)
    for sid in ("2330", "6488", "6274"):
        work = official_work(load_official_ohlc(sid, db, 60))
        assert work is not None and len(work) >= 20
        for _, row in work.tail(30).iterrows():
            d = str(row["date"])
            db_row = con.execute(
                "SELECT open,high,low,close,volume FROM daily_quotes WHERE stock_id=? AND date=?",
                (sid, d),
            ).fetchone()
            assert db_row, (sid, d)
            assert float(row["open"]) == float(db_row[0])
            assert float(row["high"]) == float(db_row[1])
            assert float(row["low"]) == float(db_row[2])
            assert float(row["close"]) == float(db_row[3])
            assert float(row["volume"]) == float(db_row[4])
            # 官方整數價不該出現還原漂浮
            for col in ("open", "high", "low", "close"):
                v = float(row[col])
                assert abs(v - round(v, 2)) < 1e-9, (sid, d, col, v)
    con.close()


def test_render_volume_zone_png_markets_twse_otc_emerging():
    """上市／上櫃／興櫃都能渲出大量區專圖（查股第三張同一條）。"""
    from vol_zone_chart import find_volume_zone, load_official_ohlc, official_work, render_volume_zone_png

    db = get_db_path()
    cases = [
        ("2330", "台積電", "twse"),
        ("6488", "環球晶", "otc"),
        ("1260", "FLAVOR", "emerging"),
    ]
    with tempfile.TemporaryDirectory() as tmp:
        for sid, name, kind in cases:
            raw = load_official_ohlc(sid, db, 120)
            work = official_work(raw)
            assert work is not None and len(work) >= 5, (sid, kind)
            assert work["dt"].iloc[0] <= work["dt"].iloc[-1], (sid, kind)
            if kind == "emerging":
                assert str(raw["quote_source"].iloc[-1]) == "emerging_quotes"
            zone = find_volume_zone(work)
            assert zone and zone["high"] > 0 and zone["low"] > 0, (sid, kind)
            out = os.path.join(tmp, f"{sid}_vz.png")
            path = render_volume_zone_png(sid, name, db, out)
            assert path and os.path.isfile(path), (sid, kind)
            assert os.path.getsize(path) > 15000, (sid, kind, os.path.getsize(path))


def test_vol_zone_xaxis_matches_k_and_volume_index():
    """底軸刻度 index＝該根 K／量；爆大量日與最後一根一定標月日。"""
    from vol_zone_chart import (
        VOL_ZONE_BARS,
        find_volume_zone,
        load_official_ohlc,
        official_work,
        render_volume_zone_png,
    )

    db = get_db_path()
    work = official_work(load_official_ohlc("6274", db, 180))
    zone = find_volume_zone(work)
    assert zone and str(zone["date"]).isdigit()
    z_date = str(zone["date"])[:8]
    n_all = len(work)
    show_n = min(max(VOL_ZONE_BARS, 30), n_all)
    start = max(0, n_all - show_n)
    if int(zone["i"]) < start:
        start = max(0, int(zone["i"]) - 8)
    view = work.iloc[start:].reset_index(drop=True)
    spike_i = int(zone["i"]) - start
    assert str(view["date"].iloc[spike_i])[:8] == z_date
    assert str(view["date"].iloc[-1]) == str(work["date"].iloc[-1])
    assert view["dt"].iloc[0] < view["dt"].iloc[-1]
    with tempfile.TemporaryDirectory() as tmp:
        out = os.path.join(tmp, "6274_axis.png")
        path = render_volume_zone_png("6274", "台燿", db, out)
        assert path and os.path.isfile(path)


def test_vol_zone_uses_shared_volume_heights():
    """大量區量柱與導航同一套線性比例高度（視窗 max＝滿高）。"""
    import inspect

    from vol_zone_chart import _paint_volume_zone
    from wayne_navigator import paint_lookup_volume_bars

    src = inspect.getsource(_paint_volume_zone)
    assert "paint_lookup_volume_bars" in src
    assert "view[\"volume\"]" in src or "view['volume']" in src
    assert "0.32" not in src  # 不准再抬 32% 假地板
    vol_src = inspect.getsource(paint_lookup_volume_bars)
    assert "nav_volume_bar_heights" in vol_src

    """話筒紅圈：大量區壓／撐要比標題更容易讀。"""
    import inspect

    from vol_zone_chart import VOL_ZONE_TAG_PT, _paint_volume_zone, render_volume_zone_png

    assert VOL_ZONE_TAG_PT >= 14
    src = inspect.getsource(render_volume_zone_png) + inspect.getsource(_paint_volume_zone)
    assert "VOL_ZONE_TAG_PT" in src


def test_emerging_help_mentions_three_in_one():
    import inspect

    from bot_servers import WayneTelegramBot

    src = inspect.getsource(WayneTelegramBot._em_no_listed_html)
    assert "高低溫度卡" in src
    assert "結構圖" in src
    assert "大量撐壓" in src
    mod = open("bot_servers.py", encoding="utf-8").read(900)
    assert "上市／上櫃／興櫃一律" in mod
    assert "結構圖" in mod
    assert "大量撐壓" in mod


def test_official_work_drops_live_and_keeps_raw_prices():
    from vol_zone_chart import official_work

    df = pd.DataFrame(
        [
            {
                "date": "20260901",
                "open": 100.0,
                "high": 110.0,
                "low": 90.0,
                "close": 105.0,
                "volume": 1000,
                "is_live": False,
            },
            {
                "date": "20260902",
                "open": 105.0,
                "high": 120.0,
                "low": 100.0,
                "close": 118.0,
                "volume": 2000,
                "is_live": True,
            },
        ]
    )
    work = official_work(df)
    assert list(work["date"]) == ["20260901"]
    assert float(work.iloc[0]["high"]) == 110.0


def test_lookup_vol_gives_header_space_from_volume_blank():
    import inspect

    from vol_zone_chart import _paint_volume_zone, render_lookup_vol_result

    src = inspect.getsource(_paint_volume_zone)
    assert "head_ratios = [1.28, 3.38, 0.40, 0.98]" in src
    assert "lookup_portrait=False" in inspect.getsource(render_lookup_vol_result)
    assert "transform=ax1.transAxes" in src
    assert "0.975" in src
    assert "ymax = ymax + (ymax - ymin) * 0.12" in src
    assert "0.985" in src or "0.992" in src
    assert "set_ylim(0, max(vol_ylim * 1.30" in src


def test_volume_bars_one_per_traded_day_3081():
    """結構／大量撐壓：每個有量交易日都有柱，不准缺口。"""
    from biaoke_chart import analyze_structure
    from vol_zone_chart import load_official_ohlc, official_work
    from wayne_navigator import nav_volume_bar_heights

    db = get_db_path()
    work = official_work(load_official_ohlc("3081", db, 180))
    assert work is not None and len(work) >= 20
    vols = [float(v or 0) for v in work["volume"].tolist()]
    heights, ylim, missing = nav_volume_bar_heights(vols)
    assert len(heights) == len(work)
    pos = 0
    for i, row in work.iterrows():
        v = float(row["volume"] or 0)
        if v > 0 and not bool(missing[pos]):
            assert float(heights[pos]) > 0, (str(row["date"]), v)
        pos += 1
    info = analyze_structure(work.to_dict("records"))
    struct_vols = info.get("vols") or vols[-len(info.get("closes") or vols) :]
    sh, _, sm = nav_volume_bar_heights(struct_vols)
    assert len(sh) == len(struct_vols)
    for i, v in enumerate(struct_vols):
        if float(v or 0) > 0 and not bool(sm[i]):
            assert float(sh[i]) > 0, i
    assert float(ylim) > 0


def test_lookup_candle_paint_shared():
    """結構／大量／導航共用同一套 K／量柱常數與 paint。"""
    import inspect

    import biaoke_chart
    import vol_zone_chart
    from wayne_navigator import (
        LOOKUP_CANDLE_BODY_W,
        LOOKUP_CANDLE_DN,
        LOOKUP_CANDLE_UP,
        LOOKUP_VOL_BAR_W,
        paint_lookup_ohlc_candles,
        paint_lookup_volume_bars,
    )

    assert LOOKUP_CANDLE_UP == "#e53935"
    assert LOOKUP_CANDLE_DN == "#00897b"
    assert LOOKUP_CANDLE_BODY_W == 0.60
    assert LOOKUP_VOL_BAR_W == 0.70
    assert biaoke_chart._UP == LOOKUP_CANDLE_UP
    assert biaoke_chart._DN == LOOKUP_CANDLE_DN
    vz = inspect.getsource(vol_zone_chart._paint_volume_zone)
    assert "paint_lookup_ohlc_candles" in vz
    assert "paint_lookup_volume_bars" in vz
    bc = inspect.getsource(biaoke_chart.render_biaoke_structure_png)
    assert "paint_lookup_ohlc_candles" in bc
    assert "paint_lookup_volume_bars" in bc
    assert paint_lookup_ohlc_candles and paint_lookup_volume_bars


def test_industry_font_matches_card_noto():
    from industry_card import _card_font

    f = _card_font(28, bold=True)
    path = str(getattr(f, "path", "") or "")
    assert "NotoSansTC" in path


@pytest.mark.production_db
def test_cross_chart_last_close_aligned_2383():
    """同一檔同一 as_of：高低卡收盤＝大量撐壓 view 收盤。"""
    from vol_zone_chart import prepare_volume_zone
    from wayne_navigator import NavigatorEngine

    db = get_db_path()
    card = NavigatorEngine(db).get_decision_card("2383", merge_live=False)
    assert card and not card.get("error")
    pack = prepare_volume_zone("2383", "台光電", db, "/tmp/vz-align-2383.png")
    assert pack and pack.get("view") is not None
    last = pack["view"].iloc[-1]
    v_date = str(last["date"]).replace("-", "")[:8]
    c_date = str(card.get("latest_date") or "").replace("-", "")[:8]
    assert v_date == c_date
    assert abs(float(last["close"]) - float(card.get("close"))) < 1e-6
