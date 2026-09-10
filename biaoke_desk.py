# -*- coding: utf-8 -*-
"""飆客獨立區：語料檢索與觀點頁。不進海選、不改高低卡。"""
from __future__ import annotations

import json
import os
import re
from functools import lru_cache
from typing import Any, Dict, List, Optional

from tg_layout import html_escape

_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "docs", "expert_notes", "飆客")
_INDEX = os.path.join(_DIR, "corpus_index.json")

_YEAR_END = re.compile(r"(去年年底|去年底|年底|年終|過年|年終獎金|2025年底|12月)")
_PROGRESS = re.compile(r"(進步|怎麼觀察|如何觀察|為什麼進步|為何進步|觀察方法|細微波)")


@lru_cache(maxsize=1)
def load_corpus() -> Dict[str, Any]:
    with open(_INDEX, encoding="utf-8") as fh:
        return json.load(fh)


def corpus_span() -> str:
    blob = load_corpus()
    return f"{blob.get('from') or ''}～{blob.get('to') or ''}　{blob.get('n') or 0} 篇"


def format_biaoke_desk_html() -> str:
    span = html_escape(corpus_span())
    return (
        "<b>飆客獨立區</b>\n"
        "這區跟海選／高低卡無關，也不改黃金買點。來源是 CMoney「期股多空雙飆客」公開發文"
        f"（{span}）。不是買訊。\n"
        "\n"
        "<b>兩年進步在哪</b>\n"
        "2025 夏：點族群、半山腰用隔日沖、漲一倍見好就收。\n"
        "2025 秋：開始用波浪＋夜盤，但點位被拿去打台指期，11 月起大盤點位少公開。\n"
        "2025-11-21：公開檢討「該看台積電量價、不該只看大盤沒出量」。\n"
        "2025 年底～2026 初：主戰場改記憶體（南亞科／華邦電／群聯／模組），PCB／F4 做頭就撤。\n"
        "2026：費半當台股先行、台指期細微波數 5／9 段、資金水位跟波段走。這套觀察幾乎沒人公開這樣做。\n"
        "\n"
        "<b>他怎麼看</b>\n"
        "1 夜盤／台指期連續盤細微波（15 分＋60 分），不是只看加權日 K\n"
        "2 費半走勢先於台股（1-4 重疊＝下跌趨勢化解）\n"
        "3 台積電量價當龍頭領先，常常比大盤早一天止跌或轉弱\n"
        "4 同族群比整理時間、誰先測高，不比絕對漲跌\n"
        "5 KD／MACD／布林他不算技術分析；認支撐、窒息量、波浪段數\n"
        "6 半山腰只做隔日沖；整理末端或突破回測才抱波段；停損約 7～10%（長線龍頭另論）\n"
        "\n"
        "<b>問語料</b>\n"
        "打 <code>飆客 去年年底</code>、<code>飆客 勤誠</code>、<code>飆大 記憶體</code>。"
        "他當下沒點名的檔，用當時主文反查。"
    )


def _date_ok(post: Dict[str, Any], start: str, end: str) -> bool:
    d = str(post.get("date") or "")
    return start <= d <= end


def search_biaoke(ask: str, *, limit: int = 6) -> str:
    """關鍵字／時間查語料。不編新聞、不猜沒寫過的股票。"""
    q = (ask or "").strip()
    if not q:
        return format_biaoke_desk_html()
    if _PROGRESS.search(q) and not re.search(r"\d{4}", q):
        return format_biaoke_desk_html()

    blob = load_corpus()
    posts: List[Dict[str, Any]] = list(blob.get("posts") or [])
    start, end = "", "9999"
    title = f"飆客語料　{html_escape(q)}"
    year_end = bool(_YEAR_END.search(q))
    if year_end:
        start, end = "2025-11-15", "2026-01-20"
        title = "飆客　2025 年底～2026 年初在做什麼"
        head = (
            "當時主戰場是<b>記憶體</b>。"
            "12/17 起布局（群聯／華邦電量價到整理末端，盯美光財報）；"
            "之後南亞科、華邦電、群聯、模組（威剛／十銓）續抱。"
            "他明講：其他族群不要再介入，專心做記憶體。"
            "同時把 PCB／F4／散熱（台光電、金像電、金居、尖點、奇鋐、勤誠）當做出貨或做頭、要撤或等反彈出清。"
            "無塵室建廠（漢唐、聖暉、亞翔）12 月中有短暫配置。"
            "下面是原文摘錄。\n"
        )
    else:
        head = ""

    skip = {"飆客", "飆大", "AI飆客", "去年年底", "去年底", "年底", "年終"}
    keys = [k for k in re.split(r"[\s,，、]+", q) if k and k not in skip]
    scored: List[tuple] = []
    for p in posts:
        if start and not _date_ok(p, start, end):
            continue
        text = str(p.get("text") or "")
        tags = [str(t) for t in (p.get("tags") or [])]
        blob_l = text + " " + " ".join(tags)
        score = 2 if year_end else 0
        for k in keys:
            if k in tags:
                score += 6
            score += blob_l.count(k)
        if year_end and "記憶體" in tags:
            score += 8
        if score <= 0:
            continue
        scored.append((score, p))
    if year_end:
        # 「去年年底」先給 12 月，尤其 12/17 布局日；其餘由新到舊。
        scored.sort(
            key=lambda x: (
                0 if str(x[1].get("date") or "").startswith("2025-12") else 1,
                0 if str(x[1].get("date") or "") == "2025-12-17" else 1,
                -int(str(x[1].get("date") or "0").replace("-", "") or 0),
                -int(x[0]),
            )
        )
    else:
        scored.sort(
            key=lambda x: (
                -x[0],
                -int(str(x[1].get("date") or "0").replace("-", "") or 0),
            )
        )
    if not scored:
        return (
            f"<b>{title}</b>\n"
            "這批 520 篇裡沒對上。換股票名、族群或「去年年底」再問。"
            "這區不猜沒寫過的代號。"
        )
    lines = [f"<b>{title}</b>", head] if head else [f"<b>{title}</b>"]
    for _sc, p in scored[:limit]:
        tags = "、".join(html_escape(t) for t in (p.get("tags") or [])[:6])
        snip = html_escape(re.sub(r"\s+", " ", str(p.get("text") or ""))[:180])
        aid = html_escape(str(p.get("id") or ""))
        lines.append(
            f"{html_escape(p.get('date'))} {html_escape(p.get('time') or '')}"
            + (f"　{tags}" if tags else "")
            + "\n"
            + snip
            + (f"\nhttps://www.cmoney.tw/forum/article/{aid}" if aid else "")
        )
    return "\n\n".join(x for x in lines if x)


def format_biaoke_html(ask: Optional[str] = None) -> str:
    return search_biaoke(ask or "")
