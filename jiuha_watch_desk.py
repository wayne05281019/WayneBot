# -*- coding: utf-8 -*-
"""啾哈每日觀盤桌（非買訊）。

今日盤後：官方柱數字＋附圖，看清當日結構。
明日要注意：只列「盤中就能觀察」的檢查點；盤後才更新的欄
（融資餘額、期貨法人 OI 日結）標成對質欄，不准當明早唯一應對鈕。

不准改黃金買點／海選／洞燭選股。時區 Asia/Taipei。
"""
from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from jiuha_observe import (
    DESK_LAYERS,
    PRINCIPLES,
    TAIPEI,
    compute_daily_structure,
    load_index_bars,
)

DEFAULT_MARKET = Path("/workspace/data/wayne_market.db")
DEFAULT_OUT = Path("/opt/cursor/artifacts/jiuha")


def _fp(size: int, weight: str = "normal"):
    """Noto CJK font for phone-readable charts."""
    import matplotlib.font_manager as fm

    from wayne_navigator import _fp as nav_fp

    return nav_fp(size, weight)


def build_tomorrow_intraday_checks(pack: Dict[str, Any]) -> List[Dict[str, Any]]:
    """明日盤中可觀測檢查點（依當日結構動態加權）。

    每條必含：when（台北時段）、watch、how（怎樣算觸發）、principle、
    data_hint。禁止把純盤後欄當唯一應對。
    """
    tw = pack.get("twii") or {}
    labs = pack.get("structure_labels") or []
    chg = tw.get("chg_pct")
    vol_vs_5 = tw.get("vol_vs_5")
    checks: List[Dict[str, Any]] = []

    # 1) 開盤 15 分——他最強調的盤中門；庫缺分K仍要列成手算／即時看板
    checks.append(
        {
            "id": "T_open15_vol",
            "when": "09:00–09:15",
            "watch": "加權開盤15分成交金額（或成交量）vs 近5日同時段",
            "how": "明顯縮鎖、幾乎無換手 → 標「開盤量鎖死」（P07）；有量換手再往下看結構",
            "principle": "P07_open15_vol",
            "data_hint": "盤中即時累計／分K；日庫常缺→以看板手算，不准假填歷史",
            "intraday": True,
            "priority": 1,
        }
    )

    # 2) 午前量速——不用等收盤才知道「今天有沒有量」
    checks.append(
        {
            "id": "T_am_vol_pace",
            "when": "09:15–11:00",
            "watch": "累計量／近5日全日均量的進度（午前應大致過半才像有換手）",
            "how": "大漲但累計量嚴重落後 → 先當「縮量反彈／逃命窗假設」（P04），不是追高證成",
            "principle": "P04_volume_rebound",
            "data_hint": "盤中累計量即可；全日比要等收盤只做對質",
            "intraday": True,
            "priority": 2,
        }
    )

    # 3) 櫃買相對——盤中看漲跌幅差
    checks.append(
        {
            "id": "T_otc_rel",
            "when": "09:30–13:00",
            "watch": "櫃買漲跌％ − 加權漲跌％",
            "how": "加權弱而櫃買相對先穩 → 融資止血偏有利假設（P06）；櫃買更弱 → 壓力警訊",
            "principle": "P06_otc_first",
            "data_hint": "盤中報價即可；完整 OHLC 若庫內僅戳記，收盤對質另標缺",
            "intraday": True,
            "priority": 3,
        }
    )

    # 4) 台幣——盤中可看
    checks.append(
        {
            "id": "T_fx_lead",
            "when": "終日（台北早盤優先）",
            "watch": "美金台幣即時／早盤方向",
            "how": "台幣升值（USDTWD 跌）＋指數反彈 → 資金面偏暖訊號之一（P05）；台幣貶而指數漲 → 加權可能騙人",
            "principle": "P05_fx_lead",
            "data_hint": "銀行／報價盤中可得；日結欄落後只標 stale，不擋盤中看",
            "intraday": True,
            "priority": 4,
        }
    )

    # 5) 關鍵位刺穿——盤中就能看，不必等收
    if any("假突破" in (x or "") for x in labs) or (
        chg is not None and chg < -1.5 and vol_vs_5 and vol_vs_5 >= 1.2
    ):
        checks.append(
            {
                "id": "T_level_probe",
                "when": "試高／試低當下",
                "watch": "是否刺穿近頸線／前高，以及刺穿後是否立刻被打回",
                "how": "小突破＋爆量無力 → 假突破／獵殺結構假設（P03）；盤中回落即可先定性，收盤站上才是盤尾確認",
                "principle": "P03_false_break",
                "data_hint": "盤中高低＋量；有點名價才對該價，不准發明新價",
                "intraday": True,
                "priority": 2,
            }
        )

    # 6) 縮量大漲翌日——特別盯開盤有沒有量把故事延續
    if any("縮量反彈" in (x or "") for x in labs) or (
        chg is not None and chg > 1.5 and vol_vs_5 is not None and vol_vs_5 < 0.85
    ):
        checks.insert(
            1,
            {
                "id": "T_escape_follow",
                "when": "09:00–10:30",
                "watch": "昨標「縮量反彈」後：今早是否補量，或高開後量縮回吐",
                "how": "高開無量／迅速翻黑 → 逃命窗延續假設偏強（P04）；開盤即帶量站穩再觀察，仍非買訊",
                "principle": "P04_volume_rebound",
                "data_hint": "盤中量價即可",
                "intraday": True,
                "priority": 1,
            },
        )

    # 7) 正二／槓桿 ETF 價格量能——融資日結盤後才有，盤中用價量代理
    checks.append(
        {
            "id": "T_lever_etf_proxy",
            "when": "09:00–13:30",
            "watch": "正二／槓桿 ETF（如 00685L）盤中價量：急殺無量 vs 有換手",
            "how": "只當「去槓桿是否仍激烈」的盤中側證（P08）；融資停加／轉減要等日結，不准用盤中價假裝融資餘額",
            "principle": "P08_lever_etf",
            "data_hint": "盤中報價；融資餘額屬盤後對質",
            "intraday": True,
            "priority": 5,
        }
    )

    # 8) W5：期貨空單盤中代理——日終 OI 不准當唯一鈕
    checks.append(
        {
            "id": "T_tx_proxy",
            "when": "08:45／09:15／11:00／13:00",
            "watch": "台指期日盤／夜盤活價＋當日量（相對加權是否虛漲）",
            "how": "急漲但期貨量萎縮、或夜盤已失守而日盤虛漲 →「回補／軋空未確認」（P02／P05）；真實減空仍等日終外資 OI 對質",
            "principle": "P02_forced_buy",
            "data_hint": "盤中期價／量；futures_inst_oi 日結只進盤後對質欄",
            "intraday": True,
            "priority": 4,
        }
    )

    # 9) W7：存活閘——無行情欄，開盤前複誦
    checks.insert(
        0,
        {
            "id": "T_l0_survive",
            "when": "08:50 開盤前（W1／W2 觸發再唸）",
            "watch": "停損／最大虧損／部位／現金／睡得著嗎",
            "how": "未設好＝L0 未過，後面燈先不當操作解讀（P09）；仍非買訊",
            "principle": "P09_risk_first",
            "data_hint": "自檢清單，無官方行情欄",
            "intraday": True,
            "priority": 0,
        },
    )

    checks.sort(key=lambda x: (x.get("priority", 9), x.get("id")))
    return checks


