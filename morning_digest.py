# -*- coding: utf-8 -*-
"""06:30 早報：一早提醒＋海選大盤狀況＋加權指數研究合成開頭一塊（去重）。"""
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


def _tw_brief_drop_outlook_overlap(tw_brief: str, outlook_html: str) -> str:
    """加權研究保留完整數字；與大盤狀況重複的夜盤／現貨句拿掉。"""
    if not tw_brief.strip() or not outlook_html.strip():
        return tw_brief.strip()
    op = _plain(outlook_html)
    out_lines: List[str] = []
    for ln in tw_brief.split("\n"):
        pl = _plain(ln)
        if not pl.strip():
            out_lines.append(ln)
            continue
        if "台指期夜盤" in pl and "台指期夜盤" in op:
            continue
        if "電子期夜盤" in pl and "電子期夜盤" in op:
            continue
        if pl.startswith("台指期　") and "台指期" in op and "夜盤" not in pl:
            continue
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


def build_morning_opening_html(
    db_path: str,
    as_of: str,
    screening: Optional[Dict[str, Any]],
    *,
    us_snap: Optional[Dict[str, Any]] = None,
) -> str:
    """合成海選第一則前的開頭（提醒＋大盤狀況＋加權研究）。"""
    outlook = _outlook_from_screening(screening)
    observe = _foreign_sell_observe_line(db_path, as_of or "")
    if observe and outlook:
        # 插在大盤狀況段下：與大盤頁同一段三句
        outlook = outlook.rstrip() + "\n" + observe
    elif observe and not outlook:
        outlook = observe
    tw_brief = ""
    try:
        from taiwan_market import format_taiwan_market_brief_html

        tw_brief = format_taiwan_market_brief_html(db_path, as_of or "")
    except Exception:
        tw_brief = ""
    tw_brief = _tw_brief_drop_outlook_overlap(tw_brief, outlook)
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
    """把合成開頭寫回 payload 第一則（大盤狀況）。"""
    if not screening or not opening_html.strip():
        return screening
    out = dict(screening)
    payload = [dict(p) for p in (out.get("payload") or []) if isinstance(p, dict)]
    replaced = False
    for part in payload:
        if str(part.get("mark_key") or "") == "market":
            part["html"] = opening_html
            part["mark_label"] = "早報彙整"
            part["mark_hint"] = "提醒＋大盤＋加權研究"
            replaced = True
            break
    if not replaced:
        payload.insert(
            0,
            {
                "mark_key": "market",
                "screen_pack_id": "",
                "line_pack_id": "",
                "mark_label": "早報彙整",
                "mark_hint": "提醒＋大盤＋加權研究",
                "html": opening_html,
                "picks": [],
            },
        )
    out["payload"] = payload
    # message 供無 payload 的 fallback
    rest = [p.get("html") for p in payload if p.get("mark_key") != "market"]
    out["message"] = opening_html + "\n\n" + "\n\n".join(x for x in rest if x)
    return out
