def test_screening_fail_message_no_fallback_wording(monkeypatch):
    from main_runner import MainRunner

    monkeypatch.setattr(
        "trading_calendar.resolve_screen_as_of",
        lambda _db, **_: "20260828",
    )
    runner = MainRunner.__new__(MainRunner)
    runner.db_path = ":memory:"
    runner.today_str = "20260901"
    msg = runner._screening_fail_message()
    assert "當沖" in msg
    assert "隔日沖" in msg
    assert "動能突破" not in msg
    assert "排程通知" in msg


def test_screening_delivered_requires_payload_or_status():
    from main_runner import MainRunner

    assert not MainRunner._screening_delivered(None)
    assert not MainRunner._screening_delivered({})
    assert MainRunner._screening_delivered({"status": "success", "payload": [{"html": "x"}]})
    assert MainRunner._screening_delivered({"status": "empty", "message": "無標的"})


def test_push_screening_failure_skips_extras(monkeypatch):
    from main_runner import MainRunner

    runner = MainRunner.__new__(MainRunner)
    runner.db_path = ":memory:"
    runner.today_str = "20260901"
    runner.bot = object()
    sent = []

    runner.send_telegram_message = lambda text: sent.append(("msg", text))
    runner._format_portfolio_section = lambda: "PORTFOLIO"
    runner._run_ai_desk = lambda *a, **k: sent.append(("ai", True))

    runner._push_screening(None, as_of="20260831")

    assert len(sent) == 1
    assert sent[0][0] == "msg"
    assert "今早海選未完成" in sent[0][1]
    assert "排程通知" in sent[0][1]


def test_push_screening_success_skips_ai_push(monkeypatch):
    from main_runner import MainRunner

    runner = MainRunner.__new__(MainRunner)
    runner.db_path = ":memory:"
    runner.today_str = "20260901"
    runner.bot = type("B", (), {"send_screening_report": lambda _s, _x: None})()
    sent = []
    ai_calls = []

    runner.send_telegram_message = lambda text: sent.append(text)
    runner._format_watch_radar_section = lambda: ""
    runner._run_ai_desk = lambda *a, **k: ai_calls.append(k) or {}

    runner._push_screening(
        {"status": "success", "payload": [{"html": "海選"}]},
        as_of="20260831",
    )

    assert len(ai_calls) == 1
    assert ai_calls[0].get("notify") is False
    assert all("AI 模擬帳戶" not in (m or "") for m in sent)
