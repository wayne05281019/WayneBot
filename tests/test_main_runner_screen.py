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

    runner.send_telegram_message = lambda text, chat_id=None: sent.append(("msg", text))
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
    runner.bot = type("B", (), {"send_screening_report": lambda _s, _x, chat_id=None: None})()
    sent = []
    ai_calls = []

    runner.send_telegram_message = lambda text, chat_id=None: sent.append(text)
    runner._format_watch_radar_section = lambda uid="": ""
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


def test_oneshot_jobs_skip_if_already_done():
    src = open("main_runner.py", encoding="utf-8").read()
    assert "skip_if_done = True" in src
    assert 'GITHUB_EVENT_NAME' in src
    assert "run_morning_screen(" in src
    assert "skip_if_done=skip_if_done" in src
    assert "notify=screen_notify_enabled()" in src
    assert "run_evening_screen(skip_if_done=True, notify=False)" in src
    assert "run_midday_review(skip_if_done=True)" in src
    assert "run_increment_job(skip_if_done=True, notify=not gha)" in src
    assert 'os.getenv("GITHUB_ACTIONS")' in src
    assert "demote_unsent_screen_success" in src


def test_oneshot_morning_push_trigger_does_not_skip():
    src = open("main_runner.py", encoding="utf-8").read()
    assert 'os.getenv("GITHUB_EVENT_NAME")' in src
    assert "skip_if_done = False" in src


def test_screen_notify_defaults_on_and_gha_can_mute(monkeypatch):
    from config import screen_notify_enabled

    monkeypatch.delenv("WAYNE_SCREEN_NOTIFY", raising=False)
    assert screen_notify_enabled() is True
    monkeypatch.setenv("WAYNE_SCREEN_NOTIFY", "0")
    assert screen_notify_enabled() is False


def test_family_chat_ids_owner_and_touched_users(tmp_path, monkeypatch):
    from main_runner import MainRunner
    from wayne_db import ensure_core_schema, touch_tg_user

    monkeypatch.delenv("WAYNE_FAMILY_CHAT_IDS", raising=False)
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "9001")
    monkeypatch.delenv("TG_CHAT_ID", raising=False)
    path = str(tmp_path / "fam.db")
    ensure_core_schema(path)
    touch_tg_user(path, "9001", "偉權")
    touch_tg_user(path, "9002", "家人")
    runner = MainRunner.__new__(MainRunner)
    runner.db_path = path
    runner.chat_id = "9001"
    assert runner._family_chat_ids() == ["9001", "9002"]


def test_family_chat_ids_include_env_extras(tmp_path, monkeypatch):
    from main_runner import MainRunner
    from wayne_db import ensure_core_schema, touch_tg_user

    monkeypatch.setenv("WAYNE_FAMILY_CHAT_IDS", "9003")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "9001,9004")
    monkeypatch.delenv("TG_CHAT_ID", raising=False)
    path = str(tmp_path / "fam.db")
    ensure_core_schema(path)
    touch_tg_user(path, "9001", "偉權")
    runner = MainRunner.__new__(MainRunner)
    runner.db_path = path
    runner.chat_id = "9001"
    assert runner._family_chat_ids() == ["9001", "9003", "9004"]


def test_extra_family_chat_ids_skips_owner_only_telegram_id(monkeypatch):
    from config import extra_family_chat_ids, get_telegram_chat_id

    monkeypatch.delenv("WAYNE_FAMILY_CHAT_IDS", raising=False)
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "9001")
    monkeypatch.setenv("TG_CHAT_ID", "9001")
    assert extra_family_chat_ids() == []
    assert get_telegram_chat_id() == "9001"


def test_watch_radar_section_is_per_uid_not_owner():
    from main_runner import MainRunner

    runner = MainRunner.__new__(MainRunner)
    runner.chat_id = "9001"
    seen = []

    class _Eng:
        def get_watchlist(self, uid):
            seen.append(str(uid))
            if str(uid) == "9002":
                return [{"stock_id": "2330", "stock_name": "台積電"}]
            return [{"stock_id": "2317", "stock_name": "鴻海"}]

    runner.portfolio_engine = _Eng()
    runner._load_latest_quotes_map = lambda: {}
    wayne = runner._format_watch_radar_section("9001")
    bro = runner._format_watch_radar_section("9002")
    assert seen == ["9001", "9002"]
    assert "2317" in wayne and "2330" not in wayne
    assert "2330" in bro and "2317" not in bro


