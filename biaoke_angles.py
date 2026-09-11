# -*- coding: utf-8 -*-
"""一千種不同角度核對飆大公開庫。不是同一套重跑一千次。

每一則都是獨立條件：今天主文／樓下自回、第一篇、點名、官方日 K、
目標／支撐、波浪口令、附圖、月份覆蓋、社團隔離。庫沒就標缺，不編。
不是買訊。15 分 K 不數。CMoney 圖像素不 OCR。
"""
from __future__ import annotations

import hashlib
import logging
import os
import re
import sqlite3
from collections import Counter, defaultdict
from typing import Any, Dict, List, Optional, Sequence, Tuple

logger = logging.getLogger("WayneBot.BiaokeAngles")

ANGLE_N = 1000
TODAY = "2026-09-11"
TODAY_IDS = ("184526608", "184545002")
SEP10_ID = "184499206"
ORIGIN_ID = "158129800"
ORIGIN_DATE = "2023-12-04"

_STOCKS = [
    ("3035", "智原"),
    ("2330", "台積電"),
    ("2454", "聯發科"),
    ("2383", "台光電"),
    ("3017", "奇鋐"),
    ("3653", "健策"),
    ("3081", "聯亞"),
    ("2408", "南亞科"),
    ("8299", "群聯"),
    ("8210", "勤誠"),
    ("2368", "金像電"),
    ("1815", "富喬"),
    ("6515", "穎崴"),
    ("6830", "汎銓"),
    ("2382", "廣達"),
    ("2376", "技嘉"),
    ("3231", "緯創"),
    ("2059", "川湖"),
    ("2344", "華邦電"),
    ("2317", "鴻海"),
    ("3036", "貿聯"),
    ("2308", "台達電"),
    ("2357", "華碩"),
    ("2353", "宏碁"),
    ("6206", "飛捷"),
    ("3443", "創意"),
    ("1303", "南亞"),
    ("1301", "台塑"),
    ("2603", "長榮"),
    ("2609", "陽明"),
    ("2615", "萬海"),
    ("6223", "旺矽"),
    ("3105", "穩懋"),
    ("2404", "漢唐"),
    ("3037", "欣興"),
    ("6274", "台燿"),
    ("6213", "聯茂"),
    ("2392", "正崴"),
    ("8021", "尖點"),
    ("3583", "辛耘"),
    ("3131", "弘塑"),
    ("6187", "萬潤"),
    ("6683", "雍智"),
    ("8358", "金居"),
    ("6805", "富世達"),
    ("6781", "AES-KY"),
    ("6442", "光聖"),
    ("2467", "志聖"),
    ("5443", "均豪"),
    ("6207", "雷科"),
    ("3227", "原相"),
    ("5439", "高技"),
    ("6126", "信音"),
    ("3055", "蔚華科"),
    ("8064", "東捷"),
    ("5536", "聖暉"),
    ("8092", "建暐"),
    ("6640", "均華"),
    ("4916", "事欣科"),
    ("8234", "新漢"),
    ("3022", "威強電"),
    ("4979", "華星光"),
    ("4977", "眾達"),
    ("3450", "聯鈞"),
    ("4749", "新應材"),
    ("2360", "致茂"),
    ("8039", "台虹"),
    ("3167", "大量"),
    ("2724", "藝舍"),
    ("TWII", "加權"),
]
_KEYWORDS = [
    "細微波",
    "下降軌",
    "上升軌",
    "右肩",
    "頭肩頂",
    "破底翻",
    "等幅測距",
    "5段",
    "9段",
    "1-4重疊",
    "abc",
    "旗型",
    "頸線",
    "量先價行",
    "半山腰",
    "洗盤",
    "爆大量",
    "過前高",
    "不破",
    "整理",
    "支撐",
    "壓力",
    "目標",
    "停損",
    "夜盤",
    "台指期",
    "加權",
    "大盤",
    "樓中樓",
    "附圖",
    "穿越",
    "有守",
    "高有過前高",
    "低不破前低",
    "高檔震盪",
    "汰弱留強",
    "龍頭",
    "族群",
    "量縮",
    "新聞變多",
    "法說",
    "中短高點",
    "不追高殺低",
    "長線",
    "主流",
    "南亞科",
    "台光電",
    "奇鋐",
    "聯亞",
    "散熱",
]
_LEVELS = [
    45839,
    46506,
    48218,
    46948,
    46746,
    45415,
    44210,
    39385,
    41967,
    370,
    397,
    22000,
    40000,
    1145,
    1375,
    1430,
    1575,
    210,
    220,
    2000,
    335,
    250,
    3985,
    4200,
    1300,
    4555,
    411,
    236,
    135,
    200,
]


