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


def _fmt_num(v: Any, n: int = 2) -> str:
    if v is None:
        return "—"
    try:
        return f"{float(v):.{n}f}"
    except (TypeError, ValueError):
        return str(v)


def render_watch_desk_markdown(desk: Dict[str, Any]) -> str:
    if not desk.get("ok"):
        return f"# 啾哈觀盤桌（非買訊）\n\n缺資料：{desk.get('note')}\n"
    d = desk.get("daily") or {}
    tw = d.get("twii") or {}
    otc = d.get("otc") or {}
    mg = d.get("margin") or {}
    fx = d.get("usdtwd") or {}
    lines = [
        f"# 啾哈觀盤桌 {desk.get('asof')}（非買訊）",
        "",
        f"**今日盤後一句：** {desk.get('headline')}",
        "",
        "## 今日盤後（官方柱）",
        f"- 加權收 {_fmt_num(tw.get('close'))}（{_fmt_num(tw.get('chg_pct'))}%），量／5日均 {_fmt_num(tw.get('vol_vs_5'))}、／20日均 {_fmt_num(tw.get('vol_vs_20'))}",
        f"- 櫃買 {_fmt_num(otc.get('close'))}（{_fmt_num(otc.get('chg_pct'))}%），相對加權 {_fmt_num(otc.get('rel_vs_twii_pp'))} pp",
        f"- 融資變動 {_fmt_num(mg.get('chg_pct_vs_prev_row'))}%，速度差 {_fmt_num(mg.get('speed_gap_pp'))} pp（融資日 {mg.get('asof') or '—'}）",
        f"- 美金台幣 {_fmt_num(fx.get('close'), 3)}（{_fmt_num(fx.get('chg_pct'), 3)}%）{'［落後］' if fx.get('stale') else ''}",
        "",
        "## 結構標籤",
    ]
    labs = desk.get("structure_labels") or []
    lines.extend(f"- {x}" for x in labs) if labs else lines.append("- （未觸發）")
    lines += ["", "## 明日盤中要注意（可當場觀察、可應對）"]
    lines.append("只列盤中看得見的燈；融資／法人 OI 日結不放這裡當唯一鈕。")
    for i, c in enumerate(desk.get("tomorrow_intraday") or [], 1):
        lines.append(
            f"{i}. **{c.get('when')}**｜{c.get('watch')} → {c.get('how')}（{c.get('principle')}）"
        )
        lines.append(f"   - 資料：{c.get('data_hint')}")
    lines += ["", "## 盤後對質欄（明早不要等它才動）"]
    for a in desk.get("after_close_audit_only") or []:
        lines.append(
            f"- `{a['id']}` {a['title']}：{a['why_not_intraday']} → {a['use']}"
        )
    miss = d.get("missing_official") or []
    if miss:
        lines += ["", "## 官方缺欄（不准假填）"]
        lines.extend(f"- {x}" for x in miss)
    lines += [
        "",
        "估值／結構觀察 ≠ 買訊。切入仍只認已量化過關的高低卡規則。",
        "",
    ]
    return "\n".join(lines)


