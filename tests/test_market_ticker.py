# -*- coding: utf-8 -*-
from datetime import datetime
from zoneinfo import ZoneInfo

from PIL import Image

from market_ticker import (
    TICKER_FRAMES,
    TICKER_H,
    TICKER_INK_PAD,
    TICKER_W,
    collect_ticker,
    render_ticker_gif,
    ticker_loop_sec,
    ticker_plain,
    ticker_refresh_sec,
    ticker_send_kwargs,
    ticker_slot,
)

TW = ZoneInfo("Asia/Taipei")
NY = ZoneInfo("America/New_York")


def test_ticker_slot_windows():
    assert ticker_slot(datetime(2026, 9, 8, 10, 0, tzinfo=TW)) == "tw_open"
    assert ticker_slot(datetime(2026, 9, 8, 8, 25, tzinfo=TW)) == "tw_pre"
    assert ticker_slot(datetime(2026, 9, 8, 8, 31, tzinfo=TW)) == "tw_match"
    assert ticker_slot(datetime(2026, 9, 8, 13, 40, tzinfo=TW)) == "tw_after"
    assert ticker_slot(datetime(2026, 9, 8, 15, 5, tzinfo=TW)) == "tw_settled"
    assert ticker_slot(datetime(2026, 9, 8, 17, 30, tzinfo=TW)) == "us_pre"
    # 週二凌晨＝美股週一現金盤
    assert ticker_slot(datetime(2026, 9, 8, 1, 22, tzinfo=TW)) == "us_night"
    # 週六白天美股已收
    assert ticker_slot(datetime(2026, 9, 5, 12, 0, tzinfo=TW)) == "weekend"


def test_collect_omits_missing_and_keeps_tw(tmp_path):
    snap = {"close": 47326.27, "chg1_pct": 1.67, "futures": {"close": 47470, "pct_change": 0.3}}
    live = {"close": 47326.27, "pct_change": 1.67}
    now = datetime(2026, 9, 8, 10, 5, tzinfo=TW)
    bundle = collect_ticker(str(tmp_path / "x.db"), live=live, snap=snap, now=now, yahoo=False)
    assert bundle["slot"] == "tw_open"
    names = [x["name"] for x in bundle["items"]]
    assert "此刻" in names
    assert bundle["clock"] == "10:05:00"
    assert "加權" in names
    assert "台指期" in names
    assert "日經" not in names  # yahoo=False 不編造
    plain = ticker_plain(bundle)
    assert "台股開盤" in plain
    assert "47,326" in plain
    tw = next(x for x in bundle["items"] if x["name"] == "加權")
    assert "," not in tw["digits"]
    assert " " not in tw["digits"]
    assert tw["digits"] == "47326"
    assert tw.get("suffix") == "+1.67%"
    assert "10:05:00" in plain


def test_live_otc_and_tx_preferred(tmp_path):
    snap = {"close": 1.0, "chg1_pct": 0.0, "futures": {"close": 1, "pct_change": 0.0}}
    live = {"close": 47326.27, "pct_change": 1.67}
    otc = {"close": 409.33, "pct_change": 1.70}
    tx = {"close": 47470.0, "pct_change": 1.63}
    now = datetime(2026, 9, 8, 10, 5, tzinfo=TW)
    bundle = collect_ticker(
        str(tmp_path / "x.db"),
        live=live,
        snap=snap,
        now=now,
        yahoo=False,
        live_otc=otc,
        live_tx=tx,
    )
    text = ticker_plain(bundle)
    assert "櫃買 409.3" in text
    assert "47,470" in text
    assert "台指期 1" not in text


def test_pick_tx_front_month_by_volume():
    from market_ticker import pick_tx_quote_row

    rows = [
        {"SymbolID": "TXF-S", "CLastPrice": "47326", "CTotalVolume": "99999"},
        {"SymbolID": "TXFI6-F", "CLastPrice": "47470", "CTotalVolume": "80000", "CDiffRate": "1.63"},
        {"SymbolID": "TXFJ6-F", "CLastPrice": "47667", "CTotalVolume": "1200", "CDiffRate": "1.67"},
        {"SymbolID": "TXFI6-M", "CLastPrice": "47333", "CTotalVolume": "5000", "CDiffRate": "-0.20"},
    ]
    day = pick_tx_quote_row(rows, night=False)
    assert day["SymbolID"] == "TXFI6-F"
    night = pick_tx_quote_row(rows, night=True)
    assert night["SymbolID"] == "TXFI6-M"


