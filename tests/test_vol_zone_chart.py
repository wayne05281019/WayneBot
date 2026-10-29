# -*- coding: utf-8 -*-
"""大量區專圖：不改導航，查股第三張；只認官方原柱。"""
from __future__ import annotations

import os
import sqlite3
import tempfile

import numpy as np
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
    assert "render_lookup_intraday_result" in src
    assert "render_three_in_one_result" not in src
    # 順序：高低溫度卡 → 介紹圖 → 結構圖 → 大量撐壓 → 當天走勢；一次一張、好了就送
    assert "create_task(_struct_item())" in src
    assert "create_task(_vol_item())" in src
    assert "create_task(_intraday_item())" in src
    assert "_bump_progress" in src
    assert src.find("glance_task = asyncio.create_task") < src.find(
        "card_item = await card_render_task"
    )
    assert src.find('current"] = "card"') < src.find("create_task(_struct_item())")
    # 結構 task 與介紹並行（ensure 在 paint 外）；bump struct／volfill 在 await 前
    assert src.find("create_task(_struct_item())") < src.find(
        "struct_item = await struct_task"
    )
    assert "ensure_official_volume_window" in src
    assert "volfill" in src
    assert "glance_queued" in src
    assert "vol_queued" in src
    vol_at = src.find("vol_task = asyncio.create_task(_vol_item())")
    intrad_at = src.find("intrad_task = asyncio.create_task(_intraday_item())")
    struct_await = src.find("struct_item = await struct_task")
    assert vol_at > 0 and struct_await > 0
    assert vol_at < struct_await
    assert intrad_at > vol_at
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
    """結構日K＝與大量撐壓同一套官方原柱；優先 pack bars，不足才長窗／view。"""
    import inspect

    from three_in_one_chart import (
        _bars_from_official,
        _bars_from_pack_face,
        _lookup_structure_bars_and_spot,
        render_lookup_structure_result,
    )

    # 柱組裝抽到 _lookup_structure_bars_and_spot；render 仍走同一套官方柱
    helper = inspect.getsource(_lookup_structure_bars_and_spot)
    src = inspect.getsource(render_lookup_structure_result)
    assert "prepare_volume_zone" in helper
    assert "_bars_from_pack_face" in helper
    assert 'pack.get("bars")' in helper or "pack.get(\"bars\")" in helper
    assert "load_official_ohlc" in helper  # pack bars 不足才退回
    assert "official_work" in helper
    assert 'pack["view"]' in helper  # 長窗也不足才退回 view
    assert "_lookup_structure_bars_and_spot" in src
    assert "_STRUCTURE_LOOKUP_FIG" in src
    assert "VOL_ZONE_FIG_H_NAV" not in src
    bars = inspect.getsource(_bars_from_official)
    assert '"is_halt": halt' in bars
    face = inspect.getsource(_bars_from_pack_face)
    assert "不准再 load_official_ohlc" in face


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
    """畫面用的每一根開高低收量＝庫內官方列，不准漂浮小數還原價。

    開市日軸對齊發明的停價／無量假柱（is_halt／no_trade_fill）不在 daily_quotes，
    略過比對；真官方柱仍須一字不差。
    """
    from vol_zone_chart import load_official_ohlc, official_work

    db = get_db_path()
    con = sqlite3.connect(db)
    for sid in ("2330", "6488", "6274"):
        work = official_work(load_official_ohlc(sid, db, 60))
        assert work is not None and len(work) >= 20
        compared = 0
        for _, row in work.tail(40).iterrows():
            d = str(row["date"])[:8]
            if bool(row.get("is_halt")) or bool(row.get("no_trade_fill")):
                continue
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
            compared += 1
        assert compared >= 15, (sid, compared)
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
    """底軸刻度 index＝該根 K／量；爆大量與最後一根相鄰時只留最後一根月日（防互壓）。"""
    import inspect

    from vol_zone_chart import (
        VOL_ZONE_BARS,
        _paint_volume_zone,
        find_volume_zone,
        load_official_ohlc,
        official_work,
        render_volume_zone_png,
    )

    src = inspect.getsource(_paint_volume_zone)
    assert "abs(int(spike_i) - int(last_i)) <= 2" in src
    assert "linestyle=(0, (1.1, 1.35))" in src  # 爆大量豎線極小間距虛線
    # 日標貼主K上框內側，不准掛回表頭壓圖例；末日豎虛線仍不畫
    assert "貼主K上框內側" in src and "不准掛表頭壓圖例" in src
    assert "axvline(\n            float(xs[-1])" not in src
    assert "axvline(float(xs[-1])" not in src

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


