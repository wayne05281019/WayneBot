# -*- coding: utf-8 -*-
"""Telegram 文字排版：標籤固定寬、區塊之間空一行。"""
from __future__ import annotations

from typing import List


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


def kv_compact(label: str, value) -> str:
    """標籤：內容（不補寬欄），長文換行從左緣起，氣泡不撐寬。"""
    return f"{html_escape(label)}：{html_escape(value)}"


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


def html_qty_tight(n, unit: str = "張", signed: bool = True) -> str:
    """數字跟單位同一格，氣泡窄時「張」不會被甩到下一行。"""
    try:
        v = int(round(float(n or 0)))
    except (TypeError, ValueError):
        v = 0
    if signed:
        body = f"0{unit}" if v == 0 else f"{v:+,}{unit}"
    else:
        body = f"{v:,}{unit}"
    return f"<code>{html_escape(body)}</code>"


def html_pct_tight(pct) -> str:
    try:
        p = float(pct)
    except (TypeError, ValueError):
        return "<code>—</code>"
    return f"<code>{html_escape(f'{p:+.1f}%')}</code>"


def html_metrics_tight(*parts: str) -> str:
    """多個數字緊湊同一格，資金移動等長文不撐寬氣泡。"""
    body = " ".join(str(p) for p in parts if p not in (None, ""))
    return f"<code>{html_escape(body)}</code>"


def html_code_join(*parts: str) -> str:
    """多個數字同一 <code>，長文才不會因為 entity 太多有的橘有的黑。"""
    body = "　".join(str(p) for p in parts if p not in (None, ""))
    return f"<code>{html_escape(body)}</code>"


def section_eq(title: str) -> str:
    """區塊標題前後 ==，跟海選分類同一種認法。"""
    return f"<b>== {html_escape(title)} ==</b>"


def _plain_num(n, decimals: int = 0, signed: bool = True) -> str:
    try:
        v = float(n or 0)
    except (TypeError, ValueError):
        return "—"
    if decimals <= 0:
        return f"{v:+,.0f}" if signed else f"{v:,.0f}"
    return f"{v:+,.{decimals}f}" if signed else f"{v:,.{decimals}f}"


def html_num_paren(main: str, pct, main_w: int = 8, *, compact: bool = False) -> str:
    """主數字與（％）同一 <code>：不拆行，各列的（對齊。"""
    try:
        right = f"{float(pct):+.1f}%"
    except (TypeError, ValueError):
        right = "—"
    left = str(main)
    if compact:
        return f"<code>{html_escape(left + '（' + right + '）')}</code>"
    pad = max(0, int(main_w) - len(left))
    return f"<code>{html_escape((' ' * pad) + left + '（' + right + '）')}</code>"


def html_last_move(last, change, pct, price_w: int = 8, *, compact: bool = False) -> str:
    """現價＋漲跌同一 <code>，▲ 與（％）不拆到下一行。"""
    try:
        px = f"{float(last):,.2f}"
    except (TypeError, ValueError):
        px = "—"
    try:
        d, p = float(change), float(pct)
    except (TypeError, ValueError):
        return f"<code>{html_escape(px.rjust(int(price_w)) if not compact else px)}</code>"
    if abs(d) < 0.005 and abs(p) < 0.005:
        move = "0.00（0.00%）"
    else:
        arrow = "▲" if d > 0 else "▼"
        move = f"{arrow}{abs(d):.2f}（{p:+.2f}%）"
    if compact:
        return f"<code>{html_escape(px + ' ' + move)}</code>"
    px = px.rjust(int(price_w))
    return f"<code>{html_escape(px + ' ' + move)}</code>"


def qty_text(n, unit: str = "張", signed: bool = True) -> str:
    try:
        v = int(round(float(n or 0)))
    except (TypeError, ValueError):
        v = 0
    if signed:
        return f"0{unit}" if v == 0 else f"{v:+,}{unit}"
    return f"{v:,}{unit}"


def pct_text(pct) -> str:
    try:
        return f"{float(pct):+.1f}%"
    except (TypeError, ValueError):
        return "—"


DASH_LINE = "┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈"


def join_dashed(*blocks: str) -> str:
    """區塊之間上虛線，資金移動這種長文才分得開。"""
    return join_sections(*blocks, sep=f"\n{DASH_LINE}\n")


def html_price(p, width: int = 9, *, compact: bool = False) -> str:
    """現價／成本對齊，不含單位（元接在後面或省略）。"""
    try:
        v = float(p)
    except (TypeError, ValueError):
        return "<code>—</code>" if compact else f"<code>{'—'.rjust(int(width))}</code>"
    body = f"{v:,.2f}"
    if compact:
        return f"<code>{html_escape(body)}</code>"
    return f"<code>{html_escape(body.rjust(int(width)))}</code>"


def html_money(n, width: int = 11, signed: bool = True, *, compact: bool = False) -> str:
    """帳戶金額：總資產／現金／損益。"""
    try:
        v = float(n or 0)
    except (TypeError, ValueError):
        v = 0.0
    if signed:
        body = f"{v:+,.0f}"
    else:
        body = f"{v:,.0f}"
    if compact:
        return f"<code>{html_escape(body)}</code>"
    return f"<code>{html_escape(body.rjust(int(width)))}</code>"


