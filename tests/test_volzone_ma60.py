# -*- coding: utf-8 -*-
"""大量區圖：季線 MA60＋右上查詢時間。"""
from __future__ import annotations

import inspect
import os
import tempfile

import numpy as np
import pandas as pd
import pytest

from config import get_db_path

pytestmark = pytest.mark.production_db


def test_attach_official_ma60_needs_60_bars():
    from vol_zone_chart import attach_official_ma60, ma60_is_rising

    closes = list(range(100, 175))  # 75 bars rising → MA60 有足夠近窗
    df = pd.DataFrame(
        {
            "date": [f"20260{i:03d}" for i in range(len(closes))],
            "close": closes,
            "open": closes,
            "high": [c + 1 for c in closes],
            "low": [c - 1 for c in closes],
            "volume": [1000] * len(closes),
        }
    )
    out = attach_official_ma60(df)
    assert "ma60" in out.columns
    assert pd.isna(out["ma60"].iloc[58])
    assert float(out["ma60"].iloc[-1]) == pytest.approx(sum(closes[-60:]) / 60.0)
    assert ma60_is_rising(out["ma60"], slope_bars=5) is True

    flat = attach_official_ma60(
        pd.DataFrame({"close": [10.0] * 80})
    )
    assert ma60_is_rising(flat["ma60"], slope_bars=5) is False


def test_paint_draws_ma60_and_query_stamp():
    from vol_zone_chart import _paint_volume_zone, _label_ma_blank, _paint_ma_line_labels

    src = inspect.getsource(_paint_volume_zone)
    assert "_MA60" in src and "_MA20" in src
    assert "format_card_query_stamp" in src
    assert "fig.text" in src and "0.985" in src  # 整圖右上時間戳
    assert "大量區壓" in src and "大量區撐" in src
    assert "linewidth=0.78" in src  # 壓／撐水平線再細
    assert "_paint_ma_line_labels" in src
    assert '"月"' in src and '"季"' in src
    assert '"5"' in src and '"10"' in src
    assert "left=0.050" in src  # 左縮右鬆放大 K 區
    assert "draw_ma20=False" in src
    # 月／季線寬仍粗於五日／十日
    assert "linewidth=1.75" in src and "linewidth=1.85" in src
    assert "linewidth=1.45" in src
    # 已刪表頭右上收盤晶片；表頭「收XXXX」稍大＋漲跌色（不准寫死紅）
    assert 'f"收 {_fmt_price(last_cl)}"' not in src
    assert "quote_limit_chip_colors" not in src
    assert "close_bit" in src
    assert "quote_move_ink" in src
    assert "color=_UP," not in src or "close_ink" in src
    assert "貼主K上框內側" in src and "不准掛表頭壓圖例" in src  # 日標在主K上框內，不壓圖例
    # 標位不准碰假 OHLC／量
    assert "不准動 OHLC" in src or "不准改 OHLC" in inspect.getsource(_paint_ma_line_labels)
    lab_src = inspect.getsource(_label_ma_blank)
    assert "_clear_of_bars" in lab_src
    assert "_clear_of_other_mas" in lab_src
    assert "_ma_x_zone_bonus" in lab_src or "中左" in lab_src
    assert "0.68" in lab_src  # 中右靠中上限
    assert inspect.getsource(_paint_ma_line_labels)
    paint_src = inspect.getsource(_paint_ma_line_labels)
    assert "other_mas" in paint_src
    assert "自動選位" in paint_src or "自己線" in paint_src