def test_push_screening_radar_keyed_by_each_family_uid(tmp_path, monkeypatch):
    from main_runner import MainRunner
    from wayne_db import ensure_core_schema, touch_tg_user

    monkeypatch.delenv("WAYNE_FAMILY_CHAT_IDS", raising=False)
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "9001")
    monkeypatch.delenv("TG_CHAT_ID", raising=False)
    path = str(tmp_path / "fam.db")
    ensure_core_schema(path)
    touch_tg_user(path, "9001", "偉權")
    touch_tg_user(path, "9002", "家人")
    runner = MainRunner.__new__(MainRunner)
    runner.db_path = path
    runner.chat_id = "9001"
    runner.today_str = "20260901"
    runner.portfolio_engine = None
    radar_uids = []
    sent = []

    class _Bot:
        def send_screening_report(self, screening, chat_id=None):
            sent.append(("screen", chat_id))

    runner.bot = _Bot()
    runner.send_telegram_message = lambda text, chat_id=None: sent.append(("extra", chat_id, text))
    runner._run_ai_desk = lambda *a, **k: {}
    runner._format_watch_radar_section = lambda uid="": radar_uids.append(str(uid)) or f"RADAR-{uid}"
    runner._push_screening(
        {"status": "success", "payload": [{"html": "海選"}], "results": {}},
        as_of="20260831",
    )
    assert ("screen", "9001") in sent
    assert ("screen", "9002") in sent
    assert radar_uids == ["9001", "9002"]
    assert ("extra", "9001", "RADAR-9001") in sent
    assert ("extra", "9002", "RADAR-9002") in sent


def test_push_screening_sends_each_family_member(tmp_path, monkeypatch):
    from main_runner import MainRunner
    from wayne_db import ensure_core_schema, touch_tg_user

    monkeypatch.delenv("WAYNE_FAMILY_CHAT_IDS", raising=False)
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "9001")
    monkeypatch.delenv("TG_CHAT_ID", raising=False)
    path = str(tmp_path / "fam.db")
    ensure_core_schema(path)
    touch_tg_user(path, "9001", "偉權")
    touch_tg_user(path, "9002", "家人")
    runner = MainRunner.__new__(MainRunner)
    runner.db_path = path
    runner.chat_id = "9001"
    runner.today_str = "20260901"
    runner.portfolio_engine = None
    sent = []

    class _Bot:
        def send_screening_report(self, screening, chat_id=None):
            sent.append(("screen", chat_id))

    runner.bot = _Bot()
    runner.send_telegram_message = lambda text, chat_id=None: sent.append(("extra", chat_id))
    runner._run_ai_desk = lambda *a, **k: {}
    runner._format_watch_radar_section = lambda uid="": ""
    runner._push_screening(
        {"status": "success", "payload": [{"html": "海選"}], "results": {}},
        as_of="20260831",
    )
    assert ("screen", "9001") in sent
    assert ("screen", "9002") in sent


def test_push_screening_returns_false_when_telegram_rejects(tmp_path, monkeypatch):
    from main_runner import MainRunner
    from wayne_db import ensure_core_schema, touch_tg_user

    monkeypatch.delenv("WAYNE_FAMILY_CHAT_IDS", raising=False)
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "9001")
    monkeypatch.delenv("TG_CHAT_ID", raising=False)
    path = str(tmp_path / "rej.db")
    ensure_core_schema(path)
    touch_tg_user(path, "9001", "偉權")
    runner = MainRunner.__new__(MainRunner)
    runner.db_path = path
    runner.chat_id = "9001"
    runner.today_str = "20260909"
    runner.portfolio_engine = None
    extras = []

    class _Bot:
        def send_screening_report(self, screening, chat_id=None):
            return False

    runner.bot = _Bot()
    runner.send_telegram_message = lambda text, chat_id=None: extras.append((chat_id, text))
    runner._run_ai_desk = lambda *a, **k: extras.append("ai")
    ok = runner._push_screening(
        {"status": "success", "payload": [{"html": "海選"}], "results": {}},
        as_of="20260908",
    )
    assert ok is False
    assert extras == []


