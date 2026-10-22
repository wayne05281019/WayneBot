# -*- coding: utf-8 -*-
"""06:30 早報 Option B：文字①環境＋最細夜盤＋加權精簡；文字②黃金買點＋紅箭。

圖（美股／台指電子盤／恐懼貪婪）由 main_runner._push_morning_session_cards 先寄，再寄文字。
輪動／月營收／雷達不進早報主輪。買訊公式不改。
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from tg_layout import DASH_LINE, join_sections, _html_plain


def _plain(html: str) -> str:
    return _html_plain(html or "")


def _outlook_from_screening(screening: Optional[Dict[str, Any]]) -> str:
    if not screening:
        return ""
    for part in screening.get("payload") or []:
        if isinstance(part, dict) and str(part.get("mark_key") or "") == "market":
            return str(part.get("html") or "").strip()
    msg = str(screening.get("message") or "")
    if "＝＝大盤狀況＝＝" in msg:
        head, _, rest = msg.partition("＝＝")
        if "＝＝" in rest:
            chunk, _, _ = rest.partition("＝＝")
            return ("＝＝" + chunk).strip()
    return ""


_DROP_ALERT_TAIL = (
    "不是從佈局名單刪掉，也不是叫你現在下單。",
)


def _early_alert_supplement_html(
    us_snap: Optional[Dict[str, Any]], *, db_path: str, outlook_html: str
) -> str:
    """大跌一早提醒：只留 outlook 沒有的判斷句／操作提醒，不重貼美股四大。"""
    if not us_snap:
        return ""
    try:
        from us_overnight import should_alert_us_drop, format_us_drop_alert
    except Exception:
        return ""
    if not should_alert_us_drop(us_snap):
        return ""
    alert = format_us_drop_alert(us_snap, db_path=db_path)
    if not alert.strip():
        return ""
    outlook_plain = _plain(outlook_html)
    keep: List[str] = []
    for block in re.split(r"\n\s*\n", alert.strip()):
        b = block.strip()
        if not b:
            continue
        # 早報砍冗尾：併進動作句即可，不另貼長免責
        if _DROP_ALERT_TAIL in _plain(b):
            b = b.replace(_DROP_ALERT_TAIL, "").rstrip()
            if not b.strip():
                continue
        p = _plain(b)
        if "一早提醒" in p:
            keep.append(b)
            continue
        if "06:30 海選" in p or "佈局先看高低卡" in p or "標少追" in p:
            keep.append(b)
            continue
        if "美股收盤偏弱" in p and b not in keep:
            keep.append(b)
            continue
        # 指數／VIX／期貨塊 outlook 通常已有，略過
        if any(k in p for k in ("道瓊", "標普", "那斯達克", "恐慌指數", "盤後期貨", "台積美股")):
            if any(k in outlook_plain for k in ("道瓊", "標普", "那斯達克", "恐慌指數")):
                continue
        if p and p not in outlook_plain and len(p) > 8:
            keep.append(b)
    if not keep:
        return ""
    return join_sections(*keep)


def _outlook_drop_short_nights(outlook: str, tw_brief: str) -> str:
    """夜盤只留加權研究詳細版；大盤狀況裡的短夜盤句（含比日盤／比現貨）拿掉。"""
    if not outlook.strip():
        return ""
    if not tw_brief.strip():
        return outlook.strip()
    bp = _plain(tw_brief)
    has_tx = "台指期夜盤" in bp
    has_te = "電子期夜盤" in bp
    if not has_tx and not has_te:
        return outlook.strip()
    out_lines: List[str] = []
    skip_follow = False
    for ln in outlook.split("\n"):
        pl = _plain(ln).strip()
        if not pl:
            out_lines.append(ln)
            continue
        if has_tx and "台指期夜盤" in pl:
            skip_follow = True
            continue
        if has_te and "電子期夜盤" in pl:
            skip_follow = True
            continue
        if skip_follow and (
            pl.startswith("比日盤")
            or pl.startswith("比現貨")
            or "比日盤收" in pl
            or "比現貨" in pl
        ):
            continue
        skip_follow = False
        out_lines.append(ln)
    return "\n".join(out_lines).strip()


def _foreign_sell_observe_line(db_path: str, as_of: str) -> str:
    """早報環境觀察：與大盤同一段三句。失敗不擋早報。"""
    try:
        from foreign_sell_display import morning_observe_line_html
        from trading_calendar import taipei_calendar_ymd

        today = taipei_calendar_ymd()
        return morning_observe_line_html(
            db_path, as_of or "", fear_as_of=today or ""
        )
    except Exception:
        return ""


def _prev_day_margin_line(db_path: str, as_of: str) -> str:
    """早報：前一日大盤融資增減（億）。沒官方列＝空。失敗不擋早報。"""
    try:
        from official_snapshots import format_prev_day_margin_line

        return format_prev_day_margin_line(db_path, as_of or "")
    except Exception:
        return ""


def build_morning_opening_html(
    db_path: str,
    as_of: str,
    screening: Optional[Dict[str, Any]],
    *,
    us_snap: Optional[Dict[str, Any]] = None,
) -> str:
    """文字①：提醒＋大盤狀況（去短夜盤）＋加權精簡（最細夜盤）＋環境／融資。"""
    outlook = _outlook_from_screening(screening)
    observe = _foreign_sell_observe_line(db_path, as_of or "")
    margin = _prev_day_margin_line(db_path, as_of or "")
    extras = [x for x in (observe, margin) if x and str(x).strip()]
    if extras and outlook:
        # 插在大盤狀況段下：環境觀察＋前一日融資（與大盤頁同一環境資訊）
        outlook = outlook.rstrip() + "\n" + "\n".join(extras)
    elif extras and not outlook:
        outlook = "\n".join(extras)
    tw_brief = ""
    try:
        from taiwan_market import format_taiwan_market_brief_html

        tw_brief = format_taiwan_market_brief_html(
            db_path, as_of or "", for_morning=True
        )
    except Exception:
        tw_brief = ""
    # 去重：留詳細夜盤（tw_brief），砍 outlook 短版
    outlook = _outlook_drop_short_nights(outlook, tw_brief)
    early = _early_alert_supplement_html(us_snap, db_path=db_path, outlook_html=outlook)
    blocks = [b for b in (early, outlook, tw_brief) if b and b.strip()]
    if not blocks:
        return ""
    if len(blocks) == 1:
        return blocks[0]
    return join_sections(*blocks, sep=f"\n{DASH_LINE}\n")


def apply_morning_opening_to_screening(
    screening: Optional[Dict[str, Any]], opening_html: str
) -> Optional[Dict[str, Any]]:
    """把合成開頭寫回 payload 第一則（文字①），再把兩桶海選合成文字②。"""
    if not screening or not opening_html.strip():
        return screening
    out = dict(screening)
    payload = [dict(p) for p in (out.get("payload") or []) if isinstance(p, dict)]
    replaced = False
    for part in payload:
        if str(part.get("mark_key") or "") == "market":
            part["html"] = opening_html
            part["mark_label"] = "早報環境"
            part["mark_hint"] = "環境＋夜盤＋加權精簡"
            replaced = True
            break
    if not replaced:
        payload.insert(
            0,
            {
                "mark_key": "market",
                "screen_pack_id": "",
                "line_pack_id": "",
                "mark_label": "早報環境",
                "mark_hint": "環境＋夜盤＋加權精簡",
                "html": opening_html,
                "picks": [],
            },
        )
    out["payload"] = payload
    out = collapse_morning_pick_parts(out)
    # message 供無 payload 的 fallback
    payload = list(out.get("payload") or [])
    rest = [p.get("html") for p in payload if str(p.get("mark_key") or "") != "market"]
    out["message"] = opening_html + "\n\n" + "\n\n".join(x for x in rest if x)
    return out


def collapse_morning_pick_parts(
    screening: Optional[Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    """Option B 文字②：黃金買點＋紅箭確認合成一則（超長仍由 Telegram 切塊）。"""
    if not screening:
        return screening
    out = dict(screening)
    payload = [dict(p) for p in (out.get("payload") or []) if isinstance(p, dict)]
    market: Optional[Dict[str, Any]] = None
    pick_parts: List[Dict[str, Any]] = []
    other: List[Dict[str, Any]] = []
    for part in payload:
        key = str(part.get("mark_key") or "")
        if key == "market":
            market = part
        elif key in ("leave_zero", "ma60_lower"):
            pick_parts.append(part)
        else:
            other.append(part)
    if len(pick_parts) <= 1:
        out["payload"] = payload
        return out
    bodies = [str(p.get("html") or "").strip() for p in pick_parts if str(p.get("html") or "").strip()]
    if not bodies:
        out["payload"] = payload
        return out
    try:
        from sanchi_clocks import sanchi_morning_one_line_html

        one = sanchi_morning_one_line_html()
    except Exception:
        one = ""
    # 各桶若已貼過完整三尺，先剝掉再改貼一行
    cleaned: List[str] = []
    for body in bodies:
        lines = body.split("\n")
        kept = [
            ln
            for ln in lines
            if "早報＝昨收" not in _plain(ln)
            and "查股藍▲" not in _plain(ln)
            and "剛脫離零＝" not in _plain(ln)
            and "圖上有箭" not in _plain(ln)
        ]
        cleaned.append("\n".join(kept).strip())
    cleaned = [c for c in cleaned if c]
    joined = join_sections(*cleaned, sep=f"\n{DASH_LINE}\n") if len(cleaned) > 1 else (cleaned[0] if cleaned else "")
    if one and one not in joined:
        joined = f"{one}\n{joined}" if joined else one
    picks: List[Any] = []
    for p in pick_parts:
        for row in p.get("picks") or []:
            picks.append(row)
    combined = {
        "mark_key": "morning_picks",
        "screen_pack_id": "leave_zero",
        "line_pack_id": "leave_zero",
        "mark_label": "海選",
        "mark_hint": "黃金買點＋紅箭確認",
        "html": joined,
        "picks": picks,
    }
    new_payload: List[Dict[str, Any]] = []
    if market is not None:
        new_payload.append(market)
    new_payload.append(combined)
    new_payload.extend(other)
    out["payload"] = new_payload
    return out