def test_label_ma_blank_auto_zone_own_line_no_overlap():
    """程式自動選位（中左→中→中右靠中）；y 只貼自己線；互不壓、不壓 K。"""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from vol_zone_chart import (
        _label_ma_blank,
        _ma_x_zone_bonus,
        _paint_ma_line_labels,
    )

    assert _ma_x_zone_bonus(0.25) > _ma_x_zone_bonus(0.45) > _ma_x_zone_bonus(0.60)
    assert _ma_x_zone_bonus(0.80) < 0  # 遠右禁

    n = 40
    xs = np.arange(n, dtype=float)
    # K 帶窄，四條均線都在帶外、彼此錯開，才能驗「四標都下＋只貼己線」
    highs = np.full(n, 112.0)
    lows = np.full(n, 108.0)
    vals = np.linspace(100.0, 102.0, n)  # 月：K 下方
    fig, ax = plt.subplots()
    ax.set_ylim(70, 150)
    ax.set_xlim(-0.05, n + 2.15)
    pos = _label_ma_blank(
        ax, xs, highs, lows, lab="月", vals=vals, color="#f9a825", face="#fffde7"
    )
    assert pos is not None
    x, y = pos
    texts = [t for t in ax.texts if t.get_text() == "月"]
    assert texts
    assert float(x) <= float(n - 1) * 0.68 + 0.05
    j = int(round(float(x)))
    j = max(0, min(n - 1, j))
    assert abs(float(y) - float(vals[j])) < 1e-5
    # 不壓進 K 高低帶
    assert float(y) <= float(lows[j]) - 1e-6 or float(y) >= float(highs[j]) + 1e-6
    plt.close(fig)

    fig2, ax2 = plt.subplots()
    ax2.set_ylim(70, 150)
    ax2.set_xlim(-0.05, n + 2.15)
    series = [
        ("5", vals + 28.0, "#ef6c00", "#fff3e0"),   # ~128–130，K 上方
        ("10", vals + 18.0, "#00838f", "#e0f7fa"),  # ~118–120
        ("月", vals, "#f9a825", "#fffde7"),         # ~100–102
        ("季", vals - 18.0, "#5c6bc0", "#e8eaf6"),  # ~82–84
    ]
    _paint_ma_line_labels(ax2, xs, highs, lows, series=series)
    labs = {t.get_text(): t.get_position() for t in ax2.texts}
    assert set(labs) >= {"5", "10", "月", "季"}
    # 各標 y 必須貼自己線
    by_lab = {lb: arr for (lb, arr, _c, _f) in series}
    for lb, (px, py) in labs.items():
        assert float(px) <= float(n - 1) * 0.68 + 0.05
        jj = max(0, min(n - 1, int(round(float(px)))))
        assert abs(float(py) - float(by_lab[lb][jj])) < 1e-5
    pts = list(labs.values())
    for i in range(len(pts)):
        for j in range(i + 1, len(pts)):
            assert abs(pts[i][0] - pts[j][0]) > 0.15 or abs(pts[i][1] - pts[j][1]) > 1.2
    plt.close(fig2)


def test_label_ma_skips_when_only_on_other_line_or_k():
    """自己線全程卡在他線／K 內 → 寧可不下標，不准硬壓。"""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from vol_zone_chart import _label_ma_blank

    n = 30
    xs = np.arange(n, dtype=float)
    highs = np.full(n, 110.0)
    lows = np.full(n, 90.0)
    # 自己線落在 K 正中
    vals = np.full(n, 100.0)
    other = np.full(n, 100.0)
    fig, ax = plt.subplots()
    ax.set_ylim(80, 120)
    ax.set_xlim(-0.05, n + 1.0)
    pos = _label_ma_blank(
        ax,
        xs,
        highs,
        lows,
        lab="5",
        vals=vals,
        color="#ef6c00",
        face="#fff3e0",
        other_mas=[other],
    )
    assert pos is None
    assert not [t for t in ax.texts if t.get_text() == "5"]
    plt.close(fig)


def test_prepare_loads_ma60_warm_bars():
    from vol_zone_chart import prepare_volume_zone

    src = inspect.getsource(prepare_volume_zone)
    assert "VOL_ZONE_MA60_WARM" in src or "attach_official_ma60" in src
    assert "attach_official_ma60" in src
    assert "attach_official_ma20" in src


