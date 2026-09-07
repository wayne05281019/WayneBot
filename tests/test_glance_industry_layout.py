# -*- coding: utf-8 -*-
"""介紹圖獲利用語／底欄不壓字；產業說明 Telegram 一列一事。"""
from __future__ import annotations

import os
import re
import tempfile

import matplotlib
import pytest

matplotlib.use("Agg")
import matplotlib.axes

from tests.test_sell_discipline import _mini_card_for_png
from wayne_navigator import render_first_glance_png


def test_wrap_fit_keeps_margin_pct_together():
    from wayne_navigator import GLANCE_FIG_W, _wrap_fit

    s = "融資 48,138張（45.4%）　融券 921張（0.9%）"
    lines = _wrap_fit(s, 13.0, 48.0, GLANCE_FIG_W)
    joined = "｜".join(lines)
    assert "0.9%）" in joined or "（0.9%）" in joined
    assert not any(ln.strip() in ("%）", "%)") for ln in lines)
    assert any("融資" in ln for ln in lines)
    assert any("融券" in ln for ln in lines)
    import inspect

    from wayne_navigator import generate_decision_card, render_first_glance_png

    glance_src = inspect.getsource(render_first_glance_png)
    html_src = inspect.getsource(generate_decision_card)
    assert "獲利（近60曆日低）" not in glance_src
    assert "曆日底" not in glance_src
    assert "日曆天" in glance_src
    assert "近60曆日低" not in html_src
    assert "日曆天" in html_src


def test_wrap_fit_breaks_at_comma_not_mid_word():
    from wayne_navigator import GLANCE_FIG_W, _wrap_fit

    s = "現在高點跟熱度都退了，先別追、也先別加碼。有持股就先出一點"
    lines = _wrap_fit(s, 13.0, 48.0, GLANCE_FIG_W)
    assert any("現在都退了" in ln or "先出一點" in ln for ln in lines)
    assert not any(ln.startswith("在") for ln in lines)
    assert "到過" not in "".join(lines)


def test_glance_footer_note_sits_above_legend(tmp_path, monkeypatch):
    seen = []
    orig = matplotlib.axes.Axes.text

    def wrap(self, *args, **kwargs):
        text = str(args[2]) if len(args) >= 3 else str(kwargs.get("s") or "")
        y = args[1] if len(args) >= 2 else kwargs.get("y")
        seen.append((float(y or 0), text))
        return orig(self, *args, **kwargs)

    monkeypatch.setattr(matplotlib.axes.Axes, "text", wrap)
    card = _mini_card_for_png(
        sell_action="直接減碼",
        sell_why="不同步（最高價但非最高溫）",
        dist_l120=80.0,
        dist_l240=90.0,
        dist_l480=100.0,
        vol_rank=30,
        vol_rank_60=20,
        vol_rank_480=10,
        temp_c="81.1 °C",
        prev_close=130.0,
        open=134.0,
        high=143.0,
        low=129.5,
        gain_pct=124.5,
        k20_high_streak=0,
    )
    tape = {
        "last": {},
        "move": {},
        "volume": {},
        "foreign": {},
        "trust": {},
        "dealer": {},
        "three": {},
        "inst_pct": 0,
        "conflict": "價漲外資轉賣",
    }
    out = tmp_path / "glance.png"
    path = render_first_glance_png("3441", card, tape, str(out))
    assert path and out.is_file()
    texts = [t for _, t in seen]
    assert "獲利" in texts
    assert any("日曆天" in t for t in texts)
    assert not any("曆日低" in t or "曆日底" in t for t in texts)
    assert "紀律" in texts
    assert any("先出一點" in t for t in texts)
    legend_y = [y for y, t in seen if "左上 K" in t][0]
    note_y = min(y for y, t in seen if "先出一點" in t)
    assert note_y - legend_y >= 2.4
    with __import__("PIL").Image.open(out) as im:
        assert im.size[0] >= 2000
        assert sum(im.size) < 10000


