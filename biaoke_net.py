# -*- coding: utf-8 -*-
"""飆大公開文節點網：同一檔／同一方法／樓中樓／時間序，只走鄰近幾則。

底圖是 Drive 公開主文＋樓中樓（約 1700 則主文），不是 git 裡 520 篇種子。
問句不把全庫塞進對話。有點位才對官方日 K。不進海選、不是買訊。
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Sequence, Tuple

from biaoke_link import graph_for

# 方法族＝一條連接。問到其中一個詞，就連同族其他節點。
FAMILIES: List[Tuple[str, re.Pattern[str]]] = [
    ("wash", re.compile(r"(洗盤|出貨|破線翻|破線洗盤)")),
    ("three", re.compile(r"(連三天|連三日|三日不破|三日之內|三日內|三日不回補|破三日低|假跌破)")),
    ("wave4", re.compile(r"(次級四|次級波|次級 4|次級4浪|回測四浪)")),
    ("micro", re.compile(r"(細微波|四步|15 分|15分|60 分|60分|波浪|位階|段數)")),
    ("label", re.compile(r"(多標籤|B-a-2|A-c-3|B-a-4|三種波浪)")),
    ("shoulder", re.compile(r"(右肩|45839|低不破前低|高有過前高|高檔震[盪檔]|汰弱留強)")),
    ("volfirst", re.compile(r"(量先價行|爆大量|價穩量縮|窒息量)")),
    ("buy3", re.compile(r"(三個買點|整理末端|突破回測|隔日沖|半山腰)")),
    ("rail", re.compile(r"(上升軌|下降壓|浪\s*2|浪\s*4|連線|黃軌|三角)")),
    ("leader", re.compile(r"(次族群|誰先過前高|領頭|族群發動)")),
    ("sox", re.compile(r"(費半|費城半導體|SOX|1[\s\-－]*4\s*重疊|一四重疊|１４重疊)")),
    ("news", re.compile(r"(新聞變多|法說|技術面領先)")),
]

_SKIP = {"飆客", "飆大", "AI飆客", "去年年底", "去年底", "年底", "年終"}
_TICKER_KEY = re.compile(r"^\d{4}$")


def family_ids(text: str) -> List[str]:
    blob = text or ""
    return [name for name, pat in FAMILIES if pat.search(blob)]


def _keys(ask: str) -> List[str]:
    """空白切開；黏在一起的「南亞科洗盤」也要拆出檔名與方法詞。"""
    parts = [k for k in re.split(r"[\s,，、]+", ask or "") if k and k not in _SKIP]
    out: List[str] = []
    seen: set[str] = set()

    def add(token: str) -> None:
        t = (token or "").strip()
        if not t or t in _SKIP or t in seen:
            return
        seen.add(t)
        out.append(t)

    for part in parts:
        add(part)
        blob = part
        for _name, pat in FAMILIES:
            for m in pat.finditer(blob):
                hit = m.group(0)
                add(hit)
                blob = blob.replace(hit, " ", 1)
        add(re.sub(r"\s+", "", blob))
    return out


def _ask_stock_keys(
    ask: str, *, db_path: str = ""
) -> Tuple[List[str], List[str]]:
    """口語「你怎麼看智邦」／「2345」→ 關鍵字＋代號。代號點名走 mentions，不靠正文撞數字。"""
    q = (ask or "").strip()
    keys = _keys(q)
    sids: List[str] = []
    core = ""
    try:
        from biaoke_facts import talk_core

        core = talk_core(q)
    except Exception:
        core = ""
    if core:
        for k in _keys(core):
            if k not in keys:
                keys.append(k)
    blobs = [q]
    if core and core != q:
        blobs.append(core)
    try:
        from biaoke_link import extract_mentions

        for blob in blobs:
            for hit in extract_mentions(blob, db_path=str(db_path or "")):
                name = str(hit.get("stock_name") or "").strip()
                sid = str(hit.get("stock_id") or "").strip()
                if name and name not in keys:
                    keys.append(name)
                if sid and sid not in sids:
                    sids.append(sid)
                if sid and sid not in keys:
                    keys.append(sid)
    except Exception:
        pass
    for blob in blobs:
        for m in re.finditer(r"(?<!\d)(\d{4})(?!\d)", blob or ""):
            sid = m.group(1)
            if sid.startswith(("19", "20")):
                continue
            if sid not in sids:
                sids.append(sid)
            if sid not in keys:
                keys.append(sid)
    return keys, sids


def score_post(
    post: Dict[str, Any],
    keys: Sequence[str],
    ask_families: Sequence[str],
    *,
    ask_sids: Sequence[str] = (),
    post_sids: Sequence[str] = (),
) -> int:
    tags = [str(t) for t in (post.get("tags") or [])]
    text = str(post.get("text") or "")
    if (post.get("kind") or "") == "reply":
        try:
            from biaoke_ingest import spoken_text

            text = spoken_text(text)
        except Exception:
            pass
    blob = text + " " + " ".join(tags)
    score = 0
    for k in keys:
        if _TICKER_KEY.match(k):
            # 正文「前高2345」是價位，不是點名智邦；代號只認 mentions／股名。
            continue
        if k in tags:
            score += 8
        score += blob.count(k)
    have = {str(s) for s in (post_sids or post.get("_sids") or []) if s}
    for sid in ask_sids or []:
        if sid and sid in have:
            score += 24
            if (post.get("kind") or "") == "reply":
                score += 12
    if ask_families:
        fams = family_ids(blob)
        score += 12 * sum(1 for f in ask_families if f in fams)
    return score


def related_posts(
    ask: str,
    posts: Sequence[Dict[str, Any]],
    *,
    limit: int = 6,
    db_path: str = "",
) -> List[Dict[str, Any]]:
    """問句 → 命中後走 2 跳：樓中樓、同代號（含最早一則）、同方法。最多 limit 則。"""
    q = (ask or "").strip()
    keys, ask_sids = _ask_stock_keys(q, db_path=str(db_path or ""))
    if not q or not posts:
        return []
    ask_fams = family_ids(q)
    if not keys and not ask_fams and not ask_sids:
        return []
    g = graph_for(posts, str(db_path or ""))
    scored: List[Tuple[int, Dict[str, Any]]] = []
    by_id = {str(p.get("id") or ""): p for p in posts if p.get("id")}
    for p in posts:
        aid = str(p.get("id") or "")
        post_sids = list(g.sids.get(aid) or p.get("_sids") or [])
        s = score_post(
            p, keys, ask_fams, ask_sids=ask_sids, post_sids=post_sids
        )
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
    seen: set = set()

    def add(p: Optional[Dict[str, Any]]) -> None:
        if not p:
            return
        aid = str(p.get("id") or "")
        if not aid or aid in seen:
            return
        gp = g.by_id.get(aid)
        row = gp if gp is not None else p
        if not row.get("_sids"):
            row["_sids"] = list(
                (gp or {}).get("_sids") or g.sids.get(aid) or []
            )
        if not row.get("_snames"):
            row["_snames"] = list((gp or {}).get("_snames") or [])
        seen.add(aid)
        out.append(row)

    # 先走問句對到的代號（樓下自回只寫「智邦」也能用 2345 問到）
    for sid in ask_sids:
        for p in g.newest(sid, skip=seen, limit=3):
            add(p)
            if len(out) >= cap:
                return out[:cap]
    for _s, p in scored[:2]:
        add(p)
    seed_sids = list(ask_sids) + [
        s for s in g.sids_of(out) if s not in ask_sids
    ]
    add(g.oldest(seed_sids))
    for p in list(out):
        parent = str(p.get("parent") or "")
        if parent:
            add(by_id.get(parent) or g.by_id.get(parent))
        for ch in (g.children.get(str(p.get("id") or "")) or [])[:2]:
            add(ch)
        if len(out) >= cap:
            return out[:cap]
    if len(out) >= cap:
        return out[:cap]
    for sid in seed_sids:
        for p in g.newest(sid, skip=seen, limit=2):
            add(p)
            if len(out) >= cap:
                return out[:cap]

    seed_tags = set()
    for p in out:
        seed_tags.update(str(t) for t in (p.get("tags") or []) if t)
        seed_tags.update(str(n) for n in (p.get("_snames") or []) if n)
    if seed_tags or ask_fams:
        extras: List[Tuple[int, Dict[str, Any]]] = []
        have = {str(p.get("id") or "") for p in out}
        for s, p in scored:
            aid = str(p.get("id") or "")
            if aid in have:
                continue
            gp = g.by_id.get(aid) or p
            tags = {str(t) for t in (gp.get("tags") or [])}
            names = {str(n) for n in (gp.get("_snames") or [])}
            fams = family_ids(str(gp.get("text") or "") + " " + " ".join(tags))
            hop = 0
            if seed_tags and (tags | names) & seed_tags:
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
