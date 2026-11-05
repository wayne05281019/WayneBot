# -*- coding: utf-8 -*-
"""手機更新說明：這次改了什麼，不貼程式代碼。"""
from phone_update import (
    UPDATE_DONE,
    UPDATE_START,
    phone_code_reply,
    phone_health_fields,
    phone_update_note,
    phone_update_notice,
    phone_update_starting,
    phone_update_title,
)


def test_update_note_is_this_change():
    note = phone_update_note()
    assert note
    assert any("\u4e00" <= ch <= "\u9fff" for ch in note)
    assert "feat:" not in note.lower()
    assert "git_sha" not in note
    # 不准再把通知機制本身推上話筒
    assert "正在更新什麼" not in note
    assert "開機會先說" not in note
    assert "再說更新完成" not in note
    title = phone_update_title()
    assert title == note
    notice = phone_update_notice("ff80cc3ce79e35a3dcbfd6dd8b92f82c51ed5991")
    assert "git_sha" not in notice
    assert "ff80cc3ce79e35a3dcbfd6dd8b92f82c51ed5991" not in notice
    assert note.split("完成")[0] in notice


def test_meta_update_mechanism_note_is_rejected(monkeypatch):
    """「開機會先說正在更新什麼…」這類內部說明＝無效口語。"""
    import phone_update as pu

    monkeypatch.delenv("WAYNE_UPDATE_NOTE", raising=False)
    monkeypatch.setattr(pu, "_git_head_note", lambda: "")
    monkeypatch.setattr(pu, "phone_schedule_wait_note", lambda now=None: "")
    monkeypatch.setattr(
        pu,
        "_file_note",
        lambda: pu._clean_note("開機會先說正在更新什麼，好了再說更新完成"),
    )
    assert phone_update_note() == ""
    assert phone_update_starting("abc") == UPDATE_START
    assert "正在更新什麼" not in phone_update_starting(
        "abc", note="開機會先說正在更新什麼，好了再說更新完成"
    )


def test_schedule_wait_note_at_fuse_window():
    """16:30 左右更新＝講盤後融合等候句，不准內部說明。"""
    from datetime import datetime
    from zoneinfo import ZoneInfo

    from phone_update import phone_schedule_wait_note, phone_update_starting

    now = datetime(2026, 11, 5, 16, 30, tzinfo=ZoneInfo("Asia/Taipei"))
    note = phone_schedule_wait_note(now=now)
    assert "盤後資料正在下載融合中" in note
    assert "請耐心等待" in note
    start = phone_update_starting("deadbeef", note=note, now=now)
    assert "盤後資料正在下載融合中" in start
    assert "正在更新什麼" not in start


def test_schedule_wait_note_beats_product_note(monkeypatch):
    from datetime import datetime
    from zoneinfo import ZoneInfo

    import phone_update as pu

    monkeypatch.setenv("WAYNE_UPDATE_NOTE", "查股兩張圖一次畫完")
    now = datetime(2026, 11, 5, 16, 40, tzinfo=ZoneInfo("Asia/Taipei"))
    assert "盤後資料正在下載融合中" in pu.phone_update_note(now=now)


def test_notice_is_spoken_without_sha(monkeypatch):
    monkeypatch.setenv("WAYNE_UPDATE_NOTE", "查股兩張圖一次畫完、同一則出現")
    monkeypatch.setenv("RENDER_GIT_COMMIT", "ff80cc3ce79e35a3dcbfd6dd8b92f82c51ed5991")
    monkeypatch.delenv("GITHUB_SHA", raising=False)
    note = phone_update_note()
    assert note == "查股兩張圖一次畫完、同一則出現"
    assert phone_update_title() == note
    text = phone_update_notice("ff80cc3ce79e35a3dcbfd6dd8b92f82c51ed5991")
    assert text.splitlines() == [
        "查股兩張圖一次畫完、同一則出現",
        UPDATE_DONE,
    ]
    start = phone_update_starting("ff80cc3ce79e35a3dcbfd6dd8b92f82c51ed5991")
    assert start == f"{UPDATE_START}：查股兩張圖一次畫完、同一則出現"
    assert "ff80cc3ce79e35a3dcbfd6dd8b92f82c51ed5991" not in start
    assert "git_sha" not in text
    assert "ff80cc3ce79e35a3dcbfd6dd8b92f82c51ed5991" not in text
    assert phone_code_reply() == text
    health = phone_health_fields()
    assert health["update"] == UPDATE_DONE
    assert phone_health_fields(updating=True)["update"] == UPDATE_START
    assert health["update_note"] == "查股兩張圖一次畫完、同一則出現"
    assert health["git_sha"] == "ff80cc3ce79e35a3dcbfd6dd8b92f82c51ed5991"


