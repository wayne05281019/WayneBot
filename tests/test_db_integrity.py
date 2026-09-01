import sqlite3


def test_db_quick_check_ok(tmp_path):
    from import_health import db_quick_check_ok

    good = tmp_path / "ok.db"
    conn = sqlite3.connect(good)
    conn.execute("CREATE TABLE t (x INTEGER)")
    conn.execute("INSERT INTO t VALUES (1)")
    conn.commit()
    conn.close()
    assert db_quick_check_ok(str(good), min_bytes=1)

    bad = tmp_path / "bad.db"
    bad.write_bytes(b"not a sqlite file" * 200_000)
    assert not db_quick_check_ok(str(bad), min_bytes=1)


def test_format_trading_date_zh():
    from trading_calendar import format_trading_date_zh

    assert format_trading_date_zh("20260828") == "2026/08/28（五）"
    assert format_trading_date_zh("20260831") == "2026/08/31（一）"
    assert format_trading_date_zh("20260901") == "2026/09/01（二）"
