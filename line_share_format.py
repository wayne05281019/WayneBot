"""LINE 轉傳純文字排版：直向對齊、產業可跨行；奇摩走自家 /y/ 避免大圖預覽。"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

# 海選／當沖轉 LINE 共用區隔線（全形，手機上清楚）
LINE_SHARE_SEP = "────────────────"

# bucket_key → (標題, 副標；與 Telegram 海選 SCREEN_PUSH_SPECS 一致)
LINE_BUCKET_META: Dict[str, tuple] = {
    "leave_zero": ("起漲", "高低卡獲利實綠／雙綠脫離（今≤5%；排除明顯空頭）"),
    "golden_buy": ("黃金買點", "60低＋獲利≈0＋月乖離<-10%（排除下坡）"),
    "revenue_cross": ("優先看", "營收轉強 × 量價突破"),
    "select_01": ("周帶量", "突破5日高＋60日量比≥2"),
    "half_year_high": ("半年高", "收盤創120日新高且量比≥2.5"),
    "select_02": ("站上季線", "昨收在季線下、今日站上季線"),
    "select_03": ("止跌", "月低附近有人接、量比≥1、今日翻紅"),
    "day_trade": ("當沖", "盤中漲幅2%～8.5%"),
    "overnight": ("隔日沖", "尾盤強勢紅K"),
}

def line_bucket_header(bucket_key: str, count: int) -> str:
    """LINE 只要分類名＋檔數；長副標／說明留在 Telegram。"""
    title, _hint = LINE_BUCKET_META.get(bucket_key, (bucket_key, ""))
    return f"＝＝{title}＝＝\n共 {count} 檔"


def line_stock_headline(
    rank: int,
    stock_id: str,
    stock_name: str = "",
    db_path: Optional[str] = None,
) -> str:
    """單行標題：股名＋代號（不含奇摩網址）。"""
    del db_path
    sid = str(stock_id or "").strip()
    name = str(stock_name or "").strip()
    label = f"{name} ({sid})" if name else sid
    return f"{rank}. {label}"


def _disp_w(text: str) -> int:
    return sum(2 if ord(ch) > 127 else 1 for ch in str(text or ""))


def _pad_label(label: str, width: int = 4) -> str:
    """標籤欄固定 2 個中文寬，後面數值才上下對齊。"""
    raw = str(label or "")
    extra = width - _disp_w(raw)
    while extra >= 2:
        raw += "　"
        extra -= 2
    if extra == 1:
        raw += " "
    return raw


def _kv_lines(label: str, value: str, *, wrap: int = 24) -> List[str]:
    """一列一個單位；值太長就在單位內折行，延續行對齊數值欄。"""
    val = str(value or "").strip()
    if not val:
        return []
    prefix = _pad_label(label) + "　"
    indent = "　　　"
    chunks = _wrap_plain_lines(val, width=wrap)
    if not chunks:
        return []
    out = [prefix + chunks[0]]
    out.extend(indent + c for c in chunks[1:])
    return out


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
    """一檔直向：股名、格局、收量額、均線、法人、獲利、產業。不要說明廢話。"""
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
        from fundamentals import format_yi

        to_s = format_yi(float(to_k), unit=False) if to_k is not None else ""
    except (TypeError, ValueError):
        to_s = ""

    vol = int(item.get("volume") or 0)

    lines = [line_stock_headline(rank, sid, sname, db_path)]
    lines.extend(_kv_lines("格局", regime_fn(item)))
    lines.extend(_kv_lines("收", f"{px_fn(item.get('close'))}　{pct_fn(item.get('pct_change'))}"))
    lines.extend(_kv_lines("量", f"{vol:,}張　量比　{q_s}"))
    if to_s:
        lines.extend(_kv_lines("額", to_s))
    lines.extend(_kv_lines("均線", f"月　{px_fn(item.get('ma20'))}　季　{px_fn(item.get('ma60'))}"))
    lines.extend(_kv_lines("法人", chip_fn(item)))
    notices = notice_fn(item)
    if notices:
        lines.extend(_kv_lines("標記", "　".join(notices)))
    if item.get("profit") is not None:
        lines.extend(_kv_lines("獲利", f"{item.get('profit')}%"))
    elif item.get("golden_buy"):
        lines.extend(
            _kv_lines("獲利", f"{item.get('profit_pct')}%　月乖離　{item.get('bias_monthly')}%")
        )
    pat = str(item.get("pattern") or "")
    if pat:
        lines.extend(_kv_lines("型態", pat))
    if item.get("vol_rank_120"):
        lines.extend(_kv_lines("量排", f"120日第{int(item['vol_rank_120'])}名"))
    for plan_line in plan_fn(item):
        raw = str(plan_line or "").strip()
        if "　" in raw:
            lab, rest = raw.split("　", 1)
            lines.extend(_kv_lines(lab, rest, wrap=22))
        else:
            for chunk in _wrap_plain_lines(raw, width=28):
                lines.append(chunk)
    industry = str(item.get("industry_plain") or "").strip()
    if industry:
        lines.extend(_kv_lines("產業", industry, wrap=24))
    try:
        from stock_links import yahoo_hop_url

        hop = yahoo_hop_url(sid)
    except Exception:
        hop = ""
    if hop:
        # 網址不折行；走自家 /y/ 代號，LINE 才不會抓奇摩大圖
        lines.append(_pad_label("奇摩") + "　" + hop)
    return "\n".join(lines)


def _wrap_plain_lines(text: str, width: int = 28) -> List[str]:
    """產業等長文折行；保留全形空白當欄位間距，不把單位擠成半形空格。"""
    from tg_layout import wrap_cjk_lines

    raw = str(text or "").replace("\n", "").strip()
    raw = re.sub(r"[ \t]+", " ", raw)
    return wrap_cjk_lines(raw, width, unit="chars")


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
