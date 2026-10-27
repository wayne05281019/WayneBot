import pytest


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


def test_evening_skip_rebuilds_when_sessions_empty(monkeypatch, tmp_path):
    """pipeline 已 success 但 screen_sessions 空 → 必須重掃補快取。"""
    from wayne_db import ensure_core_schema
    from main_runner import MainRunner

    db = str(tmp_path / "eve_empty.db")
    ensure_core_schema(db)
    runner = MainRunner.__new__(MainRunner)
    runner.db_path = db
    runner.today_str = "20260904"
    screened = []

    def fake_screen(*_a, **_k):
        screened.append(True)
        return {
            "status": "success",
            "as_of": "20260904",
            "results": {"leave_zero": [{"stock_id": "2330", "close": 1}]},
        }

    monkeypatch.setattr("import_health.latest_complete_quote_date", lambda _db: "20260904")
    runner.already_completed_today = lambda _key=None: True
    runner._run_ai_desk = lambda *_a, **_k: {}
    runner._maybe_send_evolve_digest = lambda *_a, **_k: None
    runner._mark_pipeline = lambda *_a, **_k: None
    monkeypatch.setattr("main_runner.run_full_screening", fake_screen)

    assert runner.run_evening_screen(skip_if_done=True, notify=False) is True
    assert screened == [True]


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


def test_family_chat_ids_ignore_strangers_in_tg_users(tmp_path, monkeypatch):
    from main_runner import MainRunner
    from wayne_db import ensure_core_schema, touch_tg_user

    monkeypatch.delenv("WAYNE_FAMILY_CHAT_IDS", raising=False)
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "9001")
    monkeypatch.delenv("TG_CHAT_ID", raising=False)
    path = str(tmp_path / "fam.db")
    ensure_core_schema(path)
    touch_tg_user(path, "9001", "偉權")
    touch_tg_user(path, "9002", "路人")
    runner = MainRunner.__new__(MainRunner)
    runner.db_path = path
    runner.chat_id = "9001"
    assert runner._family_chat_ids() == ["9001"]


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

    monkeypatch.setenv("WAYNE_FAMILY_CHAT_IDS", "9002")
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

    monkeypatch.setenv("WAYNE_FAMILY_CHAT_IDS", "9002")
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

    def _fake_full(**_k):
        try:
            from screen_sessions import save_screen_session

            save_screen_session(
                runner.db_path,
                "20260908",
                "morning",
                {
                    "leave_zero": [
                        {"stock_id": "2330", "stock_name": "台積電", "close": 1.0}
                    ]
                },
            )
        except Exception:
            pass
        return {"status": "success", "payload": [{"html": "海選"}], "results": {}}

    monkeypatch.setattr("main_runner.run_full_screening", _fake_full)
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

    def _screen(**_k):
        screened.append(1)
        from screen_sessions import save_screen_session

        save_screen_session(
            path,
            "20260908",
            "morning",
            {"leave_zero": [{"stock_id": "2330", "stock_name": "台積電", "close": 1.0}]},
        )
        return {"status": "success", "payload": [{"html": "海選"}], "results": {}}

    monkeypatch.setattr("main_runner.run_full_screening", _screen)

    assert runner.run_morning_screen(skip_if_done=False, notify=False) is True
    assert screened == [1]
    assert runner.run_morning_screen(skip_if_done=True, notify=False) is True
    assert screened == [1]
    assert runner.already_completed_today("screen-20260908") is False


def test_morning_success_without_sessions_rebuilds_cache(tmp_path, monkeypatch):
    """pipeline success 但 screen_sessions 空：必須重掃補快取，不准 skip 掉。"""
    import sqlite3

    from main_runner import MainRunner
    from wayne_db import ensure_core_schema, touch_tg_user

    path = str(tmp_path / "empty-sessions.db")
    ensure_core_schema(path)
    touch_tg_user(path, "9001", "偉權")
    conn = sqlite3.connect(path)
    conn.execute(
        "INSERT OR REPLACE INTO pipeline_runs VALUES (?,?,?,?)",
        ("screen-20260908", "2026-09-09T06:30:00", "success", "morning"),
    )
    conn.commit()
    conn.close()
    runner = MainRunner.__new__(MainRunner)
    runner.db_path = path
    runner.today_str = "20260909"
    runner.chat_id = "9001"
    pushes = []
    runner.bot = type(
        "B",
        (),
        {"send_screening_report": staticmethod(lambda *a, **k: pushes.append(1) or True)},
    )()
    runner._run_ai_desk = lambda *a, **k: {}
    runner._format_watch_radar_section = lambda uid="": ""
    runner.send_telegram_message = lambda *a, **k: True
    runner.token = ""
    _stub_morning_deps(monkeypatch, runner)
    screened = []

    def _screen(**_k):
        screened.append(1)
        from screen_sessions import save_screen_session

        save_screen_session(
            path,
            "20260908",
            "morning",
            {"leave_zero": [{"stock_id": "2330", "stock_name": "台積電", "close": 1.0}]},
        )
        return {"status": "success", "payload": [{"html": "海選"}], "results": {}}

    monkeypatch.setattr("main_runner.run_full_screening", _screen)
    assert runner.run_morning_screen(skip_if_done=True, notify=True) is True
    assert screened == [1]
    # 已寄過只補快取，不准再推。
    assert pushes == []
    from screen_sessions import screen_session_has_data

    assert screen_session_has_data(path, "20260908")


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


def test_morning_skips_increment_when_as_of_behind_cap(tmp_path, monkeypatch):
    """基準日已齊但 cap 已往後：不准再跑 fuse 擋 §14 寄出。"""
    from main_runner import MainRunner
    from wayne_db import ensure_core_schema, touch_tg_user

    path = str(tmp_path / "behind-cap.db")
    ensure_core_schema(path)
    touch_tg_user(path, "9001", "偉權")
    runner = MainRunner.__new__(MainRunner)
    runner.db_path = path
    runner.today_str = "20261023"
    runner.chat_id = "9001"
    runner.bot = type("B", (), {"send_screening_report": staticmethod(lambda *a, **k: True)})()
    runner._run_ai_desk = lambda *a, **k: {}
    runner._format_watch_radar_section = lambda uid="": ""
    runner.send_telegram_message = lambda *a, **k: True
    runner.token = ""
    runner._refresh_official_sidecars = lambda: (_ for _ in ()).throw(
        AssertionError("behind cap 不准重側車")
    )
    monkeypatch.setattr("tw_holidays.refresh_tw_typhoon_halt", lambda *_a, **_k: {})
    monkeypatch.setattr("tw_holidays.closed_tw_session", lambda **_k: None)
    monkeypatch.setattr("import_health.latest_complete_quote_date", lambda *_a, **_k: "20261022")
    monkeypatch.setattr("config.fuse_end_date", lambda: "20261023")
    monkeypatch.setenv("WAYNE_SCREEN_INLINE", "1")
    monkeypatch.setattr(
        "main_runner.run_full_screening",
        lambda **_k: {"status": "success", "payload": [{"html": "海選"}], "results": {}},
    )
    monkeypatch.setattr("taiwan_market.sync_futures_daily", lambda *_a, **_k: {})
    monkeypatch.setattr("taiwan_market.sync_futures_inst_oi", lambda *_a, **_k: {})
    monkeypatch.setattr("us_overnight.refresh_us_overnight", lambda *_a, **_k: {})
    monkeypatch.setattr("us_overnight.should_alert_us_drop", lambda *_a, **_k: False)

    bumped = []

    def boom(*_a, **_k):
        bumped.append(True)
        raise AssertionError("behind cap 不該再跑全市場增量")

    runner.run_daily_increment = boom
    assert runner.run_morning_screen(skip_if_done=False, notify=True) is True
    assert bumped == []
    assert runner.pipeline_status("screen-20261022") == "success"


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
    assert runner.pipeline_status("midday-20260908") == "computed"


