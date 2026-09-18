# -*- coding: utf-8 -*-
"""新文／自回先入匣，台北 02:00／開市日 13:00 才分進六顆神經元。開火只讀最近一句。

不是 CNN。不准等 Cursor 改 SYSTEM。路人引號不收。IET＝IET-KY 4971。
"""
from __future__ import annotations

import os
import re
import sqlite3
from typing import Any, Dict, List, Optional, Sequence, Tuple

NEURON_IDS = ("nest", "field", "leader", "tape", "hold", "doubt")

_DDL = """
CREATE TABLE IF NOT EXISTS biaoke_neuron_hits (
    post_id TEXT NOT NULL,
    neuron_id TEXT NOT NULL,
    stock_id TEXT NOT NULL DEFAULT '',
    stock_name TEXT NOT NULL DEFAULT '',
    post_date TEXT NOT NULL DEFAULT '',
    post_time TEXT NOT NULL DEFAULT '',
    snippet TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (post_id, neuron_id, stock_id)
);
CREATE INDEX IF NOT EXISTS idx_biaoke_neuron_hits_nid
    ON biaoke_neuron_hits(neuron_id, post_date, post_time);
"""

_PAT: Dict[str, re.Pattern[str]] = {
    "nest": re.compile(
        r"(逃命波|C波|C-2|C-3|C-1|C-5|位階二|右肩|修正末端|第五波測底|頭肩底|"
        r"細微波|加權|大盤|夜盤|43500|45839|47578|46506|確認末端|"
        r"築底|46767|45398|下降壓力線|成交金額|某商品|2天漲1000|36000|9波|橫台|"
        r"沒表態|高檔震盪|只能上不能下|周四|鏡射|10月中|升息|11月|輪漲|輪動|"
        r"假突破|做頭)"
    ),
    "field": re.compile(
        r"(產業|主戰場|CCL|InP|散熱|光通訊|光學|PCB|F10|ABF|記憶體|"
        r"下飄旗|矽光子|高階測試|CPO|FAU|散熱轉弱|僅次於InP|ASIC|"
        r"新族群|蠢蠢欲動|指引去找|從底部找落後|封測)"
    ),
    "leader": re.compile(r"(龍頭|護城河|次族群|一軍|二軍|風向球|第一名|僅次於InP)"),
    "tape": re.compile(
        r"(破撐|跌破支撐|站回|洗盤|爆量|量縮|破線|支撐區|出貨|"
        r"裸K|先看量|籌碼交換|假跌破|止漲整理|跌破平台|轉折K|"
        r"碎形|關鍵K|爆大量|回測頸線|頸線|強勢整理|超強整理|拉回淺|"
        r"整理完成|回測洗盤|只能上不能下|模糊地帶|三日低點|跌到|"
        r"調整持股|主力|非常嚴重)"
    ),
    "hold": re.compile(
        r"(長抱|調節|抽出|出清|勿輕易|可抱到|先賣|不用管|沒破線|續抱|止漲整理|"
        r"只能上不能下|減碼|抽回|不能買)"
    ),
    "doubt": re.compile(
        r"(不是已確認|言之過早|無法判斷|模糊|證據不足|不能保證|"
        r"點到為止|還沒改口|無法保證|風險也很大|過幾天|不敢保證|"
        r"非常不正常)"
    ),
}
_SPACE = re.compile(r"\s+")
_PUNCT = re.compile(r"[。；！？\n，、]")
# 沒點檔的 C 波調節／抽出是巢穴，不准當每檔 live hold。
_INDEX_HOLD = re.compile(r"(C-[1235]|逃命波|43500|46767|45398|大盤|加權|夜盤|位階)")
# 量價／進出／看錯跟最近那檔走；產業／龍頭一句可點多檔。
_NEAR_NIDS = frozenset({"tape", "hold", "doubt"})


def ensure_neuron_hits_table(db_path: str) -> None:
    if not db_path:
        return
    parent = os.path.dirname(os.path.abspath(db_path))
    if parent:
        os.makedirs(parent, exist_ok=True)
    conn = sqlite3.connect(db_path, timeout=30.0)
    try:
        conn.executescript(_DDL)
        conn.commit()
    finally:
        conn.close()


def _spoken(raw: str) -> str:
    try:
        from biaoke_ingest import spoken_text

        return spoken_text(raw or "")
    except Exception:
        return str(raw or "").strip()


