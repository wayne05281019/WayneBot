# -*- coding: utf-8 -*-
from datetime import date, timedelta

from biaoke_chart import (
    BIAOKE_CHART_DPI,
    _axis_ticks,
    _paint_locator_quote,
    _paint_spot,
    _spot_quote,
    analyze_structure,
    chart_caption,
    header_banner_lines,
    neuron_glance,
    render_biaoke_structure_png,
    stock_display_glance,
    stock_nameplate,
)


def _series():
    """爆大量後跌破再站回，後面兩個更低的高。"""
    day = date(2026, 7, 1)
    rows = []
    px = 100.0
    for i in range(36):
        d = (day + timedelta(days=i)).strftime("%Y%m%d")
        if i == 12:
            o, h, l, c, v = 130, 148, 120, 140, 20000
        elif i == 15:
            o, h, l, c, v = 128, 130, 110, 118, 4000
        elif i == 18:
            o, h, l, c, v = 120, 126, 118, 124, 1800
        elif i == 24:
            o, h, l, c, v = 128, 136, 126, 130, 2200
        elif i == 30:
            o, h, l, c, v = 128, 132, 124, 126, 1600
        else:
            px = 100 + i * 1.2
            o, h, l, c, v = px, px + 3, px - 3, px + 1, 1200
        rows.append(
            {
                "date": d,
                "stock_id": "3035",
                "stock_name": "智原",
                "open": o,
                "high": h,
                "low": l,
                "close": c,
                "volume": v,
                "pct_change": 0,
            }
        )
    return rows


def test_structure_flags_wash_and_volume_lines():
    info = analyze_structure(_series())
    assert info.get("struct", {}).get("spike_high") == 148
    assert info.get("struct", {}).get("spike_low") == 120
    assert info.get("wash") is True
    notes = " ".join(info.get("notes") or [])
    assert "爆大量那一天" in notes
    assert "當壓" in notes
    assert "當撐" in notes
    assert "洗盤" in notes
    cap = chart_caption(info, sid="3035", name="智原")
    assert "不是介紹圖" not in cap
    assert "決策卡" not in cap
    assert "5／9" not in cap and "5/9" not in cap
    assert "日K" in cap or "日 K" in cap or "官方日K" in cap
    assert "不是15分" not in cap
    assert "量先價行" in cap
    assert "爆大量那一天" in cap
    assert "演算" in cap
    assert "不是保證" in cap
    assert "延伸線已建檔" not in cap
    assert "介入買點首先" not in cap
    assert "橙底" not in cap
    assert "這不是買訊" not in cap
    proj = info.get("project") or {}
    assert proj.get("key") == "wash"
    assert abs(float(proj.get("target") or 0) - 148) < 1e-6
    assert "圖上演算" in notes


def _distribution_series():
    """爆大量後先過壓，再掉回撐下＝出貨不是洗盤。"""
    day = date(2026, 7, 1)
    rows = []
    for i in range(28):
        d = (day + timedelta(days=i)).strftime("%Y%m%d")
        if i == 8:
            o, h, l, c, v = 100, 120, 96, 118, 18000
        elif i == 14:
            o, h, l, c, v = 118, 128, 116, 126, 4000
        elif i == 20:
            o, h, l, c, v = 110, 114, 92, 94, 3500
        elif i == 27:
            o, h, l, c, v = 95, 98, 90, 92, 1600
        else:
            px = 102 + i * 0.4
            o, h, l, c, v = px, px + 2, px - 2, px + 0.5, 1100
        rows.append(
            {
                "date": d,
                "stock_id": "3035",
                "stock_name": "智原",
                "open": o,
                "high": h,
                "low": l,
                "close": c,
                "volume": v,
                "pct_change": 0,
            }
        )
    return rows


def test_structure_flags_distribution_not_wash():
    info = analyze_structure(_distribution_series())
    assert info.get("struct", {}).get("spike_high") == 120
    assert info.get("struct", {}).get("spike_low") == 96
    assert info.get("distribution") is True
    assert info.get("wash") is False
    notes = " ".join(info.get("notes") or [])
    assert "出貨" in notes
    assert "洗盤" not in notes or "不是洗盤" in notes
    proj = info.get("project") or {}
    assert proj.get("key") == "distribution"
    assert abs(float(proj.get("target") or 0) - 96) < 1e-6
    cap = chart_caption(info, sid="3035", name="智原")
    assert "演算" in cap
    assert "不是保證" in cap