def test_midday_claim_blocks_second_push(tmp_path, monkeypatch):
    """準點＋補跑＋死人開關並行時，第二個路徑不得再寄。"""
    from main_runner import MainRunner
    from wayne_db import ensure_core_schema

    path = str(tmp_path / "claim.db")
    ensure_core_schema(path)
    sent = []

    def _mk():
        r = MainRunner.__new__(MainRunner)
        r.db_path = path
        r.today_str = "20260909"
        r.chat_id = "9001"
        r.bot = object()
        r.token = "x"
        r._broadcast_family = lambda t: sent.append(t) or True
        return r

    monkeypatch.setattr("tw_holidays.closed_tw_session", lambda **_k: None)
    monkeypatch.setattr("import_health.latest_complete_quote_date", lambda *_a, **_k: "20260908")
    monkeypatch.setattr(
        "midday_review.run_midday_review",
        lambda *_a, **_k: {"html": "<b>尾盤一次</b>", "line_share": ""},
    )
    a = _mk()
    b = _mk()
    assert a.run_midday_review(skip_if_done=True) is True
    assert b.run_midday_review(skip_if_done=True) is True
    assert sent == ["<b>尾盤一次</b>"]
    assert a.already_completed_today("midday-20260908") is True


def test_midday_always_claims_even_when_skip_if_done_false(tmp_path, monkeypatch):
    """skip_if_done=False 也必須先 claim；已 success 絕對不可再寄（重開／強跑）。"""
    from main_runner import MainRunner
    from wayne_db import ensure_core_schema

    path = str(tmp_path / "force.db")
    ensure_core_schema(path)
    sent = []

    def _mk():
        r = MainRunner.__new__(MainRunner)
        r.db_path = path
        r.today_str = "20260909"
        r.chat_id = "9001"
        r.bot = object()
        r.token = "x"
        r._broadcast_family = lambda t: sent.append(t) or True
        return r

    monkeypatch.setattr("tw_holidays.closed_tw_session", lambda **_k: None)
    monkeypatch.setattr("import_health.latest_complete_quote_date", lambda *_a, **_k: "20260908")
    monkeypatch.setattr(
        "midday_review.run_midday_review",
        lambda *_a, **_k: {"html": "<b>尾盤一次</b>", "line_share": ""},
    )
    assert _mk().run_midday_review(skip_if_done=False) is True
    assert sent == ["<b>尾盤一次</b>"]
    # 模擬 Render 重開後 catch-up／watchdog／CLI 再進來
    assert _mk().run_midday_review(skip_if_done=False) is True
    assert _mk().run_midday_review(skip_if_done=True) is True
    assert sent == ["<b>尾盤一次</b>"]


def test_midday_stale_running_does_not_resend(tmp_path, monkeypatch):
    """deploy 殺行程後卡住的 running（逾時）不准被補跑重搶再寄。"""
    from datetime import datetime, timedelta
    from main_runner import MainRunner
    from wayne_db import ensure_core_schema
    import sqlite3

    path = str(tmp_path / "stale.db")
    ensure_core_schema(path)
    sent = []
    runner = MainRunner.__new__(MainRunner)
    runner.db_path = path
    runner.today_str = "20260909"
    runner.chat_id = "9001"
    runner.bot = object()
    runner.token = "x"
    runner._broadcast_family = lambda t: sent.append(t) or True

    monkeypatch.setattr("tw_holidays.closed_tw_session", lambda **_k: None)
    monkeypatch.setattr("import_health.latest_complete_quote_date", lambda *_a, **_k: "20260908")
    monkeypatch.setattr(
        "midday_review.run_midday_review",
        lambda *_a, **_k: {"html": "<b>不該再寄</b>", "line_share": ""},
    )
    # 模擬 12:45 已 claim＋可能已寄，殺行程來不及標 success
    old = (datetime.now() - timedelta(seconds=3600)).isoformat(timespec="seconds")
    conn = sqlite3.connect(path)
    conn.execute(
        "INSERT OR REPLACE INTO pipeline_runs VALUES (?,?,?,?)",
        ("midday-20260908", old, "running", "midday-claim"),
    )
    conn.commit()
    conn.close()
    assert runner.run_midday_review(skip_if_done=True) is True
    assert sent == []
    assert runner.pipeline_status("midday-20260908") == "running"


def test_midday_computed_allows_one_retry(tmp_path, monkeypatch):
    """明確寄失敗（computed）才准補跑再搶一次；成功後仍只一封。"""
    from main_runner import MainRunner
    from wayne_db import ensure_core_schema
    import sqlite3

    path = str(tmp_path / "retry.db")
    ensure_core_schema(path)
    sent = []
    runner = MainRunner.__new__(MainRunner)
    runner.db_path = path
    runner.today_str = "20260909"
    runner.chat_id = "9001"
    runner.bot = object()
    runner.token = "x"
    runner._broadcast_family = lambda t: sent.append(t) or True

    monkeypatch.setattr("tw_holidays.closed_tw_session", lambda **_k: None)
    monkeypatch.setattr("import_health.latest_complete_quote_date", lambda *_a, **_k: "20260908")
    monkeypatch.setattr(
        "midday_review.run_midday_review",
        lambda *_a, **_k: {"html": "<b>補寄一封</b>", "line_share": ""},
    )
    conn = sqlite3.connect(path)
    conn.execute(
        "INSERT OR REPLACE INTO pipeline_runs VALUES (?,?,?,?)",
        ("midday-20260908", "2026-09-09T12:46:00", "computed", "midday send-failed"),
    )
    conn.commit()
    conn.close()
    assert runner.run_midday_review(skip_if_done=True) is True
    assert sent == ["<b>補寄一封</b>"]
    assert runner.already_completed_today("midday-20260908") is True
    assert runner.run_midday_review(skip_if_done=True) is True
    assert sent == ["<b>補寄一封</b>"]


def test_midday_claim_running_blocks_even_when_stale(tmp_path):
    """尾盤 allow_stale_running=False：逾時 running 仍不可重搶。"""
    from datetime import datetime, timedelta
    from main_runner import MainRunner
    from wayne_db import ensure_core_schema
    import sqlite3

    path = str(tmp_path / "run.db")
    ensure_core_schema(path)
    runner = MainRunner.__new__(MainRunner)
    runner.db_path = path
    assert runner.try_claim_pipeline("midday-20260908", notes="a", allow_stale_running=False) is True
    assert (
        runner.try_claim_pipeline("midday-20260908", notes="b", allow_stale_running=False) is False
    )
    conn = sqlite3.connect(path)
    old = (datetime.now() - timedelta(seconds=700)).isoformat(timespec="seconds")
    conn.execute(
        "UPDATE pipeline_runs SET finished_at=? WHERE run_date=?",
        (old, "midday-20260908"),
    )
    conn.commit()
    conn.close()
    assert (
        runner.try_claim_pipeline("midday-20260908", notes="c", allow_stale_running=False) is False
    )
    # 舊行為：允許 stale 時仍可重搶（非尾盤路徑）
    assert runner.try_claim_pipeline("midday-20260908", notes="d", allow_stale_running=True) is True


def test_midday_claim_blocks_until_stale_when_allowed(tmp_path):
    """allow_stale_running=True 時：未逾時擋、逾時可重搶（相容舊測）。"""
    from datetime import datetime, timedelta
    from main_runner import MainRunner
    from wayne_db import ensure_core_schema
    import sqlite3

    path = str(tmp_path / "run-compat.db")
    ensure_core_schema(path)
    runner = MainRunner.__new__(MainRunner)
    runner.db_path = path
    assert runner.try_claim_pipeline("midday-20260908", notes="a") is True
    assert runner.try_claim_pipeline("midday-20260908", notes="b") is False
    conn = sqlite3.connect(path)
    old = (datetime.now() - timedelta(seconds=700)).isoformat(timespec="seconds")
    conn.execute(
        "UPDATE pipeline_runs SET finished_at=? WHERE run_date=?",
        (old, "midday-20260908"),
    )
    conn.commit()
    conn.close()
    assert runner.try_claim_pipeline("midday-20260908", notes="c") is True