def test_morning_screen_does_not_mark_when_telegram_rejects(tmp_path, monkeypatch):
    from main_runner import MainRunner
    from wayne_db import ensure_core_schema, touch_tg_user

    path = str(tmp_path / "mark.db")
    ensure_core_schema(path)
    touch_tg_user(path, "9001", "偉權")
    runner = MainRunner.__new__(MainRunner)
    runner.db_path = path
    runner.today_str = "20260909"
    runner.chat_id = "9001"
    runner.bot = type("B", (), {"send_screening_report": staticmethod(lambda *a, **k: False)})()

    monkeypatch.setattr("tw_holidays.refresh_tw_typhoon_halt", lambda *_a, **_k: {})
    monkeypatch.setattr("tw_holidays.closed_tw_session", lambda **_k: None)
    monkeypatch.setattr("import_health.latest_complete_quote_date", lambda *_a, **_k: "20260908")
    monkeypatch.setattr("config.fuse_end_date", lambda: "20260908")
    monkeypatch.setattr(
        "main_runner.run_full_screening",
        lambda **_k: {"status": "success", "payload": [{"html": "海選"}], "results": {}},
    )
    monkeypatch.setattr("taiwan_market.sync_futures_daily", lambda *_a, **_k: {})
    monkeypatch.setattr("taiwan_market.sync_futures_inst_oi", lambda *_a, **_k: {})
    monkeypatch.setattr("us_overnight.refresh_us_overnight", lambda *_a, **_k: {})
    monkeypatch.setattr("us_overnight.should_alert_us_drop", lambda *_a, **_k: False)
    runner._refresh_official_sidecars = lambda: None

    assert runner.run_morning_screen(skip_if_done=False, notify=True) is False
    assert runner.already_completed_today("screen-20260908") is False
    assert runner.run_morning_screen(skip_if_done=True, notify=True) is False
    assert runner.already_completed_today("screen-20260908") is False


def test_morning_screen_marks_only_after_telegram_accepts(tmp_path, monkeypatch):
    from main_runner import MainRunner
    from wayne_db import ensure_core_schema, touch_tg_user

    path = str(tmp_path / "ok.db")
    ensure_core_schema(path)
    touch_tg_user(path, "9001", "偉權")
    runner = MainRunner.__new__(MainRunner)
    runner.db_path = path
    runner.today_str = "20260909"
    runner.chat_id = "9001"
    runner.bot = type("B", (), {"send_screening_report": staticmethod(lambda *a, **k: True)})()
    runner._format_watch_radar_section = lambda uid="": ""
    runner._run_ai_desk = lambda *a, **k: {}
    runner.send_telegram_message = lambda *a, **k: None

    monkeypatch.setattr("tw_holidays.refresh_tw_typhoon_halt", lambda *_a, **_k: {})
    monkeypatch.setattr("tw_holidays.closed_tw_session", lambda **_k: None)
    monkeypatch.setattr("import_health.latest_complete_quote_date", lambda *_a, **_k: "20260908")
    monkeypatch.setattr("config.fuse_end_date", lambda: "20260908")
    monkeypatch.setattr(
        "main_runner.run_full_screening",
        lambda **_k: {"status": "success", "payload": [{"html": "海選"}], "results": {}},
    )
    monkeypatch.setattr("taiwan_market.sync_futures_daily", lambda *_a, **_k: {})
    monkeypatch.setattr("taiwan_market.sync_futures_inst_oi", lambda *_a, **_k: {})
    monkeypatch.setattr("us_overnight.refresh_us_overnight", lambda *_a, **_k: {})
    monkeypatch.setattr("us_overnight.should_alert_us_drop", lambda *_a, **_k: False)
    monkeypatch.setattr("taiwan_market.format_taiwan_market_brief_html", lambda *_a, **_k: "")
    monkeypatch.setattr("taiwan_market.analyze_taiwan_market", lambda *_a, **_k: {"ok": False})
    runner._refresh_official_sidecars = lambda: None

    assert runner.run_morning_screen(skip_if_done=False, notify=True) is True
    assert runner.already_completed_today("screen-20260908") is True


def test_send_html_returns_false_on_http_error(monkeypatch, caplog):
    import logging

    from bot_servers import WayneTelegramBot

    class _Resp:
        status_code = 400
        text = '{"ok":false,"description":"Bad Request: can\'t parse entities"}'

    monkeypatch.setattr("requests.post", lambda *a, **k: _Resp())
    bot = object.__new__(WayneTelegramBot)
    bot.token = "x"
    bot.chat_id = "1"
    with caplog.at_level(logging.ERROR):
        assert bot._send_html("1", "<b>hi</b>") is False
    assert "send_html HTTP 400" in caplog.text


def test_send_html_returns_true_on_200(monkeypatch):
    from bot_servers import WayneTelegramBot

    class _Resp:
        status_code = 200
        text = '{"ok":true}'

    monkeypatch.setattr("requests.post", lambda *a, **k: _Resp())
    bot = object.__new__(WayneTelegramBot)
    bot.token = "x"
    bot.chat_id = "1"
    assert bot._send_html("1", "<b>hi</b>") is True


def test_send_screening_report_empty_dest_returns_false():
    from bot_servers import WayneTelegramBot

    bot = object.__new__(WayneTelegramBot)
    bot.token = ""
    bot.chat_id = ""
    assert bot.send_screening_report({"payload": [{"html": "x"}]}) is False