def test_structure_spike_matches_vol_zone_for_2383():
    """查股結構圖撐壓＝大量區專圖（2383：有效大量日 10/06 壓 6115／撐 5820）。"""
    from biaoke_brain import load_bars, volume_first_price
    from vol_zone_chart import find_volume_zone, load_official_ohlc, official_work

    db = get_db_path()
    bars = load_bars(db, "2383")
    st = volume_first_price(bars, lookback=40)
    work = official_work(load_official_ohlc("2383", db, 180))
    zone = find_volume_zone(work, lookback=40)
    assert zone
    assert str(st["spike_date"]).replace("-", "")[:8] == str(zone["date"])[:8]
    assert abs(float(st["spike_high"]) - float(zone["high"])) < 0.51
    assert abs(float(st["spike_low"]) - float(zone["low"])) < 0.51


def test_volume_first_and_find_zone_same_window_synthetic():
    """結構／大量區同 lookback：候選同長、同爆大量日（防 39 vs 40 再分叉）。"""
    from biaoke_brain import volume_first_price
    from vol_zone_chart import VOL_ZONE_LOOKBACK, find_volume_zone

    lb = int(VOL_ZONE_LOOKBACK)
    rows = []
    for i in range(lb + 5):
        rows.append(
            {
                "date": f"2026{100 + i:04d}",
                "open": 100.0,
                "high": 105.0,
                "low": 95.0,
                "close": 100.0,
                "volume": 1000.0 + i,
                "is_halt": False,
            }
        )
    # 恰在「40 候選最舊那根」放壓還在頭上的爆量；若結構少看一根會選別日
    oldest = len(rows) - 1 - lb  # = end - lookback
    rows[oldest]["volume"] = 50000.0
    rows[oldest]["high"] = 120.0
    rows[oldest]["low"] = 80.0
    rows[-1]["close"] = 100.0
    rows[-1]["volume"] = 90000.0  # 末日量再大也不准當參考
    # 次新候選放較小爆量，舊 39 窗會誤鎖這根
    rows[oldest + 1]["volume"] = 40000.0
    rows[oldest + 1]["high"] = 118.0
    rows[oldest + 1]["low"] = 82.0

    st = volume_first_price(rows, lookback=lb)
    zone = find_volume_zone(pd.DataFrame(rows), lookback=lb)
    assert zone is not None
    want = str(rows[oldest]["date"]).replace("-", "")[:8]
    assert str(st["spike_date"]).replace("-", "")[:8] == want
    assert str(zone["date"]).replace("-", "")[:8] == want
    assert float(st["spike_high"]) == float(zone["high"]) == 120.0
    assert float(st["spike_low"]) == float(zone["low"]) == 80.0


def _assert_2233_spike_zone(zone: dict, st: dict) -> None:
    """2233 近窗爆大量：結構＝大量區；lookback=40 滾動後近窗最大日可換，兩圖必須同日。"""
    assert zone and st
    spike = str(zone["date"]).replace("-", "")[:8]
    assert str(st["spike_date"]).replace("-", "")[:8] == spike
    assert abs(float(st["spike_high"]) - float(zone["high"])) < 0.51
    assert abs(float(st["spike_low"]) - float(zone["low"])) < 0.51
    # 08/25（173／157.5）→出窗 08/26（177／163.5）→再滾 10/29 近窗最大 08/27（179.5／172）
    assert spike in ("20260825", "20260826", "20260827"), spike
    if spike == "20260825":
        assert abs(float(zone["high"]) - 173.0) < 0.51
        assert abs(float(zone["low"]) - 157.5) < 0.51
    elif spike == "20260826":
        assert abs(float(zone["high"]) - 177.0) < 0.51
        assert abs(float(zone["low"]) - 163.5) < 0.51
    else:
        assert abs(float(zone["high"]) - 179.5) < 0.51
        assert abs(float(zone["low"]) - 172.0) < 0.51