def build_after_close_audit_only(pack: Dict[str, Any]) -> List[Dict[str, Any]]:
    """盤後才更新＝對質用，不是明天盤中應對鈕。"""
    return [
        {
            "id": "A_margin_speed",
            "title": "融資速度差 vs 指數",
            "why_not_intraday": "市場融資餘額多為日結／T+1，盤中無法用官方餘額即時算速度差",
            "principle": "P01_margin_speed",
            "use": "今日盤後對質；明日盤中改看開盤量／櫃買／台幣",
        },
        {
            "id": "A_futures_oi",
            "title": "外資期貨淨空口數",
            "why_not_intraday": "期交所法人 OI 多為盤後日結；盤中可看期價／基差，但淨空變動不能假裝已更新",
            "principle": "P02_forced_buy／P11",
            "use": "翻篇條件的對質燈；缺列＝unverifiable",
        },
        {
            "id": "A_full_day_vol",
            "title": "全日量／5日均",
            "why_not_intraday": "比值要等收盤才定案；盤中只用累計量進度",
            "principle": "P04_volume_rebound",
            "use": "收盤後重貼結構標籤",
        },
        {
            "id": "A_triple_sync",
            "title": "減空×現貨轉買×台幣三同步",
            "why_not_intraday": "外資現貨／淨空日結常齊不了；台幣可盤中看，但三燈齊亮多在盤後",
            "principle": "P05_fx_lead",
            "use": "反轉敘事對質；缺一燈就暗",
        },
    ]


