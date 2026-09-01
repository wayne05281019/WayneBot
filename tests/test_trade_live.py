from trade_live import (
    apply_trade_live,
    format_trade_live_line,
    passes_daytrade_live,
    passes_overnight_live,
)


def test_format_trade_live_line_shows_hhmm():
    line = format_trade_live_line(
        {
            "price": 100.5,
            "change": 2.5,
            "pct": 2.55,
            "update_time": "09:45:12",
        }
    )
    assert "100.50" in line
    assert "+2.50" in line
    assert "<i>09:45</i>" in line


def test_passes_daytrade_live_range():
    live = {"price": 105.0, "yesterday_close": 100.0}
    assert passes_daytrade_live(live)
    assert not passes_daytrade_live({"price": 110.0, "yesterday_close": 100.0})
    assert not passes_daytrade_live({"price": 101.0, "yesterday_close": 100.0})


def test_passes_overnight_live_min_pct():
    live = {"price": 103.0, "yesterday_close": 100.0}
    assert passes_overnight_live(live)
    assert not passes_overnight_live({"price": 102.0, "yesterday_close": 100.0})


def test_apply_trade_live_filters(monkeypatch):
    rows = [
        {"code": "2330", "name": "台積電"},
        {"code": "2317", "name": "鴻海"},
    ]

    def fake_batch(codes, db_path):
        return {
            "2330": {
                "price": 105.0,
                "yesterday_close": 100.0,
                "change": 5.0,
                "pct": 5.0,
                "volume": 50000,
                "update_time": "10:30:00",
            },
            "2317": {
                "price": 100.5,
                "yesterday_close": 100.0,
                "change": 0.5,
                "pct": 0.5,
                "volume": 1000,
                "update_time": "10:30:01",
            },
        }

    def fake_rank(db_path, vols):
        return {"2330": 3}

    monkeypatch.setattr("trade_live.fetch_mis_batch", fake_batch)
    monkeypatch.setattr("live_quote.live_vol_rank_120_batch", fake_rank)
    out = apply_trade_live(rows, ":memory:", "daytrade")
    assert len(out) == 1
    assert out[0]["code"] == "2330"
    assert out[0]["live"]["update_time"] == "10:30:00"
    assert out[0]["live"]["vol_rank_120"] == 3
    assert out[0]["vol_rank_120"] == 3