def test_demote_premature_morning_screens_same_day(tmp_path):
    """盤後當日標的 screen-{as_of} success 要降級，隔日早報才寄得出。"""
    from main_runner import MainRunner
    from wayne_db import ensure_core_schema
    import sqlite3

    path = str(tmp_path / "premature.db")
    ensure_core_schema(path)
    conn = sqlite3.connect(path)
    conn.execute(
        "INSERT OR REPLACE INTO pipeline_runs VALUES (?,?,?,?)",
        ("screen-20260909", "2026-09-09T08:56:51", "success", "morning"),
    )
    # 隔日 06:30 真寄過的應保留
    conn.execute(
        "INSERT OR REPLACE INTO pipeline_runs VALUES (?,?,?,?)",
        ("screen-20260908", "2026-09-09T22:35:00", "success", "morning"),
    )
    conn.commit()
    conn.close()

    runner = MainRunner.__new__(MainRunner)
    runner.db_path = path
    assert runner.demote_premature_morning_screens() == 1
    rows = {
        r[0]: r[1:]
        for r in sqlite3.connect(path).execute(
            "SELECT run_date, status, notes FROM pipeline_runs"
        )
    }
    assert rows["screen-20260909"][0] == "computed"
    assert "premature-morning" in rows["screen-20260909"][1]
    assert rows["screen-20260908"][0] == "success"


def test_demote_orphaned_morning_claims_boot(tmp_path):
    """開機必須把 orphan morning-claim running→computed，不准空等 30 分租約（§14）。"""
    import sqlite3
    import time
    from datetime import datetime
    from zoneinfo import ZoneInfo

    import main_runner as mr
    from main_runner import MainRunner
    from wayne_db import ensure_core_schema

    path = str(tmp_path / "orphan-claim.db")
    ensure_core_schema(path)
    tw = ZoneInfo("Asia/Taipei")
    # 明確早於本行程 boot epoch＝orphan
    old = datetime.fromtimestamp(mr._PROCESS_BOOT_EPOCH - 120, tz=tw).isoformat(
        timespec="seconds"
    )
    # 持鎖中：必須同時 (1) ≥ boot_cut (2) 年齡 < age demote。
    # 短跑用 boot+N；長跑 CI 用 now-30——取較晚者兩邊都過。
    fresh_epoch = max(float(mr._PROCESS_BOOT_EPOCH) + 30.0, time.time() - 30.0)
    fresh = datetime.fromtimestamp(fresh_epoch, tz=tw).isoformat(timespec="seconds")
    conn = sqlite3.connect(path)
    conn.execute(
        "INSERT OR REPLACE INTO pipeline_runs VALUES (?,?,?,?)",
        ("screen-20261022", old, "running", "morning-claim"),
    )
    conn.execute(
        "INSERT OR REPLACE INTO pipeline_runs VALUES (?,?,?,?)",
        ("screen-20261020", fresh, "running", "morning-claim"),
    )
    # 休市鍵／已寄 success 不准動
    conn.execute(
        "INSERT OR REPLACE INTO pipeline_runs VALUES (?,?,?,?)",
        (
            "screen-closed-20261010",
            "2026-10-10T06:30:00+08:00",
            "success",
            "tw closed skip morning",
        ),
    )
    conn.execute(
        "INSERT OR REPLACE INTO pipeline_runs VALUES (?,?,?,?)",
        (
            "screen-20261021",
            "2026-10-22T07:23:14+08:00",
            "success",
            "morning",
        ),
    )
    conn.commit()
    conn.close()

    runner = MainRunner.__new__(MainRunner)
    runner.db_path = path
    assert runner.demote_orphaned_morning_claims() == 1
    assert runner.demote_orphaned_morning_claims() == 0
    rows = {
        r[0]: r[1:]
        for r in sqlite3.connect(path).execute(
            "SELECT run_date, status, notes FROM pipeline_runs"
        )
    }
    assert rows["screen-20261022"][0] == "computed"
    assert "orphan-boot" in rows["screen-20261022"][1]
    assert rows["screen-20261020"][0] == "running"
    assert rows["screen-closed-20261010"][0] == "success"
    assert rows["screen-20261021"][0] == "success"
    # 降級後可立刻重搶補寄（不必等 stale）
    assert (
        runner.try_claim_pipeline(
            "screen-20261022",
            notes="morning-claim",
            allow_stale_running=False,
        )
        is True
    )


def test_demote_morning_claims_by_age_regardless_of_boot(tmp_path, monkeypatch):
    """逾齡 morning-claim 即使 finished_at 在本行程 boot 之後也要降（§14）。"""
    import sqlite3
    import time
    from datetime import datetime, timedelta
    from zoneinfo import ZoneInfo

    import main_runner as mr
    from main_runner import MainRunner
    from wayne_db import ensure_core_schema

    path = str(tmp_path / "age-demote.db")
    ensure_core_schema(path)
    tw = ZoneInfo("Asia/Taipei")
    now = time.time()
    # boot 拉很早：兩筆 finished_at 都「晚於 boot」，只測年齡路徑
    monkeypatch.setattr(mr, "_PROCESS_BOOT_EPOCH", now - 10_000)
    aged = datetime.now(tz=tw) - timedelta(seconds=900)
    fresh = datetime.now(tz=tw) - timedelta(seconds=30)
    conn = sqlite3.connect(path)
    conn.execute(
        "INSERT OR REPLACE INTO pipeline_runs VALUES (?,?,?,?)",
        ("screen-20261022", aged.isoformat(timespec="seconds"), "running", "morning-claim"),
    )
    conn.execute(
        "INSERT OR REPLACE INTO pipeline_runs VALUES (?,?,?,?)",
        ("screen-20261021", fresh.isoformat(timespec="seconds"), "running", "morning-claim"),
    )
    conn.commit()
    conn.close()

    runner = MainRunner.__new__(MainRunner)
    runner.db_path = path
    assert runner.demote_orphaned_morning_claims(max_age_sec=600) == 1
    rows = {
        r[0]: r[1:]
        for r in sqlite3.connect(path).execute(
            "SELECT run_date, status, notes FROM pipeline_runs"
        )
    }
    assert rows["screen-20261022"][0] == "computed"
    assert "age demote" in rows["screen-20261022"][1]
    assert rows["screen-20261021"][0] == "running"


def test_force_demote_morning_claims(tmp_path):
    """force=True 不論年齡一律降，供 /ops/force-morning 救援。"""
    import sqlite3
    import time
    from datetime import datetime
    from zoneinfo import ZoneInfo

    import main_runner as mr
    from main_runner import MainRunner
    from wayne_db import ensure_core_schema

    path = str(tmp_path / "force-demote.db")
    ensure_core_schema(path)
    tw = ZoneInfo("Asia/Taipei")
    # 非 force 必須保留：晚於 boot_cut 且未逾齡（短跑／長跑 CI 都要過）
    fresh_epoch = max(float(mr._PROCESS_BOOT_EPOCH) + 30.0, time.time() - 30.0)
    fresh = datetime.fromtimestamp(fresh_epoch, tz=tw).isoformat(timespec="seconds")
    conn = sqlite3.connect(path)
    conn.execute(
        "INSERT OR REPLACE INTO pipeline_runs VALUES (?,?,?,?)",
        ("screen-20261022", fresh, "running", "morning-claim"),
    )
    conn.commit()
    conn.close()
    runner = MainRunner.__new__(MainRunner)
    runner.db_path = path
    assert runner.demote_orphaned_morning_claims() == 0
    assert runner.demote_orphaned_morning_claims(force=True) == 1
    st, notes = sqlite3.connect(path).execute(
        "SELECT status, notes FROM pipeline_runs WHERE run_date=?",
        ("screen-20261022",),
    ).fetchone()
    assert st == "computed"
    assert "force demote" in notes