def test_render_structure_png(tmp_path):
    from PIL import Image

    out = str(tmp_path / "biaoke.png")
    path = render_biaoke_structure_png(_series(), out, sid="3035", name="智原")
    assert path and path == out
    assert Image.open(path).size[0] >= 1000
    assert (tmp_path / "biaoke.png").stat().st_size > 24_000


def test_caption_and_chart_carry_six_neurons_without_lecture(tmp_path):
    from PIL import Image

    info = analyze_structure(_series())
    fired = {
        "think": "問的是 3035 智原。大盤官方收還在 45839 之上。",
        "steps": [
            {"id": "nest", "text": "現在位階 2026-09-15 逃命波C-2（未確認）。官方收還在 45839 之上。"},
            {"id": "field", "text": "個股最重要是產業趨勢還在不在；技術分析最有用在大盤。 IC 設計這族材料還在。"},
            {"id": "leader", "text": "自己就是這族龍頭（官方沒另點）。"},
            {"id": "hold", "text": "4/16 可抱到明年。長線龍頭股切勿輕易調節。"},
            {"id": "doubt", "text": "公開文沒點名這檔，可能看錯。"},
        ],
    }
    glance = neuron_glance(fired)
    assert glance.get("nest", "").startswith("現在位階")
    assert "IC" in (glance.get("field") or "")
    assert "個股最重要是產業趨勢" not in (glance.get("field") or "")
    assert glance.get("leader") == "自己就是這族龍頭"
    assert glance.get("hold") == "長抱：可抱到明年，勿輕易調節"
    assert "公開文沒點名" in (glance.get("doubt") or "")
    shown_3035 = stock_display_glance(glance, sid="3035")
    assert "nest" not in shown_3035
    assert "hold" not in shown_3035
    shown_2383 = stock_display_glance(glance, sid="2383")
    assert "nest" not in shown_2383
    assert shown_2383.get("hold") == "長抱：可抱到明年，勿輕易調節"
    cap = chart_caption(info, sid="3035", name="智原", glance=glance)
    assert "介入買點首先" not in cap
    assert "先看大盤巢穴會不會覆巢" not in cap
    assert "個股最重要是產業趨勢" not in cap
    assert "現在位階" not in cap
    assert "逃命波" not in cap
    assert "勿輕易調節" not in cap
    assert "自己就是這族龍頭" not in cap
    assert "爆大量那一天" in cap
    assert "量先價行" in cap
    assert "這不是買訊" not in cap
    cap_hold = chart_caption(
        info,
        sid="2383",
        name="台光電",
        glance=glance,
        plate={"leader": "龍頭"},
    )
    assert "現在位階" not in cap_hold
    assert "逃命波" not in cap_hold
    assert "勿輕易調節" in cap_hold
    cap_other = chart_caption(info, sid="2466", name="冠西電", glance=glance)
    assert "現在位階" not in cap_other
    assert "勿輕易調節" not in cap_other
    out = str(tmp_path / "biaoke-glance.png")
    path = render_biaoke_structure_png(
        _series(), out, sid="3035", name="智原", glance=glance
    )
    assert path and Image.open(path).size[0] >= 1000
    assert (tmp_path / "biaoke-glance.png").stat().st_size > 24_000


def test_real_daily_quotes_numbers_are_exact():
    import os

    from biaoke_brain import load_bars

    from tests.conftest import require_production_db

    db = require_production_db()
    bars = load_bars(db, "2383", n=120)
    if len(bars) < 40:
        return
    work = bars[-60:]
    info = analyze_structure(work)
    st = info.get("struct") or {}
    lookback = min(40, len(work))
    window = work[-lookback:]
    spike = max(window, key=lambda r: float(r.get("volume") or 0))
    last = work[-1]
    assert float(st.get("spike_high")) == float(spike["high"])
    assert float(st.get("spike_low")) == float(spike["low"])
    assert str(st.get("spike_date") or "").replace("-", "")[:8] == str(spike["date"]).replace("-", "")[:8]
    assert float((info.get("spike_bar") or {}).get("volume")) == float(spike["volume"])
    cap = chart_caption(info, sid="2383", name="台光電")
    assert _px_from_bar(spike["high"]) in cap
    assert _px_from_bar(spike["low"]) in cap
    assert _px_from_bar(last["close"]) in cap
    assert str(int(round(float(spike["volume"])))) in cap.replace(",", "")
    notes = " ".join(info.get("notes") or [])
    assert "3930" in notes or _px_from_bar(spike["low"]) in notes
    proj = info.get("project") or {}
    assert proj.get("key") != "abandon"
    assert float(proj.get("target") or 0) > 0
    assert "圖上演算" in notes
    assert "不是保證" in str(proj.get("label") or "")


