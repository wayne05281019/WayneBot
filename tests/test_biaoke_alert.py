# -*- coding: utf-8 -*-
"""緊急推播：自己研判，不是掃固定名詞。"""
from biaoke_alert import confirm_stack, judge_emergency, maybe_push_drop_alert


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


def test_yuanren_tsmc_volume_confirms_without_700():
    text = (
        "波浪理論沒辦法 100% 確認 7/29 39384 為 A 波低；"
        "但台積電＋某金融商品的量價結構已經 100% 確認。"
        "7/29 第一次抄底那天就是 A 波低。"
        "大 B 波啟動＝漲漲跌跌但趨勢向上、時間很久。"
    )
    j = judge_emergency(text, move={"ok": False, "drop": 0, "pct": 0})
    assert j["push"]
    assert j["score"] >= 5
    assert "輔助" in "".join(j["reasons"]) or "確認" in "".join(j["reasons"])
    st = confirm_stack(text)
    assert st["confirmed"]
    assert "台積電量價" in st["aux"]
    assert "台指期" not in "".join(st["aux"])


def test_prelim_stop_and_right_shoulder_do_not_push():
    j = judge_emergency(
        "夜盤 15 分細微波走了 5 段，下降軌道已破壞＝初步止訊號；"
        "確認短線修正末端，夜盤至少要穿越 46506。無法判斷是 5 段或 9 段。",
        move={"ok": False, "drop": 0, "pct": 0},
    )
    assert not j["push"]
    j2 = judge_emergency(
        "未來 2～3 交易日觀盤重點是 9/3 低點 45839 有沒有守住。"
        "有守住＝右肩還是高有過前高、低不破前低，高檔震盪趨勢向上。",
        move={"ok": False, "drop": 0, "pct": 0},
    )
    assert not j2["push"]
    j3 = judge_emergency(
        "目前趨勢向上，下波起漲可以看。",
        move=_move(120),
    )
    assert not j3["push"]


def test_sox_plus_break_confirms_low():
    j = judge_emergency(
        "大盤今天正式躍過下跌脈動的下降壓力線，再加上費半、那斯達科指數早就 14重疊，"
        "所以已經完全確認不會有第５波的末跌段，也就是說４／９就是今年的低點。",
        move={"ok": False, "drop": 0, "pct": 0},
    )
    assert j["push"]


def test_triple_aux_without_naming_wave_still_confirms():
    j = judge_emergency(
        "從費半、台指期上周五夜盤及上週五台積電用量縮上漲過最重要壓力線，"
        "台股又將從6/11開始算的主升段推升脈動產生。",
        move={"ok": False, "drop": 0, "pct": 0},
    )
    assert j["push"]
    st = confirm_stack(
        "從費半、台指期上周五夜盤及上週五台積電用量縮上漲過最重要壓力線，"
        "台股又將從6/11開始算的主升段推升脈動產生。"
    )
    assert len(st["aux"]) >= 3
    assert st["confirmed"]


def test_night_not_through_is_not_uptrend():
    j = judge_emergency(
        "夜盤沒突破下降壓，可能擴延。細微波走完 5 段看起來趨勢向上。",
        move={"ok": False, "drop": 0, "pct": 0},
    )
    assert not j["push"]
