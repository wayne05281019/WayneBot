"""查股名稱：撞名列出、讀音／錯字建議。不硬編個股。

記得名字但國字不準、KY 後綴打不對時，用讀音與近似拼音對目錄，
列出候選請使用者點確認，不直接出圖。
"""
from __future__ import annotations

import re
import unicodedata
from typing import Any, Dict, List, Sequence

# 國字少於 2 個不做讀音猜（「台」「光」會對到半個市場）。
_MIN_CJK = 2
FUZZY_MIN_SCORE = 72

_KY_TAIL_RE = re.compile(
    r"(?:[\s\-－─_‧・·.]*)(?:KY|ｋｙ|ＫＹ)$",
    re.I,
)


def strip_lookup_name(s: str) -> str:
    """去空白、全形，拿掉結尾 KY／-KY，方便「譜瑞KY」「普瑞」對到「譜瑞-KY」。"""
    text = unicodedata.normalize("NFKC", (s or "").strip())
    text = re.sub(r"[\s\u3000]+", "", text)
    prev = None
    while text != prev:
        prev = text
        text = _KY_TAIL_RE.sub("", text)
    return text


def cjk_only(s: str) -> str:
    return "".join(ch for ch in (s or "") if "\u4e00" <= ch <= "\u9fff")


def _levenshtein(a: str, b: str) -> int:
    if a == b:
        return 0
    if not a:
        return len(b)
    if not b:
        return len(a)
    if abs(len(a) - len(b)) > 6:
        return 99
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, start=1):
        cur = [i]
        for j, cb in enumerate(b, start=1):
            cur.append(
                min(
                    cur[j - 1] + 1,
                    prev[j] + 1,
                    prev[j - 1] + (0 if ca == cb else 1),
                )
            )
        prev = cur
    return prev[-1]


def pinyin_syllables(s: str) -> List[str]:
    """只取中文讀音；KY、代號、標點不進音節。"""
    core = cjk_only(strip_lookup_name(s))
    if not core:
        return []
    from pypinyin import Style, lazy_pinyin

    out = []
    for syl in lazy_pinyin(core, style=Style.NORMAL):
        token = str(syl or "").strip().lower()
        if token and token not in {"-", "ky"}:
            out.append(token)
    return out


def name_match_score(query: str, stock_name: str) -> int:
    """0–100。字形相同較高；只靠讀音／近似拼音較低。"""
    q = strip_lookup_name(query)
    n = strip_lookup_name(stock_name)
    q_cjk = cjk_only(q)
    n_cjk = cjk_only(n)
    if len(q_cjk) < _MIN_CJK or not n_cjk:
        return 0
    if q == n or q_cjk == n_cjk:
        return 100
    if n.startswith(q) or n_cjk.startswith(q_cjk):
        return 92
    if q in n or q_cjk in n_cjk:
        return 84

    pq = pinyin_syllables(q)
    pn = pinyin_syllables(n)
    if not pq or not pn:
        return 0
    if pq == pn:
        return 96
    if len(pq) <= len(pn) and pn[: len(pq)] == pq:
        return 90

    if len(pq) <= len(pn):
        pen = 0
        for i, syl in enumerate(pq):
            d = _levenshtein(syl, pn[i])
            if d == 0:
                continue
            if d == 1:
                pen += 1
            else:
                pen += 3
        extra = len(pn) - len(pq)
        if pen == 0:
            return 90
        if pen == 1:
            return 82 if extra <= 2 else 76
        if pen == 2 and len(pq) >= 3:
            return 74

    cq = "".join(pq)
    cn = "".join(pn)
    if len(cq) >= 4 and cn.startswith(cq):
        return 88
    prefix = cn[: len(cq)] if len(cn) >= len(cq) else cn
    d_prefix = _levenshtein(cq, prefix)
    if d_prefix == 1 and len(cq) >= 4:
        return 80
    if d_prefix == 2 and len(cq) >= 6:
        return 72
    d_full = _levenshtein(cq, cn)
    mx = max(len(cq), len(cn), 1)
    if len(cq) >= 6 and d_full / mx <= 0.22:
        return 72
    return 0


def name_is_exact_hit(query: str, stock_name: str) -> bool:
    """去掉 KY 後，打的字就是這檔股名（南亞科不算南亞）。"""
    q = strip_lookup_name(query)
    n = strip_lookup_name(stock_name)
    if q and q == n:
        return True
    qc = cjk_only(q)
    nc = cjk_only(n)
    return bool(qc) and qc == nc


def hits_need_picker(hits: Sequence[Dict[str, Any]] | None) -> bool:
    """讀音猜中即使只有一檔也要確認；字形命中多檔也要選。"""
    rows = list(hits or [])
    if not rows:
        return False
    if any(h.get("fuzzy") for h in rows):
        return True
    return len(rows) > 1


def lookup_picker_lead(hits: Sequence[Dict[str, Any]] | None) -> str:
    rows = list(hits or [])
    if any(h.get("category") for h in rows):
        label = str(rows[0].get("category_label") or "ETF").strip() or "ETF"
        return f"這些是成交量較大的{label}，點左邊看這檔。"
    if any(h.get("fuzzy") for h in rows):
        if len(rows) == 1:
            return "沒打準，是不是這一檔？點左邊確認。"
        return "沒打準，是不是要找這些？點左邊確認。"
    return "名稱相近，請選要看哪一檔。藍字＝奇摩；按鈕＝看這檔。"