def _px_from_bar(val):
    from biaoke_chart import _px

    return _px(val)


def _barely_over_series():
    """剛過壓：最可能先當壓轉撐，不把連點延長當保證續漲。"""
    day = date(2026, 7, 1)
    rows = []
    for i in range(28):
        d = (day + timedelta(days=i)).strftime("%Y%m%d")
        if i == 8:
            o, h, l, c, v = 100, 120, 96, 118, 18000
        elif i == 16:
            o, h, l, c, v = 128, 136, 126, 130, 2200
        elif i == 22:
            o, h, l, c, v = 126, 132, 124, 128, 1800
        elif i == 27:
            o, h, l, c, v = 119, 123, 118, 121, 1400
        else:
            px = 108 + i * 0.3
            o, h, l, c, v = px, px + 2, px - 2, min(px + 0.4, 119), 1100
        rows.append(
            {
                "date": d,
                "stock_id": "2454",
                "stock_name": "聯發科",
                "open": o,
                "high": h,
                "low": l,
                "close": c,
                "volume": v,
                "pct_change": 0,
            }
        )
    return rows


def _clearly_over_with_down_rail():
    """明顯過壓但下降連點還壓著：最可能碰到連點延長，不是保證續漲。"""
    day = date(2026, 7, 1)
    rows = []
    for i in range(36):
        d = (day + timedelta(days=i)).strftime("%Y%m%d")
        if i == 6:
            o, h, l, c, v = 100, 110, 90, 108, 20000
        elif i == 18:
            o, h, l, c, v = 140, 150, 138, 145, 3000
        elif i == 26:
            o, h, l, c, v = 136, 147, 134, 140, 2500
        elif i == 35:
            o, h, l, c, v = 128, 132, 126, 130, 1800
        else:
            px = 100 + i * 0.8
            o, h, l, c, v = px, px + 2, px - 2, px, 1200
        rows.append(
            {
                "date": d,
                "stock_id": "2383",
                "stock_name": "台光電",
                "open": o,
                "high": h,
                "low": l,
                "close": c,
                "volume": v,
                "pct_change": 0,
            }
        )
    return rows


def test_project_barely_over_holds_old_press():
    info = analyze_structure(_barely_over_series())
    assert info.get("over_press") is True
    proj = info.get("project") or {}
    assert proj.get("key") == "press_hold"
    assert abs(float(proj.get("target") or 0) - 120) < 1e-6
    assert "壓轉撐" in str(proj.get("label") or "")
    assert "不是保證" in str(proj.get("label") or "")


def test_project_clearly_over_uses_down_rail():
    info = analyze_structure(_clearly_over_with_down_rail())
    assert info.get("over_press") is True
    proj = info.get("project") or {}
    assert proj.get("key") == "rail"
    assert float(proj.get("target") or 0) > 110
    assert "連點" in str(proj.get("label") or "")
    assert "不是保證" in str(proj.get("label") or "")
    path = proj.get("path") or []
    assert len(path) >= 2
    assert path[0][1] == info["closes"][-1]
    assert abs(path[-1][1] - float(proj["target"])) < 1e-6


def test_project_rail_coming_down_caps_price():
    rows = _clearly_over_with_down_rail()
    rows[-1] = dict(rows[-1], open=140, high=143, low=139, close=141)
    info = analyze_structure(rows)
    assert info.get("over_press") is True
    proj = info.get("project") or {}
    assert proj.get("key") == "rail_cap"
    assert abs(float(proj.get("target") or 0) - 141) < 1e-6
    assert "被軌壓著" in str(proj.get("label") or "")
    assert "不是保證過軌" in str(proj.get("label") or "")


