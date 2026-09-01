"""海選整區 LINE：每檔產出介紹圖、高低決策卡、籌碼、產業說明。"""
from __future__ import annotations

import os
from typing import Any, Dict, List, Optional

from line_share_format import LINE_BUCKET_META, format_line_bucket_body


def render_line_share_pack(
    stock_id: str,
    db_path: str = None,
    charts_dir: str = None,
) -> Dict[str, Any]:
    """單檔圖文包（不含導航圖，較快）。"""
    from config import get_charts_dir, get_db_path
    from wayne_navigator import NavigatorEngine, render_decision_card_png, render_first_glance_png

    sid = str(stock_id or "").strip()
    db_path = db_path or get_db_path()
    charts_dir = charts_dir or get_charts_dir()
    os.makedirs(charts_dir, exist_ok=True)
    engine = NavigatorEngine(db_path)
    try:
        card = engine.get_decision_card(sid, lookback=20)
    except Exception as exc:
        return {"error": str(exc), "stock_id": sid}
    if card.get("error"):
        return {"error": card.get("error"), "stock_id": sid}
    tape = {}
    try:
        from chip_tape import build_tape

        tape = build_tape(db_path, sid) or {}
    except Exception:
        tape = {}
    sub = os.path.join(charts_dir, sid)
    os.makedirs(sub, exist_ok=True)
    glance = render_first_glance_png(
        sid, card, tape, os.path.join(sub, "glance.png"), db_path=db_path
    ) or ""
    card_png = render_decision_card_png(card, os.path.join(sub, "card.png")) or ""
    chips = ""
    try:
        from chips import generate_chips_image

        chips = generate_chips_image(sid, db_path, os.path.join(sub, "chips.png")) or ""
    except Exception:
        chips = ""
    industry = ""
    try:
        from industry_brief import format_industry_html

        industry = format_industry_html(sid, db_path) or ""
    except Exception:
        industry = ""
    return {
        "stock_id": sid,
        "stock_name": str(card.get("stock_name") or card.get("name") or ""),
        "glance": glance,
        "card": card_png,
        "chips": chips,
        "industry_html": industry,
        "card_data": card,
    }


def bucket_stock_rows(db_path: str, bucket_key: str, as_of: str = "") -> List[Dict[str, Any]]:
    from screen_sessions import load_bucket_rows

    rows = load_bucket_rows(db_path, bucket_key, as_of)
    out: List[Dict[str, Any]] = []
    for r in rows:
        sid = str(r.get("stock_id") or "").strip()
        if not sid:
            continue
        out.append(
            {
                "stock_id": sid,
                "stock_name": str(r.get("stock_name") or ""),
                "close": r.get("pick_close"),
                "chase_warning": r.get("chase_warning"),
            }
        )
    return out


def build_bucket_line_text(
    db_path: str,
    bucket_key: str,
    items: List[Dict[str, Any]],
    as_of: str,
) -> str:
    title, hint = LINE_BUCKET_META.get(bucket_key, (bucket_key, ""))
    body = format_line_bucket_body(items, bucket_key, db_path)
    if not body:
        return ""
    from line_hop import _date_slash

    head = f"WayneBot 海選【{title}】{hint}"
    if as_of:
        head += f"　{_date_slash(as_of)}"
    return f"{head}\n{body}"


def bucket_title(bucket_key: str) -> str:
    return LINE_BUCKET_META.get(bucket_key, (bucket_key, ""))[0]