def test_structure_spike_matches_vol_zone_for_2233():
    """2233 查股兩圖爆大量日必須同日同壓撐（石板試看正式版 bug）。"""
    from biaoke_brain import volume_first_price
    from vol_zone_chart import (
        find_volume_zone,
        load_official_ohlc,
        official_work,
        prepare_lookup_structure_bars,
        prepare_volume_zone,
    )

    db = get_db_path()
    # 與查股同源：只吃完整日官方柱（不准 load_bars 把未齊日帶進來分叉）
    work = official_work(load_official_ohlc("2233", db, 180))
    if work is None or len(work) < 50:
        pytest.skip("2233 bars thin")
    last = str(work["date"].iloc[-1]).replace("-", "")[:8]
    if last < "20261027":
        pytest.skip("need 2233 thru 20261027")
    bars = [
        {
            "date": r.date,
            "open": r.open,
            "high": r.high,
            "low": r.low,
            "close": r.close,
            "volume": r.volume,
            "is_halt": bool(getattr(r, "is_halt", False)),
            "no_trade_fill": bool(getattr(r, "no_trade_fill", False)),
        }
        for r in work.itertuples()
    ]
    st = volume_first_price(bars, lookback=40)
    zone = find_volume_zone(work, lookback=40)
    _assert_2233_spike_zone(zone, st)
    pack = prepare_lookup_structure_bars("2233", "宇隆", db)
    assert pack and pack.get("bars")
    st2 = volume_first_price(pack["bars"], lookback=40)
    vz = prepare_volume_zone(
        "2233",
        "宇隆",
        db,
        preloaded_work=pack["work"],
        known_ensure=pack.get("vol_ensure") or {},
    )
    assert vz and vz.get("zone")
    _assert_2233_spike_zone(vz["zone"], st2)


def test_2233_invent_halt_does_not_split_spike_window():
    """發明假停牌不准讓結構／大量區爆大量日分叉（近窗滾動後日期可換，但兩圖必須同）。"""
    from biaoke_brain import volume_first_price
    from vol_zone_chart import (
        find_volume_zone,
        load_official_ohlc,
        official_work,
        prepare_volume_zone,
    )

    db = get_db_path()
    raw = load_official_ohlc("2233", db, 180)
    if raw is None or getattr(raw, "empty", True):
        pytest.skip("2233 bars thin")
    last = str(raw["date"].iloc[-1]).replace("-", "")[:8]
    if last < "20261027":
        pytest.skip("need 2233 thru 20261027")
    # 強制發明（不吃 confirmed_absent）vs prepare 帶 skip：爆大量日必須同
    invent = official_work(raw, skip_invent_dates=set())
    assert invent is not None
    bars = [
        {
            "date": r.date,
            "open": r.open,
            "high": r.high,
            "low": r.low,
            "close": r.close,
            "volume": r.volume,
            "is_halt": bool(getattr(r, "is_halt", False)),
            "no_trade_fill": bool(getattr(r, "no_trade_fill", False)),
        }
        for r in invent.itertuples()
    ]
    st = volume_first_price(bars, lookback=40)
    zone = find_volume_zone(invent, lookback=40)
    _assert_2233_spike_zone(zone, st)
    vz = prepare_volume_zone("2233", "宇隆", db)
    assert vz and vz.get("zone")
    # prepare（有 skip）與強制發明路徑仍須同爆大量日
    assert str(vz["zone"]["date"]).replace("-", "")[:8] == str(zone["date"]).replace(
        "-", ""
    )[:8]


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


