# -*- coding: utf-8 -*-
"""Telegram 文字排版：標籤固定寬、區塊之間空一行。"""
from __future__ import annotations


def html_escape(val) -> str:
    return (
        str(val if val is not None else "")
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def _disp_w(s: str) -> int:
    w = 0
    for ch in str(s):
        w += 2 if ord(ch) > 127 else 1
    return w


def pad_label(label: str, width: int = 8) -> str:
    """寬度以半形為 1、全形為 2；不足用全形空白補齊。"""
    raw = str(label)
    extra = width - _disp_w(raw)
    pad = ""
    while extra >= 2:
        pad += "　"
        extra -= 2
    if extra == 1:
        pad += " "
    return html_escape(raw) + pad


def kv(label: str, value, width: int = 10) -> str:
    return f"{pad_label(label, width)} {html_escape(value)}"


def kv_html(label: str, html_value, width: int = 10) -> str:
    """value 已是安全 HTML（例如 <code> 對齊數字）。"""
    return f"{pad_label(label, width)} {html_value}"


def html_qty(n, unit: str = "張", width: int = 9, signed: bool = True) -> str:
    """數字放進等寬 <code>，單位（張／%）接在後面，同一頁同一單位會切齊。"""
    try:
        v = int(round(float(n or 0)))
    except (TypeError, ValueError):
        v = 0
    if signed:
        body = "0" if v == 0 else f"{v:+,}"
    else:
        body = f"{v:,}"
    body = body.rjust(int(width))
    return f"<code>{html_escape(body)}</code>{html_escape(unit)}"


def html_pct(pct, width: int = 7) -> str:
    try:
        p = float(pct)
    except (TypeError, ValueError):
        return f"<code>{'—'.rjust(int(width))}</code>%"
    body = f"{p:+.1f}".rjust(int(width))
    return f"<code>{html_escape(body)}</code>%"


def title_line(kind: str, code: str, name: str = "", extra: str = "") -> str:
    head = f"{html_escape(kind)}　<b>{html_escape(code)} {html_escape(name)}</b>".strip()
    if extra:
        return f"{head}\n{html_escape(extra)}"
    return head


def section(*rows: str) -> str:
    return "\n".join(r for r in rows if r)


def stock_btn_label(code: str, name: str = "", max_bytes: int = 56) -> str:
    """海選／清單左鍵：代號＋股名。Telegram 按鈕上限 64 bytes。"""
    c = str(code or "").strip()
    n = str(name or "").strip()
    s = f"{c} {n}".strip() if n else c
    raw = s.encode("utf-8")
    while len(raw) > max_bytes and s:
        s = s[:-1].rstrip()
        raw = s.encode("utf-8")
    return s or c or "看這檔"


def join_sections(*blocks: str, sep: str = "\n\n") -> str:
    parts = [b.strip("\n") for b in blocks if b and str(b).strip()]
    return sep.join(parts)
