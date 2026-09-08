"""LINE 轉傳純文字排版：直向對齊、產業可跨行；奇摩走自家 /y/ 避免大圖預覽。"""
from __future__ import annotations

import html as html_lib
import re
from typing import Any, Dict, List, Optional, Tuple

# 態度／做法列：LINE 純文字上不了色；中轉頁 HTML 與 PNG 用這組紅。
STANCE_RED = "#c41e3a"
STANCE_RED_RGB = (196, 30, 58)
STANCE_LABEL = "態度"

# 手機 LINE 氣泡約 17～19 個中文字。標籤 2 字＋全形空白後，數值最多 14 字。
# 用電腦寬螢幕對齊會看起來整齊，貼到手機就被 LINE 再折一次，直向會歪。
LINE_PHONE_WRAP = 14
LINE_PHONE_LINE_MAX = 18

# 海選／當沖轉 LINE 共用區隔線（全形，配合手機氣泡寬）
LINE_SHARE_SEP = "────────────"

# bucket_key → (標題, 副標；與 Telegram 海選 SCREEN_PUSH_SPECS 一致)
LINE_BUCKET_META: Dict[str, tuple] = {
    "leave_zero": ("黃金買點", "高低卡獲利實綠／雙綠脫離（今≤5%；排除明顯空頭）"),
    "golden_buy": ("重點觀察", "60低＋獲利≈0＋月乖離<-10%（可收下坡末端）"),
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


def is_stance_line(ln: str) -> bool:
    """舊稿「態度」列；新稿態度貼在格局／黃金買點旁邊。"""
    s = str(ln or "")
    return s.startswith(_pad_label(STANCE_LABEL))


def _geju_stance_split(ln: str) -> Optional[Tuple[str, str]]:
    """格局　黃金買點　今天先看表，先等 → (左黑, 右紅)。沒有態度就 None。"""
    pad = _pad_label("格局") + "　"
    s = str(ln or "")
    if not s.startswith(pad):
        return None
    val = s[len(pad) :]
    if "　" not in val:
        return None
    left, right = val.split("　", 1)
    if not str(right or "").strip():
        return None
    return pad + left + "　", right


def colored_line_segments(ln: str, *, in_stance_cont: bool) -> Tuple[List[Tuple[str, bool]], bool]:
    """(文字, 是否紅字) 片段；格局列黃金買點後的態度＋其折行延續畫紅。"""
    s = str(ln or "")
    split = _geju_stance_split(s)
    if split:
        left, right = split
        return [(left, False), (right, True)], True
    if s.startswith(_pad_label("格局")):
        return [(s, False)], True
    if is_stance_line(s) or (in_stance_cont and s.startswith("　　　")):
        return [(s, True)], True
    return [(s, False)], False


def _chip_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def hydrate_line_share_item(
    item: Dict[str, Any],
    db_path: Optional[str] = None,
) -> Dict[str, Any]:
    """LINE 稿對齊介紹圖／三大法人表：決策卡沒有 T86 欄時改讀庫內最近完整日。

    決策卡 payload 沒有 foreign_net；先前直接 _chip_plain 會印出全 0。
    """
    out = dict(item or {})
    if out.get("pct_change") is None and out.get("change_pct") is not None:
        out["pct_change"] = out["change_pct"]
    if out.get("profit") is None:
        if out.get("gain_pct") is not None:
            out["profit"] = out["gain_pct"]
        elif out.get("profit_pct") is not None:
            out["profit"] = out["profit_pct"]
    if out.get("ma60") is None and out.get("ma60s") is not None:
        out["ma60"] = out["ma60s"]
    if not str(out.get("quote_date") or "").strip():
        out["quote_date"] = str(out.get("latest_date") or out.get("db_as_of") or "")
    keys = ("foreign_net", "trust_net", "dealer_net")
    try:
        from wayne_db import payload_is_emerging

        skip_chips = payload_is_emerging(out)
    except Exception:
        skip_chips = False
    missing = any(k not in out for k in keys)
    item_has = any(_chip_int(out.get(k)) for k in keys)
    sid = str(out.get("stock_id") or out.get("code") or "").strip()
    if db_path and sid and not skip_chips and (missing or not item_has):
        try:
            from chip_tape import last_complete_chip_nets

            nets = last_complete_chip_nets(db_path, sid, str(out.get("quote_date") or ""))
        except Exception:
            nets = None
        if nets:
            db_has = any(_chip_int(nets.get(k)) for k in keys)
            if db_has or missing:
                for k in keys:
                    out[k] = _chip_int(nets.get(k))
                if nets.get("quote_date") and not str(out.get("quote_date") or "").strip():
                    out["quote_date"] = str(nets.get("quote_date") or "")
    return out


def _quote_md(item: Dict[str, Any]) -> str:
    """近一日行情日：MM-DD；沒日期就空。"""
    raw = str(
        item.get("quote_date")
        or item.get("latest_date")
        or item.get("db_as_of")
        or ""
    ).replace("-", "")
    if len(raw) >= 8 and raw[:8].isdigit():
        return f"{raw[4:6]}-{raw[6:8]}"
    return ""


def _line_chip_value(item: Dict[str, Any], chip_fn) -> str:
    """T86 最近一筆完整交易日買賣超張數（與該列 OHLC 同一天）。"""
    body = str(chip_fn(item) or "").strip()
    tag = "近一日"
    md = _quote_md(item)
    if md:
        tag = f"近一日　{md}"
    return f"{tag}　{body}" if body else tag


def _line_profit_value(item: Dict[str, Any]) -> str:
    """獲利＝相對近 60 個日曆日收盤最低上來的幅度。"""
    pct = item.get("profit")
    if pct is None:
        pct = item.get("profit_pct")
    if pct is None:
        return ""
    bits = [f"{pct}%", "60日低上來"]
    try:
        from decision_card_signals import ma_matches_price

        bias = item.get("bias_monthly")
        if (
            item.get("golden_buy")
            and bias is not None
            and ma_matches_price(item.get("close"), item.get("ma20"))
        ):
            bits.append(f"月乖離　{bias}%")
    except Exception:
        if item.get("golden_buy") and item.get("bias_monthly") is not None:
            bits.append(f"月乖離　{item.get('bias_monthly')}%")
    return "　".join(bits)


def _line_stance_pair(item: Dict[str, Any]) -> Tuple[str, str]:
    """這一檔今天的態度＋該怎麼做（人話，不是下單指令）。"""
    from decision_card_signals import card_daily_stance, stance_explain

    title = str(item.get("stance") or "").strip()
    kind = str(item.get("stance_kind") or "").strip()
    if not title:
        profit = item.get("profit")
        if profit is None:
            profit = item.get("profit_pct") or 0
        alert = str(item.get("alert") or item.get("預警") or "")
        if not alert and item.get("at_60_low"):
            alert = "60低"
        hl = str(item.get("hl") or item.get("hi_lo") or item.get("高低") or "")
        title, kind = card_daily_stance(
            profit_pct=profit,
            alert=alert,
            hl=hl,
            temp=item.get("temp") or item.get("temp_num") or item.get("temperature") or 0,
            trend_note=str(item.get("trend_note") or item.get("升降註") or ""),
            bias=item.get("bias") or item.get("bias_monthly") or 0,
            badges=item.get("badges") or [],
        )
    sell = str(item.get("sell_note") or "").strip()
    explain = stance_explain(kind or "wait", sell_note=sell, card=item, surface="list")
    return title, explain


def _line_stance_value(item: Dict[str, Any]) -> str:
    title, explain = _line_stance_pair(item)
    title = str(title or "").strip()
    explain = str(explain or "").strip()
    if title and explain:
        if explain.startswith(title):
            return explain
        return f"{title}。{explain}"
    return title or explain


def line_plain_to_html(text: str) -> str:
    """轉 LINE 中轉頁：黃金買點旁邊的態度紅字；其餘原樣跳脫。"""
    out: List[str] = []
    in_stance = False
    for ln in str(text or "").split("\n"):
        segs, in_stance = colored_line_segments(ln, in_stance_cont=in_stance)
        parts: List[str] = []
        for chunk, red in segs:
            esc = html_lib.escape(chunk)
            parts.append(f'<span class="stance">{esc}</span>' if red else esc)
        out.append("".join(parts))
    return "<br>\n".join(out)


def _kv_lines(label: str, value: str, *, wrap: int = LINE_PHONE_WRAP, keep_units: bool = False) -> List[str]:
    """一列一個單位；值太長就在單位內折行，延續行對齊數值欄。預設依手機氣泡寬。"""
    val = str(value or "").strip()
    if not val:
        return []
    prefix = _pad_label(label) + "　"
    indent = "　　　"
    chunks = _wrap_unit_lines(val, width=wrap) if keep_units else _wrap_plain_lines(val, width=wrap)
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
    bucket_key: str = "",
    regime_fn=None,
    pct_fn=None,
    px_fn=None,
    chip_fn=None,
    notice_fn=None,
    plan_fn=None,
) -> str:
    """一檔直向：股名、格局（黃金買點旁接今日態度）、收盤／量能／金額、均線、法人、獲利、產業。"""
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

    item = hydrate_line_share_item(item, db_path)
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

    close = item.get("close")
    if close is None:
        close = item.get("last_close")
    pct = item.get("pct_change")
    if pct is None:
        pct = item.get("change_pct")

    lines = [line_stock_headline(rank, sid, sname, db_path)]
    bucket_title = ""
    key = str(bucket_key or item.get("bucket_key") or "").strip()
    if key:
        bucket_title = str(LINE_BUCKET_META.get(key, (key, ""))[0] or "").strip()
    regime = str(regime_fn(item) or "").strip()
    geju_left = bucket_title or regime
    title, explain = _line_stance_pair(item)
    geju_val = geju_left
    if title:
        geju_val = f"{geju_left}　{title}" if geju_left else title
    if geju_val:
        # 格局＋態度要同一行：貼近20日低　漲多了，今天別追 約 16 字
        lines.extend(_kv_lines("格局", geju_val, wrap=18, keep_units=True))
    note = str(explain or "").strip()
    if note and title and note.startswith(title):
        note = note[len(title) :].lstrip("。").strip()
    if note:
        for chunk in _wrap_plain_lines(note, LINE_PHONE_WRAP):
            lines.append("　　　" + chunk)
    lines.extend(_kv_lines("收盤", f"{px_fn(close)}　{pct_fn(pct)}"))
    lines.extend(
        _kv_lines("量能", f"{vol:,}張　量比{q_s}", wrap=LINE_PHONE_WRAP, keep_units=True)
    )
    if to_s:
        lines.extend(_kv_lines("金額", to_s))
    ma20_s = px_fn(item.get("ma20"))
    ma60_s = px_fn(item.get("ma60"))
    hide_ma = False
    try:
        from decision_card_signals import ma_matches_price

        c = item.get("close")
        if c not in (None, "") and item.get("ma20") not in (None, "", 0):
            hide_ma = not ma_matches_price(c, item.get("ma20"))
        if not hide_ma and c not in (None, "") and item.get("ma60") not in (None, "", 0):
            hide_ma = not ma_matches_price(c, item.get("ma60"))
    except Exception:
        hide_ma = False
    if not hide_ma:
        lines.extend(_kv_lines("均線", f"月　{ma20_s}"))
        lines.append("　　　" + f"季　{ma60_s}")
    lines.extend(_line_chip_kv_lines(item, chip_fn))
    notices = notice_fn(item)
    if notices:
        lines.extend(_kv_lines("標記", "　".join(notices), keep_units=True))
    profit_val = _line_profit_value(item)
    if profit_val:
        lines.extend(_kv_lines("獲利", profit_val, keep_units=True))
    pat = str(item.get("pattern") or "")
    if pat:
        lines.extend(_kv_lines("型態", pat))
    if item.get("vol_rank_120"):
        lines.extend(_kv_lines("量排", f"120日第{int(item['vol_rank_120'])}名"))
    for plan_line in plan_fn(item):
        raw = str(plan_line or "").strip()
        if "　" in raw:
            lab, rest = raw.split("　", 1)
            lines.extend(_kv_lines(lab, rest))
        else:
            for chunk in _wrap_plain_lines(raw, width=LINE_PHONE_WRAP):
                lines.append(chunk)
    industry = str(item.get("industry_plain") or "").strip()
    if industry:
        lines.extend(_kv_lines("產業", industry))
    try:
        from stock_links import yahoo_hop_url

        hop = yahoo_hop_url(sid)
    except Exception:
        hop = ""
    if hop:
        # 網址單獨一列，避免手機把「奇摩　https://…」折爛；走 /y/ 才不會抓奇摩大圖
        lines.append(_pad_label("奇摩"))
        lines.append(hop)
    return "\n".join(lines)