def test_vol_zone_main_tag_is_largest_role_tier():
    """現任主區壓／撐＝大檔同大；下一層＝小檔；大小跟角色不跟文案名。"""
    import inspect

    from biaoke_next_support import LAYER_TAG_PT
    from vol_zone_chart import (
        VOL_ZONE_TAG_PAD,
        VOL_ZONE_TAG_PT,
        _paint_volume_zone,
        render_volume_zone_png,
    )

    from vol_zone_chart import _paint_key_zone_smart_tags

    assert VOL_ZONE_TAG_PT == 11.0
    assert VOL_ZONE_TAG_PT > float(LAYER_TAG_PT)
    assert float(VOL_ZONE_TAG_PAD) >= 0.16
    paint_src = inspect.getsource(_paint_volume_zone)
    key_src = inspect.getsource(_paint_key_zone_smart_tags)
    src = inspect.getsource(render_volume_zone_png) + paint_src + key_src
    assert "_paint_key_zone_smart_tags" in paint_src
    assert "VOL_ZONE_TAG_PT" in key_src
    assert key_src.count("VOL_ZONE_TAG_PT") >= 1
    assert "LAYER_TAG_PT" in paint_src
    assert "現任主區" in src or "find_volume_zone" in src or "VOL_ZONE_TAG_PT" in src


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

    from vol_zone_chart import _paint_key_zone_smart_tags

    src = inspect.getsource(_paint_volume_zone)
    key_src = inspect.getsource(_paint_key_zone_smart_tags)
    assert "head_ratios = [1.28, 3.38, 0.40, 0.98]" in src
    assert "lookup_portrait=False" in inspect.getsource(render_lookup_vol_result)
    assert "transform=ax1.transAxes" in src or "blended_transform_factory" in src
    # v12：主區壓／撐沿線智能掃位；日標仍貼主K上框內側
    assert "_paint_key_zone_smart_tags" in src
    assert "大量區壓" in key_src and "_left_tag_tf" not in src
    assert "貼主K上框內側" in src
    assert "if path_shown:" in src
    # v9：有導航時頂空略加大，橘框不跟箭頭互壓
    assert "ymax = ymax + (ymax - ymin)" in src
    assert "0.985" in src or "0.992" in src
    # 2026-10-29：量標掛上緣空帶；ylim 跟 y_top 走（顯示座標）
    assert "vol_lab_y" in src and ("set_ylim(0, float(y_top))" in src or "vol_ylim" in src)
    assert 'va="top"' in src
    assert "/ 0.78" in src
    assert "configure_lookup_vol_axis" in src
    # 主區只留桃色帶，不准再畫壓／撐水平線
    assert "ax1.axhline(hi" not in src
    assert "ax1.axhline(lo" not in src
    assert "ax1.axhspan(lo, hi" in src


