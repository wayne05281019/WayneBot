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
    assert not j["push"]


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


def test_escape_wave_caution_is_not_exit_command():
    from biaoke_alert import content_intents, format_alert, judge_emergency

    text = "目前大盤漲不動我反而覺得比較好，我是怕開牌前主力作逃命波也就是C-2，開牌後變C-3下殺。"
    score, why = content_intents(text)
    blob = "、".join(why)
    assert "出清" not in blob
    j = judge_emergency(text, move=_move(294, y=45862.52))
    assert "出清／逃命／先回收" not in "".join(j["reasons"])
    html = format_alert(
        {
            "kind": "reply",
            "date": "2026-09-15",
            "time": "10:47",
            "text": text,
        },
        j,
        _move(294, y=45862.52),
    )
    assert "他原文" in html
    assert "10:47" in html
    assert "漲不動" in html
    assert "研判：" not in html
    assert "沒過按鈕" not in html
    assert "怕錯過" not in html
    assert "飆大盤中補充" in html
    assert "對原文用" in html
    assert "程式標籤（不是他原文）" not in html
    assert "官方加權盤中現價" not in html


def test_stand_back_is_not_an_order():
    from biaoke_alert import content_intents, judge_emergency

    text = (
        "穩懋就是昨天跌破支撐立刻站回去，從細微觀察近期會比台達電強，"
        "今年年底或明年大盤漲完目標就是冊歷史高點。"
    )
    score, why = content_intents(text)
    blob = "、".join(why)
    assert "命令句" not in blob
    assert "短句大盤命令" not in blob
    j = judge_emergency(text, move=_move(294, y=45862.52))
    assert not j["push"]


def test_night_not_through_is_not_uptrend():
    j = judge_emergency(
        "夜盤沒突破下降壓，可能擴延。細微波走完 5 段看起來趨勢向上。",
        move={"ok": False, "drop": 0, "pct": 0},
    )
    assert not j["push"]


def test_worst_case_almost_never_is_not_an_alarm():
    j = judge_emergency(
        "用技術分析K棒來講就是築底等開牌。但有一個更差的波段位階我沒提，"
        "因為我認為可能性微乎其微，那就是所謂築底只是橫台整理，"
        "橫台整理之後再走4段，也就是走9波擴延。C-3就會到36000，代表AI 時代結束。",
        move=_move(294, y=45862.52),
    )
    assert not j["push"]
    j2 = judge_emergency(
        "最差情境幾乎不可能(5%)，所以目前開盤之後會有比較正向發展機率較大",
        move=_move(120),
    )
    assert not j2["push"]


def test_screenshot_old_replies_are_inbox_not_push():
    from biaoke_alert import format_alert

    move = _move(351, y=45862.52)
    light = (
        "最一開始認識飆大就是光聖時期，也是我第一檔玩超過百趴的個股。"
        "光聖是我過年前封關93介入，過年後不到10個交易日，7根漲停板，"
        "可是那個時候波段功力比較差，幾乎全部賣光只留一張光聖，"
        "後面還有2段更大的波段。"
    )
    if_c3 = (
        "如果C-2 轉C-3一定要先將非龍頭股先賣出一趟，因為回檔比較深。"
        "應該星期二~星期四夜盤，這三天就知道答案了。"
        "因為只要C走3段就好，應該會落在43000~44000之間，拉回也不少。"
    )
    maybe_run = (
        "今天沒買到 就算了，明天大盤反彈萬一是C-2是要逃命的，"
        "但現在完全看不出來，先等美股開盤"
    )
    for text in (light, if_c3, maybe_run):
        j = judge_emergency(text, move=move)
        assert not j["push"], text[:40]
    db_stats = maybe_push_drop_alert(
        "",
        [
            {"id": "a", "kind": "reply", "date": "2026-09-14", "time": "18:25", "text": light},
            {"id": "b", "kind": "reply", "date": "2026-09-14", "time": "16:21", "text": if_c3},
            {"id": "c", "kind": "reply", "date": "2026-09-14", "time": "16:27", "text": maybe_run},
        ],
        move=move,
    )
    assert db_stats["pushed"] == 0
    html = format_alert(
        {"kind": "reply", "date": "2026-09-14", "time": "18:25", "text": light},
        {"push": False, "score": 0, "reasons": ["出清／逃命／先回收"]},
        move,
    )
    assert "他原文" in html
    assert "幾乎全部賣光" in html
    assert "官方加權盤中現價" not in html
    assert "程式標籤" not in html