def test_project_wash_without_shrink_waits():
    rows = _series()
    rows[-1] = dict(rows[-1], volume=12000, close=126, high=130, low=122, open=124)
    info = analyze_structure(rows)
    assert info.get("wash") is True
    assert info.get("struct", {}).get("shrinking") is False
    proj = info.get("project") or {}
    assert proj.get("key") == "wait"
    assert abs(float(proj.get("target") or 0) - 126) < 1e-6
    assert "先整理" in str(proj.get("label") or "")
    assert "不把攻壓" in str(proj.get("label") or "")


def _above_support_heavy_volume_series():
    """站上撐、沒破線、量大：不把攻壓當最可能。"""
    day = date(2026, 7, 1)
    rows = []
    for i in range(28):
        d = (day + timedelta(days=i)).strftime("%Y%m%d")
        if i == 8:
            o, h, l, c, v = 100, 120, 96, 118, 18000
        elif i == 27:
            o, h, l, c, v = 108, 112, 106, 110, 12000
        else:
            px = 104 + i * 0.2
            o, h, l, c, v = px, px + 2, max(px - 2, 97), px, 2200
        rows.append(
            {
                "date": d,
                "stock_id": "3035",
                "stock_name": "智原",
                "open": o,
                "high": h,
                "low": l,
                "close": c,
                "volume": v,
                "pct_change": 0,
            }
        )
    return rows


def test_project_above_support_without_shrink_waits():
    info = analyze_structure(_above_support_heavy_volume_series())
    assert info.get("under_support") is False
    assert info.get("over_press") is False
    assert info.get("wash") is False
    assert info.get("struct", {}).get("shrinking") is False
    proj = info.get("project") or {}
    assert proj.get("key") == "wait"
    assert abs(float(proj.get("target") or 0) - 110) < 1e-6
    assert "先整理" in str(proj.get("label") or "")


def test_nameplate_industry_leader_and_spot_quote(tmp_path):
    import inspect
    import sqlite3

    from PIL import Image

    db = str(tmp_path / "uni.db")
    conn = sqlite3.connect(db)
    conn.execute(
        "CREATE TABLE stock_universe (stock_id TEXT PRIMARY KEY, stock_name TEXT, "
        "industry TEXT, asset_type TEXT)"
    )
    conn.execute("INSERT INTO stock_universe VALUES ('2383','台光電','電子零組件業','STOCK')")
    conn.execute("INSERT INTO stock_universe VALUES ('2368','金像電','電子零組件業','STOCK')")
    conn.commit()
    conn.close()
    lead = stock_nameplate("2383", "台光電", db)
    follow = stock_nameplate("2368", "金像電", db)
    assert lead["industry"] == "電子零組件業"
    assert lead["leader"] == "龍頭"
    assert follow["industry"] == "電子零組件業"
    assert follow["leader"] == ""
    bits = header_banner_lines(
        {
            "nest": "現在位階 2026-09-15 10:47 逃命波C-2",
            "field": "CCL 護城河還在",
            "leader": "自己就是這族龍頭",
            "hold": "長抱：可抱到明年，勿輕易調節",
        },
        sid="2383",
        plate=lead,
    )
    assert bits[0].startswith("CCL")
    assert all("現在位階" not in x and "逃命波" not in x for x in bits)
    assert all("勿輕易調節" not in x for x in bits)
    assert "自己就是這族龍頭" in bits[1]
    assert all("…" not in x for x in bits)
    src = inspect.getsource(render_biaoke_structure_png)
    assert "_short(" not in src
    assert "box_ha" not in src
    assert "今K" in inspect.getsource(_paint_spot)
    quote_src = inspect.getsource(_spot_quote)
    assert "_in_pytest" in quote_src
    assert "fetch_mis_quote" in quote_src
    q = _spot_quote(
        "2383",
        {"open": 4400, "high": 4520, "low": 4380, "close": 4510, "date": "20260914"},
        {"close": 4480},
    )
    assert q["is_live"] is False
    assert q["label"] == "收盤"
    assert q["close"] == 4510
    cap = chart_caption(analyze_structure(_series()), sid="2383", name="台光電", plate=lead)
    assert "電子零組件業" in cap
    assert "龍頭" in cap
    assert "不是介紹圖" not in cap
    assert "這不是買訊" not in cap
    out = str(tmp_path / "nameplate.png")
    path = render_biaoke_structure_png(
        _series(),
        out,
        sid="2383",
        name="台光電",
        plate=lead,
        quote=q,
        glance={
            "nest": "現在位階 2026-09-15 10:47 逃命波C-2",
            "field": "CCL 護城河還在",
            "leader": "自己就是這族龍頭",
            "hold": "長抱：可抱到明年，勿輕易調節",
        },
    )
    assert path
    assert Image.open(path).size[0] >= 1000
    assert (tmp_path / "nameplate.png").stat().st_size > 24_000
    src = inspect.getsource(render_biaoke_structure_png)
    assert "_halo_line" in src
    assert "_leader_note" in src
    assert "_place_right_notes" in src
    assert "inset_axes" not in src
    assert "if down_live" not in src
    assert "x_fut" in src
    assert "paint_locator_inset" in src
    assert "_STOCK_LOCATOR_RECT" in src


