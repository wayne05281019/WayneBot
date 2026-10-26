"""寄出回執：DB lock 時仍可靠檔擋重寄。"""


def test_record_survives_db_lock_via_file(tmp_path, monkeypatch):
    import sqlite3

    import pipeline_delivery as pd

    db = str(tmp_path / "x.db")
    # 真庫先建好
    pd.ensure_delivery_schema(db)
    real = sqlite3.connect
    calls = {"n": 0}

    def _flaky(*a, **k):
        calls["n"] += 1
        # 讓 record 的 DB 寫入全失敗，只留檔
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(pd.sqlite3, "connect", _flaky)
    monkeypatch.setattr(pd.time, "sleep", lambda *_a, **_k: None)
    ok = pd.record_push_delivery(
        db, "screen-20261022", kind="morning-digest", n_ok=2, retries=3
    )
    assert ok is True
    # 查詢時改回真 connect
    monkeypatch.setattr(pd.sqlite3, "connect", real)
    assert pd.push_delivery_recorded(db, "screen-20261022") is True
    loaded = pd.load_push_delivery(db, "screen-20261022")
    assert loaded is not None
    assert loaded["n_ok"] == 2


def test_record_and_query_roundtrip(tmp_path):
    import pipeline_delivery as pd

    db = str(tmp_path / "ok.db")
    assert (
        pd.record_push_delivery(
            db, "midday-20261022", kind="midday", n_ok=2, notes="x"
        )
        is True
    )
    assert pd.push_delivery_recorded(db, "midday-20261022") is True
    assert pd.push_delivery_recorded(db, "midday-missing") is False


def test_delivery_taipei_ymd_and_clear(tmp_path):
    import pipeline_delivery as pd

    assert pd.delivery_taipei_ymd("2026-10-23T06:32:00+08:00") == "20261023"
    assert pd.delivery_taipei_ymd("2026-10-22 22:32:00+00:00") == "20261023"
    db = str(tmp_path / "clr.db")
    assert (
        pd.record_push_delivery(
            db, "screen-20261022", kind="morning-digest", n_ok=2
        )
        is True
    )
    assert pd.push_delivery_recorded(db, "screen-20261022") is True
    assert pd.clear_push_delivery(db, "screen-20261022", bak_suffix=".bak-t") is True
    assert pd.push_delivery_recorded(db, "screen-20261022") is False
