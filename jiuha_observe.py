# -*- coding: utf-8 -*-
"""啾哈觀察指標（非買訊）。

語料：data/jiuha_corpus/（獨立，不准寫進飆客／海選／黃金買點／洞燭選股）。
每日用官方柱算「盤勢結構」＋「重點觀察」；原則只認他原文證據。
時區 Asia/Taipei。盤中未收不當收。
"""
from __future__ import annotations

import json
import os
import re
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple
from zoneinfo import ZoneInfo

TAIPEI = ZoneInfo("Asia/Taipei")
AUTHOR_ID = "20269"
AUTHOR_NAME = "啾哈"

DEFAULT_CORPUS = Path("/workspace/data/jiuha_corpus/jiuha.sqlite")
DEFAULT_MARKET = Path("/workspace/data/wayne_market.db")
DEFAULT_OUT = Path("/opt/cursor/artifacts/jiuha")

# 每日儀表層級（辯論 D 定調；A／B／C 掛載）。衝突時 L0＋非買訊勝出。
DESK_LAYERS: List[Dict[str, str]] = [
    {"id": "L0", "title": "存活閘", "hint": "停損／最大虧損／部位／現金／睡得著嗎"},
    {"id": "L1", "title": "天氣", "hint": "台幣・外資期現貨・總經節點"},
    {"id": "L2", "title": "路寬", "hint": "產業／供應鏈容錯（只觀察）"},
    {"id": "L3", "title": "結構", "hint": "融資速度差・正二・真假換手・空單"},
    {"id": "L4", "title": "節奏", "hint": "量價定性・頸線・開盤量・關鍵位"},
    {"id": "L5", "title": "控車", "hint": "空手／減碼／避險／等待（禁止建議買入）"},
]

# 原則卡：每條必須能指回至少一篇 article_id（深度閱讀後鎖）
PRINCIPLES: List[Dict[str, Any]] = [
    {
        "id": "P01_margin_speed",
        "title": "去槓桿看速度差，不猜點位",
        "rule": "融資跌幅必須明顯快過指數跌幅，清算才算有進度；只看大盤點位會誤判。",
        "evidence": ["189413133"],
        "observe": "margin_vs_index_speed",
    },
    {
        "id": "P02_forced_buy",
        "title": "空頭回補是系統性買盤",
        "rule": "跌深時第一波撐盤常是空頭被迫回補，不是抄底多頭；禁空可能趕走這批買盤。",
        "evidence": ["189479825"],
        "observe": "short_policy_liquidity",
    },
    {
        "id": "P03_false_break",
        "title": "頸線假突破真獵殺",
        "rule": "未達法人常用突破門檻（文中示例約 3%）的「小突破」＋爆量收黑＝出貨／獵殺結構，不是真突破。",
        "evidence": ["188588578"],
        "observe": "neckline_break_quality",
    },
    {
        "id": "P04_volume_rebound",
        "title": "縮量反彈≠新錢；真底要帶量",
        "rule": "大漲若縮量，偏向空手回補／逃命窗，不是新買盤證明趨勢反轉。",
        "evidence": ["188453849"],
        "observe": "rebound_volume_quality",
    },
    {
        "id": "P05_fx_lead",
        "title": "台幣是領先、加權會騙人",
        "rule": "匯率／資金流比單看指數更靠近真相；反轉信心要等外資減空＋現貨轉買＋台幣升值同步。",
        "evidence": ["188453849"],
        "observe": "fx_foreign_sync",
    },
    {
        "id": "P06_otc_first",
        "title": "櫃買先止穩才是融資止血",
        "rule": "觀察櫃買相對加權是否先穩；融資體質比指數面子重要。",
        "evidence": ["189479825"],
        "observe": "otc_vs_twii",
    },
    {
        "id": "P07_open15_vol",
        "title": "開盤15分量縮鎖死→空手",
        "rule": "開盤量能鎖死、無換手，政策／反彈都救不了斷頭排隊。",
        "evidence": ["189479825"],
        "observe": "open_volume_lock",
    },
    {
        "id": "P08_lever_etf",
        "title": "正二融資停加才像段落；還在加＝狀態未完",
        "rule": "槓桿 ETF 融資持續加碼只證明去槓桿未結束，不能當距離指標；停加／轉減才是狀態切換。",
        "evidence": ["187720375", "188178992"],
        "observe": "lever_etf_margin",
    },
    {
        "id": "P09_risk_first",
        "title": "先問最多虧多少",
        "rule": "進場前先定停損與可承受虧損；國家隊／紀律＝反人性接下恐慌籌碼，不是情緒追價。",
        "evidence": ["187304605"],
        "observe": "risk_checklist",
    },
    {
        "id": "P10_structure_first",
        "title": "真假換手決定下一波風險從哪來",
        "rule": "大漲日要分辨換手還是誘多：看融資／空單／維持率是否同步修復，不是只看漲跌％。",
        "evidence": ["188178992"],
        "observe": "turnover_authenticity",
    },
    {
        "id": "P11_domestic_etf_regime",
        "title": "內資／ETF／官股體質質變",
        "rule": "恐慌期官股與大眾 ETF 逆勢布局屬紀律均值回歸敘事；軋空／擠壓反彈要對外資空單是否認錯回補，不是只看點數。",
        "evidence": ["180121967", "181014061", "181896104"],
        "observe": "domestic_etf_regime",
    },
]


