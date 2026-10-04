import sqlite3


def test_db_quick_check_ok(tmp_path):
    from import_health import db_liveness_ok, db_quick_check_ok

    good = tmp_path / "ok.db"
    conn = sqlite3.connect(good)
    conn.execute("CREATE TABLE t (x INTEGER)")
    conn.execute("INSERT INTO t VALUES (1)")
    conn.commit()
    conn.close()
    assert db_quick_check_ok(str(good), min_bytes=1)
    assert db_liveness_ok(str(good), min_bytes=1)

    bad = tmp_path / "bad.db"
    bad.write_bytes(b"not a sqlite file" * 200_000)
    assert not db_quick_check_ok(str(bad), min_bytes=1)
    assert not db_liveness_ok(str(bad), min_bytes=1)

    missing = tmp_path / "gone.db"
    assert not db_liveness_ok(str(missing), min_bytes=1)


def test_liveness_snapshot_uses_cheap_db_check():
    """健檢路徑不准 PRAGMA quick_check（會卡過 Render 5s）。"""
    import inspect

    import main

    src = inspect.getsource(main._liveness_snapshot)
    assert "db_liveness_ok" in src
    assert "db_quick_check_ok" not in src
    run_src = inspect.getsource(main.run_web)
    assert "db_liveness_ok" in run_src


def test_format_trading_date_zh():
    from trading_calendar import format_trading_date_zh

    assert format_trading_date_zh("20260828") == "2026/08/28（五）"
    assert format_trading_date_zh("20260831") == "2026/08/31（一）"
    assert format_trading_date_zh("20260901") == "2026/09/01（二）"
