# -*- coding: utf-8 -*-
"""排程單一擁有者。

GHA 與 Render 各自有一份 pipeline_runs，互相看不到，所以同一個工作
兩邊都跑時 skip_if_done 會失效，使用者收到兩份一樣的推播。
分派規則必須是「每個工作只有一個擁有者」。
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config  # noqa: E402
import main  # noqa: E402

ALL_JOBS = ("morning", "midday", "fuse", "evening")


def test_default_role_is_data(monkeypatch):
    monkeypatch.delenv("WAYNE_SCHEDULER_ROLE", raising=False)
    monkeypatch.delenv("ENABLE_DAILY_SCHEDULER", raising=False)
    assert config.scheduler_role() == "data"


def test_legacy_disable_flag_maps_to_off(monkeypatch):
    monkeypatch.delenv("WAYNE_SCHEDULER_ROLE", raising=False)
    monkeypatch.setenv("ENABLE_DAILY_SCHEDULER", "false")
    assert config.scheduler_role() == "off"


def test_explicit_role_wins_over_legacy_flag(monkeypatch):
    monkeypatch.setenv("ENABLE_DAILY_SCHEDULER", "false")
    monkeypatch.setenv("WAYNE_SCHEDULER_ROLE", "full")
    assert config.scheduler_role() == "full"


def test_unknown_role_falls_back_to_data(monkeypatch):
    monkeypatch.delenv("ENABLE_DAILY_SCHEDULER", raising=False)
    monkeypatch.setenv("WAYNE_SCHEDULER_ROLE", "banana")
    assert config.scheduler_role() == "data"


def test_data_role_yields_morning_to_gha(monkeypatch):
    monkeypatch.setenv("WAYNE_SCHEDULER_ROLE", "data")
    assert config.scheduler_owns("morning") is False
    assert config.scheduler_may_push("morning") is False


def test_data_role_keeps_midday_because_gha_has_no_such_cron(monkeypatch):
    monkeypatch.setenv("WAYNE_SCHEDULER_ROLE", "data")
    assert config.scheduler_owns("midday") is True
    assert config.scheduler_may_push("midday") is True


def test_data_role_refreshes_silently(monkeypatch):
    monkeypatch.setenv("WAYNE_SCHEDULER_ROLE", "data")
    for job in ("fuse", "evening"):
        assert config.scheduler_owns(job) is True
        assert config.scheduler_may_push(job) is False


def test_off_role_owns_nothing(monkeypatch):
    monkeypatch.setenv("WAYNE_SCHEDULER_ROLE", "off")
    for job in ALL_JOBS:
        assert config.scheduler_owns(job) is False
        assert config.scheduler_may_push(job) is False


def test_full_role_owns_everything(monkeypatch):
    monkeypatch.setenv("WAYNE_SCHEDULER_ROLE", "full")
    for job in ALL_JOBS:
        assert config.scheduler_owns(job) is True
        assert config.scheduler_may_push(job) is True


def test_every_job_has_exactly_one_pusher(monkeypatch):
    """data 角色下，會推播的工作與 GHA 的 cron 不能重疊。"""
    monkeypatch.setenv("WAYNE_SCHEDULER_ROLE", "data")
    gha_jobs = {"morning", "fuse"}  # daily_run.yml 的兩個 cron
    local_pushers = {j for j in ALL_JOBS if config.scheduler_may_push(j)}
    assert local_pushers & gha_jobs == set()


class _Recorder:
    def __init__(self):
        self.calls = []

    def run_morning_screen(self, **kw):
        self.calls.append(("morning", kw))
        return True

    def run_midday_review(self, **kw):
        self.calls.append(("midday", kw))
        return True

    def run_evening_screen(self, **kw):
        self.calls.append(("evening", kw))
        return True

    def run_increment_job(self, **kw):
        self.calls.append(("fuse", kw))
        return True


@pytest.fixture()
def recorder(monkeypatch):
    rec = _Recorder()
    import main_runner

    monkeypatch.setattr(main_runner, "MainRunner", lambda *a, **k: rec)
    return rec


def test_dispatch_skips_unowned_job(monkeypatch, recorder):
    monkeypatch.setenv("WAYNE_SCHEDULER_ROLE", "data")
    main.run_scheduled_job("morning")
    assert recorder.calls == []


def test_dispatch_runs_owned_job(monkeypatch, recorder):
    monkeypatch.setenv("WAYNE_SCHEDULER_ROLE", "data")
    main.run_scheduled_job("midday")
    assert [c[0] for c in recorder.calls] == ["midday"]


def test_dispatch_silences_fuse_in_data_role(monkeypatch, recorder):
    monkeypatch.setenv("WAYNE_SCHEDULER_ROLE", "data")
    main.run_scheduled_job("fuse")
    assert recorder.calls[0][0] == "fuse"
    assert recorder.calls[0][1]["notify"] is False


def test_dispatch_notifies_fuse_in_full_role(monkeypatch, recorder):
    monkeypatch.setenv("WAYNE_SCHEDULER_ROLE", "full")
    main.run_scheduled_job("fuse")
    assert recorder.calls[0][1]["notify"] is True


def test_dispatch_runs_morning_in_full_role(monkeypatch, recorder):
    monkeypatch.setenv("WAYNE_SCHEDULER_ROLE", "full")
    main.run_scheduled_job("morning")
    assert [c[0] for c in recorder.calls] == ["morning"]


def test_dispatch_off_role_runs_nothing(monkeypatch, recorder):
    monkeypatch.setenv("WAYNE_SCHEDULER_ROLE", "off")
    for job in ALL_JOBS:
        main.run_scheduled_job(job)
    assert recorder.calls == []


def test_evening_stays_silent_in_every_role(monkeypatch, recorder):
    for role in ("data", "full"):
        recorder.calls.clear()
        monkeypatch.setenv("WAYNE_SCHEDULER_ROLE", role)
        main.run_scheduled_job("evening")
        assert recorder.calls[0][1]["notify"] is False


def test_catch_up_after_2000_runs_evening_on_data_role(monkeypatch, recorder):
    from datetime import datetime
    from zoneinfo import ZoneInfo

    monkeypatch.setenv("WAYNE_SCHEDULER_ROLE", "data")
    now = datetime(2026, 9, 4, 20, 16, tzinfo=ZoneInfo("Asia/Taipei"))
    main.catch_up_missed_jobs(now)
    kinds = [c[0] for c in recorder.calls]
    assert "evening" in kinds
    assert "morning" not in kinds
    eve = [c for c in recorder.calls if c[0] == "evening"][0]
    assert eve[1]["skip_if_done"] is True
    assert eve[1]["notify"] is False


def test_catch_up_before_2000_skips_evening(monkeypatch, recorder):
    from datetime import datetime
    from zoneinfo import ZoneInfo

    monkeypatch.setenv("WAYNE_SCHEDULER_ROLE", "data")
    now = datetime(2026, 9, 4, 19, 50, tzinfo=ZoneInfo("Asia/Taipei"))
    main.catch_up_missed_jobs(now)
    assert recorder.calls == []


def test_catch_up_weekend_runs_nothing(monkeypatch, recorder):
    from datetime import datetime
    from zoneinfo import ZoneInfo

    monkeypatch.setenv("WAYNE_SCHEDULER_ROLE", "data")
    now = datetime(2026, 9, 5, 21, 0, tzinfo=ZoneInfo("Asia/Taipei"))  # Saturday
    main.catch_up_missed_jobs(now)
    assert recorder.calls == []


def test_scheduler_thread_not_started_when_off(monkeypatch):
    monkeypatch.setenv("WAYNE_SCHEDULER_ROLE", "off")
    assert main.start_daily_scheduler() is None


def test_increment_job_notify_flag_is_accepted():
    """runner 必須真的接受 notify，不能只有分派端假設。"""
    import inspect

    from main_runner import MainRunner

    sig = inspect.signature(MainRunner.run_increment_job)
    assert "notify" in sig.parameters
    assert sig.parameters["notify"].default is True


def test_render_yaml_declares_the_owner():
    """擁有者要寫在程式碼裡，不能只存在 Render 後台。"""
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    with open(os.path.join(root, "render.yaml"), encoding="utf-8") as fh:
        text = fh.read()
    assert "WAYNE_SCHEDULER_ROLE" in text
    assert "data" in text
    assert "healthCheckPath: /live" in text
