"""海選 LINE 轉寄：按鈕／連結走 /line/…，伺服器 302 直跳 line.me。"""
from __future__ import annotations

import html
import json
from typing import Dict, Optional
from urllib.parse import quote


LINE_PACKS = (
    ("night", "開 LINE・夜盤", "夜盤判斷"),
    ("layout", "開 LINE・起漲", "起漲與佈局"),
    ("trade", "開 LINE・短線", "短線說明"),
)
PACK_IDS = {p[0] for p in LINE_PACKS}


def line_share_href(text: str) -> str:
    """LINE 官方分享網址。"""
    return "https://line.me/R/share?text=" + quote(text or "", safe="")


def hop_redirect_for_text(text: str) -> Optional[str]:
    body = (text or "").strip()
    if not body:
        return None
    return line_share_href(body)


def render_line_redirect_html(text: str) -> str:
    """極簡備援頁：立刻跳 LINE（302 不可用時）。"""
    url = line_share_href(text or "")
    safe = html.escape(url, quote=True)
    payload = json.dumps(url, ensure_ascii=False)
    return (
        "<!DOCTYPE html><html><head>"
        '<meta charset="utf-8">'
        f'<meta http-equiv="refresh" content="0;url={safe}">'
        f"</head><body><script>location.replace({payload});</script></body></html>"
    )


def load_pack_text(db_path: str, pack_id: str, as_of: str = "") -> Dict[str, str]:
    from screen_sessions import load_line_pack

    return load_line_pack(db_path, pack_id, as_of)


def hop_stock_response(db_path: str, stock_id: str) -> Dict[str, str]:
    from screen_sessions import load_line_stock

    sid = str(stock_id or "").strip()
    if not sid:
        return {"redirect": None, "error": "缺少代號"}
    row = load_line_stock(db_path, sid)
    text = str((row or {}).get("text") or "").strip()
    if not text:
        return {"redirect": None, "error": f"查無 {sid}，請先按一次海選"}
    return {"redirect": hop_redirect_for_text(text)}


def hop_response(db_path: str, pack_id: str) -> Optional[Dict[str, str]]:
    pid = str(pack_id or "").strip()
    if not pid:
        return None
    row = load_pack_text(db_path, pid)
    text = str((row or {}).get("text") or "").strip() if row else ""
    if not text:
        return {"redirect": None, "error": "查無內容，請先按一次海選"}
    return {"redirect": hop_redirect_for_text(text)}


# 相容舊測試／呼叫
def render_line_hop_html(title: str, text: str) -> str:
    del title
    return render_line_redirect_html(text)