def _line_chip_kv_lines(item: Dict[str, Any], chip_fn) -> List[str]:
    """法人：近一日日期一列，外資／投信／自營各一列，手機才不會從數字中間折。"""
    try:
        from wayne_db import payload_is_emerging

        if payload_is_emerging(item):
            return []
    except Exception:
        pass
    tag = "近一日"
    md = _quote_md(item)
    if md:
        tag = f"近一日　{md}"
    out = _kv_lines("法人", tag)
    body = str(chip_fn(item) or "").strip()
    for part in body.split("　"):
        bit = part.strip()
        if bit:
            out.append("　　　" + bit)
    return out


def _wrap_plain_lines(text: str, width: int = LINE_PHONE_WRAP) -> List[str]:
    """產業等長文折行；保留全形空白當欄位間距，不把單位擠成半形空格。"""
    from tg_layout import wrap_cjk_lines

    raw = str(text or "").replace("\n", "").strip()
    raw = re.sub(r"[ \t]+", " ", raw)
    return wrap_cjk_lines(raw, width, unit="chars")


def _wrap_unit_lines(text: str, width: int = 22) -> List[str]:
    """只在全形空白切開，避免法人「投信+3,200張」被從中間折斷。"""
    bits = [b for b in str(text or "").replace("\n", "").split("　") if b]
    if not bits:
        return []
    lines: List[str] = []
    cur = ""
    for bit in bits:
        cand = bit if not cur else f"{cur}　{bit}"
        if cur and len(cand) > width:
            lines.append(cur)
            cur = bit
        else:
            cur = cand
    if cur:
        lines.append(cur)
    return lines


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
        parts.append(format_line_stock_block(it, n, db_path, bucket_key=bucket_key))
    return "\n".join(parts)