def test_render_volume_zone_includes_ma60_column(tmp_path):
    from vol_zone_chart import (
        clear_vol_zone_render_cache,
        prepare_volume_zone,
        render_volume_zone_png,
    )

    clear_vol_zone_render_cache()
    db = get_db_path()
    pack = prepare_volume_zone("2330", "台積電", db, str(tmp_path / "x.jpg"))
    assert pack is not None
    assert "ma60" in pack["view"].columns
    assert "ma20" in pack["view"].columns
    ma60 = pd.to_numeric(pack["view"]["ma60"], errors="coerce")
    ma20 = pd.to_numeric(pack["view"]["ma20"], errors="coerce")
    assert ma60.notna().sum() >= 10
    assert ma20.notna().sum() >= 10
    # 近窗第一根就要有線（暖機）
    assert pd.notna(ma20.iloc[0])
    assert pd.notna(ma60.iloc[0])
    out = render_volume_zone_png("2330", "台積電", db, str(tmp_path / "2330_vz.jpg"))
    assert out and os.path.isfile(out)
    assert os.path.getsize(out) > 20000


def test_volzone_ma60_verify_gate_never_promotes_buy(tmp_path):
    from volzone_ma60_verify import (
        TRACK_VARIANTS,
        VARIANT_CURRENT,
        VARIANT_MA60_RISING,
        VARIANT_MA60_RISING_THIN,
        ensure_tables,
        filter_ma60_rising_thin,
        gate_status,
        rank_pool,
    )
    import sqlite3

    assert VARIANT_CURRENT in TRACK_VARIANTS
    assert VARIANT_MA60_RISING in TRACK_VARIANTS
    assert VARIANT_MA60_RISING_THIN in TRACK_VARIANTS
    # 無庫／空池 → 再生軌空名單（不算有記）
    assert filter_ma60_rising_thin([], db_path="", as_of="") == []
    ranked = rank_pool(
        [
            {
                "stock_id": "B",
                "dist_to_press_pct": 2.0,
                "vol_ratio": 0.5,
                "close": 100,
                "pressure": 105,
                "support": 90,
            },
            {
                "stock_id": "A",
                "dist_to_press_pct": 0.3,
                "vol_ratio": 0.2,
                "close": 104,
                "pressure": 105,
                "support": 90,
            },
        ],
        "sideways",
    )
    assert ranked[0]["stock_id"] == "A"
    db = str(tmp_path / "g.db")
    sqlite3.connect(db).close()
    ensure_tables(db)
    g = gate_status(db)
    assert g.get("promote_buy_signals") is False
    assert g.get("promote_ready") is False


def test_volzone_ma60_verify_persist_and_gate(tmp_path):
    from volzone_ma60_verify import (
        VARIANT_CURRENT,
        VARIANT_MA60_RISING,
        ensure_tables,
        gate_status,
        persist_ranked,
        optimize_status_one_liner,
    )

    db = str(tmp_path / "m.db")
    # minimal empty market db file so tape_store_path works beside it
    import sqlite3

    sqlite3.connect(db).close()
    ensure_tables(db)
    rows = [
        {
            "stock_id": "2330",
            "stock_name": "台積電",
            "close": 100.0,
            "pressure": 105.0,
            "support": 90.0,
            "vol_ratio": 0.4,
            "dist_to_press_pct": 1.0,
            "ma60_rising": 1,
        }
    ]
    from volzone_ma60_verify import VARIANT_MA60_RISING_THIN

    assert persist_ranked(db, "20260901", "sideways", VARIANT_CURRENT, rows) == 1
    assert persist_ranked(db, "20260901", "sideways", VARIANT_MA60_RISING, rows) == 1
    thin_rows = [dict(rows[0], vol_ratio=0.2, vol_thin=1)]
    assert persist_ranked(db, "20260901", "sideways", VARIANT_MA60_RISING_THIN, thin_rows) == 1
    g = gate_status(db)
    assert g["promote_buy_signals"] is False
    assert g["promote_ready"] is False
    assert VARIANT_MA60_RISING_THIN in g.get("tracks", [])
    assert "季線" in optimize_status_one_liner(db) or "大量區" in optimize_status_one_liner(db)


def test_judge_tape_hooks_volzone_ma60():
    import judge_tape

    src = inspect.getsource(judge_tape._snapshot_pressure_support)
    assert "volzone_ma60_verify" in src
    assert "volzone_ma60_night_tick" in src


def test_button_catalog_lists_volzone_ma60():
    from button_silent_verify import catalog

    rows = catalog()
    hit = [r for r in rows if "volzone_ma60" in (r.get("kinds") or ())]
    assert hit
    assert hit[0]["status"] == "external"
