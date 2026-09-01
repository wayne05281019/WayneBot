"""LINE 轉傳純文字排版：整齊、少斷行、股名帶奇摩連結。"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

# 海選／當沖轉 LINE 共用區隔線（全形，手機上清楚）
LINE_SHARE_SEP = "────────────────"

# bucket_key → (標題, 右側說明)
LINE_BUCKET_META: Dict[str, tuple] = {
    "leave_zero": ("起漲", "高低卡獲利剛離零"),
    "golden_buy": ("黃金買點", "60低＋獲利≈0＋月乖離超跌"),
    "revenue_cross": ("優先看", "營收轉強×量價突破"),
    "select_01": ("周帶量", "突破5日高＋60日量比≥2"),
    "half_year_high": ("半年高", "收盤創120日新高且量比≥2.5"),
    "select_02": ("站上季線", "昨收在季線下、今日站上季線"),
    "select_03": ("止跌", "月低有人接、量比≥1、今日翻紅"),
    "select_04": ("雙綠", "高低卡20低剛脫離"),
    "day_trade": ("當沖", "盤中漲幅2%～8.5%"),
    "overnight": ("隔日沖", "尾盤強勢紅K"),
}


def line_bucket_header(bucket_key: str, count: int) -> str:
    title, hint = LINE_BUCKET_META.get(bucket_key, (bucket_key, ""))
    if hint:
        return f"【{title}】{hint}｜{count}檔"
    return f"【{title}】｜{count}檔"


def line_stock_headline(
    rank: int,
    stock_id: str,
    stock_name: str = "",
    db_path: Optional[str] = None,
) -> str:
    """單行標題：股名＋代號＋奇摩連結（LINE 內點連結開手機奇摩）。"""
    from stock_links import line_yahoo_quote_url

    sid = str(stock_id or "").strip()
    name = str(stock_name or "").strip()
    label = f"{name}({sid})" if name else sid
    url = line_yahoo_quote_url(sid, db_path)
    if url:
        return f"{rank}. {label} {url}"
    return f"{rank}. {label}"


def format_line_stock_block(
    item: Dict[str, Any],
    rank: int,
    db_path: Optional[str] = None,
    *,
    regime_fn=None,
    pct_fn=None,
    px_fn=None,
    chip_fn=None,
    notice_fn=None,
    plan_fn=None,
) -> str:
    """一檔股票：重點合併成少行，方便 LINE 閱讀。"""
    from screening_engine import (
        _chip_plain,
        _pct_str,
        _px_str,
        _regime_label,
        _safety_plan_plain,
        _share_notices_plain,
    )

    regime_fn = regime_fn or _regime_label
    pct_fn = pct_fn or _pct_str
    px_fn = px_fn or _px_str
    chip_fn = chip_fn or _chip_plain
    notice_fn = notice_fn or _share_notices_plain
    plan_fn = plan_fn or _safety_plan_plain

    sid = str(item.get("stock_id") or item.get("code") or "")
    sname = str(item.get("stock_name") or item.get("name") or "")

    q = item.get("q60r")
    try:
        q_s = f"{float(q):.2f}×" if q is not None else "—"
    except (TypeError, ValueError):
        q_s = "—"
    to_k = item.get("turnover_k")
    try:
        to_s = f"{float(to_k) / 1000.0:.1f}億" if to_k is not None else ""
    except (TypeError, ValueError):
        to_s = ""

    vol = int(item.get("volume") or 0)
    line_quote = (
        f"格局 {regime_fn(item)} "
        f"收 {px_fn(item.get('close'))} {pct_fn(item.get('pct_change'))} "
        f"量 {vol:,}張 量比 {q_s}"
    )
    if to_s:
        line_quote += f" 額 {to_s}"

    lines = [
        line_stock_headline(rank, sid, sname, db_path),
        line_quote,
        f"均線 月 {px_fn(item.get('ma20'))} 季 {px_fn(item.get('ma60'))}",
        f"法人 {chip_fn(item)}",
    ]

    notices = notice_fn(item)
    if notices:
        lines.append("標記 " + " ".join(notices))

    if item.get("profit") is not None:
        lines.append(f"獲利 {item.get('profit')}%（近60日低點上來）")
    elif item.get("golden_buy"):
        lines.append(
            f"獲利 {item.get('profit_pct')}% 月乖離 {item.get('bias_monthly')}%（60低超跌）"
        )

    pat = str(item.get("pattern") or "")
    if pat:
        lines.append(f"型態 {pat}")
    if item.get("vol_rank_120"):
        lines.append(f"120量 第{int(item['vol_rank_120'])}名")

    for plan_line in plan_fn(item):
        lines.append(plan_line.replace("　", " ").strip())

    return "\n".join(lines)


def format_line_bucket_body(
    items: List[Dict[str, Any]],
    bucket_key: str,
    db_path: Optional[str] = None,
) -> str:
    dict_items = [it for it in items if isinstance(it, dict)]
    if not dict_items:
        return ""
    parts = [line_bucket_header(bucket_key, len(dict_items))]
    for n, it in enumerate(dict_items, start=1):
        if n > 1:
            parts.append(LINE_SHARE_SEP)
        parts.append(format_line_stock_block(it, n, db_path))
    return "\n".join(parts)