def _stub_morning_deps(monkeypatch, runner):
    monkeypatch.setattr("tw_holidays.refresh_tw_typhoon_halt", lambda *_a, **_k: {})
    monkeypatch.setattr("tw_holidays.closed_tw_session", lambda **_k: None)
    monkeypatch.setattr("import_health.latest_complete_quote_date", lambda *_a, **_k: "20260908")
    monkeypatch.setattr("config.fuse_end_date", lambda: "20260908")
    monkeypatch.setattr(
        "main_runner.run_full_screening",
        lambda **_k: {"status": "success", "payload": [{"html": "海選"}], "results": {}},
    )
    monkeypatch.setattr("taiwan_market.sync_futures_daily", lambda *_a, **_k: {})
    monkeypatch.setattr("taiwan_market.sync_futures_inst_oi", lambda *_a, **_k: {})
    monkeypatch.setattr("us_overnight.refresh_us_overnight", lambda *_a, **_k: {})
    monkeypatch.setattr("us_overnight.should_alert_us_drop", lambda *_a, **_k: False)
    runner._refresh_official_sidecars = lambda: None


def test_morning_notify_off_marks_computed_not_success(tmp_path, monkeypatch):
    """GHA 不算已寄過：Release zip 灌進 Render 不能讓 skip_if_done 跳過真寄。"""
    from main_runner import MainRunner
    from wayne_db import ensure_core_schema, touch_tg_user

    path = str(tmp_path / "computed.db")
    ensure_core_schema(path)
    touch_tg_user(path, "9001", "偉權")
    runner = MainRunner.__new__(MainRunner)
    runner.db_path = path
    runner.today_str = "20260909"
    runner.chat_id = "9001"
    runner.bot = type("B", (), {"send_screening_report": staticmethod(lambda *a, **k: True)})()
    runner._run_ai_desk = lambda *a, **k: {}
    runner._format_watch_radar_section = lambda uid="": ""
    runner.send_telegram_message = lambda *a, **k: True
    runner.token = ""
    _stub_morning_deps(monkeypatch, runner)

    assert runner.run_morning_screen(skip_if_done=False, notify=False) is True
    assert runner.already_completed_today("screen-20260908") is False
    import sqlite3

    row = sqlite3.connect(path).execute(
        "SELECT status, notes FROM pipeline_runs WHERE run_date=?",
        ("screen-20260908",),
    ).fetchone()
    assert row[0] == "computed"
    assert "notify-off" in row[1]
    # 常駐 notify=1：computed 不能當已寄過，必須再寄。
    assert runner.run_morning_screen(skip_if_done=True, notify=True) is True


def test_morning_computed_skips_when_gha_still_silent(tmp_path, monkeypatch):
    """GHA notify=0 第二次跑不要重算；computed 仍不是已寄過。"""
    from main_runner import MainRunner
    from wayne_db import ensure_core_schema, touch_tg_user

    path = str(tmp_path / "computed-skip.db")
    ensure_core_schema(path)
    touch_tg_user(path, "9001", "偉權")
    runner = MainRunner.__new__(MainRunner)
    runner.db_path = path
    runner.today_str = "20260909"
    runner.chat_id = "9001"
    runner.bot = type("B", (), {"send_screening_report": staticmethod(lambda *a, **k: True)})()
    runner._run_ai_desk = lambda *a, **k: {}
    runner._format_watch_radar_section = lambda uid="": ""
    runner.send_telegram_message = lambda *a, **k: True
    runner.token = ""
    _stub_morning_deps(monkeypatch, runner)
    screened = []
    monkeypatch.setattr(
        "main_runner.run_full_screening",
        lambda **_k: screened.append(1) or {"status": "success", "payload": [{"html": "海選"}], "results": {}},
    )

    assert runner.run_morning_screen(skip_if_done=False, notify=False) is True
    assert screened == [1]
    assert runner.run_morning_screen(skip_if_done=True, notify=False) is True
    assert screened == [1]
    assert runner.already_completed_today("screen-20260908") is False