def build_watch_desk(
    market_db: str,
    *,
    asof: str = "",
) -> Dict[str, Any]:
    pack = compute_daily_structure(market_db, asof=asof)
    if not pack.get("ok"):
        return {
            "ok": False,
            "note": pack.get("note") or "daily structure failed",
            "not_buy_signal": True,
        }
    tomorrow = build_tomorrow_intraday_checks(pack)
    audit = build_after_close_audit_only(pack)
    # 近窗柱供出圖
    twii = load_index_bars(market_db, "TWII", limit=30)
    otc = load_index_bars(market_db, "OTC", limit=30)
    fx = load_index_bars(market_db, "USDTWD", limit=30)
    day = pack["asof"]
    twii_w = [b for b in reversed(twii) if b.date <= day][-20:]
    otc_w = [b for b in reversed(otc) if b.date <= day][-20:]
    fx_w = [b for b in reversed(fx) if b.date <= day][-20:]
    return {
        "ok": True,
        "asof": day,
        "not_buy_signal": True,
        "author": "啾哈觀察",
        "daily": pack,
        "today_focus": pack.get("focus") or [],
        "structure_labels": pack.get("structure_labels") or [],
        "tomorrow_intraday": tomorrow,
        "after_close_audit_only": audit,
        "desk_layers": DESK_LAYERS,
        "series": {
            "twii": [
                {
                    "date": b.date,
                    "o": b.open,
                    "h": b.high,
                    "l": b.low,
                    "c": b.close,
                    "v": b.volume,
                }
                for b in twii_w
            ],
            "otc": [
                {"date": b.date, "c": b.close} for b in otc_w if b.close is not None
            ],
            "usdtwd": [
                {"date": b.date, "c": b.close} for b in fx_w if b.close is not None
            ],
        },
        "headline": _headline(pack),
    }


def _headline(pack: Dict[str, Any]) -> str:
    labs = pack.get("structure_labels") or []
    if labs:
        return "／".join(labs[:2])
    tw = pack.get("twii") or {}
    chg = tw.get("chg_pct")
    if chg is None:
        return "結構未觸發明確標籤"
    if chg >= 1.5:
        return "偏強日・先辨真假換手"
    if chg <= -1.5:
        return "偏弱日・先看清算進度"
    return "震盪日・看量與櫃買相對"


def plain_today_line(desk: Dict[str, Any]) -> str:
    """手機白話一句：今天發生什麼（不准買訊口吻）。"""
    d = desk.get("daily") or {}
    tw = d.get("twii") or {}
    chg = tw.get("chg_pct")
    labs = desk.get("structure_labels") or []
    bits: List[str] = []
    if chg is not None:
        if chg <= -3:
            bits.append(f"大盤大跌 {_fmt_num(chg)}%")
        elif chg <= -1:
            bits.append(f"大盤偏弱 {_fmt_num(chg)}%")
        elif chg >= 3:
            bits.append(f"大盤大漲 {_fmt_num(chg)}%")
        elif chg >= 1:
            bits.append(f"大盤偏強 {_fmt_num(chg)}%")
        else:
            bits.append(f"大盤震盪 {_fmt_num(chg)}%")
    for lab in labs:
        if "融資跌更快" in lab or "去槓桿有進度" in lab:
            bits.append("融資掉得比指數快＝洗籌碼有在進行")
        elif "清算不足" in lab:
            bits.append("指數跌但融資沒更快掉＝還沒洗乾淨")
        elif "縮量反彈" in lab:
            bits.append("漲但量不夠＝先當反彈不是翻多")
        elif "帶量上攻" in lab:
            bits.append("漲且有量＝比較像有人真的在買")
        elif "爆量下跌" in lab:
            bits.append("跌且爆量＝恐慌或出貨要再辨")
        elif "櫃買相對強" in lab:
            bits.append("櫃買比加權強")
        elif "櫃買弱" in lab:
            bits.append("櫃買比加權弱＝壓力較大")
        elif "台幣偏升" in lab:
            bits.append("台幣偏升（資金面偏暖的訊號之一）")
        elif "台幣偏貶" in lab:
            bits.append("台幣偏貶（資金面偏壓的訊號之一）")
    if not bits:
        bits.append(desk.get("headline") or "今天沒觸發明確標籤")
    # 最多兩句，手機一眼
    return "；".join(bits[:2])


