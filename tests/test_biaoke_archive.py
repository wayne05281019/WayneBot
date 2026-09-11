# -*- coding: utf-8 -*-
"""Drive 1709 公開文 overlay：社團不進公開語料。"""
from __future__ import annotations

from biaoke_archive import (
    load_bundled_archive,
    parse_archive_markdown,
    seed_biaoke_archive,
)
from biaoke_desk import load_corpus, search_biaoke


_FIXTURE = """
# 期股多空雙飆客 操盤邏輯與歷史研讀庫

> 全量收錄 2 篇主文、2 則作者主留言與樓中樓深度問答。

---

## [貼文 1] 2023/12/4 下午1:04:56

**原文連結**：https://www.cmoney.tw/forum/article/158129800

### 📌 主文分析
智原這幾天支撐線370不跌破，就會開始進入推升另一波脈動！

### 🖼️ 主文附圖 (1 張)：
- 附圖 1: https://image.cmoney.tw/profile/member/1725033600/51cbb11b-a890-422e-b84b-3c09e4b364b9.jpg

### 💬 作者即時盤勢微調、問答與樓中樓指引 (1 則)
- **[2023/12/6 上午10:21:34] (主文留言)**：蔡森型態學，滿足點算的

---

## [貼文 2] 2026/9/10 上午9:51:28

**原文連結**：https://www.cmoney.tw/forum/article/184499206

### 📌 主文分析
目前台股長線主流股族群目前就是散熱族群最為強勢。

### 🖼️ 主文附圖 (1 張)：
- 附圖 1: https://image.cmoney.tw/attachment/post/1789000000/main.png

### 💬 作者即時盤勢微調、問答與樓中樓指引 (2 則)
- **[2026/9/10 上午10:40:00] (主文留言)**：矽光子最重要一檔就是聯亞
- **[2026/9/10 下午1:07:00] (回覆 路人甲)**：如果大盤測48218失敗很難
  - 補充圖表: https://image.cmoney.tw/attachment/post/1789000000/chart.png
"""


def test_parse_public_fixture_not_club():
    blob = parse_archive_markdown(_FIXTURE)
    assert blob["club"] is False
    assert blob["n"] == 2
    assert blob["replies"] == 3
    ids = {p["id"] for p in blob["posts"]}
    assert "158129800" in ids
    assert "158129800:a1" in ids
    first = next(p for p in blob["posts"] if p["id"] == "158129800")
    assert first["date"] == "2023-12-04"
    assert first["time"] == "13:04"
    assert "智原" in first["text"]
    assert "profile/member" not in first["text"]
    nested = next(p for p in blob["posts"] if p["id"] == "184499206:a2")
    assert nested["layer"] == 2
    assert "48218" in nested["text"]
    assert "附圖：" in nested["text"]
    assert "chart.png" in nested["text"]
    main = next(p for p in blob["posts"] if p["id"] == "184499206")
    assert "main.png" in main["text"]


def test_parse_club_markdown_is_flagged():
    text = open(
        "/tmp/biaoke-drive/期股多空雙飆客_社團專屬語料庫(由舊到新)_共72篇_含雙層樓中樓.md",
        encoding="utf-8",
    ).read() if __import__("os").path.isfile(
        "/tmp/biaoke-drive/期股多空雙飆客_社團專屬語料庫(由舊到新)_共72篇_含雙層樓中樓.md"
    ) else "## [社團貼文 1] 2025/6/5 下午8:00:00\n\n**原文連結**：https://www.cmoney.tw/forum/article/1\n\n### 📌 主文分析\n量先價行\n"
    blob = parse_archive_markdown(text)
    assert blob["club"] is True


def test_bundled_archive_has_1709_and_not_club():
    blob = load_bundled_archive()
    assert int(blob.get("n") or 0) >= 1709
    assert int(blob.get("replies") or 0) >= 1300
    assert blob.get("club") is False
    assert blob.get("from", "").startswith("2023-12")
    assert str(blob.get("to") or "").startswith("2026-09")
    texts = " ".join(p.get("text") or "" for p in blob["posts"])
    assert "智原" in texts
    assert "勤誠" in texts
    assert "散熱" in texts
    assert "48218" in texts
    replies = [p for p in blob["posts"] if p.get("kind") == "reply"]
    assert any("48218" in (p.get("text") or "") for p in replies)


def test_bundled_club_is_20_plus_72_not_in_public_search():
    from biaoke_archive import load_bundled_club

    club = load_bundled_club()
    assert int(club.get("n") or 0) >= 92
    assert int(club.get("replies") or 0) >= 60
    assert club.get("club") is True
    assert str(club.get("from") or "").startswith("2025-05")
    ids = {p["id"] for p in club["posts"] if (p.get("kind") or "post") != "reply"}
    assert "171400455" in ids
    assert "171407503" in ids
    pub = load_corpus(None)
    pub_ids = {p["id"] for p in pub["posts"] if (p.get("kind") or "post") != "reply"}
    assert "171400455" not in pub_ids
    html = search_biaoke("171400455")
    assert "恢復同名社團" not in html


def test_seed_overlay_makes_1709_searchable(tmp_path):
    db = str(tmp_path / "w.db")
    n = seed_biaoke_archive(db)
    assert n >= 1709
    fused = load_corpus(db)
    assert int(fused["n"]) >= 1709
    assert int(fused.get("replies") or 0) >= 1300
    html = search_biaoke("智原", db_path=db)
    assert "智原" in html
    assert any(
        str(p.get("date") or "") == "2023-12-04" and "智原" in str(p.get("text") or "")
        for p in fused["posts"]
    )
    # 第二次不覆蓋已有列
    assert seed_biaoke_archive(db) == 0