def test_demote_orphaned_morning_claims_retries_db_lock(tmp_path, monkeypatch):
    """DB lock 必須重試，不准一次失敗就讓 §14 永遠略過。"""
    import sqlite3

    import main_runner as mr
    from main_runner import MainRunner
    from wayne_db import ensure_core_schema

    path = str(tmp_path / "orphan-retry.db")
    ensure_core_schema(path)
    from datetime import datetime
    from zoneinfo import ZoneInfo

    tw = ZoneInfo("Asia/Taipei")
    old = datetime.fromtimestamp(mr._PROCESS_BOOT_EPOCH - 60, tz=tw).isoformat(
        timespec="seconds"
    )
    sqlite3.connect(path).execute(
        "INSERT OR REPLACE INTO pipeline_runs VALUES (?,?,?,?)",
        ("screen-20261022", old, "running", "morning-claim"),
    ).connection.commit()

    runner = MainRunner.__new__(MainRunner)
    runner.db_path = path
    calls = {"n": 0}
    real_connect = sqlite3.connect

    def _flaky(*a, **k):
        calls["n"] += 1
        if calls["n"] <= 2:
            raise sqlite3.OperationalError("database is locked")
        return real_connect(*a, **k)

    monkeypatch.setattr(mr.sqlite3, "connect", _flaky)
    monkeypatch.setattr(mr.time, "sleep", lambda *_a, **_k: None)
    assert runner.demote_orphaned_morning_claims(retries=5) == 1
    assert calls["n"] >= 3
    row = real_connect(path).execute(
        "SELECT status, notes FROM pipeline_runs WHERE run_date=?",
        ("screen-20261022",),
    ).fetchone()
    assert row[0] == "computed"
    assert "orphan-boot" in row[1]


def test_morning_claim_is_fresh_running(tmp_path):
    import sqlite3
    from datetime import datetime
    from zoneinfo import ZoneInfo

    from main_runner import MainRunner
    from wayne_db import ensure_core_schema

    path = str(tmp_path / "fresh-claim.db")
    ensure_core_schema(path)
    tw = ZoneInfo("Asia/Taipei")
    now = datetime.now(tw).isoformat(timespec="seconds")
    sqlite3.connect(path).execute(
        "INSERT OR REPLACE INTO pipeline_runs VALUES (?,?,?,?)",
        ("screen-20261022", now, "running", "morning-claim"),
    ).connection.commit()
    runner = MainRunner.__new__(MainRunner)
    runner.db_path = path
    assert runner.morning_claim_is_fresh_running() is True
    sqlite3.connect(path).execute(
        "UPDATE pipeline_runs SET status='computed' WHERE run_date=?",
        ("screen-20261022",),
    ).connection.commit()
    assert runner.morning_claim_is_fresh_running() is False


def test_demote_holiday_skip_morning_screens(tmp_path):
    """連假休市誤標 screen-{as_of} success 必須降級，開市日才能補寄。"""
    from main_runner import MainRunner
    from wayne_db import ensure_core_schema
    import sqlite3

    path = str(tmp_path / "holiday_skip.db")
    ensure_core_schema(path)
    conn = sqlite3.connect(path)
    conn.execute(
        "INSERT OR REPLACE INTO pipeline_runs VALUES (?,?,?,?)",
        (
            "screen-20260924",
            "2026-09-28T01:03:00",
            "success",
            "tw closed 20260928 教師節 skip morning",
        ),
    )
    conn.execute(
        "INSERT OR REPLACE INTO pipeline_runs VALUES (?,?,?,?)",
        (
            "screen-closed-20260928",
            "2026-09-28T01:03:00",
            "success",
            "tw closed 20260928 教師節 skip morning",
        ),
    )
    conn.execute(
        "INSERT OR REPLACE INTO pipeline_runs VALUES (?,?,?,?)",
        ("screen-20260923", "2026-09-24T22:35:00", "success", "morning"),
    )
    conn.commit()
    conn.close()

    runner = MainRunner.__new__(MainRunner)
    runner.db_path = path
    assert runner.demote_holiday_skip_morning_screens() == 1
    rows = {
        r[0]: r[1:]
        for r in sqlite3.connect(path).execute(
            "SELECT run_date, status, notes FROM pipeline_runs"
        )
    }
    assert rows["screen-20260924"][0] == "computed"
    assert "holiday-skip-demote" in rows["screen-20260924"][1]
    assert rows["screen-closed-20260928"][0] == "success"
    assert rows["screen-20260923"][0] == "success"


def test_morning_closed_uses_screen_closed_key(tmp_path, monkeypatch):
    """休市不寫 screen-{as_of}；記 screen-closed-*＋us-digest-*；不跑海選。"""
    from main_runner import MainRunner
    from wayne_db import ensure_core_schema

    path = str(tmp_path / "closed_key.db")
    ensure_core_schema(path)
    runner = MainRunner.__new__(MainRunner)
    runner.db_path = path
    runner.chat_id = "9001"
    runner.bot = None
    marks = []
    pushed = []
    cards = []

    monkeypatch.setattr(
        "tw_holidays.refresh_tw_typhoon_halt", lambda *_a, **_k: {"ok": True}
    )
    monkeypatch.setattr(
        "tw_holidays.closed_tw_session",
        lambda **_k: {
            "ymd": "20260928",
            "zh": "教師節",
            "kind": "full_close",
            "prev_ymd": "20260926",
        },
    )
    monkeypatch.setattr(
        "import_health.latest_complete_quote_date",
        lambda *_a, **_k: "20260926",
    )
    monkeypatch.setattr("us_overnight.refresh_us_overnight", lambda *_a, **_k: {})
    monkeypatch.setattr("us_overnight.should_alert_us_drop", lambda *_a, **_k: False)
    monkeypatch.setattr("taiwan_market.sync_futures_daily", lambda *_a, **_k: {})
    monkeypatch.setattr(
        "morning_digest.build_closed_day_digest_html",
        lambda *_a, **_k: "<b>WayneBot 早報</b>\n今日無開盤，因為教師節",
    )

    def _mark(status, notes="", run_date=None):
        marks.append((status, notes, run_date))

    runner._mark_pipeline = _mark  # type: ignore
    runner._refresh_official_sidecars = lambda: None  # type: ignore
    runner.try_claim_pipeline = lambda *a, **k: True  # type: ignore
    runner.pipeline_status = lambda *_a, **_k: ""  # type: ignore
    runner._family_chat_ids = lambda: ["9001", "9002"]  # type: ignore
    runner._push_morning_session_cards = (  # type: ignore
        lambda cid, us_snap=None: cards.append(cid)
    )
    runner.send_telegram_message = (  # type: ignore
        lambda text, chat_id=None: pushed.append((chat_id, text)) or True
    )
    # 不准走全市場海選
    runner._morning_screening_surviving_oom = lambda *_a, **_k: (_ for _ in ()).throw(  # type: ignore
        AssertionError("closed day must not run screening")
    )

    assert runner.run_morning_screen(skip_if_done=True, notify=True) is True
    keys = [m[2] for m in marks]
    assert "screen-closed-20260928" in keys
    assert "us-digest-20260928" in keys
    assert not any(
        (m[2] or "").startswith("screen-2026") and "closed" not in (m[2] or "")
        for m in marks
    )
    assert any("skip screen" in str(m[1]) for m in marks)
    assert any("us-digest" in str(m[1]) and m[0] == "success" for m in marks)
    assert cards == ["9001", "9002"]
    assert len(pushed) == 2
    assert all("今日無開盤，因為教師節" in (t or "") for _, t in pushed)


def test_midday_closed_uses_midday_closed_key_and_sends_nothing(tmp_path, monkeypatch):
    """休市 12:45：midday-closed-*；不准寄任何對話框、不准寫 midday-{as_of}。"""
    from main_runner import MainRunner
    from wayne_db import ensure_core_schema

    path = str(tmp_path / "midday_closed.db")
    ensure_core_schema(path)
    runner = MainRunner.__new__(MainRunner)
    runner.db_path = path
    marks = []
    sent = []

    monkeypatch.setattr(
        "tw_holidays.closed_tw_session",
        lambda **_k: {"ymd": "20261026", "zh": "光復節補假", "kind": "full_close"},
    )
    monkeypatch.setattr(
        "import_health.latest_complete_quote_date",
        lambda *_a, **_k: "20261024",
    )

    def _mark(status, notes="", run_date=None):
        marks.append((status, notes, run_date))

    runner._mark_pipeline = _mark  # type: ignore
    runner._broadcast_family = lambda t: sent.append(t) or True  # type: ignore
    runner.send_telegram_message = lambda *a, **k: sent.append(a) or True  # type: ignore

    assert runner.run_midday_review(skip_if_done=True) is True
    assert marks == [
        (
            "success",
            "tw closed 20261026 光復節補假 skip midday",
            "midday-closed-20261026",
        )
    ]
    assert sent == []
    assert not any((m[2] or "").startswith("midday-2026") for m in marks)