def test_industry_html_one_metric_per_line():
    import sqlite3
    import tempfile

    from fundamentals import ensure_fundamentals_tables
    from industry_brief import format_industry_html
    from wayne_db import ensure_core_schema

    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    try:
        ensure_core_schema(path)
        ensure_fundamentals_tables(path)
        conn = sqlite3.connect(path)
        now = "2026-08-31T00:00:00"
        for sid, name, mkt, atype, ind in (
            ("3035", "智原", "TWSE", "STOCK", "半導體業"),
            ("2408", "南亞科", "TWSE", "STOCK", "半導體業"),
            ("6854", "錼創科技-KY", "TWSE", "KY", "半導體業"),
            ("7770", "君曜", "TWSE", "STOCK", "半導體業"),
        ):
            conn.execute(
                "INSERT INTO stock_universe(stock_id,stock_name,market_type,asset_type,industry,is_active,updated_at) VALUES (?,?,?,?,?,1,?)",
                (sid, name, mkt, atype, ind, now),
            )
        for sid, name, yoy, mom, gm in (
            ("3035", "智原", 10.0, -25.0, 46.1),
            ("2408", "南亞科", 719.6, 1.0, 20.0),
            ("6854", "錼創科技-KY", -46.7, 0.0, 10.0),
            ("7770", "君曜", -58.2, 0.0, 8.0),
        ):
            conn.execute(
                "INSERT INTO monthly_revenue(stock_id,yyyymm,stock_name,market,industry,revenue,mom_pct,yoy_pct,ytd_yoy_pct) VALUES (?,?,?,?,?,?,?,?,?)",
                (sid, "202607", name, "TW", "半導體業", 1000, mom, yoy, yoy),
            )
            conn.execute(
                "INSERT INTO quarterly_income(stock_id,year,season,stock_name,market,revenue,gross_profit,gross_margin_pct,operating_income,net_income,eps) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (sid, 2026, 2, name, "TW", 10000, 1000, gm, 400, 300, 1.0),
            )
            conn.execute(
                "INSERT INTO daily_quotes(date,stock_id,stock_name,market,open,high,low,close,volume,turnover_k,pct_change,avg_price,foreign_net,trust_net,dealer_net) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                ("20260904", sid, name, "TW", 100, 101, 99, 100, 10000, 50000, 1.0, 100, -100, 0, 0),
            )
        conn.commit()
        conn.close()
        html = format_industry_html("3035", path)
        assert "怎麼用" not in html
        assert "不能替代高低卡" not in html
        assert "少賠：" not in html
        assert "本族群產業狀況簡述" in html
        assert "這族資金" not in html
        assert "這族" not in html
        assert "不是論壇分類" not in html
        assert "年增特別大" not in html
        assert "也會幌" not in html
        assert "也會晃" not in html
        assert "半導體業含代工、記憶體、設計" in html
        assert "同業＝同一官方產業別全組" in html
        lines = html.split("\n")
        for line in lines:
            plain = re.sub(r"<[^>]+>", "", line)
            if "這檔月增" in plain:
                assert "同業中位" not in plain
            if "同業中位年增" in plain:
                assert "%" in plain
            if "同業中位毛利率" in plain:
                assert "%" in plain
        codes = [re.sub(r"<[^>]+>", "", ln) for ln in lines]
        peer_lines = [ln for ln in codes if re.search(r"\b(2408|6854|7770)\b", ln)]
        for ln in peer_lines:
            found = re.findall(r"\b(?:2408|6854|7770|3035)\b", ln)
            assert len(found) <= 1, ln
        assert any("2408" in ln and "南亞科" in ln for ln in codes)
        assert any("6854" in ln and "錼創科技-KY" in ln for ln in codes)
    finally:
        os.remove(path)


@pytest.mark.production_db
def test_tsmc_peers_share_twse_semiconductor_bucket(production_db):
    """台積電不是記憶體；南亞科／鈺創出現是因為證交所半導體業太粗。"""
    import sqlite3

    from industry_brief import format_industry_html

    conn = sqlite3.connect(f"file:{production_db}?mode=ro", uri=True)
    try:
        rows = {
            str(r[0]): (str(r[1] or ""), str(r[2] or ""))
            for r in conn.execute(
                "SELECT stock_id, stock_name, industry FROM stock_universe WHERE stock_id IN ('2330','2408','5351')"
            )
        }
    finally:
        conn.close()
    assert rows["2330"][1] == "半導體業"
    assert rows["2408"][1] == "半導體業"
    assert rows["5351"][1] == "半導體業"
    html = format_industry_html("2330", production_db)
    assert "半導體業" in html
    assert "本族群產業狀況簡述" in html
    assert "這族資金" not in html
    assert "這族" not in html
    assert "不是論壇分類" not in html
    assert "年增特別大" not in html
    assert "也會幌" not in html
    assert "半導體業含代工、記憶體、設計" in html
    assert "本產業" in html