def test_spark_prefers_last_minute_bar():
    from market_ticker import _quote_from_spark_block

    q = _quote_from_spark_block(
        {
            "symbol": "^N225",
            "close": [100.0, None, 110.0],
            "fulldayPrice": 99.0,
            "fulldayChangePercent": -1.0,
            "previousClose": 100.0,
            "chartPreviousClose": 100.0,
        },
        "^N225",
    )
    assert q["px"] == 110.0
    assert abs(q["pct"] - 10.0) < 0.01


def test_spark_uses_fullday_when_no_bars():
    from market_ticker import _quote_from_spark_block

    q = _quote_from_spark_block(
        {
            "symbol": "ES=F",
            "close": None,
            "fulldayPrice": 7722.0,
            "fulldayChangePercent": -0.422,
            "previousClose": 7754.75,
        },
        "ES=F",
    )
    assert q["px"] == 7722.0
    assert abs(q["pct"] + 0.422) < 0.001


def test_us_pre_does_not_invent_futures():
    now = datetime(2026, 9, 8, 17, 0, tzinfo=TW)
    bundle = collect_ticker(None, snap={"close": 100.0, "chg1_pct": 0.0}, now=now, yahoo=False)
    assert bundle["slot"] == "us_pre"
    names = [x["name"] for x in bundle["items"]]
    assert "標普期" not in names
    assert "那斯達克期" not in names


def test_render_gif_scrolls(tmp_path):
    bundle = {
        "title": "台股開盤",
        "items": [
            {"name": "加權", "text": "加權 47,326 +1.67%", "pct": 1.67},
            {"name": "台指期", "text": "台指期 47,470 +0.30%", "pct": 0.3},
            {"name": "日經", "text": "日經 38,000 -0.40%", "pct": -0.4},
            {"name": "韓國", "text": "韓國 2,550 +0.20%", "pct": 0.2},
            {"name": "滬指", "text": "滬指 3,100 +0.10%", "pct": 0.1},
        ],
    }
    path = str(tmp_path / "ticker.gif")
    out = render_ticker_gif(bundle, path)
    assert out == path
    with Image.open(path) as im:
        assert im.format == "GIF"
        assert im.size == (TICKER_W, TICKER_H)
        n = getattr(im, "n_frames", 1)
        assert n >= 8
        assert n == TICKER_FRAMES
    assert (tmp_path / "ticker.gif").stat().st_size > 2000


def test_morning_countdown_and_match_copy(tmp_path):
    snap = {"close": 47326.27, "chg1_pct": 1.67, "futures": {"close": 47470, "pct_change": 0.3}}
    live = {"close": 47326.27, "pct_change": 1.67}
    db = str(tmp_path / "x.db")
    pre = collect_ticker(db, live=live, snap=snap, now=datetime(2026, 9, 8, 8, 25, tzinfo=TW), yahoo=False)
    plain = ticker_plain(pre)
    assert pre["slot"] == "tw_pre"
    assert "距離試搓 05:00" in plain
    assert "距離台指期開盤 20:00" in plain
    assert "加權" not in plain
    match = collect_ticker(db, live=live, snap=snap, now=datetime(2026, 9, 8, 8, 31, tzinfo=TW), yahoo=False)
    mp = ticker_plain(match)
    assert "個股試搓價格中" in mp
    assert "距離台指期開盤 14:00" in mp
    assert "加權" not in mp
    tx_on = collect_ticker(
        db,
        live=live,
        snap=snap,
        now=datetime(2026, 9, 8, 8, 45, tzinfo=TW),
        yahoo=False,
        live_tx={"close": 47470.0, "pct_change": 1.63},
    )
    tp = ticker_plain(tx_on)
    assert "個股試搓價格中" in tp
    assert "47,470" in tp
    assert "距離台指期開盤" not in tp
    after = collect_ticker(
        db,
        live=live,
        snap=snap,
        now=datetime(2026, 9, 8, 13, 40, tzinfo=TW),
        yahoo=False,
        live_otc={"close": 409.33, "pct_change": 1.70},
    )
    ap = ticker_plain(after)
    assert "台股日盤收盤" in ap
    assert "加權盤後交易中" in ap
    assert "櫃買 409.3" in ap
    settled = collect_ticker(
        db,
        live=live,
        snap=snap,
        now=datetime(2026, 9, 8, 15, 5, tzinfo=TW),
        yahoo=False,
        live_otc={"close": 409.0, "pct_change": 1.2},
    )
    sp = ticker_plain(settled)
    assert "加權收盤" in sp
    assert "櫃買收盤" in sp
    assert "47,326" in sp