def _snip(text: str, needle: str = "", n: int = 96, *, near: str = "") -> str:
    """摘句對齊檔名或標點，不准從半個字開始、也不准兩檔共用一句。"""
    blob = _SPACE.sub(" ", text or "").strip()
    if not blob:
        return ""
    i = blob.find(near) if near else -1
    if i < 0 and needle:
        i = blob.find(needle)
    if i < 0:
        return blob[:n]
    window = blob[max(0, i - 24) : i]
    last = None
    for m in _PUNCT.finditer(window):
        last = m
    a = (max(0, i - 24) + last.end()) if last else i
    return blob[a : a + n].lstrip("，、；。 ")


def _names_for_sid(sid: str, shown: str) -> List[str]:
    names = [shown] if shown else []
    try:
        from biaoke_why import _NAME_SID

        for n, s in _NAME_SID.items():
            if str(s) == str(sid) and n and n not in names:
                names.append(n)
    except Exception:
        pass
    return names


def _nearest_sid(
    blob: str, pos: int, stocks: Sequence[Tuple[str, str]]
) -> str:
    """針落到哪、就只進那檔。鑑測轉折K 不准把調節奇鋐寫進健策 hold。"""
    best_sid = ""
    best_d = 10**9
    for sid, shown in stocks:
        for nm in _names_for_sid(sid, shown):
            start = 0
            while True:
                k = blob.find(nm, start)
                if k < 0:
                    break
                d = abs(k - pos)
                if d < best_d:
                    best_d = d
                    best_sid = sid
                start = k + max(1, len(nm))
    return best_sid


def classify_spoken(text: str, tags: Optional[Sequence[Any]] = None) -> List[Dict[str, str]]:
    """一句他的話 → 進哪幾顆、點了哪幾檔。沒點檔的產業／大盤 sid 空白。"""
    spoken = _spoken(text)
    if not spoken:
        return []
    hit_nids = [nid for nid, pat in _PAT.items() if pat.search(spoken)]
    if not hit_nids:
        return []
    try:
        from biaoke_tape import named_pairs

        pairs = named_pairs(text, tags)
    except Exception:
        pairs = []
    stocks = [(str(s), str(n)) for s, n in pairs if str(s) and str(s) != "TWII"]
    out: List[Dict[str, str]] = []
    seen = set()
    indexish = any(s == "TWII" for s, _n in pairs) or bool(
        re.search(r"(大盤|加權|台指|夜盤|逃命波|C-[123]|位階)", spoken)
    )
    for nid in hit_nids:
        needle = ""
        m = _PAT[nid].search(spoken)
        if m:
            needle = m.group(0)
        if nid == "nest":
            sid, name = ("TWII", "加權") if indexish else ("", "")
            key = (nid, sid)
            if key not in seen:
                seen.add(key)
                out.append(
                    {
                        "neuron": nid,
                        "sid": sid,
                        "name": name,
                        "snippet": _snip(spoken, needle),
                    }
                )
            continue
        if nid == "hold" and not stocks and _INDEX_HOLD.search(spoken):
            continue
        spoken_has_name = any(
            nm and nm in spoken
            for sid, shown in stocks
            for nm in _names_for_sid(sid, shown)
        )
        targets = stocks or [("", "")]
        if stocks and not spoken_has_name:
            targets = [("", "")]
        multi = len(stocks) > 1 and spoken_has_name
        for sid, name in targets:
            use_needle = needle
            if multi and name and nid in _NEAR_NIDS:
                keep = False
                for m2 in _PAT[nid].finditer(spoken):
                    if _nearest_sid(spoken, m2.start(), stocks) == sid:
                        keep = True
                        use_needle = m2.group(0) or needle
                        break
                if not keep:
                    continue
            key = (nid, sid)
            if key in seen:
                continue
            seen.add(key)
            out.append(
                {
                    "neuron": nid,
                    "sid": sid,
                    "name": name,
                    "snippet": _snip(spoken, use_needle, near=name),
                }
            )
    return out