def test_catch_up_skips_morning_on_as_of_day(monkeypatch):
    """基準日當日補跑不可提早寄早上海選。"""
    import main as main_mod
    import main_runner
    import config
    from datetime import datetime
    from zoneinfo import ZoneInfo

    calls = []

    class FakeRunner:
        db_path = "/tmp/x.db"

        def run_increment_job(self, **kw):
            calls.append(("fuse", kw))

        def run_morning_screen(self, **kw):
            calls.append(("morning", kw))

        def run_midday_review(self, **kw):
            calls.append(("midday", kw))

        def run_evening_screen(self, **kw):
            calls.append(("evening", kw))

        def run_winrate_buypoint(self, **kw):
            calls.append(("winrate", kw))
            return True

        def run_nightly_open_check(self, **kw):
            calls.append(("open_check", kw))
            return True

    monkeypatch.setattr(main_runner, "MainRunner", FakeRunner)
    monkeypatch.setattr(config, "scheduler_owns", lambda job: True)
    monkeypatch.setattr(config, "scheduler_may_push", lambda job: True)
    monkeypatch.setattr(
        "import_health.latest_complete_quote_date", lambda *_a, **_k: "20260909"
    )
    # 本測只驗基準日當日不提早寄早報；名單現行 → 17:00 不觸發勝率補掃。
    monkeypatch.setattr(
        "winrate_buypoint.roster_is_current", lambda *_a, **_k: True
    )
    now = datetime(2026, 9, 9, 17, 0, tzinfo=ZoneInfo("Asia/Taipei"))
    main_mod.catch_up_missed_jobs(now)
    kinds = [c[0] for c in calls]
    assert "morning" not in kinds
    assert "fuse" in kinds
    assert "midday" not in kinds
    assert "winrate" not in kinds


def test_morning_claim_blocks_parallel_second_send(tmp_path, monkeypatch):
    """準點＋catch-up／watchdog 並行：第二槍搶不到鎖，海選／加權不連寄。"""
    import sqlite3

    from main_runner import MainRunner
    from wayne_db import ensure_core_schema, touch_tg_user

    path = str(tmp_path / "morning-claim.db")
    ensure_core_schema(path)
    touch_tg_user(path, "9001", "偉權")
    touch_tg_user(path, "8772209416", "哥哥")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "9001")
    monkeypatch.setenv("WAYNE_FAMILY_CHAT_IDS", "8772209416")

    pushes = []
    extras = []

    def _make_runner():
        runner = MainRunner.__new__(MainRunner)
        runner.db_path = path
        runner.today_str = "20260909"
        runner.chat_id = "9001"
        runner.bot = type(
            "B",
            (),
            {
                "send_screening_report": staticmethod(
                    lambda *a, **k: pushes.append(("screen", k.get("chat_id"))) or True
                )
            },
        )()
        runner._run_ai_desk = lambda *a, **k: {}
        runner._format_watch_radar_section = lambda uid="": ""
        runner.send_telegram_message = lambda text, chat_id=None: extras.append(
            (chat_id, text)
        ) or True
        runner.token = ""
        return runner

    runner_a = _make_runner()
    _stub_morning_deps(monkeypatch, runner_a)
    monkeypatch.setattr(
        "taiwan_market.format_taiwan_market_brief_html",
        lambda *_a, **_k: "＝＝台灣加權指數研究＝＝\n測試",
    )
    monkeypatch.setattr(
        "taiwan_market.analyze_taiwan_market", lambda *_a, **_k: {"ok": False}
    )
    monkeypatch.setattr("money_flow.format_sector_rotation_html", lambda *_a, **_k: "")
    monkeypatch.setattr("fundamentals.format_hot_revenue_html", lambda *_a, **_k: "")

    # 模擬準點已搶鎖、尚未標 success（長掃／加權附帶還在寄）
    assert (
        runner_a.try_claim_pipeline(
            "screen-20260908", notes="morning-claim", allow_stale_running=False
        )
        is True
    )
    row = sqlite3.connect(path).execute(
        "SELECT status, notes FROM pipeline_runs WHERE run_date=?",
        ("screen-20260908",),
    ).fetchone()
    assert row[0] == "running"
    assert "morning-claim" in row[1]

    # watchdog／catch-up 第二槍：搶不到 → 零推播
    # _stub_morning_deps 只 stub 了 runner_a；runner_b 必須自己略過側車，
    # 否則 as_of==cap 會真打 MOPS／TLS，本機／CI 卡住就不測到搶鎖。
    runner_b = _make_runner()
    sidecar_hits = []
    runner_b._refresh_official_sidecars = lambda: sidecar_hits.append(1)
    assert runner_b.run_morning_screen(skip_if_done=True, notify=True) is True
    assert pushes == []
    assert extras == []
    # running 中第二槍不准跑預搶鎖側車（§14 不擋 catch-up）
    assert sidecar_hits == []
    assert (
        sqlite3.connect(path)
        .execute(
            "SELECT status FROM pipeline_runs WHERE run_date=?",
            ("screen-20260908",),
        )
        .fetchone()[0]
        == "running"
    )


def test_refresh_official_sidecars_hard_timeout(monkeypatch):
    """MOPS／TLS 卡住時側車必須逾時返回，不准拖死早報執行緒。"""
    import time

    import company_events
    import ex_rights
    import fundamentals
    import official_snapshots
    from main_runner import MainRunner

    runner = MainRunner.__new__(MainRunner)
    runner.db_path = ":memory:"
    monkeypatch.setenv("WAYNE_MORNING_SIDECAR_TIMEOUT_SEC", "1")

    def _hang(*_a, **_k):
        time.sleep(30)
        return {}

    # body 內 from X import sync_*：patch 模組屬性即可
    monkeypatch.setattr(fundamentals, "sync_fundamentals", _hang)
    monkeypatch.setattr(company_events, "sync_company_events", _hang)
    monkeypatch.setattr(ex_rights, "sync_ex_preview", _hang)
    monkeypatch.setattr(official_snapshots, "sync_official_snapshots", _hang)
    t0 = time.perf_counter()
    runner._refresh_official_sidecars()
    elapsed = time.perf_counter() - t0
    assert elapsed < 3.0, elapsed


