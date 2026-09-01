def test_screening_fail_message_no_fallback_wording(monkeypatch):
    from main_runner import MainRunner

    monkeypatch.setattr(
        "import_health.latest_complete_quote_date",
        lambda _db, **_: "20260829",
    )
    runner = MainRunner.__new__(MainRunner)
    runner.db_path = ":memory:"
    runner.today_str = "20260901"
    msg = runner._screening_fail_message()
    assert "當沖" in msg
    assert "隔日沖" in msg
    assert "動能突破" not in msg
