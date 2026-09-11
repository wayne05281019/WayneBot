# -*- coding: utf-8 -*-
"""飆大公開文節點網：同一檔／同一方法／樓中樓／時間序，只走鄰近幾則。

底圖是 Drive 公開主文＋樓中樓（約 1700 則主文），不是 git 裡 520 篇種子。
問句不把全庫塞進對話。有點位才對官方日 K。不進海選、不是買訊。
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Sequence, Tuple

# 方法族＝一條連接。問到其中一個詞，就連同族其他節點。
FAMILIES: List[Tuple[str, re.Pattern[str]]] = [
    ("wash", re.compile(r"(洗盤|出貨|破線翻|破線洗盤)")),
    ("three", re.compile(r"(連三天|連三日|三日不破|三日之內|三日內|三日不回補|破三日低|假跌破)")),
    ("wave4", re.compile(r"(次級四|次級波|次級 4|次級4浪|回測四浪)")),
    ("micro", re.compile(r"(細微波|四步|15 分|15分|60 分|60分)")),
    ("label", re.compile(r"(多標籤|B-a-2|A-c-3|B-a-4|三種波浪)")),
    ("shoulder", re.compile(r"(右肩|45839|低不破前低|高有過前高|高檔震[盪檔]|汰弱留強)")),
    ("volfirst", re.compile(r"(量先價行|爆大量|價穩量縮|窒息量)")),
    ("buy3", re.compile(r"(三個買點|整理末端|突破回測|隔日沖|半山腰)")),
    ("rail", re.compile(r"(上升軌|下降壓|浪\s*2|浪\s*4|連線|黃軌|三角)")),
    ("leader", re.compile(r"(次族群|誰先過前高|領頭|族群發動)")),
    ("sox", re.compile(r"(費半|1-4|１-４|一四重疊)")),
    ("news", re.compile(r"(新聞變多|法說|技術面領先)")),
]

_SKIP = {"飆客", "飆大", "AI飆客", "去年年底", "去年底", "年底", "年終"}


def family_ids(text: str) -> List[str]:
    blob = text or ""
    return [name for name, pat in FAMILIES if pat.search(blob)]


def _keys(ask: str) -> List[str]:
    return [k for k in re.split(r"[\s,，、]+", ask or "") if k and k not in _SKIP]


def score_post(post: Dict[str, Any], keys: Sequence[str], ask_families: Sequence[str]) -> int:
    tags = [str(t) for t in (post.get("tags") or [])]
    text = str(post.get("text") or "")
    blob = text + " " + " ".join(tags)
    score = 0
    for k in keys:
        if k in tags:
            score += 8
        score += blob.count(k)
    if ask_families:
        fams = family_ids(blob)
        score += 12 * sum(1 for f in ask_families if f in fams)
    return score


def related_posts(
    ask: str,
    posts: Sequence[Dict[str, Any]],
    *,
    limit: int = 6,
) -> List[Dict[str, Any]]:
    """問句 → 先命中，再走 1 跳：樓中樓主文、同檔、同方法。最多 limit 則。"""
    q = (ask or "").strip()
    keys = _keys(q)
    if not q or not posts:
        return []
    ask_fams = family_ids(q)
    if not keys and not ask_fams:
        return []
    scored: List[Tuple[int, Dict[str, Any]]] = []
    by_id = {str(p.get("id") or ""): p for p in posts if p.get("id")}
    for p in posts:
        s = score_post(p, keys, ask_fams)
        if s > 0:
            scored.append((s, p))
    scored.sort(
        key=lambda x: (
            -x[0],
            -int(str(x[1].get("date") or "0").replace("-", "") or 0),
        )
    )
    cap = max(1, int(limit))
    out: List[Dict[str, Any]] = []
    seen = set()

    def add(p: Optional[Dict[str, Any]]) -> None:
        if not p:
            return
        aid = str(p.get("id") or "")
        if not aid or aid in seen:
            return
        seen.add(aid)
        out.append(p)

    for _s, p in scored[: max(3, cap)]:
        add(p)
        parent = str(p.get("parent") or "")
        if parent:
            add(by_id.get(parent))
        if len(out) >= cap:
            return out[:cap]

    seed_tags = set()
    for p in out:
        seed_tags.update(str(t) for t in (p.get("tags") or []) if t)
    if seed_tags or ask_fams:
        extras: List[Tuple[int, Dict[str, Any]]] = []
        have = {str(p.get("id") or "") for p in out}
        for s, p in scored:
            aid = str(p.get("id") or "")
            if aid in have:
                continue
            tags = {str(t) for t in (p.get("tags") or [])}
            fams = family_ids(str(p.get("text") or "") + " " + " ".join(tags))
            hop = 0
            if seed_tags and tags & seed_tags:
                hop += 4
            if ask_fams and any(f in fams for f in ask_fams):
                hop += 3
            if hop:
                extras.append((hop * 1000 + s, p))
        extras.sort(key=lambda x: -x[0])
        for _s, p in extras:
            add(p)
            if len(out) >= cap:
                break
    return out[:cap]
