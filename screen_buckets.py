# -*- coding: utf-8 -*-
"""海選桶內部鍵 ↔ 話筒中文：唯一對照表。

內部鍵保留 leave_zero／golden_buy（庫與測試相容）：
- leave_zero ＝ 黃金買點（獲利剛離零，才是買點）
- golden_buy ＝ 還在零（60低超跌，只觀察不是買）

畫面／早報／AI 文案只准讀這裡，不准各檔自創「重點觀察／60低超跌」當主標。
「重點觀察」僅當舊別名辨識，不寫進新字串。
"""
from __future__ import annotations

from typing import Dict, Tuple

# 內部鍵 → 話筒主標（短、固定）
BUCKET_TITLE: Dict[str, str] = {
    "leave_zero": "黃金買點",
    "golden_buy": "還在零",
    "revenue_cross": "優先看",
    "select_01": "周帶量",
    "half_year_high": "半年高",
    "select_02": "站上季線",
    "select_03": "止跌",
    "day_trade": "當沖",
    "overnight": "隔日沖",
}

# 內部鍵 → 一句副標（觀察／買點講清楚）
BUCKET_HINT: Dict[str, str] = {
    "leave_zero": "買點＝剛離零可切入；還在零＝觀察不是買",
    "golden_buy": "60低＋獲利≈0＋月乖離超跌（觀察不是買）",
    "revenue_cross": "營收轉強 × 量價突破（須趨勢向上）",
    "select_01": "突破5日高＋60日量比≥2（須趨勢向上）",
    "half_year_high": "收盤創120日新高且量比≥2.5（須趨勢向上）",
    "select_02": "昨收在季線下、今日站上季線（須趨勢向上）",
    "select_03": "月低附近有人接、量比≥1、今日翻紅（須趨勢向上）",
    "day_trade": "盤中漲幅2%～8.5%",
    "overnight": "尾盤強勢紅K",
}

# 舊中文 → 內部鍵（讀舊文／舊 reason／使用者打字）
TITLE_ALIASES: Dict[str, str] = {
    "黃金買點": "leave_zero",
    "剛離零": "leave_zero",
    "剛脫離零": "leave_zero",
    "買點": "leave_zero",
    "還在零": "golden_buy",
    "重點觀察": "golden_buy",  # 舊名，只認不寫
    "60低超跌": "golden_buy",
    "優先看": "revenue_cross",
    "周帶量": "select_01",
    "周突破": "select_01",
    "半年高": "half_year_high",
    "站上季線": "select_02",
    "止跌": "select_03",
    "當沖": "day_trade",
    "隔日沖": "overnight",
    "隔夜": "overnight",
}

# 覆盤／早報統計列順序（key, 中文）
REVIEW_BUCKETS: Tuple[Tuple[str, str], ...] = tuple(
    (k, BUCKET_TITLE[k])
    for k in (
        "leave_zero",
        "golden_buy",
        "revenue_cross",
        "select_01",
        "select_02",
        "select_03",
        "day_trade",
        "overnight",
    )
)


def bucket_title(key: str) -> str:
    k = str(key or "").strip()
    if k in BUCKET_TITLE:
        return BUCKET_TITLE[k]
    # 已是中文主標
    if k in TITLE_ALIASES:
        return BUCKET_TITLE[TITLE_ALIASES[k]]
    return k


def bucket_key_from_label(label: str) -> str:
    s = str(label or "").strip()
    if s in BUCKET_TITLE:
        return s
    return TITLE_ALIASES.get(s, "")


def bucket_meta(key: str) -> Tuple[str, str]:
    k = str(key or "").strip()
    return BUCKET_TITLE.get(k, k), BUCKET_HINT.get(k, "")