def test_render_gif_uses_casio_digits(tmp_path):
    bundle = {
        "title": "開盤倒數",
        "items": [
            {"name": "此刻", "label": "此刻", "digits": "08:25:00", "text": "此刻 08:25:00", "kind": "clock", "pct": None},
            {"name": "試搓", "label": "距離試搓", "digits": "05:00", "text": "距離試搓 05:00", "kind": "count", "pct": None},
        ],
    }
    path = str(tmp_path / "casio.gif")
    render_ticker_gif(bundle, path)
    with Image.open(path) as im:
        assert im.size == (TICKER_W, TICKER_H)
        rgb = im.convert("RGB")
        mint = 0
        for x in range(0, TICKER_W, 4):
            for y in range(10, TICKER_H - 10, 4):
                r, g, b = rgb.getpixel((x, y))[:3]
                if g >= r + 10 and g >= 140 and b < 200:
                    mint += 1
        assert mint >= 8


def test_render_gif_ink_hugs_top_and_bottom(tmp_path):
    """中文與七段要貼近上下緣，不能只擠在中間三分之一。"""
    bundle = {
        "title": "台股開盤",
        "items": [
            {
                "name": "加權",
                "label": "加權",
                "digits": "47326.78",
                "text": "加權 47326.78",
                "pct": 1.67,
            },
        ],
    }
    path = str(tmp_path / "hug.gif")
    render_ticker_gif(bundle, path)
    with Image.open(path) as im:
        rgb = im.convert("RGB")
        navy = (18, 26, 38)

        def ink_count(y0, y1):
            n = 0
            for y in range(y0, y1 + 1):
                for x in range(0, TICKER_W, 2):
                    p = rgb.getpixel((x, y))[:3]
                    if abs(p[0] - navy[0]) + abs(p[1] - navy[1]) + abs(p[2] - navy[2]) > 40:
                        n += 1
            return n

        top0 = TICKER_INK_PAD
        bot1 = TICKER_H - TICKER_INK_PAD - 1
        assert ink_count(top0, top0 + 2) >= 8
        assert ink_count(bot1 - 2, bot1) >= 8
        # 中間當然也有墨，但不能是唯一有字的區域
        mid0, mid1 = TICKER_H // 2 - 6, TICKER_H // 2 + 6
        assert ink_count(mid0, mid1) >= 8