def test_morning_double_call_sends_once(tmp_path, monkeypatch):
    """連續兩次 run_morning_screen：白名單各只收到一輪海選（加權併入彙整，不另寄）。"""
    import sqlite3

    from main_runner import MainRunner
    from wayne_db import ensure_core_schema, touch_tg_user

    path = str(tmp_path / "morning-once.db")
    ensure_core_schema(path)
    touch_tg_user(path, "9001", "偉權")
    touch_tg_user(path, "8772209416", "哥哥")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "9001")
    monkeypatch.setenv("WAYNE_FAMILY_CHAT_IDS", "8772209416")

    pushes = []
    extras = []
    screenings = []

    runner = MainRunner.__new__(MainRunner)
    runner.db_path = path
    runner.today_str = "20260909"
    runner.chat_id = "9001"

    def _send_screen(screening, chat_id=None):
        pushes.append(chat_id)
        screenings.append((chat_id, screening))
        return True

    runner.bot = type(
        "B",
        (),
        {"send_screening_report": staticmethod(_send_screen)},
    )()
    runner._run_ai_desk = lambda *a, **k: {}
    runner._format_watch_radar_section = lambda uid="": ""
    runner.send_telegram_message = lambda text, chat_id=None: extras.append(
        (chat_id, text)
    ) or True
    runner.token = ""
    _stub_morning_deps(monkeypatch, runner)

    def _screen_with_message(**_k):
        from screen_sessions import save_screen_session

        save_screen_session(
            path,
            "20260908",
            "morning",
            {"leave_zero": [{"stock_id": "2330", "stock_name": "台積電", "close": 1.0}]},
        )
        # format_taiwan_market_brief_html 只在 screening 有 message 時才當附帶寄出
        return {
            "status": "success",
            "payload": [
                {"mark_key": "market", "html": "＝＝大盤狀況＝＝", "picks": []},
                {"mark_key": "leave_zero", "html": "海選", "picks": []},
            ],
            "message": "海選本文",
            "results": {},
        }

    monkeypatch.setattr("main_runner.run_full_screening", _screen_with_message)
    monkeypatch.setattr(
        "taiwan_market.format_taiwan_market_brief_html",
        lambda *_a, **_k: "＝＝台灣加權指數研究＝＝\n測試",
    )
    monkeypatch.setattr(
        "taiwan_market.analyze_taiwan_market", lambda *_a, **_k: {"ok": False}
    )
    monkeypatch.setattr("money_flow.format_sector_rotation_html", lambda *_a, **_k: "")
    monkeypatch.setattr("fundamentals.format_hot_revenue_html", lambda *_a, **_k: "")

    assert runner.run_morning_screen(skip_if_done=True, notify=True) is True
    assert runner.run_morning_screen(skip_if_done=True, notify=True) is True

    assert sorted(pushes) == ["8772209416", "9001"]
    assert not any("加權指數研究" in (e[1] or "") for e in extras)
    for uid in ("9001", "8772209416"):
        blob = " ".join(
            p.get("html") or ""
            for _, scr in screenings
            if _ == uid
            for p in (scr.get("payload") or [])
        )
        assert "加權指數研究" in blob
    assert (
        sqlite3.connect(path)
        .execute(
            "SELECT status, notes FROM pipeline_runs WHERE run_date=?",
            ("screen-20260908",),
        )
        .fetchone()
        == ("success", "morning")
    )


def test_morning_send_failed_marks_computed_for_retry(tmp_path, monkeypatch):
    """寄失敗必須放 computed，不可卡在 running 讓 §14 補寄永遠搶不到。"""
    import sqlite3

    from main_runner import MainRunner
    from wayne_db import ensure_core_schema, touch_tg_user

    path = str(tmp_path / "morning-fail.db")
    ensure_core_schema(path)
    touch_tg_user(path, "9001", "偉權")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "9001")
    monkeypatch.delenv("WAYNE_FAMILY_CHAT_IDS", raising=False)
    runner = MainRunner.__new__(MainRunner)
    runner.db_path = path
    runner.today_str = "20260909"
    runner.chat_id = "9001"
    runner.bot = type("B", (), {"send_screening_report": staticmethod(lambda *a, **k: False)})()
    _stub_morning_deps(monkeypatch, runner)

    assert runner.run_morning_screen(skip_if_done=True, notify=True) is False
    row = sqlite3.connect(path).execute(
        "SELECT status, notes FROM pipeline_runs WHERE run_date=?",
        ("screen-20260908",),
    ).fetchone()
    assert row[0] == "computed"
    assert "send-failed" in row[1]
    # 明確失敗後可再搶補寄
    assert (
        runner.try_claim_pipeline(
            "screen-20260908", notes="morning-claim", allow_stale_running=False
        )
        is True
    )


def test_morning_stale_running_reclaims_and_sends_both(tmp_path, monkeypatch):
    """死鎖 morning-claim（租約過期）必須能重搶並寄兩支話筒（§14）。"""
    import sqlite3
    from datetime import datetime, timedelta
    from zoneinfo import ZoneInfo

    from main_runner import MainRunner
    from ops_watchdog import MORNING_RUNNING_STALE_SEC
    from wayne_db import ensure_core_schema, touch_tg_user

    path = str(tmp_path / "morning-stale.db")
    ensure_core_schema(path)
    touch_tg_user(path, "9001", "偉權")
    touch_tg_user(path, "8772209416", "哥哥")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "9001")
    monkeypatch.setenv("WAYNE_FAMILY_CHAT_IDS", "8772209416")

    pushes = []
    runner = MainRunner.__new__(MainRunner)
    runner.db_path = path
    runner.today_str = "20261020"
    runner.chat_id = "9001"
    runner.bot = type(
        "B",
        (),
        {
            "send_screening_report": staticmethod(
                lambda *a, **k: pushes.append(k.get("chat_id")) or True
            )
        },
    )()
    runner._run_ai_desk = lambda *a, **k: {}
    runner._format_watch_radar_section = lambda uid="": ""
    runner.send_telegram_message = lambda *a, **k: True
    runner.token = ""
    _stub_morning_deps(monkeypatch, runner)
    monkeypatch.setattr(
        "import_health.latest_complete_quote_date", lambda *_a, **_k: "20261019"
    )
    monkeypatch.setattr("config.fuse_end_date", lambda: "20261019")
    monkeypatch.setattr(
        "main_runner.run_full_screening",
        lambda **_k: {
            "status": "success",
            "payload": [{"html": "海選"}],
            "message": "海選",
            "results": {},
        },
    )
    from screen_sessions import save_screen_session

    save_screen_session(
        path,
        "20261019",
        "morning",
        {"leave_zero": [{"stock_id": "2330", "stock_name": "台積電", "close": 1.0}]},
    )

    tw = ZoneInfo("Asia/Taipei")
    old = (
        datetime(2026, 10, 20, 6, 30, 41, tzinfo=tw)
        - timedelta(seconds=MORNING_RUNNING_STALE_SEC + 60)
    ).isoformat()
    sqlite3.connect(path).execute(
        "INSERT OR REPLACE INTO pipeline_runs VALUES (?,?,?,?)",
        ("screen-20261019", old, "running", "morning-claim"),
    ).connection.commit()

    assert runner.run_morning_screen(skip_if_done=True, notify=True) is True
    assert sorted(pushes) == ["8772209416", "9001"]
    row = sqlite3.connect(path).execute(
        "SELECT status, notes FROM pipeline_runs WHERE run_date=?",
        ("screen-20261019",),
    ).fetchone()
    assert row[0] == "success"
    assert "morning" in row[1]


def test_morning_crash_marks_computed_for_retry(tmp_path, monkeypatch):
    """claim 後未標終態就例外 → computed，不准卡 running。"""
    import sqlite3

    from main_runner import MainRunner
    from wayne_db import ensure_core_schema, touch_tg_user

    path = str(tmp_path / "morning-crash.db")
    ensure_core_schema(path)
    touch_tg_user(path, "9001", "偉權")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "9001")
    monkeypatch.delenv("WAYNE_FAMILY_CHAT_IDS", raising=False)
    runner = MainRunner.__new__(MainRunner)
    runner.db_path = path
    runner.today_str = "20260909"
    runner.chat_id = "9001"
    runner.bot = type("B", (), {"send_screening_report": staticmethod(lambda *a, **k: True)})()
    _stub_morning_deps(monkeypatch, runner)

    def _boom(*_a, **_k):
        raise RuntimeError("simulated morning crash")

    runner._push_screening = _boom  # type: ignore

    with pytest.raises(RuntimeError, match="simulated morning crash"):
        runner.run_morning_screen(skip_if_done=True, notify=True)

    row = sqlite3.connect(path).execute(
        "SELECT status, notes FROM pipeline_runs WHERE run_date=?",
        ("screen-20260908",),
    ).fetchone()
    assert row[0] == "computed"
    assert "crashed" in row[1]
    assert (
        runner.try_claim_pipeline(
            "screen-20260908",
            notes="morning-claim",
            allow_stale_running=True,
            stale_running_sec=1800,
        )
        is True
    )