def plain_tomorrow_rows(checks: List[Dict[str, Any]]) -> List[Dict[str, str]]:
    """明天盤中：時段＋一句白話（去掉原則代號與長句）。"""
    table = {
        "T_l0_survive": ("開盤前", "先問：停損／最多虧多少設好了嗎"),
        "T_open15_vol": ("09:00–09:15", "開盤有沒有量？量縮鎖死就先別急"),
        "T_escape_follow": ("09:00–10:30", "昨縮量漲的話：今早有沒有補量"),
        "T_am_vol_pace": ("午前", "若大漲，累計量有沒有跟上"),
        "T_level_probe": ("碰到前高／頸線時", "刺穿後有沒有立刻被打回"),
        "T_otc_rel": ("盤中", "櫃買是不是比加權更弱"),
        "T_fx_lead": ("盤中", "台幣升還是貶（升偏暖、貶偏壓）"),
        "T_tx_proxy": ("盤中", "期貨有沒有跟著、還是只有現貨虛漲"),
        "T_lever_etf_proxy": ("盤中", "正二／槓桿ETF是急殺無量還是有換手"),
    }
    out: List[Dict[str, str]] = []
    seen = set()
    for c in checks or []:
        cid = str(c.get("id") or "")
        if cid in seen:
            continue
        seen.add(cid)
        if cid in table:
            when, line = table[cid]
        else:
            when = str(c.get("when") or "")[:12]
            line = str(c.get("watch") or "")[:28]
        out.append({"when": when, "line": line, "id": cid})
        if len(out) >= 6:
            break
    return out


def _fmt_num(v: Any, n: int = 2) -> str:
    if v is None:
        return "—"
    try:
        return f"{float(v):.{n}f}"
    except (TypeError, ValueError):
        return str(v)


def render_watch_desk_markdown(desk: Dict[str, Any]) -> str:
    if not desk.get("ok"):
        return f"# 啾哈觀盤（非買訊）\n\n缺資料：{desk.get('note')}\n"
    d = desk.get("daily") or {}
    tw = d.get("twii") or {}
    otc = d.get("otc") or {}
    fx = d.get("usdtwd") or {}
    lines = [
        f"# 啾哈觀盤 {desk.get('asof')}（非買訊）",
        "",
        f"**今天：** {plain_today_line(desk)}",
        "",
        "## 數字",
        f"- 加權 {_fmt_num(tw.get('close'))}（{_fmt_num(tw.get('chg_pct'))}%）",
        f"- 量／五日 {_fmt_num(tw.get('vol_vs_5'))}×",
        f"- 櫃買相對 {_fmt_num(otc.get('rel_vs_twii_pp'))} 百分點",
        f"- 台幣 {_fmt_num(fx.get('close'), 3)}{'［落後］' if fx.get('stale') else ''}",
        "",
        "## 明天盤中這樣看",
    ]
    for i, r in enumerate(plain_tomorrow_rows(desk.get("tomorrow_intraday") or []), 1):
        lines.append(f"{i}. {r.get('when')}｜{r.get('line')}")
    lines += [
        "",
        "融資餘額、空單口數＝收盤後才更新，明早先看上面。",
        "",
        "觀察 ≠ 買訊。切入仍只認已量化過關的高低卡。",
        "",
    ]
    return "\n".join(lines)


