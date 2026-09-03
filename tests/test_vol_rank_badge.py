from decision_card_signals import volume_headline_rank


def _badge(vr480, vr120, vr60=99):
    lab, n = volume_headline_rank(vr480, vr120, vr60)
    if n <= 10:
        return [f"{lab}第 {n} 名"]
    return []


def test_volume_badge_prefers_480_window():
    """表頭量能徽章：近 480 日量前 10 優先顯示 480日量（對齊 CaryBot 穩懋範本）。"""
    assert _badge(6, 15) == ["480日量第 6 名"]


def test_volume_badge_falls_back_to_120():
    assert _badge(88, 5) == ["120日量第 5 名"]


def test_volume_badge_falls_back_to_60():
    """3105 型：480／120 都不是前十，60 日量第 7 仍要亮。"""
    assert _badge(25, 25, 7) == ["60日量第 7 名"]


def test_volume_badge_omitted_when_not_top():
    assert _badge(88, 120, 40) == []
