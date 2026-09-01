"""LINE 轉傳純文字排版：直向排列、不含網址（避免奇摩預覽卡）。"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

# 海選／當沖轉 LINE 共用區隔線（全形，手機上清楚）
LINE_SHARE_SEP = "────────────────"

# bucket_key → (標題, 副標；與 Telegram 海選 SCREEN_PUSH_SPECS 一致)
LINE_BUCKET_META: Dict[str, tuple] = {
    "leave_zero": ("起漲", "高低卡獲利剛離零（昨0.0～0.1%，今≤5%；排除明顯空頭）"),
    "golden_buy": ("黃金買點", "60低＋獲利≈0＋月乖離<-10%（排除下坡）"),
    "revenue_cross": ("優先看", "營收轉強 × 量價突破"),
    "select_01": ("周帶量", "突破5日高＋60日量比≥2"),
    "half_year_high": ("半年高", "收盤創120日新高且量比≥2.5"),
    "select_02": ("站上季線", "昨收在季線下、今日站上季線"),
    "select_03": ("止跌", "月低附近有人接、量比≥1、今日翻紅"),
    "day_trade": ("當沖", "盤中漲幅2%～8.5%"),
    "overnight": ("隔日沖", "尾盤強勢紅K"),
}

# 起漲／黃金買點：表頭下多一行白話說明（避免跟決策卡欄位混淆）
LINE_BUCKET_HELP: Dict[str, str] = {
    "leave_zero": "說明：決策卡「獲利」格剛轉正；要趨勢向上或站穩月線，明顯空頭不列",
    "golden_buy": "說明：60日低＋超跌觀察名單；候選而已，不是今天必買",
}


def line_bucket_header(bucket_key: str, count: int) -> str:
    title, hint = LINE_BUCKET_META.get(bucket_key, (bucket_key, ""))
    lines: List[str] = []
    if hint:
        lines.append(f"＝＝{title}｜{hint}＝＝")
    else:
        lines.append(f"＝＝{title}＝＝")
    help_line = LINE_BUCKET_HELP.get(bucket_key, "")
    if help_line:
        lines.append(help_line)
    lines.append(f"共 {count} 檔")
    return "\n".join(lines)


def line_stock_headline(
    rank: int,
    stock_id: str,
    stock_name: str = "",
    db_path: Optional[str] = None,
) -> str:
    """單行標題：股名＋代號（不含網址，避免 LINE 底部預覽卡）。"""
    del db_path  # 保留參數以相容既有呼叫
    sid = str(stock_id or "").strip()
    name = str(stock_name or "").strip()
    label = f"{name} ({sid})" if name else sid
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
    """一檔股票：每項資訊獨立一行，方便 LINE 手機閱讀。"""
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

    lines = [
        line_stock_headline(rank, sid, sname, db_path),
        f"格局：{regime_fn(item)}",
        f"收　{px_fn(item.get('close'))}　{pct_fn(item.get('pct_change'))}",
        f"量　{vol:,}張　量比　{q_s}",
    ]
    if to_s:
        lines.append(f"額　{to_s}")

    lines.append(f"均線　月　{px_fn(item.get('ma20'))}　季　{px_fn(item.get('ma60'))}")
    lines.append(f"法人　{chip_fn(item)}")

    notices = notice_fn(item)
    if notices:
        lines.append("標記　" + "　".join(notices))

    if item.get("profit") is not None:
        lines.append(f"獲利　{item.get('profit')}%（近60日低點上來）")
    elif item.get("golden_buy"):
        lines.append(
            f"獲利　{item.get('profit_pct')}%　月乖離　{item.get('bias_monthly')}%（60低超跌）"
        )

    pat = str(item.get("pattern") or "")
    if pat:
        lines.append(f"型態　{pat}")
    if item.get("vol_rank_120"):
        lines.append(f"120量　第{int(item['vol_rank_120'])}名")

    for plan_line in plan_fn(item):
        lines.append(plan_line.replace("　", " ").strip())

    industry = str(item.get("industry_plain") or "").strip()
    if industry:
        lines.append("產業說明")
        for chunk in _wrap_plain_lines(industry, width=28):
            lines.append(f"　{chunk}")

    return "\n".join(lines)


def _wrap_plain_lines(text: str, width: int = 28) -> List[str]:
    """產業說明等長文：切成適合 LINE 手機寬度的行。"""
    raw = re.sub(r"\s+", " ", str(text or "").strip())
    if not raw:
        return []
    out: List[str] = []
    while raw:
        if len(raw) <= width:
            out.append(raw)
            break
        cut = raw.rfind(" ", 0, width + 1)
        if cut < width // 2:
            cut = width
        out.append(raw[:cut].strip())
        raw = raw[cut:].strip()
    return out


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