def render_watch_desk_png(desk: Dict[str, Any], path: str) -> str:
    """手機白話卡：今天一句＋四大數字＋一條走勢＋明天時段（大字、不擠）。"""
    if not desk.get("ok"):
        return ""
    import matplotlib

    matplotlib.use("Agg", force=False)
    import matplotlib.pyplot as plt
    from matplotlib.patches import FancyBboxPatch

    asof = desk.get("asof") or ""
    asof_slash = f"{asof[4:6]}/{asof[6:8]}" if len(asof) == 8 else asof
    d = desk.get("daily") or {}
    tw = d.get("twii") or {}
    otc = d.get("otc") or {}
    fx = d.get("usdtwd") or {}
    series = desk.get("series") or {}
    twii_s = series.get("twii") or []
    plain = plain_today_line(desk)
    rows = plain_tomorrow_rows(desk.get("tomorrow_intraday") or [])

    # 台股慣例：紅漲綠跌
    chg = tw.get("chg_pct")
    up = chg is not None and chg >= 0
    chg_color = "#c62828" if up else "#2e7d32"

    bg = "#f7f5f0"
    ink = "#1a1a1a"
    mute = "#5c5c5c"
    card = "#ffffff"
    line_c = "#c62828" if up else "#2e7d32"

    fig_w, fig_h, dpi = 9.0, 16.0, 150
    fig = plt.figure(figsize=(fig_w, fig_h), dpi=dpi, facecolor=bg)

    # 標題
    fig.text(
        0.05,
        0.975,
        f"啾哈觀盤  {asof_slash}",
        color=ink,
        fontproperties=_fp(28, "bold"),
        ha="left",
        va="top",
    )
    fig.text(
        0.95,
        0.975,
        "非買訊",
        color=mute,
        fontproperties=_fp(16, "bold"),
        ha="right",
        va="top",
    )

    # 今天一句（大框）
    ax_head = fig.add_axes([0.05, 0.82, 0.90, 0.12])
    ax_head.set_xlim(0, 1)
    ax_head.set_ylim(0, 1)
    ax_head.axis("off")
    ax_head.add_patch(
        FancyBboxPatch(
            (0, 0),
            1,
            1,
            boxstyle="round,pad=0.012,rounding_size=0.03",
            facecolor=card,
            edgecolor="#e0dcd3",
            linewidth=1.5,
            transform=ax_head.transAxes,
        )
    )
    ax_head.text(
        0.04,
        0.78,
        "今天盤後一句",
        color=mute,
        fontproperties=_fp(14, "bold"),
        va="top",
    )
    # 手動換行：約 16 全形字
    def _wrap(s: str, n: int = 16) -> str:
        s = str(s or "")
        if len(s) <= n:
            return s
        parts = []
        while s:
            parts.append(s[:n])
            s = s[n:]
        return "\n".join(parts[:3])

    ax_head.text(
        0.04,
        0.48,
        _wrap(plain, 17),
        color=ink,
        fontproperties=_fp(20, "bold"),
        va="top",
        linespacing=1.35,
    )

    # 四大數字
    def _chip(ax, title, value, sub, value_color=ink):
        ax.set_xlim(0, 1)
        ax.set_ylim(0, 1)
        ax.axis("off")
        ax.add_patch(
            FancyBboxPatch(
                (0, 0),
                1,
                1,
                boxstyle="round,pad=0.02,rounding_size=0.04",
                facecolor=card,
                edgecolor="#e0dcd3",
                linewidth=1.2,
                transform=ax.transAxes,
            )
        )
        ax.text(0.08, 0.78, title, color=mute, fontproperties=_fp(13, "bold"), va="top")
        ax.text(
            0.08,
            0.42,
            value,
            color=value_color,
            fontproperties=_fp(22, "bold"),
            va="center",
        )
        if sub:
            ax.text(0.08, 0.14, sub, color=mute, fontproperties=_fp(12), va="bottom")

    fx_chg = fx.get("chg_pct")
    # USDTWD 升＝台幣貶
    fx_plain = "—"
    fx_col = ink
    if fx_chg is not None:
        if fx_chg > 0.05:
            fx_plain = "台幣偏貶"
            fx_col = "#2e7d32"  # 資金偏壓用綠字警示區分漲跌色
        elif fx_chg < -0.05:
            fx_plain = "台幣偏升"
            fx_col = "#c62828"
        else:
            fx_plain = "台幣持平"

    otc_rel = otc.get("rel_vs_twii_pp")
    otc_plain = "—"
    if otc_rel is not None:
        otc_plain = "櫃買較強" if otc_rel > 0.3 else ("櫃買較弱" if otc_rel < -0.3 else "差不多")

    chips = [
        (
            0.05,
            "加權",
            f"{_fmt_num(tw.get('close'), 0)}",
            f"{_fmt_num(chg)}%",
            chg_color,
        ),
        (
            0.28,
            "量（vs五日）",
            f"{_fmt_num(tw.get('vol_vs_5'))}×",
            "＞1＝量比平常大" if (tw.get("vol_vs_5") or 0) >= 1 else "＜1＝量偏縮",
            ink,
        ),
        (
            0.51,
            "櫃買相對",
            otc_plain,
            f"{_fmt_num(otc_rel)} 百分點" if otc_rel is not None else "缺官方柱",
            ink,
        ),
        (
            0.74,
            "台幣",
            fx_plain,
            f"匯率 {_fmt_num(fx.get('close'), 3)}"
            + (" 落後" if fx.get("stale") else ""),
            fx_col,
        ),
    ]
    for x0, title, val, sub, vc in chips:
        ax = fig.add_axes([x0, 0.68, 0.21, 0.12])
        _chip(ax, title, val, sub, vc)

    # 一條加權走勢（大）
    ax_c = fig.add_axes([0.08, 0.42, 0.84, 0.22])
    ax_c.set_facecolor(card)
    for sp in ax_c.spines.values():
        sp.set_color("#e0dcd3")
    ax_c.tick_params(colors=mute, labelsize=11)
    ax_c.set_title(
        "加權近況（一眼看方向）",
        color=ink,
        fontproperties=_fp(15, "bold"),
        loc="left",
        pad=8,
    )
    if twii_s:
        closes = [x.get("c") for x in twii_s if x.get("c") is not None]
        xs = list(range(len(closes)))
        ax_c.plot(xs, closes, color=line_c, lw=2.6)
        ax_c.fill_between(xs, closes, min(closes), color=line_c, alpha=0.08)
        # 只標首尾日期，避免擠
        if len(twii_s) >= 2:
            d0 = str(twii_s[0].get("date") or "")
            d1 = str(twii_s[-1].get("date") or "")
            ax_c.set_xticks([0, len(closes) - 1])
            ax_c.set_xticklabels(
                [
                    f"{d0[4:6]}/{d0[6:8]}" if len(d0) == 8 else d0,
                    f"{d1[4:6]}/{d1[6:8]}" if len(d1) == 8 else d1,
                ],
                fontproperties=_fp(12),
            )
        ax_c.yaxis.set_major_formatter(
            plt.FuncFormatter(lambda v, _: f"{v:,.0f}")
        )
        for lab in ax_c.get_yticklabels():
            lab.set_fontproperties(_fp(11))

    # 明天清單
    ax_t = fig.add_axes([0.05, 0.04, 0.90, 0.34])
    ax_t.set_xlim(0, 1)
    ax_t.set_ylim(0, 1)
    ax_t.axis("off")
    ax_t.add_patch(
        FancyBboxPatch(
            (0, 0),
            1,
            1,
            boxstyle="round,pad=0.012,rounding_size=0.03",
            facecolor=card,
            edgecolor="#e0dcd3",
            linewidth=1.5,
            transform=ax_t.transAxes,
        )
    )
    ax_t.text(
        0.04,
        0.94,
        "明天盤中這樣看（當場看得出才列）",
        color=ink,
        fontproperties=_fp(18, "bold"),
        va="top",
    )
    ax_t.text(
        0.04,
        0.84,
        "融資餘額、空單口數＝收盤後才更新，明早先看下面",
        color=mute,
        fontproperties=_fp(13),
        va="top",
    )
    y = 0.72
    for i, r in enumerate(rows[:6], 1):
        ax_t.text(
            0.04,
            y,
            f"{i}",
            color="#c62828",
            fontproperties=_fp(18, "bold"),
            va="top",
        )
        ax_t.text(
            0.10,
            y,
            r.get("when") or "",
            color=mute,
            fontproperties=_fp(15, "bold"),
            va="top",
        )
        ax_t.text(
            0.38,
            y,
            r.get("line") or "",
            color=ink,
            fontproperties=_fp(16, "bold"),
            va="top",
        )
        y -= 0.11

    fig.text(
        0.05,
        0.012,
        "觀察用，不是買訊。怎麼買仍看高低卡已過關規則。",
        color=mute,
        fontproperties=_fp(12),
        ha="left",
        va="bottom",
    )
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, facecolor=fig.get_facecolor(), edgecolor="none")
    plt.close(fig)
    return path