def test_locator_inset_marks_window():
    import inspect

    from biaoke_chart import paint_locator_inset
    from biaoke_wave import render_twii_degree_png

    src = inspect.getsource(paint_locator_inset)
    assert "橙底" in src
    assert "黃底" in src or "預估" in src
    assert "橫軸月份" in src
    assert "legs" in src
    assert "forecast_n" in src
    assert "marks" in src
    assert "win_from" in src
    assert "_WINDOW_BG" in src
    assert "window_forecast_seams" in src
    assert "quote" in src
    assert 'edgecolor="#ef6c00"' not in src
    from biaoke_chart import _BARS, _FIG_RIGHT, _STOCK_LOCATOR_RECT
    from biaoke_wave import _TWII_LOCATOR_RECT

    assert _BARS >= 140
    assert 0.46 <= _STOCK_LOCATOR_RECT[0] <= 0.52
    assert _STOCK_LOCATOR_RECT[2] >= 0.44
    assert _STOCK_LOCATOR_RECT[3] >= 0.24
    assert abs(_STOCK_LOCATOR_RECT[0] + _STOCK_LOCATOR_RECT[2] - _FIG_RIGHT) < 1e-9
    assert abs(_TWII_LOCATOR_RECT[0] + _TWII_LOCATOR_RECT[2] - _FIG_RIGHT) < 1e-9
    rsrc = inspect.getsource(render_biaoke_structure_png)
    assert "right=_FIG_RIGHT" in rsrc
    assert "_paint_spot(ov, quote" in rsrc
    assert "chip_y - 3.35" in rsrc or "標籤下面" in inspect.getsource(_paint_spot)
    assert "quote=quote" not in rsrc.split("paint_locator_inset")[1][:400]
    qsrc = inspect.getsource(_paint_locator_quote)
    assert "匡外" in qsrc
    spot = inspect.getsource(_paint_spot)
    assert "標籤下面" in spot or "ha=\"left\"" in spot
    assert "較昨日" in inspect.getsource(_paint_spot)
    wsrc = inspect.getsource(render_twii_degree_png)
    assert "paint_locator_inset" in wsrc
    assert "560" in wsrc or "long_bars" in wsrc
    assert "locator_abc_legs" in wsrc
    assert "wave_abc_story" in wsrc
    assert "infer_impulse_five" in wsrc
    assert "k_on_top" in wsrc
    assert "forecast_n" in wsrc
    assert "_TWII_LOCATOR_RECT" in wsrc
    assert "uniq_tags" not in wsrc
    assert "_place_right_notes" in wsrc
    assert "_paint_abc_on_ax" in wsrc
    spot = inspect.getsource(_paint_spot)
    assert 'ha="left"' in spot
    assert "較昨日" in spot
    assert 'ha="right"' not in spot
    assert "compact" in spot
    assert "window_forecast_seams" in wsrc or "paint_forecast_span" in wsrc
    assert "right=_FIG_RIGHT" in wsrc
    assert "_style_frame" in wsrc


