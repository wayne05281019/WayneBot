# -*- coding: utf-8 -*-
"""T86 股→張：對官方列、對齊籌碼K線四捨五入。"""
from chips import (
    _looks_like_share_as_lot,
    _shares_to_lots,
    parse_tpex_t86,
    parse_twse_t86,
)

_T86_FIELDS = [
    "證券代號",
    "證券名稱",
    "外陸資買進股數(不含外資自營商)",
    "外陸資賣出股數(不含外資自營商)",
    "外陸資買賣超股數(不含外資自營商)",
    "外資自營商買進股數",
    "外資自營商賣出股數",
    "外資自營商買賣超股數",
    "投信買進股數",
    "投信賣出股數",
    "投信買賣超股數",
    "自營商買賣超股數",
    "自營商買進股數(自行買賣)",
    "自營商賣出股數(自行買賣)",
    "自營商買賣超股數(自行買賣)",
    "自營商買進股數(避險)",
    "自營商賣出股數(避險)",
    "自營商買賣超股數(避險)",
    "三大法人買賣超股數",
]


def test_shares_to_lots_rounds_t86_shares():
    assert _shares_to_lots(-65) == 0
    assert _shares_to_lots(-402) == 0
    assert _shares_to_lots(218964) == 219
    assert _shares_to_lots(-221000) == -221
    assert _shares_to_lots(90185) == 90
    assert _shares_to_lots(-2885) == -3
    assert _shares_to_lots(3955) == 4
    assert _shares_to_lots(4839) == 5
    assert _shares_to_lots(99951) == 100
    assert _shares_to_lots(-1680) == -2
    assert _shares_to_lots(0) == 0
    assert _shares_to_lots(-382) == 0


def test_looks_like_share_as_lot_2724_style():
    """成交 8 張、合計 -382＝舊股當張殘值；合計 0 或真張數不誤判。"""
    assert _looks_like_share_as_lot(8, -382) is True
    assert _looks_like_share_as_lot(8, 0) is False
    assert _looks_like_share_as_lot(5000, -382) is False
    assert _looks_like_share_as_lot(8, -2000) is False
    assert _looks_like_share_as_lot(8, -382, vol_mult=20) is True
    # 真張數 500、量 200：嚴門檻不誤殺
    assert _looks_like_share_as_lot(200, 500, vol_mult=20) is False


def test_scrub_share_as_lot_residue_offline_zeros_2724_style(tmp_path):
    from chips import scrub_share_as_lot_residue_offline

    db = str(tmp_path / "t.db")
    conn = __import__("sqlite3").connect(db)
    conn.execute(
        """
        CREATE TABLE daily_quotes(
            date TEXT, stock_id TEXT, volume INTEGER,
            foreign_net INTEGER, trust_net INTEGER, dealer_net INTEGER
        )
        """
    )
    conn.execute(
        "INSERT INTO daily_quotes VALUES ('20260915','2724',8,0,0,-382)"
    )
    conn.execute(
        "INSERT INTO daily_quotes VALUES ('20260915','2330',50000,100,0,-50)"
    )
    conn.commit()
    conn.close()
    n = scrub_share_as_lot_residue_offline(db)
    assert n == 1
    conn = __import__("sqlite3").connect(db)
    row = conn.execute(
        "SELECT foreign_net, trust_net, dealer_net FROM daily_quotes WHERE stock_id='2724'"
    ).fetchone()
    keep = conn.execute(
        "SELECT dealer_net FROM daily_quotes WHERE stock_id='2330'"
    ).fetchone()
    conn.close()
    assert row == (0, 0, 0)
    assert keep == (-50,)


def test_parse_twse_t86_6526_20260917_dealer_is_zero_lots():
    """官方 6526 20260917：自營合計 -65 股＝0 張，三大法人 90,185 股＝90 張。"""
    payload = {
        "fields": _T86_FIELDS,
        "data": [
            [
                "6526",
                "達發",
                "239,282",
                "149,032",
                "90,250",
                "0",
                "0",
                "0",
                "0",
                "0",
                "0",
                "-65",
                "2,210",
                "0",
                "2,210",
                "3,497",
                "5,772",
                "-2,275",
                "90,185",
            ]
        ],
    }
    got = parse_twse_t86(payload)["6526"]
    assert got["foreign_net"] == 90
    assert got["trust_net"] == 0
    assert got["dealer_net"] == 0
    assert got["three_net"] == 90


def test_parse_twse_t86_6526_20260908_dealer_not_minus_402_lots():
    """官方自營合計 -402 股＝0 張，不是 -402 張。"""
    payload = {
        "fields": _T86_FIELDS,
        "data": [
            [
                "6526",
                "達發",
                "0",
                "0",
                "67,332",
                "0",
                "0",
                "0",
                "0",
                "0",
                "0",
                "-402",
                "0",
                "2,100",
                "-2,100",
                "1,698",
                "0",
                "1,698",
                "66,930",
            ]
        ],
    }
    got = parse_twse_t86(payload)["6526"]
    assert got["foreign_net"] == 67
    assert got["trust_net"] == 0
    assert got["dealer_net"] == 0
    assert got["three_net"] == 67