def _fuse_log_path(out_dir: Path) -> Path:
    return out_dir / "desk_fuse_log.jsonl"


def append_fuse_log(desk: Dict[str, Any], out_dir: str) -> str:
    """每日融會紀要：可重畫、可追加，不准當買訊。"""
    outp = Path(out_dir)
    outp.mkdir(parents=True, exist_ok=True)
    path = _fuse_log_path(outp)
    row = {
        "fused_at_taipei": datetime.now(TAIPEI).isoformat(),
        "asof": desk.get("asof"),
        "headline": desk.get("headline"),
        "structure_labels": desk.get("structure_labels") or [],
        "tomorrow_ids": [c.get("id") for c in (desk.get("tomorrow_intraday") or [])],
        "missing_official": (desk.get("daily") or {}).get("missing_official") or [],
        "not_buy_signal": True,
    }
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")
    latest = outp / "desk_fuse_latest.json"
    latest.write_text(json.dumps(row, ensure_ascii=False, indent=2), encoding="utf-8")
    return str(path)


def _phone_caption(desk: Dict[str, Any]) -> str:
    if not desk.get("ok"):
        return "啾哈觀盤暫時組不出（非買訊）。"
    asof = desk.get("asof") or ""
    asof_slash = f"{asof[4:6]}/{asof[6:8]}" if len(asof) == 8 else asof
    lines = [
        f"啾哈觀盤 {asof_slash}（非買訊）",
        plain_today_line(desk),
    ]
    rows = plain_tomorrow_rows(desk.get("tomorrow_intraday") or [])
    if rows:
        tip = "；".join(f"{r['when']} {r['line']}" for r in rows[:3])
        lines.append(f"明天先看：{tip}")
    lines.append("融資／空單口數收盤後才更新。")
    return "\n".join(lines)


