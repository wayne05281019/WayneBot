# -*- coding: utf-8 -*-
"""手機更新說明：這次改了什麼，不貼程式代碼。"""
from phone_update import (
    UPDATE_DONE,
    phone_code_reply,
    phone_health_fields,
    phone_update_note,
    phone_update_notice,
    phone_update_title,
)


def test_update_note_is_this_change():
    note = phone_update_note()
    assert note
    assert any("\u4e00" <= ch <= "\u9fff" for ch in note)
    assert "feat:" not in note.lower()
    assert "git_sha" not in note
    title = phone_update_title()
    assert title == note
    notice = phone_update_notice("ff80cc3ce79e35a3dcbfd6dd8b92f82c51ed5991")
    assert "git_sha" not in notice
    assert "ff80cc3ce79e35a3dcbfd6dd8b92f82c51ed5991" not in notice
    assert note.split("完成")[0] in notice


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
    assert "git_sha" not in text
    assert "ff80cc3ce79e35a3dcbfd6dd8b92f82c51ed5991" not in text
    assert phone_code_reply() == text
    health = phone_health_fields()
    assert health["update"] == UPDATE_DONE
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