def test_volume_bars_one_per_traded_day_3081():
    """結構／大量撐壓：每個交易日都有柱；0 量也貼底，不准挖洞（3081 洞型）。"""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    from biaoke_chart import analyze_structure
    from vol_zone_chart import load_official_ohlc, official_work
    from wayne_navigator import (
        LOOKUP_VOL_FLOOR_FACE,
        LOOKUP_VOL_FLOOR_FRAC,
        LOOKUP_VOL_MIN_VISIBLE_FRAC,
        nav_volume_bar_heights,
        paint_lookup_volume_bars,
    )
    from matplotlib.colors import to_rgb

    db = get_db_path()
    work = official_work(load_official_ohlc("3081", db, 180))
    assert work is not None and len(work) >= 20
    vols = [float(v or 0) for v in work["volume"].tolist()]
    heights, ylim, missing = nav_volume_bar_heights(vols)
    assert len(heights) == len(work)
    pos = 0
    zero_days = []
    for i, row in work.iterrows():
        v = float(row["volume"] or 0)
        if v > 0 and not bool(missing[pos]):
            assert float(heights[pos]) > 0, (str(row["date"]), v)
        if v <= 0 or bool(missing[pos]) or bool(row.get("is_halt", False)):
            zero_days.append(pos)
        pos += 1
    info = analyze_structure(work.to_dict("records"))
    struct_vols = info.get("vols") or vols[-len(info.get("closes") or vols) :]
    sh, _, sm = nav_volume_bar_heights(struct_vols)
    assert len(sh) == len(struct_vols)
    for i, v in enumerate(struct_vols):
        if float(v or 0) > 0 and not bool(sm[i]):
            assert float(sh[i]) > 0, i
    assert float(ylim) > 0

    # 畫圖層：每個 index 都有可見柱（正量 bar 或貼底灰短柱）
    n = len(work)
    xs = list(range(n))
    opens = work["open"].to_numpy(dtype=float)
    closes = work["close"].to_numpy(dtype=float)
    halt = (
        work["is_halt"].fillna(False).astype(bool).to_numpy()
        if "is_halt" in work.columns
        else np.zeros(n, dtype=bool)
    )
    from wayne_navigator import lookup_candle_up_mask

    up = lookup_candle_up_mask(opens, closes, halt=halt)
    fig, ax = plt.subplots(figsize=(8, 1.5))
    paint_lookup_volume_bars(ax, xs, work["volume"], up, halt=halt)
    floor_rgb = to_rgb(LOOKUP_VOL_FLOOR_FACE)
    occupied = set()
    floor_n = 0
    for p in ax.patches:
        if float(p.get_height()) <= 0:
            continue
        occupied.add(int(round(float(p.get_x()) + float(p.get_width()) / 2.0)))
        fc = p.get_facecolor()
        if isinstance(fc, tuple) and len(fc) >= 3:
            if all(abs(a - b) < 0.02 for a, b in zip(fc[:3], floor_rgb)):
                floor_n += 1
                assert abs(float(p.get_height()) - float(ylim) * LOOKUP_VOL_FLOOR_FRAC) < 1e-6
    assert occupied == set(range(n)), sorted(set(range(n)) - occupied)
    assert floor_n == len(zero_days) or floor_n >= len(zero_days)
    # 開方顯示後正量柱應高於灰短柱；最低可視只擋極端貼底
    from wayne_navigator import lookup_vol_to_display

    floor_h = float(ylim) * LOOKUP_VOL_FLOOR_FRAC
    min_h = float(ylim) * LOOKUP_VOL_MIN_VISIBLE_FRAC
    pos_draw = {}
    for p in ax.patches:
        cx = int(round(float(p.get_x()) + float(p.get_width()) / 2.0))
        pos_draw[cx] = max(pos_draw.get(cx, 0.0), float(p.get_height()))
    pos_heights = []
    for pos in range(len(work)):
        v = float(work.iloc[pos]["volume"] or 0)
        if v > 0 and float(heights[pos]) > 0 and pos not in zero_days:
            dh = float(lookup_vol_to_display([float(heights[pos])], float(ylim))[0])
            got = float(pos_draw.get(pos, 0.0))
            assert got >= min(dh, min_h) * 0.54 - 1e-6, (pos, got, dh, min_h)
            assert got > floor_h + 1e-9
            pos_heights.append(got)
    # 一般量日彼此要看得出起伏（不准大半同一高度）
    if len(pos_heights) >= 8:
        assert len({round(h, 1) for h in pos_heights}) >= 5
    # 3081 近窗應有停價 0 量日（洞型樣本）；沒有也不准回歸回挖洞
    if zero_days:
        assert floor_n >= 1
    plt.close(fig)


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
    assert LOOKUP_CANDLE_BODY_W == 0.70
    assert LOOKUP_VOL_BAR_W == 0.84
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


def test_load_official_ohlc_drops_incomplete_after_as_of(tmp_path, monkeypatch):
    """讀圖丟掉完整日之後殘列，免盤中未齊柱擠爆大量近窗／與高低卡分叉。"""
    from vol_zone_chart import load_official_ohlc

    db = str(tmp_path / "wayne_market.db")
    monkeypatch.setattr(
        "quote_integrity.db_as_of_trading_date", lambda *_a, **_k: "20261027"
    )
    conn = sqlite3.connect(db)
    conn.execute(
        """
        CREATE TABLE daily_quotes (
            date TEXT, stock_id TEXT, stock_name TEXT, market TEXT,
            open REAL, high REAL, low REAL, close REAL, volume REAL,
            PRIMARY KEY (date, stock_id)
        )
        """
    )
    for d, c, v in (("20261022", 144.5, 595), ("20261027", 149.0, 446), ("20261028", 149.5, 193)):
        conn.execute(
            "INSERT INTO daily_quotes VALUES (?,?,?,?,?,?,?,?,?)",
            (d, "2233", "宇隆", "TW", c, c + 1, c - 1, c, v),
        )
    conn.commit()
    conn.close()
    df = load_official_ohlc("2233", db, 60)
    dates = {str(x).replace("-", "")[:8] for x in df["date"].tolist()}
    assert "20261027" in dates
    assert "20261028" not in dates


def test_vol_zone_no_prev_close_right_tag():
    """大量區右軸不准再畫「昨收」白底標（與今收／壓撐重複干擾）。"""
    src = open("vol_zone_chart.py", encoding="utf-8").read()
    assert 'f"昨收 {_fmt_price(prev_c)}"' not in src
    assert "右軸空位補昨收" not in src
    assert "不准再畫「昨收」白底標" in src
