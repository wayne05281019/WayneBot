# -*- coding: utf-8 -*-
from datetime import date, timedelta

from biaoke_chart import (
    _paint_spot,
    _spot_quote,
    analyze_structure,
    chart_caption,
    header_banner_lines,
    neuron_glance,
    render_biaoke_structure_png,
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
    assert "不是介紹圖" in cap
    assert "決策卡" in cap
    assert "這不是買訊" in cap
    assert "5／9" in cap or "5/9" in cap
    assert "日K" in cap or "日 K" in cap or "官方日K" in cap
    assert "不是15分" in cap
    assert "量先價行" in cap
    assert "爆大量那一天" in cap
    assert "演算" in cap
    assert "不是保證" in cap
    assert "延伸線已建檔" in cap
    assert "介入買點首先" not in cap
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
    cap = chart_caption(info, sid="3035", name="智原", glance=glance)
    assert "介入買點首先" not in cap
    assert "先看大盤巢穴會不會覆巢" not in cap
    assert "個股最重要是產業趨勢" not in cap
    assert "現在位階" in cap
    assert "自己就是這族龍頭" in cap
    assert "勿輕易調節" in cap
    assert "爆大量那一天" in cap
    assert "量先價行" in cap
    assert "這不是買訊" in cap
    out = str(tmp_path / "biaoke-glance.png")
    path = render_biaoke_structure_png(
        _series(), out, sid="3035", name="智原", glance=glance
    )
    assert path and Image.open(path).size[0] >= 1000
    assert (tmp_path / "biaoke-glance.png").stat().st_size > 24_000


def test_real_daily_quotes_numbers_are_exact():
    import os

    from biaoke_brain import load_bars

    db = "data/wayne_market.db"
    if not os.path.isfile(db):
        return
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
        }
    )
    assert bits[0].startswith("現在位階")
    assert "逃命波C-2" in bits[0]
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
    assert "不是介紹圖" in cap
    assert "這不是買訊" in cap
    out = str(tmp_path / "nameplate.png")
    path = render_biaoke_structure_png(
        _series(),
        out,
        sid="2383",
        name="台光電",
        plate=lead,
        quote=q,
        glance={
            "nest": bits[0],
            "field": bits[1],
            "leader": bits[2],
        },
    )
    assert path
    assert Image.open(path).size[0] >= 1000
    assert (tmp_path / "nameplate.png").stat().st_size > 24_000
    src = inspect.getsource(render_biaoke_structure_png)
    assert "_halo_line" in src
    assert "_callout" in src
    assert "if down_live" not in src
    assert "x_fut" in src


def test_caption_records_forecast_line():
    cap = chart_caption(analyze_structure(_series()), sid="3035", name="智原")
    assert "延伸線已建檔" in cap
    assert "官方柱走完再對質" in cap
    assert "這不是買訊" in cap
    assert "不是介紹圖" in cap
    assert "5／9" in cap or "5/9" in cap
