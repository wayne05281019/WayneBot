# -*- coding: utf-8 -*-
"""緊急推播：自己研判，不是掃固定名詞。"""
from biaoke_alert import judge_emergency, maybe_push_drop_alert


def _move(drop: float, y: float = 47000.0) -> dict:
    px = y - drop
    return {"ok": True, "y": y, "px": px, "drop": drop, "pct": round((px - y) / y * 100.0, 2)}


def test_crash_plus_bottom_call_pushes():
    j = judge_emergency(
        "如果判斷差不多，應該就是台積電最值得抄底的時間了",
        move=_move(820),
    )
    assert j["push"]
    assert j["score"] >= 5


def test_crash_plus_paraphrase_still_pushes():
    j = judge_emergency(
        "這就是技術分析抄底位置，第一次回測波浪四，下跌走5段。",
        move=_move(710),
    )
    assert j["push"]


def test_crash_without_special_does_not_push():
    j = judge_emergency(
        "目前台股長線主流股族群目前就是散熱族群最為強勢。",
        move=_move(800),
    )
    assert not j["push"]


def test_full_exit_is_emergency_even_without_700():
    j = judge_emergency(
        "有矽光子股票下星期全面出清一股不留。",
        move={"ok": False, "drop": 0, "pct": 0},
    )
    assert j["push"]
    assert "出清" in "".join(j["reasons"])


def test_degree_retract_plus_night_crash():
    j = judge_emergency(
        "夜盤目前大跌，最樂觀第五波兩次擴延已經沒了，改走 A-c。",
        move={"ok": False, "drop": 0, "pct": 0},
    )
    assert j["push"]


def test_small_dip_chat_is_not_emergency():
    j = judge_emergency(
        "奇鋐、健策應該是第一批創新高的長線主流股。",
        move=_move(120),
    )
    assert not j["push"]


def test_maybe_push_dedupes(tmp_path, monkeypatch):
    db = str(tmp_path / "w.db")
    row = {
        "id": "x1",
        "kind": "post",
        "date": "2026-09-12",
        "time": "10:20",
        "text": "如果判斷差不多，應該就是台積電最值得抄底的時間了",
    }
    move = _move(850)
    a = maybe_push_drop_alert(db, [row], move=move)
    assert a["pushed"] == 1
    b = maybe_push_drop_alert(db, [row], move=move)
    assert b["pushed"] == 0
    assert b["skipped"] == 1