def _ymd(raw: Any) -> str:
    s = "".join(ch for ch in str(raw or "") if ch.isdigit())
    if len(s) >= 8:
        return s[:8]
    if len(s) == 7:  # ROC
        try:
            y = int(s[:3]) + 1911
            return f"{y:04d}{s[3:7]}"
        except ValueError:
            return ""
    return ""


def _finite(raw: Any) -> Optional[float]:
    if raw is None:
        return None
    try:
        v = float(raw)
    except (TypeError, ValueError):
        return None
    if v != v:
        return None
    return v


def _pct(a: Optional[float], b: Optional[float]) -> Optional[float]:
    if a is None or b is None or b == 0:
        return None
    return (a - b) / abs(b) * 100.0


@dataclass
class Bar:
    date: str
    open: Optional[float] = None
    high: Optional[float] = None
    low: Optional[float] = None
    close: Optional[float] = None
    volume: Optional[float] = None


def load_index_bars(
    db_path: str, symbol: str, *, limit: int = 120
) -> List[Bar]:
    if not db_path or not os.path.isfile(db_path):
        return []
    con = sqlite3.connect(db_path, timeout=30.0)
    try:
        rows = con.execute(
            """
            SELECT REPLACE(CAST(date AS TEXT),'-',''), open, high, low, close, volume
            FROM index_daily
            WHERE symbol=?
            ORDER BY REPLACE(CAST(date AS TEXT),'-','') DESC
            LIMIT ?
            """,
            (symbol, limit),
        ).fetchall()
    finally:
        con.close()
    out: List[Bar] = []
    for r in rows:
        out.append(
            Bar(
                date=_ymd(r[0]),
                open=_finite(r[1]),
                high=_finite(r[2]),
                low=_finite(r[3]),
                close=_finite(r[4]),
                volume=_finite(r[5]),
            )
        )
    return out