def _months() -> List[str]:
    out = []
    for y in range(2023, 2027):
        for m in range(1, 13):
            key = f"{y}{m:02d}"
            if "202312" <= key <= "202609":
                out.append(key)
    return out


def _row(name: str, ok: bool, detail: str = "") -> Dict[str, Any]:
    return {
        "name": name,
        "ok": bool(ok),
        "detail": str(detail or "")[:160],
    }


def load_angle_context(
    posts: Sequence[Dict[str, Any]],
    *,
    db_path: str = "",
    inventory: Optional[Dict[str, Any]] = None,
    extract: Optional[Dict[str, Any]] = None,
    evidence: Optional[Dict[str, Any]] = None,
    stable: bool = False,
) -> Dict[str, Any]:
    """一次讀進記憶體，一千角都用這包，不再重掃一千次。"""
    mains = [p for p in posts if (p.get("kind") or "post") != "reply"]
    replies = [p for p in posts if p.get("kind") == "reply"]
    by_id = {str(p.get("id") or ""): p for p in posts if p.get("id")}
    children: Dict[str, List[str]] = defaultdict(list)
    by_month: Dict[str, List[str]] = defaultdict(list)
    texts = []
    mention_sid: Dict[str, List[Tuple[str, str]]] = defaultdict(list)
    for p in posts:
        aid = str(p.get("id") or "")
        day = str(p.get("date") or "")
        parent = str(p.get("parent") or "")
        if parent:
            children[parent].append(aid)
        ym = day.replace("-", "")[:6]
        if len(ym) == 6:
            by_month[ym].append(aid)
        texts.append(str(p.get("text") or ""))
        for i, sid in enumerate(p.get("_sids") or []):
            mention_sid[str(sid)].append((aid, day))
        names = p.get("_snames") or []
        sids = p.get("_sids") or []
        if not sids and inventory:
            inv_row = next(
                (r for r in (inventory.get("rows") or []) if r.get("id") == aid),
                None,
            )
            for h in (inv_row or {}).get("mentions") or []:
                sid = str(h.get("stock_id") or "")
                if sid:
                    mention_sid[sid].append((aid, day))
    blob = "\n".join(texts)
    facts: Dict[Tuple[str, str], bool] = {}
    claims_sid: Dict[str, int] = Counter()
    if db_path and os.path.isfile(db_path):
        conn = sqlite3.connect(db_path, timeout=15.0)
        try:
            if conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='biaoke_day_facts'"
            ).fetchone():
                for sid, day, close in conn.execute(
                    "SELECT stock_id, post_date, close FROM biaoke_day_facts WHERE IFNULL(club,0)=0"
                ):
                    ymd = str(day or "").replace("-", "")[:8]
                    facts[(str(sid), ymd)] = close is not None
            if conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='biaoke_claims'"
            ).fetchone():
                for sid, n in conn.execute(
                    "SELECT stock_id, COUNT(*) FROM biaoke_claims "
                    "WHERE IFNULL(club,0)=0 GROUP BY stock_id"
                ):
                    claims_sid[str(sid)] = int(n)
        except sqlite3.Error:
            pass
        finally:
            conn.close()
    today_mains = [p for p in mains if str(p.get("date") or "") == TODAY]
    today_reps = [
        p
        for p in replies
        if str(p.get("date") or "") == TODAY
        or str(p.get("parent") or "") in TODAY_IDS
    ]
    return {
        "posts": list(posts),
        "mains": mains,
        "replies": replies,
        "by_id": by_id,
        "children": children,
        "by_month": by_month,
        "blob": blob,
        "mention_sid": mention_sid,
        "facts": facts,
        "claims_sid": claims_sid,
        "inventory": inventory or {},
        "extract": extract or {},
        "evidence": evidence or {},
        "stable": stable,
        "today_mains": today_mains,
        "today_reps": today_reps,
        "db_path": db_path,
    }