def test_gha_demotes_screen_success_not_increment(tmp_path, monkeypatch):
    """401 那天寫進 zip 的 screen success 必須在 GHA 改成 computed。"""
    import sqlite3

    from main_runner import MainRunner
    from wayne_db import ensure_core_schema

    path = str(tmp_path / "poison.db")
    ensure_core_schema(path)
    conn = sqlite3.connect(path)
    conn.execute(
        "INSERT OR REPLACE INTO pipeline_runs VALUES (?,?,?,?)",
        ("screen-20260908", "2026-09-09T00:00:00", "success", "401 poison"),
    )
    conn.execute(
        "INSERT OR REPLACE INTO pipeline_runs VALUES (?,?,?,?)",
        ("20260908", "2026-09-08T16:40:00", "success", "increment"),
    )
    conn.commit()
    conn.close()
    runner = MainRunner.__new__(MainRunner)
    runner.db_path = path
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    assert runner.demote_unsent_screen_success() == 0
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    assert runner.demote_unsent_screen_success() == 1
    conn = sqlite3.connect(path)
    screen = conn.execute(
        "SELECT status, notes FROM pipeline_runs WHERE run_date='screen-20260908'"
    ).fetchone()
    inc = conn.execute(
        "SELECT status FROM pipeline_runs WHERE run_date='20260908'"
    ).fetchone()
    conn.close()
    assert screen[0] == "computed"
    assert "gha-sanitize-no-send" in screen[1]
    assert inc[0] == "success"
    assert runner.already_completed_today("screen-20260908") is False


def test_morning_skip_increment_refreshes_sidecars(tmp_path, monkeypatch):
    from main_runner import MainRunner
    from wayne_db import ensure_core_schema, touch_tg_user

    path = str(tmp_path / "side.db")
    ensure_core_schema(path)
    touch_tg_user(path, "9001", "偉權")
    runner = MainRunner.__new__(MainRunner)
    runner.db_path = path
    runner.today_str = "20260909"
    runner.chat_id = "9001"
    runner.bot = type("B", (), {"send_screening_report": staticmethod(lambda *a, **k: True)})()
    runner._run_ai_desk = lambda *a, **k: {}
    runner._format_watch_radar_section = lambda uid="": ""
    runner.send_telegram_message = lambda *a, **k: True
    runner.token = ""
    called = []
    runner._refresh_official_sidecars = lambda: called.append("sidecars")
    monkeypatch.setattr("tw_holidays.refresh_tw_typhoon_halt", lambda *_a, **_k: {})
    monkeypatch.setattr("tw_holidays.closed_tw_session", lambda **_k: None)
    monkeypatch.setattr("import_health.latest_complete_quote_date", lambda *_a, **_k: "20260908")
    monkeypatch.setattr("config.fuse_end_date", lambda: "20260908")
    monkeypatch.setattr(
        "main_runner.run_full_screening",
        lambda **_k: {"status": "success", "payload": [{"html": "海選"}], "results": {}},
    )
    monkeypatch.setattr("taiwan_market.sync_futures_daily", lambda *_a, **_k: {})
    monkeypatch.setattr("taiwan_market.sync_futures_inst_oi", lambda *_a, **_k: {})
    monkeypatch.setattr("us_overnight.refresh_us_overnight", lambda *_a, **_k: {})
    monkeypatch.setattr("us_overnight.should_alert_us_drop", lambda *_a, **_k: False)
    monkeypatch.setattr("taiwan_market.format_taiwan_market_brief_html", lambda *_a, **_k: "")
    monkeypatch.setattr("taiwan_market.analyze_taiwan_market", lambda *_a, **_k: {"ok": False})

    bumped = []

    def boom(*_a, **_k):
        bumped.append(True)
        raise AssertionError("行情已齊不該再跑全市場增量")

    runner.run_daily_increment = boom
    assert runner.run_morning_screen(skip_if_done=False, notify=True) is True
    assert called == ["sidecars"]
    assert bumped == []


def test_midday_does_not_mark_when_telegram_rejects(tmp_path, monkeypatch):
    from main_runner import MainRunner
    from wayne_db import ensure_core_schema, touch_tg_user

    path = str(tmp_path / "mid.db")
    ensure_core_schema(path)
    touch_tg_user(path, "9001", "偉權")
    runner = MainRunner.__new__(MainRunner)
    runner.db_path = path
    runner.today_str = "20260909"
    runner.chat_id = "9001"
    runner.bot = object()
    runner.token = "x"
    runner._broadcast_family = lambda _t: False
    runner.send_telegram_message = lambda *_a, **_k: False
    monkeypatch.setattr("tw_holidays.closed_tw_session", lambda **_k: None)
    monkeypatch.setattr("import_health.latest_complete_quote_date", lambda *_a, **_k: "20260908")
    monkeypatch.setattr(
        "midday_review.run_midday_review",
        lambda *_a, **_k: {"html": "<b>尾盤</b>", "line_share": ""},
    )
    assert runner.run_midday_review(skip_if_done=False) is False
    assert runner.already_completed_today("midday-20260908") is False