def test_notice_keeps_done_in_spoken_line():
    text = phone_update_notice("", note="查股兩張圖一次畫完、同一則出現完成")
    assert text == "查股兩張圖一次畫完、同一則出現完成"
    assert "git_sha" not in text


def test_title_does_not_force_suffix():
    assert phone_update_title("海選股名旁五角星") == "海選股名旁五角星"
    assert not phone_update_title("海選股名旁五角星").endswith("的更新")


def test_git_note_beats_stale_file(monkeypatch, tmp_path):
    """舊 phone_update_note.txt 不准蓋過這次合進的真改動。"""
    import phone_update as pu

    monkeypatch.delenv("WAYNE_UPDATE_NOTE", raising=False)
    stale = tmp_path / "phone_update_note.txt"
    stale.write_text("飆大改口語講當下重點\n", encoding="utf-8")
    monkeypatch.setattr(pu, "_NOTE_FILE", str(stale))
    monkeypatch.setattr(pu, "_git_head_note", lambda: "導航量柱軟頂，有官方量就畫得出")
    assert phone_update_note() == "導航量柱軟頂，有官方量就畫得出"
    assert "飆大" not in phone_update_notice("deadbeefcafebabe0123456789abcdef01234567")


def test_same_note_different_sha_does_not_renotify(tmp_path, monkeypatch):
    """#409／#411／#412 那種：SHA 不同但口語同一句 → 不准洗版。"""
    monkeypatch.setenv("WAYNE_DB_PATH", str(tmp_path / "wayne_market.db"))
    monkeypatch.delenv("DB_PATH", raising=False)
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    monkeypatch.setattr("bot_servers.skip_telegram_polling", lambda: False)
    from bot_servers import (
        remember_notified_sha,
        should_notify_phone_update,
    )

    note = "飆大改口語講當下重點"
    remember_notified_sha("aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", note=note)
    assert should_notify_phone_update(
        "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb", note=note
    ) is False
    assert should_notify_phone_update(
        "cccccccccccccccccccccccccccccccccccccccc",
        note="高低卡對齊作者視覺",
    ) is True


def test_push_phone_update_starting_then_done_dedupe(tmp_path, monkeypatch):
    """開始更新與更新完畢各推一次；同 SHA 不重送開始。"""
    monkeypatch.setenv("WAYNE_DB_PATH", str(tmp_path / "wayne_market.db"))
    monkeypatch.delenv("DB_PATH", raising=False)
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    monkeypatch.setenv("WAYNE_UPDATE_NOTE", "早報舊回執放行並閃過融合")
    monkeypatch.setenv("RENDER_GIT_COMMIT", "dddddddddddddddddddddddddddddddddddddddd")
    monkeypatch.setattr("bot_servers.skip_telegram_polling", lambda: False)
    sent = []

    def _fake_send(text: str) -> int:
        sent.append(text)
        return 2

    import bot_servers as bs

    monkeypatch.setattr(bs, "_sync_send_whitelist_text", _fake_send)
    from bot_servers import (
        push_phone_update_starting,
        remember_notified_sha,
        should_notify_phone_update,
        should_notify_phone_update_start,
    )

    sha = "dddddddddddddddddddddddddddddddddddddddd"
    assert should_notify_phone_update_start(sha) is True
    assert push_phone_update_starting(sha=sha) == 2
    assert sent and sent[0].startswith(UPDATE_START)
    assert "早報舊回執放行並閃過融合" in sent[0]
    assert push_phone_update_starting(sha=sha) == 0  # 同 SHA 不重送
    assert should_notify_phone_update(sha, note="早報舊回執放行並閃過融合") is True
    remember_notified_sha(sha, note="早報舊回執放行並閃過融合")
    assert should_notify_phone_update_start(sha) is False
    assert should_notify_phone_update(sha, note="早報舊回執放行並閃過融合") is False


def test_start_same_note_different_sha_does_not_renotify(tmp_path, monkeypatch):
    """同句「正在更新」口語換 SHA 不准再推（20:37／20:42 雙推）。"""
    monkeypatch.setenv("WAYNE_DB_PATH", str(tmp_path / "wayne_market.db"))
    monkeypatch.delenv("DB_PATH", raising=False)
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    monkeypatch.setattr("bot_servers.skip_telegram_polling", lambda: False)
    from bot_servers import (
        remember_started_sha,
        should_notify_phone_update_start,
    )

    note = "開機會先說正在更新什麼，好了再說更新完成"
    remember_started_sha("aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", note=note)
    assert (
        should_notify_phone_update_start(
            "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb", note=note
        )
        is False
    )
    assert (
        should_notify_phone_update_start(
            "cccccccccccccccccccccccccccccccccccccccc",
            note="更新通知改講人話，不再推內部說明句",
        )
        is True
    )