def test_mark_pipeline_retries_db_lock(tmp_path, monkeypatch):
    """寄出後蓋戳若遇 DB lock 必須重試，否則 force-morning 會重寄。"""
    import sqlite3

    import main_runner as mr
    from main_runner import MainRunner
    from wayne_db import ensure_core_schema

    path = str(tmp_path / "mark-retry.db")
    ensure_core_schema(path)
    runner = MainRunner.__new__(MainRunner)
    runner.db_path = path
    runner.today_str = "20261023"
    calls = {"n": 0}
    real_connect = sqlite3.connect

    def _flaky(*a, **k):
        calls["n"] += 1
        if calls["n"] <= 2:
            raise sqlite3.OperationalError("database is locked")
        return real_connect(*a, **k)

    monkeypatch.setattr(mr.sqlite3, "connect", _flaky)
    monkeypatch.setattr(mr.time, "sleep", lambda *_a, **_k: None)
    runner._mark_pipeline("success", "morning-digest", run_date="screen-20261022")
    assert calls["n"] >= 3
    row = real_connect(path).execute(
        "SELECT status, notes FROM pipeline_runs WHERE run_date=?",
        ("screen-20261022",),
    ).fetchone()
    assert row[0] == "success"
    assert row[1] == "morning-digest"


def test_push_screening_keeps_sent_ok_when_mark_fails(monkeypatch, tmp_path):
    """Telegram 已 2/2 後蓋戳炸裂，不准再往上丟例外（否則當未寄→重寄）。"""
    import sqlite3

    from main_runner import MainRunner
    from wayne_db import ensure_core_schema

    path = str(tmp_path / "push-mark-fail.db")
    ensure_core_schema(path)
    runner = MainRunner.__new__(MainRunner)
    runner.db_path = path
    runner.today_str = "20261023"
    runner.token = "x"
    runner.chat_id = "1"
    runner.bot = type(
        "B",
        (),
        {"send_screening_report": staticmethod(lambda *a, **k: True)},
    )()
    monkeypatch.setattr(runner, "_family_chat_ids", lambda: ["111", "222"])
    monkeypatch.setattr(runner, "_push_morning_session_cards", lambda *a, **k: None)
    marks = {"n": 0}

    def _boom(*_a, **_k):
        marks["n"] += 1
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(runner, "_mark_pipeline", _boom)
    screening = {"status": "success", "payload": [{"html": "海選"}], "message": "海選", "results": {}}
    ok = runner._push_screening(
        screening,
        as_of="20261022",
        morning_digest=True,
        pipeline_run_date="screen-20261022",
    )
    assert ok is True
    assert marks["n"] == 1


def test_send_ok_mark_fail_force_morning_does_not_resend(tmp_path, monkeypatch):
    """2026-10-23：Telegram 2/2 後蓋戳失敗，第二次 force 不准再寄。"""
    import sqlite3

    import main_runner as mr
    from main_runner import MainRunner
    from wayne_db import ensure_core_schema

    path = str(tmp_path / "dup-force.db")
    ensure_core_schema(path)
    runner = MainRunner.__new__(MainRunner)
    runner.db_path = path
    runner.today_str = "20261023"
    runner.token = "x"
    runner.chat_id = "111"
    runner.bot = type(
        "B",
        (),
        {"send_screening_report": staticmethod(lambda *a, **k: True)},
    )()
    monkeypatch.setattr(runner, "_family_chat_ids", lambda: ["111", "222"])
    monkeypatch.setattr(runner, "_push_morning_session_cards", lambda *a, **k: None)
    monkeypatch.setattr(mr.time, "sleep", lambda *_a, **_k: None)

    # 模擬 DB 蓋戳永遠 locked（寄出回執仍要靠檔／表寫成）
    real_mark = runner._mark_pipeline

    def _mark_boom(*a, **k):
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(runner, "_mark_pipeline", _mark_boom)

    screening = {
        "status": "success",
        "payload": [{"html": "海選"}],
        "message": "海選",
        "results": {},
    }
    ok = runner._push_screening(
        screening,
        as_of="20261022",
        morning_digest=True,
        pipeline_run_date="screen-20261022",
    )
    assert ok is True
    assert runner.push_already_delivered("screen-20261022") is True

    # pipeline 仍可能不是 success（蓋戳失敗）
    # 模擬仍卡在 running morning-claim
    conn = sqlite3.connect(path)
    conn.execute(
        "INSERT OR REPLACE INTO pipeline_runs VALUES (?,?,?,?)",
        ("screen-20261022", "2026-10-23T18:32:00+08:00", "running", "morning-claim"),
    )
    conn.commit()
    conn.close()

    # force demote 不准降有回執的鍵
    assert runner.demote_orphaned_morning_claims(force=True) == 0

    # reconcile／honor 補標 success（用真 _mark_pipeline）
    monkeypatch.setattr(runner, "_mark_pipeline", real_mark)
    assert runner.honor_push_delivery("screen-20261022") is True
    assert runner.pipeline_status("screen-20261022") == "success"

    # 第二次 force／claim 不准再搶
    assert (
        runner.try_claim_pipeline(
            "screen-20261022",
            notes="morning-claim",
            allow_stale_running=True,
            stale_running_sec=1,
        )
        is False
    )

    morning_calls = {"n": 0}

    def _morning(*_a, **_k):
        morning_calls["n"] += 1
        return True

    monkeypatch.setattr(runner, "run_morning_screen", _morning)
    monkeypatch.setattr(
        "import_health.latest_complete_quote_date", lambda *_a, **_k: "20261022"
    )
    out = runner.force_rescue_morning()
    # reconcile 已把 key 標 success → 不再當成未寄去跑 morning（或跑了也因 skip 不寄）
    assert out.get("delivered") is True or runner.pipeline_status("screen-20261022") == "success"
    assert runner.push_already_delivered("screen-20261022") is True
    # 第二次 demote+claim 仍擋
    assert runner.demote_orphaned_morning_claims(force=True) == 0
    assert (
        runner.try_claim_pipeline(
            "screen-20261022", notes="morning-claim", allow_stale_running=True
        )
        is False
    )
    _ = morning_calls


def test_midday_records_delivery_before_mark(tmp_path, monkeypatch):
    """12:45 寄出後即使蓋戳失敗，也要有回執擋重寄。"""
    import sqlite3

    from main_runner import MainRunner
    from wayne_db import ensure_core_schema

    path = str(tmp_path / "midday-receipt.db")
    ensure_core_schema(path)
    runner = MainRunner.__new__(MainRunner)
    runner.db_path = path
    runner.today_str = "20261023"
    monkeypatch.setattr(
        "import_health.latest_complete_quote_date", lambda *_a, **_k: "20261022"
    )
    monkeypatch.setattr(
        "tw_holidays.closed_tw_session", lambda **_k: None
    )
    claim_n = {"n": 0}
    real_claim = runner.try_claim_pipeline

    def _claim_once(*a, **k):
        claim_n["n"] += 1
        if claim_n["n"] == 1:
            return True
        return real_claim(*a, **k)

    monkeypatch.setattr(runner, "try_claim_pipeline", _claim_once)
    monkeypatch.setattr(
        "midday_review.run_midday_review",
        lambda *_a, **_k: {"html": "<b>比價</b>"},
    )
    monkeypatch.setattr(runner, "_broadcast_family", lambda *_a, **_k: True)
    monkeypatch.setattr(runner, "_family_chat_ids", lambda: ["1", "2"])

    def _boom(*_a, **_k):
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(runner, "_mark_pipeline", _boom)
    assert runner.run_midday_review(skip_if_done=True) is True
    assert runner.push_already_delivered("midday-20261022") is True
    # 還原真 claim：有回執則 honor 擋住
    monkeypatch.setattr(runner, "try_claim_pipeline", real_claim)
    monkeypatch.setattr(runner, "_mark_pipeline", lambda *a, **k: None)
    assert (
        runner.try_claim_pipeline(
            "midday-20261022", notes="midday-claim", allow_stale_running=False
        )
        is False
    )