def load_margin_series(db_path: str, *, limit: int = 60) -> List[Dict[str, Any]]:
    if not db_path or not os.path.isfile(db_path):
        return []
    con = sqlite3.connect(db_path, timeout=30.0)
    try:
        rows = con.execute(
            """
            SELECT REPLACE(CAST(date AS TEXT),'-',''), margin_bal_k, margin_delta_k, source
            FROM market_margin_daily
            ORDER BY REPLACE(CAST(date AS TEXT),'-','') DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    finally:
        con.close()
    return [
        {
            "date": _ymd(r[0]),
            "margin_bal_k": _finite(r[1]),
            "margin_delta_k": _finite(r[2]),
            "source": str(r[3] or ""),
        }
        for r in rows
    ]


def load_jiuha_mains(corpus_db: str) -> List[Dict[str, Any]]:
    if not corpus_db or not os.path.isfile(corpus_db):
        return []
    con = sqlite3.connect(corpus_db, timeout=30.0)
    try:
        rows = con.execute(
            """
            SELECT article_id, title, published_at_taipei, text, image_paths_json, source_url
            FROM records
            WHERE kind='main' AND is_author_judgment=1
            ORDER BY published_at_taipei DESC
            """
        ).fetchall()
    finally:
        con.close()
    out: List[Dict[str, Any]] = []
    for r in rows:
        pub = str(r[2] or "")
        day = _ymd(pub[:10].replace("-", "")) if pub else ""
        if not day and pub:
            day = _ymd(pub)
        imgs: List[str] = []
        try:
            imgs = list(json.loads(r[4] or "[]"))
        except Exception:
            imgs = []
        out.append(
            {
                "article_id": str(r[0]),
                "title": str(r[1] or ""),
                "published_at_taipei": pub,
                "asof": day,
                "text": str(r[3] or ""),
                "images": imgs,
                "source_url": str(r[5] or ""),
            }
        )
    return out


_LEVEL_RE = re.compile(
    r"(?<![\d.])(\d{2,3}(?:,\d{3})+(?:\.\d+)?|\d{4,5}(?:\.\d+)?)(?!\d)"
)
_TICKER_RE = re.compile(r"(?<!\d)([0-9]{4}(?:L|R)?)(?!\d)")


def extract_mentioned_levels(text: str) -> List[float]:
    """抽可能的加權點位（粗篩；之後用當日高低窗過濾）。"""
    out: List[float] = []
    for m in _LEVEL_RE.finditer(text or ""):
        raw = m.group(1).replace(",", "")
        v = _finite(raw)
        if v is None:
            continue
        if 8000 <= v <= 60000:
            out.append(v)
    # 去重保序
    seen = set()
    uniq: List[float] = []
    for v in out:
        if v in seen:
            continue
        seen.add(v)
        uniq.append(v)
    return uniq


def extract_tickers(text: str) -> List[str]:
    skip = {
        "2025",
        "2026",
        "2024",
        "2020",
        "2015",
        "119%",
    }
    out: List[str] = []
    for m in _TICKER_RE.finditer(text or ""):
        t = m.group(1)
        if t in skip:
            continue
        # 常見槓桿 ETF 他點名
        if t.endswith(("L", "R")) or t in {
            "00631",
            "00663",
            "00675",
            "00685",
            "00632",
        }:
            out.append(t if t[-1] in "LR" else t)
            continue
        if len(t) == 4 and t.isdigit():
            # 四碼股；排除明顯年份殘段已 skip
            out.append(t)
    seen = set()
    uniq: List[str] = []
    for t in out:
        if t in seen:
            continue
        seen.add(t)
        uniq.append(t)
    return uniq[:30]


def align_post_to_bar(
    post: Dict[str, Any], twii: Sequence[Bar]
) -> Dict[str, Any]:
    """主文日期對當日（或前一交易日）加權官方柱。"""
    by = {b.date: b for b in twii}
    asof = str(post.get("asof") or "")
    bar = by.get(asof)
    note = "exact"
    if bar is None and asof:
        # 假日文 → 往前找最近有柱日
        older = [b for b in twii if b.date <= asof]
        if older:
            bar = older[0]
            note = f"prev_session:{bar.date}"
        else:
            note = "no_bar"
    levels = extract_mentioned_levels(str(post.get("text") or ""))
    hit: List[Dict[str, Any]] = []
    if bar and levels:
        lo = _finite(bar.low)
        hi = _finite(bar.high)
        cl = _finite(bar.close)
        for lv in levels:
            inside = lo is not None and hi is not None and lo <= lv <= hi
            hit.append(
                {
                    "level": lv,
                    "inside_bar": bool(inside),
                    "vs_close_pct": _pct(cl, lv),
                }
            )
    return {
        "article_id": post.get("article_id"),
        "title": post.get("title"),
        "post_asof": asof,
        "bar_date": bar.date if bar else "",
        "align": note,
        "twii_ohlc": (
            {
                "o": bar.open,
                "h": bar.high,
                "l": bar.low,
                "c": bar.close,
                "v": bar.volume,
            }
            if bar
            else {}
        ),
        "mentioned_levels": levels[:20],
        "level_hits": hit[:20],
        "tickers": extract_tickers(str(post.get("text") or "")),
    }


def _bar_by_date(bars: Sequence[Bar]) -> Dict[str, Bar]:
    return {b.date: b for b in bars if b.date}


def compute_daily_structure(
    market_db: str,
    *,
    asof: str = "",
) -> Dict[str, Any]:
    """依啾哈原則可量化的每日盤勢結構（觀察用，非買訊）。"""
    twii = load_index_bars(market_db, "TWII", limit=80)
    otc = load_index_bars(market_db, "OTC", limit=80)
    fx = load_index_bars(market_db, "USDTWD", limit=80)
    margin = load_margin_series(market_db, limit=40)
    if not twii:
        return {"ok": False, "note": "缺加權官方柱", "asof": asof}
    day = asof or twii[0].date
    # 若指定日無柱，用最新已收
    twii_by = _bar_by_date(twii)
    if day not in twii_by:
        day = twii[0].date
    b0 = twii_by[day]
    # 前一交易日
    older = [b for b in twii if b.date < day]
    b1 = older[0] if older else None
    # 近 5／20 日均量
    window = [b for b in twii if b.date <= day][:21]
    vols = [b.volume for b in window[1:6] if b.volume]
    vol20 = [b.volume for b in window[1:21] if b.volume]
    avg5 = sum(vols) / len(vols) if vols else None
    avg20 = sum(vol20) / len(vol20) if vol20 else None

    chg = _pct(b0.close, b1.close) if b1 else None
    vol_vs_5 = (
        (b0.volume / avg5) if (b0.volume is not None and avg5) else None
    )
    vol_vs_20 = (
        (b0.volume / avg20) if (b0.volume is not None and avg20) else None
    )

    # 櫃買相對
    otc_by = _bar_by_date(otc)
    o0 = otc_by.get(day)
    o1 = None
    if o0:
        o_older = [b for b in otc if b.date < day]
        o1 = o_older[0] if o_older else None
    otc_chg = _pct(o0.close, o1.close) if (o0 and o1) else None
    otc_lead = None
    if chg is not None and otc_chg is not None:
        otc_lead = otc_chg - chg

    # 融資速度差（對近期有融資列的窗口）
    m_by = {m["date"]: m for m in margin}
    m0 = m_by.get(day)
    # 找 day 之前最近一筆融資
    m_prev = None
    for m in margin:
        if m["date"] < day:
            m_prev = m
            break
    margin_chg = None
    speed_gap = None
    if m0 and m_prev and m_prev.get("margin_bal_k"):
        margin_chg = _pct(m0.get("margin_bal_k"), m_prev.get("margin_bal_k"))
        # 同窗指數跌幅：m_prev.date → day
        tw_a = twii_by.get(m_prev["date"])
        if tw_a and margin_chg is not None and chg is not None:
            # 用融資兩點之間的指數變化更貼他的「速度差」
            idx_span = _pct(b0.close, tw_a.close)
            if idx_span is not None:
                # 去槓桿進度：融資跌幅 − 指數跌幅（融資更負＝洗得較徹）
                speed_gap = margin_chg - idx_span

    # 台幣
    fx_by = _bar_by_date(fx)
    f0 = fx_by.get(day)
    if f0 is None and fx:
        # 允許匯率落後一日，但標 stale
        f_older = [b for b in fx if b.date <= day]
        f0 = f_older[0] if f_older else None
    f1 = None
    fx_stale = False
    if f0:
        fx_stale = f0.date != day
        f_prev = [b for b in fx if b.date < f0.date]
        f1 = f_prev[0] if f_prev else None
    fx_chg = _pct(f0.close, f1.close) if (f0 and f1) else None
    # 台幣升值＝USDTWD 下跌
    twd_stronger = (fx_chg is not None and fx_chg < 0)

    # 結構標籤（觀察用語，沿他的詞）
    labels: List[str] = []
    if chg is not None and vol_vs_5 is not None:
        if chg > 1.5 and vol_vs_5 < 0.85:
            labels.append("縮量反彈／疑空手回補")
        if chg < -1.5 and vol_vs_5 >= 1.5:
            labels.append("爆量下跌／出貨或恐慌換手待辨")
        if chg > 1.5 and vol_vs_5 >= 1.2:
            labels.append("帶量上攻／較接近新錢假設")
    if otc_lead is not None:
        if otc_lead > 0.5:
            labels.append("櫃買相對強於加權")
        elif otc_lead < -0.5:
            labels.append("櫃買弱於加權／融資壓力警訊")
    if speed_gap is not None:
        if speed_gap < -5:
            labels.append("融資跌更快＝去槓桿有進度")
        elif speed_gap > 2 and chg is not None and chg < 0:
            labels.append("指數跌但融資未更快降＝清算不足")
    if twd_stronger:
        labels.append("台幣偏升（資金面偏暖訊號之一）")
    elif fx_chg is not None and fx_chg > 0.15:
        labels.append("台幣偏貶（資金面壓力訊號之一）")

    focus: List[str] = []
    # 順序對齊 DESK_LAYERS（L0→L5）；辯論四組共識
    focus.append("L0 存活閘：停損與最大虧損有無預設；現金／槓桿是否先理好")
    focus.append("L1 天氣：台幣＋外資現貨／期貨是否同向改善（缺列則標缺）")
    focus.append("L1 反轉三同步：減空×現貨轉買×台幣升值；缺一則大反彈偏逃命窗")
    focus.append("L3 融資速度差 vs 指數；正二融資是否停加／連續減")
    focus.append("L3 真假換手三點：正二連續減×空單回補×新融資未立刻被洗")
    focus.append("L3 櫃買是否比加權先止穩（融資止血）")
    focus.append("L4 若反彈：是否帶量；縮量大漲當逃命窗而非追高證成")
    focus.append("L4 開盤至午前量能：有無換手，或量縮鎖死")
    focus.append("L2／P11 內資／ETF／官股恐慌承接（敘事觀察；申贖／官股列缺則標缺）")
    focus.append("L5 控車：空手／減碼／避險／等待（禁止建議買入）")
    if any("假突破" in (x or "") for x in labels) or (
        chg is not None and chg < -2 and vol_vs_5 and vol_vs_5 >= 1.3
    ):
        focus.insert(
            7,
            "L4 若有頸線／前高試探：突破幅度是否達有效門檻，收盤是否仍站上",
        )

    missing: List[str] = []
    if o0 is None:
        missing.append("櫃買當日柱")
    if m0 is None:
        missing.append("市場融資當日列")
    if f0 is None:
        missing.append("美金台幣")
    elif fx_stale:
        missing.append(f"美金台幣僅至{f0.date}")
    missing.append("外資期貨淨空口數（官方列未接則每日缺）")
    missing.append("開盤15分成交金額（需分K／另源）")

    return {
        "ok": True,
        "asof": day,
        "author": AUTHOR_NAME,
        "not_buy_signal": True,
        "twii": {
            "close": b0.close,
            "chg_pct": None if chg is None else round(chg, 2),
            "volume": b0.volume,
            "vol_vs_5": None if vol_vs_5 is None else round(vol_vs_5, 2),
            "vol_vs_20": None if vol_vs_20 is None else round(vol_vs_20, 2),
        },
        "otc": {
            "close": o0.close if o0 else None,
            "chg_pct": None if otc_chg is None else round(otc_chg, 2),
            "rel_vs_twii_pp": None if otc_lead is None else round(otc_lead, 2),
            "asof": o0.date if o0 else "",
        },
        "margin": {
            "bal_k": m0.get("margin_bal_k") if m0 else None,
            "delta_k": m0.get("margin_delta_k") if m0 else None,
            "chg_pct_vs_prev_row": (
                None if margin_chg is None else round(margin_chg, 2)
            ),
            "speed_gap_pp": None if speed_gap is None else round(speed_gap, 2),
            "asof": m0["date"] if m0 else "",
            "source": m0.get("source") if m0 else "",
        },
        "usdtwd": {
            "close": f0.close if f0 else None,
            "chg_pct": None if fx_chg is None else round(fx_chg, 3),
            "asof": f0.date if f0 else "",
            "stale": fx_stale,
        },
        "structure_labels": labels,
        "focus": focus,
        "missing_official": missing,
        "principles_used": [p["id"] for p in PRINCIPLES],
    }


def build_alignment_report(
    corpus_db: str,
    market_db: str,
    *,
    limit_posts: int = 80,
) -> Dict[str, Any]:
    posts = load_jiuha_mains(corpus_db)[:limit_posts]
    # 語料可跨兩年以上；400 根不夠蓋到最早主文
    twii = load_index_bars(market_db, "TWII", limit=900)
    rows = [align_post_to_bar(p, twii) for p in posts]
    return {
        "author": AUTHOR_NAME,
        "author_id": AUTHOR_ID,
        "n_posts": len(posts),
        "n_aligned": sum(1 for r in rows if r.get("bar_date")),
        "rows": rows,
        "principles": PRINCIPLES,
    }


def render_daily_markdown(pack: Dict[str, Any]) -> str:
    if not pack.get("ok"):
        return f"# 啾哈觀察（非買訊）\n\n缺資料：{pack.get('note')}\n"
    tw = pack.get("twii") or {}
    otc = pack.get("otc") or {}
    mg = pack.get("margin") or {}
    fx = pack.get("usdtwd") or {}
    lines = [
        f"# 啾哈盤勢結構觀察 {pack.get('asof')}（非買訊）",
        "",
        f"- 加權收 {tw.get('close')}（{tw.get('chg_pct')}%），量／5日均 {tw.get('vol_vs_5')}、／20日均 {tw.get('vol_vs_20')}",
        f"- 櫃買 {otc.get('close')}（{otc.get('chg_pct')}%），相對加權 {otc.get('rel_vs_twii_pp')} pp（柱日 {otc.get('asof') or '—'}）",
        f"- 融資餘額變動 {mg.get('chg_pct_vs_prev_row')}%，速度差 {mg.get('speed_gap_pp')} pp（融資日 {mg.get('asof') or '—'}）",
        f"- 美金台幣 {fx.get('close')}（{fx.get('chg_pct')}%）{'［落後］' if fx.get('stale') else ''}",
        "",
        "## 結構標籤",
    ]
    labs = pack.get("structure_labels") or []
    if labs:
        lines.extend(f"- {x}" for x in labs)
    else:
        lines.append("- （當日條件未觸發明確標籤）")
    lines += ["", "## 今日重點觀察"]
    lines.extend(
        f"{i}. {x}" for i, x in enumerate(pack.get("focus") or [], 1)
    )
    miss = pack.get("missing_official") or []
    if miss:
        lines += ["", "## 官方缺欄（不准假填）"]
        lines.extend(f"- {x}" for x in miss)
    lines += ["", "## 儀表層級（L0→L5）"]
    lines.extend(f"- {x['id']} {x['title']}：{x['hint']}" for x in DESK_LAYERS)
    lines += [
        "",
        "## 原則依據（原文證據）",
    ]
    for p in PRINCIPLES:
        lines.append(
            f"- `{p['id']}` {p['title']} ← 文 {', '.join(p['evidence'])}"
        )
    lines.append("")
    lines.append("估值／結構觀察 ≠ 買訊。切入仍只認已量化過關的高低卡規則。")
    return "\n".join(lines) + "\n"


def write_daily_artifacts(
    *,
    corpus_db: str = str(DEFAULT_CORPUS),
    market_db: str = str(DEFAULT_MARKET),
    out_dir: str = str(DEFAULT_OUT),
    asof: str = "",
) -> Dict[str, Any]:
    outp = Path(out_dir)
    outp.mkdir(parents=True, exist_ok=True)
    daily = compute_daily_structure(market_db, asof=asof)
    align = build_alignment_report(corpus_db, market_db)
    md = render_daily_markdown(daily)
    stamp = daily.get("asof") or _ymd(datetime.now(TAIPEI).strftime("%Y%m%d"))
    md_path = outp / f"daily_structure_{stamp}.md"
    json_path = outp / f"daily_structure_{stamp}.json"
    align_path = outp / "alignment_latest.json"
    principles_path = outp / "principles.json"
    md_path.write_text(md, encoding="utf-8")
    json_path.write_text(
        json.dumps(daily, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    align_path.write_text(
        json.dumps(align, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    principles_path.write_text(
        json.dumps(PRINCIPLES, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return {
        "ok": bool(daily.get("ok")),
        "asof": stamp,
        "md": str(md_path),
        "json": str(json_path),
        "align": str(align_path),
        "principles": str(principles_path),
        "n_posts": align.get("n_posts"),
        "daily": daily,
    }


__all__ = [
    "PRINCIPLES",
    "align_post_to_bar",
    "build_alignment_report",
    "compute_daily_structure",
    "load_jiuha_mains",
    "render_daily_markdown",
    "write_daily_artifacts",
]
