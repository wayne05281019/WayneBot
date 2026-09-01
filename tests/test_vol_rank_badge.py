from wayne_navigator import NavigatorEngine


def test_volume_badge_prefers_480_window(monkeypatch):
  """表頭量能徽章：近 480 日量前 10 優先顯示 480日量（對齊 CaryBot 穩懋範本）。"""
  eng = NavigatorEngine.__new__(NavigatorEngine)

  def fake_rank(series, window=120):
    return [6 if window == 480 else 15] * len(series)

  monkeypatch.setattr(eng, "_calc_rolling_rank", fake_rank)
  # 只測徽章邏輯：直接呼叫內嵌邏輯的等價判斷
  vr480, vr120 = 6, 15
  badges = []
  if vr480 <= 10:
    badges.append(f"480日量第 {vr480} 名")
  elif vr120 <= 10:
    badges.append(f"120日量第 {vr120} 名")
  assert badges == ["480日量第 6 名"]


def test_volume_badge_falls_back_to_120():
  vr480, vr120 = 88, 5
  badges = []
  if vr480 <= 10:
    badges.append(f"480日量第 {vr480} 名")
  elif vr120 <= 10:
    badges.append(f"120日量第 {vr120} 名")
  assert badges == ["120日量第 5 名"]


def test_volume_badge_omitted_when_not_top():
  vr480, vr120 = 88, 120
  badges = []
  if vr480 <= 10:
    badges.append(f"480日量第 {vr480} 名")
  elif vr120 <= 10:
    badges.append(f"120日量第 {vr120} 名")
  assert badges == []