def html_pct(pct, width: int = 7) -> str:
    try:
        p = float(pct)
    except (TypeError, ValueError):
        return f"<code>{'—'.rjust(int(width))}</code>%"
    body = f"{p:+.1f}".rjust(int(width))
    return f"<code>{html_escape(body)}</code>%"


def price_change(close, pct, yesterday=None):
    """現價相對昨收差幾元。有昨收直接減；否則用漲跌％反推。"""
    try:
        y = float(yesterday) if yesterday not in (None, "", 0, 0.0) else None
    except (TypeError, ValueError):
        y = None
    if y and y > 0:
        try:
            return round(float(close) - y, 2)
        except (TypeError, ValueError):
            return None
    try:
        c, p = float(close), float(pct)
    except (TypeError, ValueError):
        return None
    if p == -100:
        return None
    yest = c / (1.0 + p / 100.0)
    return round(c - yest, 2)


def html_move(change, pct) -> str:
    """奇摩式漲跌：先金額再％。下跌 ▼ 5.50（-3.05%），上漲 ▲。"""
    try:
        d = float(change)
        p = float(pct)
    except (TypeError, ValueError):
        return "—"
    if abs(d) < 0.005 and abs(p) < 0.005:
        return html_escape("0.00（0.00%）")
    arrow = "▲" if d > 0 else "▼"
    body = f"{arrow} {abs(d):.2f}（{p:+.2f}%）"
    return f"<b>{html_escape(body)}</b>"


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


def html_quote_move(
    pct,
    chg=None,
    *,
    pts_decimals: int = 2,
    width: int = 26,
    compact: bool = False,
) -> str:
    """指數／期貨漲跌：整段放進等寬 <code>，手機不會從中間斷行。"""
    if pct is None and chg is None:
        body = "—"
    else:
        try:
            p = float(pct) if pct is not None else None
        except (TypeError, ValueError):
            p = None
        if p is None:
            body = "—"
        else:
            pct_s = f"{p:+.2f}%"
            if chg is not None:
                try:
                    c = float(chg)
                    body = f"{pct_s}（{c:+.{pts_decimals}f}點）"
                except (TypeError, ValueError):
                    body = pct_s
            else:
                body = pct_s
    if body == "—":
        return "<code>—</code>"
    if compact or width <= 0:
        return f"<code>{html_escape(body)}</code>"
    return f"<code>{html_escape(str(body).rjust(int(width)))}</code>"


def html_level_pct(level, pct, *, level_decimals: int = 2, width: int = 22, compact: bool = False) -> str:
    """VIX 等：水位＋（漲跌幅）同一等寬欄。"""
    if level is None:
        return "<code>—</code>"
    try:
        lv = float(level)
    except (TypeError, ValueError):
        return "<code>—</code>"
    base = f"{lv:.{level_decimals}f}"
    if pct is None:
        body = base
    else:
        try:
            body = f"{base}（{float(pct):+.2f}%）"
        except (TypeError, ValueError):
            body = base
    if compact or width <= 0:
        return f"<code>{html_escape(body)}</code>"
    return f"<code>{html_escape(str(body).rjust(int(width)))}</code>"


def aligned_rows(rows, label_width: int = 8) -> str:
    """多列標籤＋數值，每列獨立一行、標籤對齊。"""
    lines = []
    for label, value in rows:
        if not label:
            continue
        val = value if isinstance(value, str) and ("<" in value or "&" in value) else html_escape(value)
        lines.append(kv_html(str(label), val, width=int(label_width)))
    return "\n".join(lines)


def aligned_block(title: str, rows, label_width: int = 8) -> str:
    """區塊標題（==）＋對齊表；標題與內文之間空一行。"""
    body = aligned_rows(rows, label_width=label_width)
    if not title:
        return body
    if not body:
        return section_eq(title)
    return f"{section_eq(title)}\n{body}"


def headline_lines(*parts: str) -> str:
    """標題資訊分行，避免擠成一段難讀的長句。"""
    return "\n".join(str(p) for p in parts if p is not None and str(p).strip())


def chunk_telegram_text(text: str, limit: int = 3500) -> List[str]:
    if not text:
        return []
    return [text[i : i + limit] for i in range(0, len(text), limit)]


def chunk_telegram_html(html: str, limit: int = 3500) -> List[str]:
    """依 </blockquote> 或換行切開，避免把 <a> 切成半截導致 Telegram parse 失敗。"""
    if not html:
        return []
    if len(html) <= limit:
        return [html]
    chunks: List[str] = []
    rest = html
    close = "</blockquote>"
    while rest:
        if len(rest) <= limit:
            chunks.append(rest)
            break
        cut = rest.rfind(close, 0, limit)
        if cut != -1:
            cut += len(close)
        else:
            cut = rest.rfind("\n", 0, limit)
            if cut < 1:
                cut = limit
        chunks.append(rest[:cut])
        rest = rest[cut:].lstrip("\n")
    return [c for c in chunks if c]