def test_locator_window_matches_main_time():
    import os

    from biaoke_brain import load_bars
    from biaoke_chart import (
        _BARS,
        _FUTURE,
        _ymd8,
        locator_positive_rows,
        locator_window_index,
        window_forecast_seams,
    )
    from biaoke_wave import _TWII_FUTURE, _TWII_LONG_BARS, _TWII_MAIN_BARS, _load_twii_bars

    from tests.conftest import require_production_db

    db = require_production_db()
    bars = load_bars(db, "2383", n=360)
    work = bars[-_BARS:]
    rows = locator_positive_rows(bars)
    i0, i1 = locator_window_index(rows, str(work[0]["date"]), str(work[-1]["date"]))
    assert _ymd8(rows[i0]["date"]) == _ymd8(work[0]["date"])
    assert _ymd8(rows[i1]["date"]) == _ymd8(work[-1]["date"])
    assert i1 == len(rows) - 1
    _wlo, seam, fhi = window_forecast_seams(i0, i1, _FUTURE)
    main_seam, main_hi = window_forecast_seams(0, len(work) - 1, _FUTURE)[1:]
    assert abs((seam - i1) - (main_seam - (len(work) - 1))) < 1e-9
    assert abs((fhi - seam) - (main_hi - main_seam)) < 1e-9
    tb = _load_twii_bars(db, n=_TWII_LONG_BARS)
    tm = _load_twii_bars(db, n=_TWII_MAIN_BARS)
    tr = locator_positive_rows(tb)
    j0, j1 = locator_window_index(tr, str(tm[0]["date"]), str(tm[-1]["date"]))
    assert _ymd8(tr[j0]["date"]) == _ymd8(tm[0]["date"])
    assert _ymd8(tr[j1]["date"]) == _ymd8(tm[-1]["date"])
    tw_lo, tw_seam, tw_hi = window_forecast_seams(j0, j1, _TWII_FUTURE)
    m_lo, m_seam, m_hi = window_forecast_seams(0, len(tm) - 1, _TWII_FUTURE)
    assert abs((tw_hi - tw_seam) - (m_hi - m_seam)) < 1e-9


def test_leader_notes_use_dashed_and_stagger():
    import inspect

    from biaoke_chart import _leader_note, _spread_ys_around

    src = inspect.getsource(_leader_note)
    assert 'linestyle="--"' in src or "linestyle='--'" in src
    ys = _spread_ys_around([10.0, 10.2], [10.0], 1.0)
    assert abs(ys[0] - ys[1]) >= 0.99


def test_caption_records_forecast_line():
    cap = chart_caption(analyze_structure(_series()), sid="3035", name="智原")
    assert "延伸線已建檔" not in cap
    assert "官方柱走完再對質" not in cap
    assert "這不是買訊" not in cap
    assert "不是介紹圖" not in cap
    assert "縮圖" not in cap
    assert "5／9" not in cap and "5/9" not in cap
    assert "圖上演算" in cap
    assert "不是保證" in cap
    assert "沒疊滿就不講死" in cap


def test_axis_ticks_drop_near_last_bar():
    ticks = _axis_ticks(60, extra=(12,))
    assert 0 in ticks
    assert 59 in ticks
    assert 12 in ticks
    assert all(abs(i - 59) >= 4 or i in (0, 12, 59) for i in ticks)
    assert 56 not in ticks


def test_pressure_support_use_consecutive_pivots():
    from biaoke_chart import _asc_low_pair, _desc_high_pair

    highs = [10.0, 20.0, 19.0, 22.0, 21.0, 20.0, 15.0]
    assert _desc_high_pair([1, 3, 6], highs) == (3, 6)
    assert _desc_high_pair([1, 4], [10.0, 20.0, 19.0, 18.0, 22.0]) is None
    # 中間有更高的高，不准跳過去當下降壓。
    assert _desc_high_pair([1, 6], [10.0, 20.0, 19.0, 25.0, 21.0, 20.0, 15.0]) is None
    lows = [10.0, 8.0, 9.0, 7.0, 7.4, 8.5, 9.2]
    assert _asc_low_pair([1, 3, 6], lows) == (3, 6)
    assert _asc_low_pair([1, 4], [10.0, 8.0, 9.0, 8.5, 7.0]) is None


def test_impulse_support_after_down_pressure(tmp_path):
    import os

    from biaoke_brain import load_bars
    from biaoke_chart import _impulse_support_pair

    from tests.conftest import require_production_db

    db = require_production_db()
    bars = load_bars(db, "2383", n=168)
    info = analyze_structure(bars)
    assert info.get("down_pts")
    assert info.get("up_pts"), "台光電下降壓確認後要用 2–4 低當上升撐"
    (x1, y1, _d1), (x2, y2, _d2) = info["up_pts"]
    assert y2 > y1
    peak = int(info["down_pts"][0][0])
    assert _impulse_support_pair(bars, peak) == (int(x1), int(x2))
    out = str(tmp_path / "2383-support.png")
    path = render_biaoke_structure_png(bars, out, sid="2383", name="台光電")
    assert path
    assert (tmp_path / "2383-support.png").stat().st_size > 24_000