def record_neuron_events(db_path: str, events: Sequence[Dict[str, Any]]) -> int:
    """捕獲後立刻寫進六顆。同一則先刪再寫，舊分類不准留下來累積。"""
    if not db_path:
        return 0
    ensure_neuron_hits_table(db_path)
    rows: List[Tuple[Any, ...]] = []
    pids: List[str] = []
    seen_pid = set()
    for ev in events:
        if str(ev.get("kind") or "") == "bystander":
            continue
        pid = str(ev.get("id") or ev.get("post_id") or "").strip()
        raw = str(ev.get("text") or "").strip()
        if not pid or not raw:
            continue
        if pid not in seen_pid:
            seen_pid.add(pid)
            pids.append(pid)
        day = str(ev.get("date") or "")
        hm = str(ev.get("time") or "")
        for hit in classify_spoken(raw, ev.get("tags")):
            rows.append(
                (
                    pid,
                    hit["neuron"],
                    hit["sid"],
                    hit["name"],
                    day,
                    hm,
                    hit["snippet"],
                )
            )
    if not pids:
        return 0
    conn = sqlite3.connect(db_path, timeout=30.0)
    try:
        conn.executemany(
            "DELETE FROM biaoke_neuron_hits WHERE post_id=?",
            [(p,) for p in pids],
        )
        if rows:
            conn.executemany(
                """
                INSERT INTO biaoke_neuron_hits
                (post_id, neuron_id, stock_id, stock_name, post_date, post_time, snippet)
                VALUES (?,?,?,?,?,?,?)
                """,
                rows,
            )
        conn.commit()
    finally:
        conn.close()
    return len(rows)


def latest_bundle(db_path: str, sid: str = "", *, n: int = 3) -> Dict[str, str]:
    """開火一次讀六顆最近句。個股只收這檔；空 sid 不准蓋到健策／台光電。"""
    if not db_path or not os.path.isfile(db_path):
        return {}
    ensure_neuron_hits_table(db_path)
    want = str(sid or "").strip()
    lim = max(1, int(n))
    picked: Dict[str, List[str]] = {nid: [] for nid in NEURON_IDS}
    conn = sqlite3.connect(db_path, timeout=8.0)
    try:
        for nid in NEURON_IDS:
            try:
                if nid == "nest":
                    rows = conn.execute(
                        """
                        SELECT stock_id, post_date, post_time, snippet
                        FROM biaoke_neuron_hits
                        WHERE neuron_id='nest' AND (stock_id='' OR stock_id='TWII')
                        ORDER BY post_date DESC, post_time DESC
                        LIMIT ?
                        """,
                        (lim,),
                    ).fetchall()
                elif want:
                    rows = conn.execute(
                        """
                        SELECT stock_id, post_date, post_time, snippet
                        FROM biaoke_neuron_hits
                        WHERE neuron_id=? AND stock_id=?
                        ORDER BY post_date DESC, post_time DESC
                        LIMIT ?
                        """,
                        (nid, want, lim),
                    ).fetchall()
                else:
                    rows = conn.execute(
                        """
                        SELECT stock_id, post_date, post_time, snippet
                        FROM biaoke_neuron_hits
                        WHERE neuron_id=? AND IFNULL(stock_id,'')=''
                        ORDER BY post_date DESC, post_time DESC
                        LIMIT ?
                        """,
                        (nid, lim),
                    ).fetchall()
            except sqlite3.Error:
                rows = []
            for _stock, day, hm, snip in rows:
                snip = _SPACE.sub(" ", str(snip or "")).strip()
                if not snip:
                    continue
                stamp = " ".join(x for x in (str(day or ""), str(hm or "")) if x)
                picked[nid].append(f"{stamp} {snip}".strip() if stamp else snip)
    finally:
        conn.close()
    return {k: "；".join(v) for k, v in picked.items() if v}


def backfill_recent_neurons(db_path: str, *, n: int = 160) -> int:
    """庫裡最近主文／自回補進六顆。UPSERT，不重掃 1709。"""
    if not db_path or not os.path.isfile(db_path):
        return 0
    conn = sqlite3.connect(db_path, timeout=15.0)
    try:
        hit = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='biaoke_posts'"
        ).fetchone()
        if not hit:
            return 0
        rows = conn.execute(
            """
            SELECT id, date, time, kind, text FROM biaoke_posts
            WHERE IFNULL(kind,'post') != 'bystander'
            ORDER BY date DESC, time DESC LIMIT ?
            """,
            (max(24, int(n)),),
        ).fetchall()
    except sqlite3.Error:
        rows = []
    finally:
        conn.close()
    events = [
        {
            "id": r[0],
            "date": r[1],
            "time": r[2],
            "kind": r[3] or "post",
            "text": r[4] or "",
        }
        for r in rows
    ]
    return record_neuron_events(db_path, events)
