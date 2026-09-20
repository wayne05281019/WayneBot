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
    assert "程式代碼" in title


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