def test_render_gif_full_width_always_scrolls(tmp_path):
    """短字也要整條從最左捲到最右，不能停在靜態一幀。"""
    bundle = {
        "title": "台股開盤",
        "items": [{"name": "加權", "text": "加權 47,326 +1.67%", "pct": 1.67}],
    }
    path = str(tmp_path / "short.gif")
    render_ticker_gif(bundle, path)
    with Image.open(path) as im:
        assert im.size == (TICKER_W, TICKER_H)
        n = getattr(im, "n_frames", 1)
        assert n == TICKER_FRAMES
        im.seek(0)
        first = im.convert("RGB").tobytes()
        left = im.convert("RGB").getpixel((6, 1))
        right = im.convert("RGB").getpixel((TICKER_W - 8, 1))
        assert left[2] >= 180 and right[2] >= 180
        im.seek(n // 2)
        mid = im.convert("RGB").tobytes()
        assert first != mid


def test_ticker_full_width_slow_loop_and_live_refresh(monkeypatch):
    assert TICKER_W >= 1080
    assert TICKER_H == 96
    assert ticker_loop_sec() >= 6
    kw = ticker_send_kwargs()
    assert kw["width"] == TICKER_W
    assert kw["height"] == TICKER_H
    monkeypatch.delenv("WAYNE_TICKER_REFRESH_SEC", raising=False)
    assert abs(ticker_refresh_sec() - ticker_loop_sec()) < 0.01
    monkeypatch.setenv("WAYNE_TICKER_REFRESH_SEC", "4")
    assert ticker_refresh_sec() == 4.0


def test_bot_market_page_no_longer_sends_ticker():
    src = open("bot_servers.py", encoding="utf-8").read()
    assert "build_market_ticker" not in src
    assert "_ticker_keyboard" not in src
    assert "tk:r" not in src
    assert "刷新跑馬燈" not in src


def test_ticker_sectors_and_alerts_from_official(tmp_path):
    import sqlite3

    from money_flow import ensure_sector_flow_table, peek_live_sector_rows

    db = str(tmp_path / "s.db")
    conn = sqlite3.connect(db)
    ensure_sector_flow_table(conn)
    conn.executemany(
        """
        INSERT INTO daily_sector_flow(date, industry, stock_n, avg_pct, three_net)
        VALUES (?, ?, ?, ?, ?)
        """,
        [
            ("20260907", "半導體業", 12, 1.82, 8000),
            ("20260907", "金融保險業", 8, 0.91, 3000),
            ("20260907", "鋼鐵工業", 6, -1.24, -4000),
            ("20260907", "航運業", 5, 0.02, 100),
        ],
    )
    conn.commit()
    conn.close()
    snap = {
        "close": 47326.27,
        "chg1_pct": 1.67,
        "as_of": "20260907",
        "official_breadth": {
            "up_count": 210,
            "down_count": 920,
            "limit_up": 4,
            "limit_down": 42,
        },
        "futures_lead": {"label": "期貨領跌"},
        "falling_risk": 70,
        "risk_zone": "elevated",
    }
    live = {"close": 47326.27, "pct_change": 1.67}
    bundle = collect_ticker(
        db,
        live=live,
        snap=snap,
        now=datetime(2026, 9, 8, 10, 5, tzinfo=TW),
        yahoo=False,
    )
    plain = ticker_plain(bundle)
    assert "昨收強勢 半導體" in plain
    assert "+1.82%" in plain
    assert "昨收弱勢 鋼鐵" in plain
    assert "-1.24%" in plain
    assert "跌停 42" in plain
    assert "跌家 920" not in plain
    assert "期貨領跌" not in plain
    assert "昨收強勢 金融" not in plain
    assert peek_live_sector_rows(db) == []

    live_bundle = collect_ticker(
        db,
        live=live,
        snap=snap,
        now=datetime(2026, 9, 8, 10, 5, tzinfo=TW),
        yahoo=False,
        live_sectors=[
            {"industry": "金融保險業", "avg_pct": 0.85, "mode": "live"},
            {"industry": "鋼鐵工業", "avg_pct": -1.10, "mode": "live"},
        ],
    )
    lp = ticker_plain(live_bundle)
    assert "強勢 金融" in lp
    assert "昨收強勢" not in lp
    assert "弱勢 鋼鐵" in lp
    assert "+0.85%" in lp


def test_ticker_does_not_invent_sectors(tmp_path):
    bundle = collect_ticker(
        str(tmp_path / "empty.db"),
        live={"close": 47326.27, "pct_change": 1.67},
        snap={"close": 47326.27, "chg1_pct": 1.67},
        now=datetime(2026, 9, 8, 10, 5, tzinfo=TW),
        yahoo=False,
    )
    plain = ticker_plain(bundle)
    assert "強勢" not in plain
    assert "弱勢" not in plain
    assert "警語" not in plain
    assert "法人買超" not in plain
