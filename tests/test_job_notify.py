def test_notify_increment_result_ok(tmp_path):
    import sqlite3

    from main_runner import MainRunner

    db = tmp_path / "n.db"
    conn = sqlite3.connect(db)
    conn.execute(
        "CREATE TABLE daily_quotes (stock_id TEXT, market TEXT, date TEXT, close REAL, "
        "volume INTEGER, foreign_net INTEGER, trust_net INTEGER, dealer_net INTEGER)"
    )
    for i in range(900):
        conn.execute(
            "INSERT INTO daily_quotes VALUES (?, 'TW', '20260901', 100, 1000, 1, 0, 0)",
            (f"T{i:04d}",),
        )
    for i in range(700):
        conn.execute(
            "INSERT INTO daily_quotes VALUES (?, 'OTC', '20260901', 50, 500, 0, 0, 0)",
            (f"O{i:04d}",),
        )
    conn.commit()
    conn.close()

    sent = []
    runner = MainRunner(db_path=str(db))
    runner.chat_id = "123"
    runner.send_telegram_message = lambda t: sent.append(t)
    runner.notify_increment_result(
        source="測試",
        health={"tw": 1318, "two": 888, "total": 2206},
        cap="20260901",
    )
    assert sent
    assert "盤後行情已更新" in sent[0]
    assert "2026/09/01（二）" in sent[0]