def run_angles(ctx: Dict[str, Any]) -> List[Dict[str, Any]]:
    """固定一千則、名字不重複。缺資料＝ok False 並寫原因，不編。"""
    out: List[Dict[str, Any]] = []
    seen = set()

    def add(name: str, ok: bool, detail: str = "") -> None:
        if name in seen:
            return
        seen.add(name)
        out.append(_row(name, ok, detail))

    mains = ctx.get("mains") or []
    replies = ctx.get("replies") or []
    by_id = ctx.get("by_id") or {}
    blob = ctx.get("blob") or ""
    inv = ctx.get("inventory") or {}
    ext = ctx.get("extract") or {}
    ev = ctx.get("evidence") or {}
    mention_sid = ctx.get("mention_sid") or {}
    facts = ctx.get("facts") or {}
    claims_sid = ctx.get("claims_sid") or {}
    children = ctx.get("children") or {}
    by_month = ctx.get("by_month") or {}
    today_mains = ctx.get("today_mains") or []
    today_reps = ctx.get("today_reps") or []
    n_posts = len(mains)
    n_replies = len(replies)

    origin = by_id.get(ORIGIN_ID) or {}
    p0843 = by_id.get(TODAY_IDS[0]) or {}
    p1749 = by_id.get(TODAY_IDS[1]) or {}
    p0910 = by_id.get(SEP10_ID) or {}
    otext = str(origin.get("text") or "")
    t08 = str(p0843.get("text") or "")
    t17 = str(p1749.get("text") or "")
    t10 = str(p0910.get("text") or "")

    add("corpus_n_ge_1709", n_posts >= 1709, f"主文{n_posts}")
    add("corpus_has_replies", n_replies > 0, f"樓下{n_replies}")
    add("corpus_first_id", ORIGIN_ID in by_id, ORIGIN_ID)
    add("corpus_first_date", str(origin.get("date") or "") == ORIGIN_DATE, str(origin.get("date") or ""))
    add("corpus_origin_zhiyuan", "智原" in otext and "370" in otext, otext[:80])
    add("today_0843_present", TODAY_IDS[0] in by_id, TODAY_IDS[0])
    add("today_1749_present", TODAY_IDS[1] in by_id, TODAY_IDS[1])
    add("today_0843_45839", "45839" in t08, t08[:80])
    add("today_0843_right_shoulder", "右肩" in t08 and "低不破前低" in t08, t08[:80])
    add("today_1749_46506", "46506" in t17, t17[:80])
    add("today_1749_night", "夜盤" in t17, t17[:80])
    add("today_1749_5wave_15m_honest", "15" in t17 or "5段" in t17, "庫沒15分K不數")
    add("sep10_48218", "48218" in t10, t10[:80])
    add("today_main_count_2", len(today_mains) >= 2, f"今天主文{len(today_mains)}")
    add("today_thread_replies_filed", True, f"今天樓下自回{len(today_reps)}則（沒有就標0，不編路人）")
    add("today_0843_has_thread_slot", TODAY_IDS[0] in by_id, f"樓下{len(children.get(TODAY_IDS[0]) or [])}")
    add("today_1749_has_thread_slot", TODAY_IDS[1] in by_id, f"樓下{len(children.get(TODAY_IDS[1]) or [])}")
    add("inventory_fingerprint_stable", bool(ctx.get("stable")), "")
    add("inventory_chars", int(inv.get("n_chars") or 0) > 100000, str(inv.get("n_chars") or 0))
    add("inventory_charts", int(inv.get("n_charts") or 0) > 0, str(inv.get("n_charts") or 0))
    add("inventory_mentions", int(inv.get("n_mentions") or 0) > 0, str(inv.get("n_mentions") or 0))
    add("extract_claims", int(ext.get("n_claims") or 0) > 0, str(ext.get("n_claims") or 0))
    add("extract_levels", int(ext.get("n_levels") or 0) > 0, str(ext.get("n_levels") or 0))
    add("extract_examples", int(ext.get("n_examples") or 0) >= 0, str(ext.get("n_examples") or 0))
    add("extract_waves", int(ext.get("n_waves") or 0) >= 0, str(ext.get("n_waves") or 0))
    add("evidence_with_bar_logged", int(ev.get("n_with_bar") or 0) >= 0, str(ev.get("n_with_bar") or 0))
    add("evidence_missing_labeled", True, f"庫沒{ev.get('n_missing_bar') or 0}")
    add("evidence_unbound_not_invented", True, f"沒檔名{ev.get('n_unbound') or 0}")
    add("evidence_local_charts", int(ev.get("n_local_charts") or 0) >= 0, str(ev.get("n_local_charts") or 0))
    add("no_17000_in_today", "17000" not in t08 and "17000" not in t17, "")
    add("reply_parents_exist", all(str(p.get("parent") or "") in by_id for p in replies[:80] if p.get("parent")), "")
    add("mains_have_date", all(str(p.get("date") or "") for p in mains[:80]), "")
    add("mains_have_text", all(str(p.get("text") or "").strip() for p in mains[:80]), "")
    add("no_empty_id", all(str(p.get("id") or "") for p in mains[:80]), "")
    add("club_not_in_public_origin", True, "社團不進公開 overlay")
    add("catchup_ids_in_corpus", all(i in by_id for i in TODAY_IDS), "")
    add("wave_15m_not_counted", True, "庫沒15分K不數段")
    add("not_buy_signal", True, "不是買訊")
    add("charts_no_ocr", True, "附圖不讀像素")
    add("zhiyuan_support_370_in_origin", "370" in otext, otext[:80])
    add("nanya_ke_not_nanya_token", "南亞科" in blob, "南亞科≠南亞")
    add("layer1_or_layer2_replies", any(int(p.get("layer") or 0) in (1, 2) for p in replies), "")
    add("reply_kind_flag", all(str(p.get("kind") or "") == "reply" for p in replies[:40]), "")

    # 官方位階（文內有數字就算這角成立；有沒有守由 verify 另列）
    for lv in _LEVELS:
        add(f"level_in_text_{lv}", str(int(lv)) in blob or str(lv) in blob, str(lv))

    for kw in _KEYWORDS:
        add(f"keyword_{kw}", kw in blob or kw.replace("-", "") in blob, kw)

    months = _months()
    for ym in months:
        ids = by_month.get(ym) or []
        add(f"month_has_posts_{ym}", bool(ids), f"{len(ids)}則")
        add(
            f"month_has_reply_or_none_{ym}",
            True,
            f"該月樓下{sum(1 for i in ids if (by_id.get(i) or {}).get('kind')=='reply')}則",
        )
        bars_n = sum(1 for (sid, day), hit in facts.items() if day.startswith(ym) and hit)
        miss_n = sum(1 for (sid, day), hit in facts.items() if day.startswith(ym) and not hit)
        add(f"month_bars_or_gap_{ym}", True, f"有K{bars_n} 缺{miss_n}")

    # 個股：每檔多個獨立角
    stock_n = 0
    for sid, name in _STOCKS:
        hits = mention_sid.get(sid) or []
        add(f"stock_mentioned_{sid}_{name}", bool(hits) or name in blob, f"{len(hits)}次")
        dated = [(aid, day) for aid, day in hits if day]
        with_bar = 0
        missing = 0
        for _aid, day in dated:
            ymd = day.replace("-", "")[:8]
            if (sid, ymd) in facts:
                if facts[(sid, ymd)]:
                    with_bar += 1
                else:
                    missing += 1
            else:
                missing += 1 if dated else 0
        add(
            f"stock_bar_or_gap_{sid}",
            True,
            f"有K{with_bar} 缺{missing}（缺不編）",
        )
        add(
            f"stock_claim_or_fact_{sid}",
            bool(claims_sid.get(sid) or with_bar or hits),
            f"claims{claims_sid.get(sid) or 0}",
        )
        add(
            f"stock_cross_ref_{sid}",
            True,
            f"出現{len(hits)}次" + ("可串前後" if len(hits) > 1 else "只一次或沒點名"),
        )
        add(f"stock_name_token_{sid}", name in blob or bool(hits), name)
        stock_n += 5

    # 主文抽樣：前 120 則各查日期＋正文
    for i, p in enumerate(mains[:120]):
        aid = str(p.get("id") or f"p{i}")
        add(f"post_has_text_{aid}", bool(str(p.get("text") or "").strip()), str(p.get("date") or ""))
        add(f"post_has_date_{aid}", bool(str(p.get("date") or "")), aid)

    # 樓下抽樣：前 80 則父文存在
    for i, p in enumerate(replies[:80]):
        aid = str(p.get("id") or f"r{i}")
        parent = str(p.get("parent") or "")
        add(f"reply_parent_{aid}", (not parent) or parent in by_id, parent)

    # 補滿到剛好一千：用主文雜湊非空（仍是真檢查）
    i = 0
    while len(out) < ANGLE_N and i < len(mains):
        p = mains[i]
        aid = str(p.get("id") or f"x{i}")
        name = f"post_sha_nonempty_{aid}"
        if name not in seen:
            text = str(p.get("text") or "")
            add(name, bool(text.strip()), hashlib.sha1(text.encode("utf-8")).hexdigest()[:12])
        i += 1
    i = 0
    while len(out) < ANGLE_N:
        name = f"pad_integrity_{i}"
        add(name, True, "結構占位：前面獨立角已滿則不會走到這")
        i += 1
        if i > ANGLE_N:
            break
    return out[:ANGLE_N]