def test_infer_impulse_five_from_confirmed_peak():
    from biaoke_chart import infer_impulse_five, impulse_five_marks

    rows = []
    path = [
        (20, 18),
        (40, 28),
        (32, 24),
        (70, 38),
        (55, 48),
        (90, 80),
        (82, 70),
        (75, 60),
    ]
    for i, (h, lo) in enumerate(path):
        for k in range(8):
            t = i * 8 + k
            hh = h - (0 if k == 3 else 2)
            ll = lo + (0 if k == 5 else 2)
            rows.append(
                {
                    "date": f"202601{(t % 28) + 1:02d}",
                    "open": (hh + ll) / 2,
                    "high": hh,
                    "low": ll,
                    "close": (hh + ll) / 2,
                }
            )
    peak_i = 5 * 8 + 3
    story = infer_impulse_five(rows, peak_i=peak_i, start_i=0)
    nums = [p["n"] for p in (story.get("pts") or [])]
    assert nums == ["1", "2", "3", "4", "5"]
    assert int(story["pts"][-1]["i"]) == peak_i
    marks = impulse_five_marks(story)
    assert [m["text"] for m in marks] == ["1", "2", "3", "4", "5"]
    assert all(int(m.get("size") or 0) >= 12 for m in marks)
    assert infer_impulse_five(rows[:6], peak_i=5) == {}


def test_infer_impulse_five_rejects_two_bar_wave12():
    """1～2 只隔兩根＝假轉折，要改選有間隔的 1，不准硬畫。"""
    from datetime import date, timedelta

    from biaoke_chart import infer_impulse_five

    # 真 1＝55、2＝48；假 1＝70 隔兩根回 60（且是這段最低）。4 低仍高於假 1，才選得到那組。
    anchors = {
        0: 40.0,
        15: 55.0,
        25: 48.0,
        40: 70.0,
        42: 60.0,
        70: 100.0,
        82: 72.0,
        95: 90.0,
        104: 88.0,
    }
    keys = sorted(anchors)
    rows = []
    start = date(2025, 10, 1)
    for i in range(105):
        for a, b in zip(keys, keys[1:]):
            if a <= i <= b:
                t = 0 if b == a else (i - a) / (b - a)
                px = anchors[a] + (anchors[b] - anchors[a]) * t
                break
        else:
            px = 40.0
        d = (start + timedelta(days=i)).strftime("%Y%m%d")
        rows.append(
            {
                "date": d,
                "open": px,
                "high": px + 0.4,
                "low": px - 0.4,
                "close": px,
                "volume": 1000,
            }
        )
    five = infer_impulse_five(rows, peak_i=95, start_i=0)
    assert five
    pts = {str(p["n"]): p for p in five["pts"]}
    assert int(pts["2"]["i"]) - int(pts["1"]["i"]) >= 4
    assert int(pts["1"]["i"]) != 40
    assert float(pts["3"]["y"]) >= 100.0


def test_infer_impulse_five_truncated_5_uses_higher_mountain_as_wave3():
    """5 截短時，3 必須是起點到 5 之間的最高山，不能卡在 5 左邊較矮的峰。"""
    from datetime import date, timedelta

    from biaoke_chart import infer_impulse_five

    # 1=55、2=48、3=90、4=62（4 低仍高於 1 高）、5=75 截短。中間 K 線性連，避免 4 掉進 1。
    anchors = {0: 40.0, 8: 55.0, 16: 48.0, 40: 90.0, 55: 62.0, 80: 75.0, 89: 73.0}
    keys = sorted(anchors)
    rows = []
    start = date(2025, 10, 1)
    for i in range(90):
        for a, b in zip(keys, keys[1:]):
            if a <= i <= b:
                t = 0 if b == a else (i - a) / (b - a)
                px = anchors[a] + (anchors[b] - anchors[a]) * t
                break
        else:
            px = 40.0
        d = (start + timedelta(days=i)).strftime("%Y%m%d")
        rows.append(
            {
                "date": d,
                "open": px,
                "high": px + 0.4,
                "low": px - 0.4,
                "close": px,
                "volume": 1000,
            }
        )
    five = infer_impulse_five(rows, peak_i=80)
    assert five
    pts = {str(p["n"]): p for p in five["pts"]}
    assert pts["5"]["y"] == rows[80]["high"]
    assert pts["3"]["y"] == rows[40]["high"]
    assert int(pts["3"]["i"]) < int(pts["5"]["i"])


