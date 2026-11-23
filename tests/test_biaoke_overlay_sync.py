# -*- coding: utf-8 -*-
"""SYNC-OVERLAY：API 列轉換、delta 合併、不准路人／假圖。"""
from __future__ import annotations

import gzip
import json
import os

from biaoke_ingest import AUTHOR_ID
from biaoke_observe_atoms import load_corpus_rows
from biaoke_overlay_sync import (
    api_article_to_row,
    export_overlay_delta,
    load_overlay_delta,
    merge_chart_index_from_rows,
)


def test_api_article_to_row_keeps_author_charts(tmp_path):
    raw = {
        "id": 189626201,
        "createTime": 1795447101712,  # 2026-11-23 Taipei
        "weight": 1,
        "content": {
            "creatorId": int(AUTHOR_ID),
            "text": "台指期夜盤盤中見漲停，明早大盤觀察 35442。",
            "commodityTags": [{"type": "Stock", "key": "TWA00"}],
            "multiMedia": [
                {
                    "mediaType": "image",
                    "url": "https://image.cmoney.tw/attachment/post/x/a.png",
                },
                {
                    "mediaType": "image",
                    "url": "https://image.cmoney.tw/profile/avatar.png",
                },
            ],
        },
    }
    row = api_article_to_row(raw)
    assert row is not None
    assert row["id"] == "189626201"
    assert row["date"] == "2026-11-23"
    assert "附圖：https://image.cmoney.tw/attachment/post/x/a.png" in row["text"]
    assert "profile/avatar" not in row["text"]


def test_api_article_rejects_alien_creator():
    raw = {
        "id": 1,
        "createTime": 1795447101712,
        "content": {
            "creatorId": 999999,
            "text": "別人的文 夜盤 35442",
            "multiMedia": [],
        },
    }
    assert api_article_to_row(raw) is None


def test_export_and_load_overlay_delta_merges_atoms(tmp_path, monkeypatch):
    import biaoke_overlay_sync as syn
    import biaoke_observe_atoms as atoms

    db = tmp_path / "t.db"
    import sqlite3

    conn = sqlite3.connect(str(db))
    conn.execute(
        "CREATE TABLE biaoke_posts("
        "id TEXT PRIMARY KEY, n INTEGER, date TEXT, time TEXT, parent TEXT, "
        "layer INTEGER, kind TEXT, tags TEXT, text TEXT, updated_at TEXT, "
        "reply_to_text TEXT)"
    )
    conn.execute(
        "INSERT INTO biaoke_posts VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (
            "ov1",
            0,
            "2026-11-23",
            "21:00",
            "",
            0,
            "post",
            "[]",
            "夜盤穿刺 36000 明早大盤確認。附圖：https://image.cmoney.tw/attachment/post/z.png",
            "",
            "",
        ),
    )
    conn.commit()
    conn.close()

    dest = tmp_path / "overlay_delta.json.gz"
    monkeypatch.setattr(syn, "OVERLAY_DELTA_GZ", str(dest))
    monkeypatch.setattr(atoms, "load_overlay_delta_posts", lambda: [
        {
            "id": "ov1",
            "date": "2026-11-23",
            "time": "21:00",
            "parent": "",
            "layer": 0,
            "kind": "post",
            "text": "夜盤穿刺 36000 明早大盤確認。",
            "source": "overlay_delta",
            "club": False,
        }
    ])
    blob = export_overlay_delta(str(db), since_date="2026-11-01", path=str(dest))
    assert blob["n"] == 1
    assert blob["chart_urls_n"] == 1
    loaded = load_overlay_delta(str(dest))
    assert loaded["n"] == 1
    rows, meta = load_corpus_rows(db_path=str(db), include_club=False)
    assert any(r["id"] == "ov1" for r in rows)
    assert meta["to"] >= "2026-11-23" or any(r["date"] == "2026-11-23" for r in rows)


def test_merge_chart_index_no_avatar(tmp_path):
    idx = tmp_path / "chart_index.json.gz"
    with gzip.open(idx, "wt", encoding="utf-8") as fh:
        json.dump({"n": 0, "sources": {}, "note": "t", "charts": []}, fh)
    stats = merge_chart_index_from_rows(
        [
            {
                "id": "p1",
                "date": "2026-11-23",
                "kind": "post",
                "text": (
                    "附圖：https://image.cmoney.tw/attachment/post/ok.png\n"
                    "附圖：https://image.cmoney.tw/profile/no.png"
                ),
            }
        ],
        index_path=str(idx),
    )
    assert stats["added"] == 1
    with gzip.open(idx, "rt", encoding="utf-8") as fh:
        blob = json.load(fh)
    assert blob["n"] == 1
    assert "profile" not in blob["charts"][0]["url"]