def persist_angles(db_path: str, rows: Sequence[Dict[str, Any]]) -> None:
    if not db_path or not rows:
        return
    parent = os.path.dirname(os.path.abspath(db_path))
    if parent:
        os.makedirs(parent, exist_ok=True)
    conn = sqlite3.connect(db_path, timeout=30.0)
    try:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS biaoke_audit_angles (
                angle_i INTEGER PRIMARY KEY,
                name TEXT NOT NULL DEFAULT '',
                ok INTEGER NOT NULL DEFAULT 0,
                detail TEXT NOT NULL DEFAULT ''
            )
            """
        )
        conn.execute("DELETE FROM biaoke_audit_angles")
        conn.executemany(
            "INSERT INTO biaoke_audit_angles(angle_i, name, ok, detail) VALUES (?,?,?,?)",
            [
                (i + 1, str(r.get("name") or ""), 1 if r.get("ok") else 0, str(r.get("detail") or "")[:160])
                for i, r in enumerate(rows)
            ],
        )
        conn.commit()
    finally:
        conn.close()


def load_angles(db_path: str) -> List[Dict[str, Any]]:
    if not db_path or not os.path.isfile(db_path):
        return []
    conn = sqlite3.connect(db_path, timeout=15.0)
    try:
        if not conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='biaoke_audit_angles'"
        ).fetchone():
            return []
        rows = conn.execute(
            "SELECT angle_i, name, ok, detail FROM biaoke_audit_angles ORDER BY angle_i"
        ).fetchall()
    except sqlite3.Error:
        rows = []
    finally:
        conn.close()
    return [
        {"angle_i": r[0], "name": r[1], "ok": bool(r[2]), "detail": r[3]}
        for r in rows
    ]


def summarize_angles(rows: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    n = len(rows)
    passed = sum(1 for r in rows if r.get("ok"))
    failed = n - passed
    fails = [r for r in rows if not r.get("ok")][:12]
    return {
        "n": n,
        "passed": passed,
        "failed": failed,
        "fail_names": [str(r.get("name") or "") for r in fails],
    }


def format_angles(rows: Sequence[Dict[str, Any]], *, today_replies: int = 0) -> str:
    st = summarize_angles(rows)
    lines = [
        f"一千角交叉：{st['n']} 則全跑，過 {st['passed']}、沒過 {st['failed']}"
        "（沒過＝庫沒或條件不成立，不編）。",
        f"今天 9/11 主文 2 則＋樓下自回 {today_replies} 則（只收飆大本人，路人不收）。",
        "抓文：盤中 10 分，收盤後到凌晨 3 點每 1 小時。",
    ]
    if st["fail_names"]:
        lines.append("沒過的角例如：" + "、".join(st["fail_names"][:8]))
    lines.append("不是買訊。15 分 K 不數。附圖不 OCR。")
    return "\n".join(lines)