def render_watch_desk_png(desk: Dict[str, Any], path: str) -> str:
    """手機寬長圖：上盤後結構，下明日盤中檢查點。"""
    if not desk.get("ok"):
        return ""
    import matplotlib

    matplotlib.use("Agg", force=False)
    import matplotlib.pyplot as plt
    from matplotlib.patches import FancyBboxPatch

    asof = desk.get("asof") or ""
    d = desk.get("daily") or {}
    tw = d.get("twii") or {}
    series = desk.get("series") or {}
    twii_s = series.get("twii") or []
    otc_s = series.get("otc") or []
    fx_s = series.get("usdtwd") or []
    checks = desk.get("tomorrow_intraday") or []
    labs = desk.get("structure_labels") or []

    # 手機對話框寬：高一點塞檢查點
    fig_w, fig_h, dpi = 9.0, 14.2, 140
    fig = plt.figure(figsize=(fig_w, fig_h), dpi=dpi, facecolor="#0f1115")
    # header
    fig.text(
        0.04,
        0.975,
        f"啾哈觀盤桌 {asof}（非買訊）",
        color="#f2f2f2",
        fontproperties=_fp(22, "bold"),
        ha="left",
        va="top",
    )
    fig.text(
        0.04,
        0.948,
        f"今日盤後：{desk.get('headline')}",
        color="#c8d0dc",
        fontproperties=_fp(14),
        ha="left",
        va="top",
    )
    # metrics strip
    def _fmt(v, n=2):
        if v is None:
            return "—"
        try:
            return f"{float(v):.{n}f}"
        except (TypeError, ValueError):
            return str(v)

    otc_rel = (d.get("otc") or {}).get("rel_vs_twii_pp")
    metric = (
        f"加權 {_fmt(tw.get('close'))}（{_fmt(tw.get('chg_pct'))}%）  "
        f"量/5日 {_fmt(tw.get('vol_vs_5'))}  "
        f"櫃買相對 {_fmt(otc_rel)}pp  "
        f"台幣 {_fmt((d.get('usdtwd') or {}).get('close'), 3)}"
    )
    fig.text(
        0.04,
        0.922,
        metric,
        color="#9aa7b8",
        fontproperties=_fp(11),
        ha="left",
        va="top",
    )

    def _dates(xs):
        return [str(x.get("date") or "")[-4:] for x in xs]

    # axes: TWII close, vol, OTC/TWII, FX
    ax1 = fig.add_axes([0.08, 0.68, 0.84, 0.18])
    ax2 = fig.add_axes([0.08, 0.54, 0.84, 0.11])
    ax3 = fig.add_axes([0.08, 0.40, 0.40, 0.11])
    ax4 = fig.add_axes([0.54, 0.40, 0.38, 0.11])
    for ax in (ax1, ax2, ax3, ax4):
        ax.set_facecolor("#171a21")
        ax.tick_params(colors="#8b95a5", labelsize=8)
        for sp in ax.spines.values():
            sp.set_color("#2a3140")

    if twii_s:
        closes = [x.get("c") for x in twii_s]
        ax1.plot(range(len(closes)), closes, color="#5b9cff", lw=1.8)
        ax1.set_xticks(range(len(closes)))
        ax1.set_xticklabels(_dates(twii_s), rotation=45, ha="right")
        ax1.set_title("加權收盤（近窗）", color="#d7dee8", fontproperties=_fp(12, "bold"), loc="left")
        vols = [x.get("v") or 0 for x in twii_s]
        colors = []
        for i, x in enumerate(twii_s):
            if i == 0 or x.get("c") is None or twii_s[i - 1].get("c") is None:
                colors.append("#6b7380")
            else:
                colors.append("#e85d5d" if x["c"] >= twii_s[i - 1]["c"] else "#3ecf8e")
        ax2.bar(range(len(vols)), vols, color=colors, width=0.8)
        ax2.set_xticks(range(len(vols)))
        ax2.set_xticklabels(_dates(twii_s), rotation=45, ha="right")
        ax2.set_title("成交量", color="#d7dee8", fontproperties=_fp(12, "bold"), loc="left")

    # OTC relative if both aligned by date
    tw_map = {x["date"]: x.get("c") for x in twii_s if x.get("c") is not None}
    otc_rel = []
    otc_dates = []
    prev_t = prev_o = None
    for o in otc_s:
        t = tw_map.get(o["date"])
        if t is None or o.get("c") is None:
            continue
        if prev_t and prev_o:
            t_chg = (t - prev_t) / abs(prev_t) * 100
            o_chg = (o["c"] - prev_o) / abs(prev_o) * 100
            otc_rel.append(o_chg - t_chg)
            otc_dates.append(o["date"])
        prev_t, prev_o = t, o["c"]
    if otc_rel:
        ax3.bar(
            range(len(otc_rel)),
            otc_rel,
            color=["#3ecf8e" if v >= 0 else "#e85d5d" for v in otc_rel],
            width=0.8,
        )
        ax3.axhline(0, color="#445066", lw=0.8)
        ax3.set_xticks(range(len(otc_rel)))
        ax3.set_xticklabels([d[-4:] for d in otc_dates], rotation=45, ha="right")
    ax3.set_title("櫃買−加權（pp）", color="#d7dee8", fontproperties=_fp(11, "bold"), loc="left")

    if fx_s:
        fxc = [x.get("c") for x in fx_s]
        ax4.plot(range(len(fxc)), fxc, color="#f0c14b", lw=1.6)
        ax4.set_xticks(range(len(fxc)))
        ax4.set_xticklabels(_dates(fx_s), rotation=45, ha="right")
    ax4.set_title("美金台幣", color="#d7dee8", fontproperties=_fp(11, "bold"), loc="left")

    # labels box
    lab_ax = fig.add_axes([0.08, 0.335, 0.84, 0.05])
    lab_ax.set_xlim(0, 1)
    lab_ax.set_ylim(0, 1)
    lab_ax.axis("off")
    lab_ax.add_patch(
        FancyBboxPatch(
            (0, 0),
            1,
            1,
            boxstyle="round,pad=0.01,rounding_size=0.02",
            facecolor="#1b2130",
            edgecolor="#2f3a4d",
            transform=lab_ax.transAxes,
        )
    )
    lab_txt = "結構：" + ("／".join(labs[:3]) if labs else "（未觸發明確標籤）")
    lab_ax.text(0.02, 0.5, lab_txt, color="#e6ebf2", fontproperties=_fp(12), va="center")

    # tomorrow checks panel
    chk_ax = fig.add_axes([0.08, 0.04, 0.84, 0.28])
    chk_ax.set_xlim(0, 1)
    chk_ax.set_ylim(0, 1)
    chk_ax.axis("off")
    chk_ax.add_patch(
        FancyBboxPatch(
            (0, 0),
            1,
            1,
            boxstyle="round,pad=0.01,rounding_size=0.02",
            facecolor="#141821",
            edgecolor="#3a465c",
            transform=chk_ax.transAxes,
        )
    )
    chk_ax.text(
        0.03,
        0.94,
        "明日盤中要注意（當場可觀察）",
        color="#7ec8ff",
        fontproperties=_fp(14, "bold"),
        va="top",
    )
    chk_ax.text(
        0.03,
        0.86,
        "融資／法人OI日結＝盤後對質，不是明早唯一應對鈕",
        color="#8b95a5",
        fontproperties=_fp(10),
        va="top",
    )
    y = 0.78
    for i, c in enumerate(checks[:6], 1):
        line1 = f"{i}. {c.get('when')}｜{c.get('watch')}"
        line2 = f"   → {c.get('how')}"
        chk_ax.text(0.03, y, line1, color="#f0f3f7", fontproperties=_fp(10, "bold"), va="top")
        y -= 0.075
        chk_ax.text(0.03, y, line2, color="#aeb8c6", fontproperties=_fp(9), va="top")
        y -= 0.055
        if y < 0.06:
            break

    fig.text(
        0.04,
        0.012,
        "觀察 ≠ 買訊｜切入只認已量化過關高低卡",
        color="#6b7380",
        fontproperties=_fp(9),
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
        return "啾哈觀盤桌暫時組不出（非買訊）。"
    asof = desk.get("asof") or ""
    head = desk.get("headline") or ""
    checks = desk.get("tomorrow_intraday") or []
    tips = "／".join(str(c.get("when") or "") for c in checks[:3] if c.get("when"))
    lines = [
        f"啾哈觀盤桌 {asof}（非買訊）",
        f"今日盤後：{head}",
    ]
    if tips:
        lines.append(f"明日盤中先看：{tips}")
    lines.append("融資／法人OI日結＝盤後對質，不是明早唯一鈕。")
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
    "render_watch_desk_markdown",
    "render_watch_desk_png",
    "run_jiuha_daily_fuse",
    "write_watch_desk_artifacts",
]