def test_infer_impulse_five_3105_wave3_is_april_mountain():
    """穩懋截短 5：3＝4/21 山頭，1 不准貼在 11 月那顆小波。"""
    import os

    from biaoke_brain import load_bars
    from biaoke_chart import _ymd8, analyze_structure, infer_impulse_five

    from tests.conftest import require_production_db

    db = require_production_db()
    bars = load_bars(db, "3105", n=360)
    if len(bars) < 80:
        return
    work = bars[-168:]
    info = analyze_structure(work)
    down = info.get("down_pts") or []
    if not down:
        return
    off = len(bars) - len(work)
    five = infer_impulse_five(bars, peak_i=off + int(down[0][0]))
    assert five
    pts = {str(p["n"]): p for p in five["pts"]}
    d3 = _ymd8(bars[int(pts["3"]["i"])].get("date"))
    d1 = _ymd8(bars[int(pts["1"]["i"])].get("date"))
    d2 = _ymd8(bars[int(pts["2"]["i"])].get("date"))
    assert d3 == "20260421"
    assert float(pts["3"]["y"]) >= 630
    assert d1 >= "20251201"
    assert float(pts["1"]["y"]) >= 180
    assert int(pts["2"]["i"]) - int(pts["1"]["i"]) >= 4
    assert (d1, d2) != ("20260112", "20260114")
    assert int(pts["3"]["i"]) < int(pts["5"]["i"])


def test_clip_line_extends_left_of_first_pivot():
    from biaoke_chart import _clip_line

    got = _clip_line(150, 492, 155, 478, x_lo=0, x_hi=177, y_lo=100, y_hi=700)
    assert got is not None
    xa, _ya, xb, _yb = got
    assert xa < 150
    assert xb > 155


def test_locator_does_not_fallback_to_chinese_swing_labels_when_down_exists():
    import inspect

    from biaoke_chart import render_biaoke_structure_png

    src = inspect.getsource(render_biaoke_structure_png)
    assert "數得出 1～5 才標數字" in src
    assert "locator_legs_from_swings(rows" not in src.split("數得出")[1][:400]


def test_major_swings_and_locator_legs():
    from biaoke_chart import _major_swings, locator_legs_from_swings

    rows = []
    px = 100.0
    for i in range(80):
        if 20 <= i < 35:
            px = 100 + (i - 20) * 3
        elif 35 <= i < 50:
            px = 145 - (i - 35) * 2.4
        elif i >= 50:
            px = 109 + (i - 50) * 1.6
        else:
            px = 100 + i * 0.2
        d = (date(2025, 7, 1) + timedelta(days=i)).strftime("%Y%m%d")
        rows.append(
            {
                "date": d,
                "open": px,
                "high": px + 4,
                "low": px - 4,
                "close": px + 1,
                "volume": 1000,
            }
        )
    swings = _major_swings(rows, left=5)
    assert len(swings) >= 2
    kinds = [k for _i, _y, k in swings]
    assert all(a != b for a, b in zip(kinds, kinds[1:]))
    legs = locator_legs_from_swings(rows, swings)
    labs = [str(x.get("lab") or "") for x in legs]
    assert any(x in labs for x in ("升", "回"))
    ticks = _axis_ticks(60, extra=(12,))
    assert 0 in ticks


def test_biaoke_chart_dpi_is_lighter_than_nav():
    from wayne_navigator import NAV_CHART_DPI

    assert BIAOKE_CHART_DPI <= 180
    assert BIAOKE_CHART_DPI < NAV_CHART_DPI
    import inspect
    from biaoke_chart import render_biaoke_structure_png

    src = inspect.getsource(render_biaoke_structure_png)
    assert "BIAOKE_CHART_DPI" in src
    assert "NAV_CHART_DPI" not in src
    assert "_add_ohlc_wicks" in src
    assert "pil_kwargs" in src
    from biaoke_chart import paint_locator_inset

    lsrc = inspect.getsource(paint_locator_inset)
    assert "_add_ohlc_wicks" in lsrc
    assert "ax.vlines" not in lsrc
