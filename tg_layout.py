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


def title_line(kind: str, code: str, name: str = "", extra: str = "") -> str:
    head = f"{html_escape(kind)}　<b>{html_escape(code)} {html_escape(name)}</b>".strip()
    if extra:
        return f"{head}\n{html_escape(extra)}"
    return head


def section(*rows: str) -> str:
    return "\n".join(r for r in rows if r)


def join_sections(*blocks: str) -> str:
    return "\n\n".join(b.strip("\n") for b in blocks if b and str(b).strip())
