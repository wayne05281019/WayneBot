# -*- coding: utf-8 -*-
"""用已下載的 Drive 原文＋分類結果建檔。不准重抓圖、不准重跑 OCR。"""
from __future__ import annotations

import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from biaoke_archive import (  # noqa: E402
    CLUB_GZ,
    merge_archive_posts,
    parse_archive_markdown,
    write_archive_gzip,
)
from biaoke_charts import (  # noqa: E402
    build_chart_index,
    load_name_map,
    valid_stock_ids,
    write_chart_index,
)

DRIVE = "/tmp/biaoke-drive"
CATALOG = "/tmp/biaoke-imgs/all/catalog_raw.json"


def _read(path: str) -> str:
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def main() -> int:
    public = parse_archive_markdown(_read(os.path.join(DRIVE, "public1709.md")))
    club20 = parse_archive_markdown(_read(os.path.join(DRIVE, "club20.md")))
    club72 = parse_archive_markdown(_read(os.path.join(DRIVE, "club72.md")))
    if int(public.get("n") or 0) < 1700:
        raise SystemExit("public n < 1700")
    club = merge_archive_posts(club20, club72)
    club["club"] = True
    club["source"] = "drive-club"
    if int(club.get("n") or 0) < 92:
        raise SystemExit("club n < 92")
    write_archive_gzip(public)
    write_archive_gzip(club, CLUB_GZ)
    with open(CATALOG, encoding="utf-8") as fh:
        catalog = json.load(fh)
    db = os.path.join(ROOT, "data", "wayne_market.db")
    posts = list(public.get("posts") or []) + list(club.get("posts") or [])
    blob = build_chart_index(
        catalog,
        posts=posts,
        name_to_sid=load_name_map(db),
        valid_ids=valid_stock_ids(db),
    )
    if int(blob.get("n") or 0) != 341:
        raise SystemExit("chart n=%s want 341" % blob.get("n"))
    write_chart_index(blob)
    print(
        "public",
        public.get("n"),
        public.get("replies"),
        "club",
        club.get("n"),
        club.get("replies"),
        "charts",
        blob.get("n"),
        blob.get("sources"),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
