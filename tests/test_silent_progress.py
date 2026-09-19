# -*- coding: utf-8 -*-
"""默默畫、覆盤、能講才開口。現在不准主動講。"""
from pathlib import Path

from silent_progress import (
    WAVE_NEURONS_MATCH,
    maybe_speak,
    night_review,
    simulate_next_legs,
    speak_line,
    speak_ready,
)


def test_speak_ready_stays_off():
    assert WAVE_NEURONS_MATCH is False
    assert speak_ready("twii") is False
    assert speak_ready("dongzhu") is False
    assert speak_ready("leave_zero") is False
    assert speak_ready("golden_buy") is False
    assert maybe_speak("twii") == ""
    assert maybe_speak("dongzhu") == ""
    assert maybe_speak("leave_zero") == ""


def test_speak_line_shape():
    line = speak_line(
        path="先守住他自己點過的低",
        level="45839",
        maybe="再測一次",
        prep="只看、不追",
        because="官方柱還沒碰到他的位",
        result="還沒走完",
    )
    assert "預計大盤走勢會是" in line
    assert "到45839有可能會發生" in line
    assert "建議現在要提前" in line
    assert "因為依照" in line


def test_simulate_next_legs_only_his_levels():
    legs = simulate_next_legs("逃命波C-2", 45862.0, [])
    ys = [float(x["y"]) for x in legs]
    assert 43500.0 in ys
    assert 45839.36 in ys
    blob = str(legs)
    assert "1-2-3-4-5" not in blob
    assert 17000 not in ys
    c5 = simulate_next_legs("C-5低點", 45511.0, [])
    c5y = [float(x["y"]) for x in c5]
    assert 43500.0 in c5y
    assert 45398.43 in c5y


def test_night_review_does_not_speak(tmp_path):
    db = str(tmp_path / "n.db")
    Path(db).write_text("")
    out = night_review(db)
    assert out.get("speak") is False
    src = Path("silent_progress.py").read_text(encoding="utf-8")
    assert "send_telegram" not in src
    assert "TELEGRAM_BOT_TOKEN" not in src
    absorb = Path("biaoke_absorb.py").read_text(encoding="utf-8")
    assert "night_review" in absorb
    i = absorb.find("night_review")
    assert "send_telegram" not in absorb[i : i + 400]
    assert absorb.find('endswith("-0200")') < absorb.find("night_review")
    from dongzhu_tape import optimize_ready

    assert optimize_ready(19) is False