def write_watch_desk_artifacts(
    *,
    market_db: str = str(DEFAULT_MARKET),
    out_dir: str = str(DEFAULT_OUT),
    asof: str = "",
    png_path: str = "",
    fuse_log: bool = True,
) -> Dict[str, Any]:
    """產出觀盤桌。每次呼叫重算＋重畫（圖不准一成不變鎖死）。"""
    outp = Path(out_dir)
    outp.mkdir(parents=True, exist_ok=True)
    desk = build_watch_desk(market_db, asof=asof)
    stamp = desk.get("asof") or datetime.now(TAIPEI).strftime("%Y%m%d")
    md = render_watch_desk_markdown(desk)
    md_path = outp / f"watch_desk_{stamp}.md"
    json_path = outp / f"watch_desk_{stamp}.json"
    target_png = Path(png_path) if png_path else (outp / f"watch_desk_{stamp}.png")
    target_png.parent.mkdir(parents=True, exist_ok=True)
    md_path.write_text(md, encoding="utf-8")
    json_path.write_text(json.dumps(desk, ensure_ascii=False, indent=2), encoding="utf-8")
    png = ""
    if desk.get("ok"):
        try:
            if target_png.is_file():
                target_png.unlink()
        except OSError:
            pass
        png = render_watch_desk_png(desk, str(target_png))
    log_path = ""
    if fuse_log and desk.get("ok"):
        log_path = append_fuse_log(desk, str(outp))
    return {
        "ok": bool(desk.get("ok")),
        "asof": stamp,
        "md": str(md_path),
        "json": str(json_path),
        "png": png or str(target_png),
        "fuse_log": log_path,
        "n_tomorrow_intraday": len(desk.get("tomorrow_intraday") or []),
        "desk": desk,
        "caption": _phone_caption(desk),
    }


def run_jiuha_daily_fuse(
    *,
    market_db: str = str(DEFAULT_MARKET),
    out_dir: str = str(DEFAULT_OUT),
    charts_dir: str = "",
) -> Dict[str, Any]:
    """盤後融會：依最新官方柱重算觀盤桌＋追加融會日誌（圖每次重畫）。"""
    res = write_watch_desk_artifacts(
        market_db=market_db,
        out_dir=out_dir,
        fuse_log=True,
    )
    if charts_dir and res.get("ok"):
        stamp = res.get("asof") or "na"
        dest = Path(charts_dir) / "jiuha" / f"watch_desk_{stamp}.png"
        dest.parent.mkdir(parents=True, exist_ok=True)
        src = Path(res.get("png") or "")
        if src.is_file():
            dest.write_bytes(src.read_bytes())
            res["charts_png"] = str(dest)
            res["png"] = str(dest)
    return res


__all__ = [
    "append_fuse_log",
    "build_after_close_audit_only",
    "build_tomorrow_intraday_checks",
    "build_watch_desk",
    "plain_today_line",
    "plain_tomorrow_rows",
    "render_watch_desk_markdown",
    "render_watch_desk_png",
    "run_jiuha_daily_fuse",
    "write_watch_desk_artifacts",
]