def test_winrate_records_delivery_before_mark(tmp_path, monkeypatch):
    import sqlite3

    from main_runner import MainRunner
    from wayne_db import ensure_core_schema

    path = str(tmp_path / "wr-receipt.db")
    ensure_core_schema(path)
    runner = MainRunner.__new__(MainRunner)
    runner.db_path = path
    runner.today_str = "20261023"
    runner.bot = None
    monkeypatch.setattr(
        "tw_holidays.closed_tw_session", lambda **_k: None
    )
    monkeypatch.setattr(
        "import_health.latest_complete_quote_date", lambda *_a, **_k: "20261022"
    )
    monkeypatch.setattr(
        "winrate_buypoint.scan_winrate_leave_zero",
        lambda *_a, **_k: ("20261022", []),
    )
    monkeypatch.setattr(
        "winrate_buypoint.save_winrate_roster", lambda *_a, **_k: 0
    )
    monkeypatch.setattr(
        "winrate_buypoint.silent_remember_roster", lambda *_a, **_k: None
    )
    monkeypatch.setattr(runner, "_broadcast_family", lambda *_a, **_k: True)
    monkeypatch.setattr(runner, "_family_chat_ids", lambda: ["1", "2"])

    def _boom(*_a, **_k):
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(runner, "_mark_pipeline", _boom)
    from winrate_buypoint import pipeline_run_key

    key = pipeline_run_key("20261022")
    assert runner.run_winrate_buypoint(skip_if_done=True, notify=True) is True
    assert runner.push_already_delivered(key) is True


def test_force_rescue_skips_when_fresh_morning_claim(tmp_path, monkeypatch):
    """新鮮 morning-claim 進行中：force-rescue 不准 demote 再開第二條。"""
    from main_runner import MainRunner
    from wayne_db import ensure_core_schema

    path = str(tmp_path / "inflight.db")
    ensure_core_schema(path)
    runner = MainRunner.__new__(MainRunner)
    runner.db_path = path
    runner.today_str = "20261027"
    called = {"demote": 0, "morning": 0}
    monkeypatch.setattr(runner, "reconcile_push_deliveries", lambda **k: 0)
    monkeypatch.setattr(runner, "morning_claim_is_fresh_running", lambda: True)
    monkeypatch.setattr(
        runner,
        "demote_orphaned_morning_claims",
        lambda **k: called.__setitem__("demote", called["demote"] + 1) or 0,
    )
    monkeypatch.setattr(
        runner,
        "demote_orphaned_increment_claims",
        lambda **k: 0,
    )
    monkeypatch.setattr(
        runner,
        "run_morning_screen",
        lambda **k: called.__setitem__("morning", called["morning"] + 1) or True,
    )
    out = runner.force_rescue_morning()
    assert out.get("ok") is True
    assert out.get("skipped_inflight") is True
    assert called["demote"] == 0
    assert called["morning"] == 0


def test_push_screening_skips_when_delivery_recorded(tmp_path, monkeypatch):
    """已有寄出回執：_push_screening 不准再打 Telegram。"""
    from main_runner import MainRunner
    from pipeline_delivery import record_push_delivery
    from wayne_db import ensure_core_schema

    path = str(tmp_path / "dedupe.db")
    ensure_core_schema(path)
    record_push_delivery(
        path, "screen-20261022", kind="morning-digest", n_ok=2
    )
    runner = MainRunner.__new__(MainRunner)
    runner.db_path = path
    runner.today_str = "20261027"
    runner.chat_id = "1"
    sends = {"n": 0}

    def _boom(*_a, **_k):
        sends["n"] += 1
        return True

    runner.bot = type(
        "B", (), {"send_screening_report": staticmethod(_boom)}
    )()
    monkeypatch.setattr(runner, "_family_chat_ids", lambda: ["1", "2"])
    monkeypatch.setattr(runner, "_push_morning_session_cards", lambda *a, **k: None)
    ok = runner._push_screening(
        {"status": "success", "payload": [{"html": "x"}], "message": "x", "results": {}},
        as_of="20261022",
        morning_digest=True,
        pipeline_run_date="screen-20261022",
    )
    assert ok is True
    assert sends["n"] == 0


def test_morning_open_day_reissues_after_holiday_same_as_of(tmp_path, monkeypatch):
    """§14：連假後 as_of 未前進，舊開市日 screen-{as_of} 回執不准擋今日真寄。"""
    import sqlite3

    from main_runner import MainRunner
    from pipeline_delivery import record_push_delivery
    from wayne_db import ensure_core_schema, touch_tg_user

    path = str(tmp_path / "reissue.db")
    ensure_core_schema(path)
    touch_tg_user(path, "9001", "偉權")
    # 模擬 10/23 已寄 screen-20261022；今日 10/27 開市、as_of 仍 20261022
    record_push_delivery(
        path,
        "screen-20261022",
        kind="morning-digest",
        n_ok=2,
        delivered_at="2026-10-23T06:32:00+08:00",
    )
    conn = sqlite3.connect(path)
    conn.execute(
        "INSERT OR REPLACE INTO pipeline_runs VALUES (?,?,?,?)",
        (
            "screen-20261022",
            "2026-10-23T06:32:00+08:00",
            "success",
            "morning",
        ),
    )
    conn.execute(
        "INSERT OR REPLACE INTO pipeline_runs VALUES (?,?,?,?)",
        (
            "screen-closed-20261026",
            "2026-10-26T06:30:00+08:00",
            "success",
            "tw closed 光復節補假 skip screen",
        ),
    )
    conn.commit()
    conn.close()

    runner = MainRunner.__new__(MainRunner)
    runner.db_path = path
    runner.today_str = "20261027"
    runner.chat_id = "9001"
    runner.token = "x"
    sends = {"n": 0}

    def _send_report(*_a, **_k):
        sends["n"] += 1
        return True

    runner.bot = type(
        "B", (), {"send_screening_report": staticmethod(_send_report)}
    )()
    runner._format_watch_radar_section = lambda uid="": ""
    runner._run_ai_desk = lambda *a, **k: {}
    runner.send_telegram_message = lambda *a, **k: None
    runner._push_morning_session_cards = lambda *a, **k: None
    runner._refresh_official_sidecars = lambda: None
    runner.demote_premature_morning_screens = lambda: 0
    runner.demote_holiday_skip_morning_screens = lambda: 0
    monkeypatch.setattr(
        "tw_holidays.refresh_tw_typhoon_halt", lambda *_a, **_k: {"ok": True}
    )
    monkeypatch.setattr("tw_holidays.closed_tw_session", lambda **_k: None)
    monkeypatch.setattr(
        "import_health.latest_complete_quote_date",
        lambda *_a, **_k: "20261022",
    )
    monkeypatch.setattr("config.fuse_end_date", lambda: "20261023")
    monkeypatch.setattr(
        "main_runner.run_full_screening",
        lambda **_k: {
            "status": "success",
            "payload": [{"html": "海選"}],
            "results": {},
        },
    )
    monkeypatch.setattr("taiwan_market.sync_futures_daily", lambda *_a, **_k: {})
    monkeypatch.setattr("taiwan_market.sync_futures_inst_oi", lambda *_a, **_k: {})
    monkeypatch.setattr("us_overnight.refresh_us_overnight", lambda *_a, **_k: {})
    monkeypatch.setattr("us_overnight.should_alert_us_drop", lambda *_a, **_k: False)
    monkeypatch.setattr(
        "taiwan_market.format_taiwan_market_brief_html", lambda *_a, **_k: ""
    )
    monkeypatch.setattr(
        "taiwan_market.analyze_taiwan_market", lambda *_a, **_k: {"ok": False}
    )
    monkeypatch.setattr(runner, "_family_chat_ids", lambda: ["9001", "9002"])

    assert runner.push_already_delivered("screen-20261022") is True
    assert runner.run_morning_screen(skip_if_done=True, notify=True) is True
    assert sends["n"] >= 1
    assert runner.pipeline_status("screen-20261022") == "success"
    assert runner.push_already_delivered("screen-20261022") is True
    # 同日再跑仍擋
    n1 = sends["n"]
    assert runner.run_morning_screen(skip_if_done=True, notify=True) is True
    assert sends["n"] == n1