def test_parse_tpex_2724_20260915_dealer_minus_382_shares_is_zero_lots():
    """櫃買官方 2724 20260915：自營／三大法人 -382 股＝0 張，不是 -382 張。"""
    fields = [
        "代號",
        "名稱",
        "買進股數",
        "賣出股數",
        "買賣超股數",
        "買進股數",
        "賣出股數",
        "買賣超股數",
        "買進股數",
        "賣出股數",
        "買賣超股數",
        "買進股數",
        "賣出股數",
        "買賣超股數",
        "買進股數",
        "賣出股數",
        "買賣超股數",
        "買進股數",
        "賣出股數",
        "買賣超股數",
        "買進股數",
        "賣出股數",
        "買賣超股數",
        "三大法人買賣超股數合計",
    ]
    row = [
        "2724",
        "藝舍-KY",
        "0",
        "0",
        "0",
        "0",
        "0",
        "0",
        "0",
        "0",
        "0",
        "0",
        "0",
        "0",
        "0",
        "0",
        "0",
        "0",
        "382",
        "-382",
        "0",
        "382",
        "-382",
        "-382",
    ]
    payload = {"tables": [{"fields": fields, "data": [row]}]}
    got = parse_tpex_t86(payload)["2724"]
    assert got["foreign_net"] == 0
    assert got["trust_net"] == 0
    assert got["dealer_net"] == 0
    assert got["three_net"] == 0


def test_apply_chips_retries_through_short_lock(tmp_path, monkeypatch):
    """開機／早報窗 DB locked：busy＋重試後仍要寫進，不准整段近窗重抓炸掉。"""
    import sqlite3

    import chips
    from chips import apply_chips_to_quotes

    db = str(tmp_path / "t.db")
    conn = sqlite3.connect(db)
    conn.execute(
        """
        CREATE TABLE daily_quotes(
            date TEXT, stock_id TEXT,
            foreign_net INTEGER, trust_net INTEGER, dealer_net INTEGER
        )
        """
    )
    conn.execute("INSERT INTO daily_quotes VALUES ('20261103','2330',0,0,0)")
    conn.commit()
    conn.close()

    real_connect = chips._connect
    calls = {"n": 0}

    def _flaky_connect(path, **kwargs):
        calls["n"] += 1
        if calls["n"] <= 2:
            raise sqlite3.OperationalError("database is locked")
        return real_connect(path, **kwargs)

    monkeypatch.setattr(chips, "_connect", _flaky_connect)
    monkeypatch.setattr(chips.time, "sleep", lambda *_a, **_k: None)
    n = apply_chips_to_quotes(
        db, "20261103", {"2330": {"foreign_net": 12, "trust_net": 3, "dealer_net": -1}}
    )
    assert n == 1
    assert calls["n"] >= 3
    c = sqlite3.connect(db)
    row = c.execute(
        "SELECT foreign_net, trust_net, dealer_net FROM daily_quotes WHERE stock_id='2330'"
    ).fetchone()
    c.close()
    assert row == (12, 3, -1)


def test_rebake_continues_after_one_day_locked(tmp_path, monkeypatch):
    """單日重試用盡仍 locked：續跑後面殘值日，不准整段開機重抓炸掉。"""
    import sqlite3

    import chips
    from chips import rebake_share_as_lot_chip_dates

    db = str(tmp_path / "rebake.db")
    conn = sqlite3.connect(db)
    conn.execute(
        """
        CREATE TABLE daily_quotes(
            date TEXT, stock_id TEXT, volume INTEGER,
            foreign_net INTEGER, trust_net INTEGER, dealer_net INTEGER
        )
        """
    )
    # 股當張殘值：three=100、vol=1 → 進殘值日清單
    for day, sid in (("20261102", "2330"), ("20261103", "2330")):
        conn.execute(
            "INSERT INTO daily_quotes VALUES (?,?,?,?,?,?)",
            (day, sid, 1, 100, 0, 0),
        )
    conn.commit()
    conn.close()

    calls: list[str] = []

    def _fake_update(path, day, session=None):
        calls.append(str(day))
        if str(day) == "20261102":
            raise sqlite3.OperationalError("database is locked")
        return 7

    monkeypatch.setattr(chips, "update_chips_for_date", _fake_update)
    monkeypatch.setattr(chips.time, "sleep", lambda *_a, **_k: None)
    out = rebake_share_as_lot_chip_dates(db, since_ymd="20261101", sleep_s=0)
    assert calls == ["20261102", "20261103"]
    assert out["dates"] == 2
    assert out["updated_rows"] == 7
    assert out["failed_n"] == 1
    assert out["failed_dates"] == ["20261102"]
    assert ("20261103", 7) in out["detail"]
