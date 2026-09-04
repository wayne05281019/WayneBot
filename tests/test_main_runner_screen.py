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


def test_evening_skip_reruns_ai_from_snapshot(monkeypatch, tmp_path):
    """16:30 已寫 evening 快照時，20:00 不能整段略過，要用快照再跑模擬倉。"""
    from screen_sessions import save_screen_session
    from wayne_db import ensure_core_schema
    from main_runner import MainRunner

    db = str(tmp_path / "eve.db")
    ensure_core_schema(db)
    save_screen_session(
        db,
        "20260904",
        "evening",
        {"leave_zero": [{"stock_id": "4915", "stock_name": "致伸", "close": 60.8}]},
    )
    runner = MainRunner.__new__(MainRunner)
    runner.db_path = db
    runner.today_str = "20260904"
    ai = []
    screened = []

    def boom(*_a, **_k):
        screened.append(True)
        raise AssertionError("skip_if_done 不該重跑全市場海選")

    monkeypatch.setattr("import_health.latest_complete_quote_date", lambda _db: "20260904")
    runner.already_completed_today = lambda _key=None: True
    runner._run_ai_desk = lambda as_of, results=None, **k: ai.append(
        {"as_of": as_of, "results": results, **k}
    ) or {}
    monkeypatch.setattr("main_runner.run_full_screening", boom)

    assert runner.run_evening_screen(skip_if_done=True, notify=False) is True
    assert screened == []
    assert ai[0]["as_of"] == "20260904"
    assert ai[0]["results"]["leave_zero"][0]["stock_id"] == "4915"
    assert ai[0]["results"]["leave_zero"][0]["close"] == 60.8
    assert ai[0].get("notify") is False
