# -*- coding: utf-8 -*-
"""大盤波浪位階：只跟飆大自己點過的標籤走。

從他講過的時間往後對質：後來再點名，就拿先前那筆跟官方柱比。
不准發明 5／9 段、不准把波浪套個股、不准拿教科書升浪。
不是買訊。
"""
from __future__ import annotations

import os
import re
import sqlite3
from typing import Any, Dict, List, Optional, Sequence, Tuple

_WAVE_ASK = re.compile(
    r"(現在波浪位階|哪個位階|波浪位階|以波浪|"
    r"細微波|右肩型態|大盤現在|現在大盤|"
    r"上昇|上升還是下降|升浪還是|哪一浪|哪一波|"
    r"C-1|C-2|C-3|位階二|修正末端|測底|逃命波)"
)
_EYES_ASK = re.compile(
    r"(技術線圖|他看到什麼|看大盤轉折|轉折最準|沒人比|"
    r"怎麼判.{0,8}(大盤|轉折|位階)|用了?(什麼|啥)工具|"
    r"大盤對比類股|類股對比個股)"
)
_SKIP_FIFTH = re.compile(r"抱到.?2027|第五波漲勢結束")
_INDEX_CTX = re.compile(r"(大盤|加權|台指|指數|TWA00)")
_NEG_FIFTH = re.compile(
    r"(不會產生|不會有|有沒有|沒辦法).{0,16}(第五波|末升段第五波)"
)
_TAGGERS: Tuple[Tuple[str, str, re.Pattern[str]], ...] = (
    ("逃命波C-2", "down", re.compile(r"逃命波.{0,12}C-2|做逃命波\s*C-2")),
    ("C-3", "down", re.compile(r"小心C-2\s*轉\s*C-3|出現C-2\s*轉\s*C-3|轉C-3先")),
    ("C-1", "down", re.compile(r"C波下殺\s*C-1|走C波下殺|最差情境.{0,24}C-1")),
    ("第五波測底", "retest", re.compile(r"第五波.{0,8}測底|再一次測底|短線築底")),
    ("修正末端", "retest", re.compile(r"修正的?末端")),
    ("3-3-4調整", "down", re.compile(r"3-3-3-4調整|3-3-4浪即將結束|進入3-3-3-4")),
    ("位階二", "side", re.compile(r"波浪位階二|位階二|波浪位階的\s*2")),
    ("右肩", "side", re.compile(r"做右肩|右肩型態|持續做右肩|就是做右肩|做型態右肩")),
    ("A波低", "down_done", re.compile(r"A波低點|就是A波低|見A波低")),
    ("大B波", "up", re.compile(r"走大B波|進行大B波|大B波反彈|就算走大B波|有大B波")),
    ("波浪四", "down", re.compile(r"來到波浪四|波浪四點位")),
    ("頭肩底", "retest", re.compile(r"頭肩底")),
    ("第五波失敗", "down", re.compile(r"第五波.{0,10}(沒了|失敗|開始做頭)")),
    ("邪惡第五波", "up", re.compile(r"邪惡第五波")),
    ("末升段", "up", re.compile(r"3-5末升|末升段推動|末升段第五波|第五波擴延")),
    ("大A-c", "down", re.compile(r"大A-c|走大A-c|改\s*A-c")),
    ("細微波主跌", "down", re.compile(r"主跌段跌完|細微波.{0,12}主跌")),
    ("第4浪", "down", re.compile(r"要走第4浪|第4浪\s*abc|4浪\s*abc修正")),
)
_TAG_PAT = {name: pat for name, _d, pat in _TAGGERS}
_TAG_RANK = {
    "逃命波C-2": 90,
    "第五波測底": 80,
    "修正末端": 70,
    "頭肩底": 60,
    "C-3": 50,
    "位階二": 40,
    "右肩": 35,
    "3-3-4調整": 22,
    "C-1": 20,
    "邪惡第五波": 18,
    "末升段": 16,
    "大B波": 15,
    "大A-c": 14,
    "A波低": 12,
    "細微波主跌": 11,
    "波浪四": 10,
    "第4浪": 9,
    "第五波失敗": 8,
    "第五波條件": 5,
}

# 他自己點名過、能對上公開文的位階帶。2023-12 開示到 2024-03 沒寫死浪名，不加教科書浪。
_CURATED: Tuple[Dict[str, str], ...] = (
    {
        "date": "2024-03-15",
        "time": "00:28",
        "aid": "160426431",
        "tag": "3-3-4調整",
        "direc": "down",
        "quote": "台指期這一次推動脈動 3-3-3-3 上升軌道已破壞，將進入 3-3-3-4 調整，回測 19660。",
    },
    {
        "date": "2024-03-19",
        "time": "09:49",
        "aid": "160518715",
        "tag": "修正末端",
        "direc": "retest",
        "quote": "大盤及台指期已打到上升軌道臨界，應該到了修正末端，3-3-4 浪即將結束。",
    },
    {
        "date": "2024-05-30",
        "time": "00:12",
        "aid": "162297588",
        "tag": "第4浪",
        "direc": "down",
        "quote": "85% 確定 3-5 浪已經走完要走第 4 浪 abc 修正。",
    },
    {
        "date": "2024-06-02",
        "time": "11:47",
        "aid": "162385525",
        "tag": "大B波",
        "direc": "up",
        "quote": "大盤從 19291 到 21937 的 5 浪推升已經走完。最好情況是大 B 波假突破過 21937。",
    },
    {
        "date": "2024-07-04",
        "time": "00:09",
        "aid": "163220935",
        "tag": "邪惡第五波",
        "direc": "up",
        "quote": "台指期夜盤創新高，開始走 5-5 邪惡第五波最後第五小浪延升浪。七月最多 24730。",
    },
    {
        "date": "2025-03-04",
        "time": "21:20",
        "aid": "169293290",
        "tag": "細微波主跌",
        "direc": "down",
        "quote": "台指期細微波只是主跌段跌完，還會有末跌段；跌幅滿足超過九成會跌破 22000。不是抄底時機。",
    },
    {
        "date": "2025-05-19",
        "time": "10:55",
        "aid": "171472406",
        "tag": "右肩",
        "direc": "side",
        "quote": "細微波脈動結束會開始高檔震盪，以做型態右肩可能性最大。",
    },
    {
        "date": "2025-12-03",
        "time": "",
        "aid": "",
        "tag": "第五波條件",
        "direc": "up",
        "quote": "台積電 9/3 低連 11/24 低，或加權 9/3 低連 11/21 低；不破才談第五波。",
    },
    {
        "date": "2025-12-15",
        "time": "",
        "aid": "",
        "tag": "第五波失敗",
        "direc": "down",
        "quote": "1-4 重疊、軌道幾乎破壞，那組末升第五波判定失敗、開始做頭。",
    },
    {
        "date": "2026-07-07",
        "time": "",
        "aid": "",
        "tag": "第五波失敗",
        "direc": "down",
        "quote": "樂觀第五波擴延沒了，改 A-c。",
    },
    {
        "date": "2026-07-29",
        "time": "11:13",
        "aid": "181095970",
        "tag": "波浪四",
        "direc": "down",
        "quote": "大盤及台積電已經來到波浪四點位，今天第一次抄底，即會開始進行 B 波反彈。",
    },
    {
        "date": "2026-07-30",
        "time": "09:55",
        "aid": "181149602",
        "tag": "大B波",
        "direc": "up",
        "quote": "A波從 6/23～7/29。就算走大B波也是漲漲跌跌、至少 6 周，不要急著買。",
    },
    {
        "date": "2026-07-31",
        "time": "08:54",
        "aid": "181180579",
        "tag": "A波低",
        "direc": "down_done",
        "quote": "要這麼精準抓到 7/29 是 A 波低點，憑藉細微波波型。波浪沒辦法 100%，台積電＋某金融商品量價已 100% 確認。",
    },
    {
        "date": "2026-09-10",
        "time": "09:51",
        "aid": "184499206",
        "tag": "修正末端",
        "direc": "retest",
        "quote": "9/8 起 abc、當天看到 c 末端；下波起漲至少測 48218。",
    },
    {
        "date": "2026-09-11",
        "time": "08:43",
        "aid": "184526608",
        "tag": "右肩",
        "direc": "side",
        "quote": "9/3 低 45839 有守住＝右肩高有過前高、低不破前低，高檔震盪趨勢向上。細微波已走 5 段，5 或 9 無法判斷。",
    },
    {
        "date": "2026-09-11",
        "time": "17:56",
        "aid": "184545002",
        "tag": "位階二",
        "direc": "side",
        "quote": "我一直主張大盤就是做右肩，也就是走橫台震盪整理的波浪位階的 2，不是位階 3。",
    },
    {
        "date": "2026-09-12",
        "time": "10:34",
        "aid": "184545002",
        "tag": "位階二",
        "direc": "side",
        "quote": "下周要過前波高點 47578，才能維持高有過前高做右肩（還是在波浪位階二）。",
    },
    {
        "date": "2026-09-13",
        "time": "22:19",
        "aid": "184545002",
        "tag": "C-3",
        "direc": "down",
        "quote": "明天最好漲至少 500 點，否則要小心 C-2 轉 C-3。出現會發文。",
    },
    {
        "date": "2026-09-14",
        "time": "09:51",
        "aid": "184578674",
        "tag": "修正末端",
        "direc": "retest",
        "quote": "60 分最後走 1-2-3-4-5 不是 abc。最差 C-1，等 C-2 轉 C-3 再出清、目前言之過早。已到本波指數修正末端。頭肩底頸線沒破。",
    },
    {
        "date": "2026-09-14",
        "time": "21:50",
        "aid": "184578674",
        "tag": "第五波測底",
        "direc": "retest",
        "quote": "目前是對第五波再一次測底；今天就是再一次測底（或稱短線築底，等反彈）。",
    },
    {
        "date": "2026-09-15",
        "time": "09:02",
        "aid": "184601742",
        "tag": "逃命波C-2",
        "direc": "down",
        "quote": "今天大盤強彈，反而要提高警惕，小心市場黑手開始做逃命波C-2。10:47 樓下：漲不動反而比較好；怕開牌前作 C-2、開牌後變 C-3。不是已確認。",
    },
)

# 加權圖只畫他自己點過、能對官方柱的水平。46506 是台指日盤低，不畫在加權。
_TWII_LEVELS: Tuple[Tuple[float, str, str], ...] = (
    (39384.85, "7/29 A波低", "20260729"),
    (43500.0, "他原文C波最差", ""),
    (45839.36, "9/3低右肩", "20260903"),
    (47578.24, "9/8前波高", "20260908"),
    (48218.87, "6/23大一級前高", "20260623"),
)

EYES = (
    "他看線圖不是 KD／MACD／布林／均線——那些他當不算技術分析。"
    "順序是：先定大盤（台指期夜盤→15 分細微波 5 或 9、60 分、下降壓連他自己點過的高例如 48218；"
    "加權日K對質 45839／47578／48218；常先畫台積電兩個低連線當先行）。"
    "確認低點他明講波浪沒辦法 100%，要疊台積電量價、費半／那指、夜盤有沒有先過下降壓。"
    "類股看資金輪動、誰先過前高、這族龍頭攻還是休；個股看量先價行（爆大量日高當壓、低當撐），"
    "相對龍頭的位階，不把波浪套在那一檔。"
    "2026-07-31 他寫要這麼精準抓到 7/29 是 A 波低，憑細微波波型；官方加權當日低 39385 對得上。"
)


def is_wave_question(ask: str) -> bool:
    q = (ask or "").strip()
    if not q:
        return False
    return bool(_WAVE_ASK.search(q) or _EYES_ASK.search(q))


def _clip(text: str, n: int) -> str:
    s = " ".join(str(text or "").split())
    return s if len(s) <= n else s[: n - 1] + "…"


def _px(val: Any) -> str:
    try:
        n = float(val)
    except (TypeError, ValueError):
        return ""
    if abs(n - round(n)) < 1e-6:
        return str(int(round(n)))
    return f"{n:.2f}".rstrip("0").rstrip(".")


def _ymd(raw: Any) -> str:
    t = str(raw or "").replace("-", "")[:8]
    return t if len(t) == 8 and t.isdigit() else ""


def _spoken(raw: str) -> str:
    try:
        from biaoke_ingest import spoken_text

        return spoken_text(raw or "")
    except Exception:
        return str(raw or "")


def _quote_near(text: str, tag: str) -> str:
    blob = _spoken(text)
    pat = _TAG_PAT.get(tag)
    if pat is None:
        return _clip(blob, 160)
    m = pat.search(blob)
    if not m:
        return _clip(blob, 160)
    i = max(0, m.start() - 24)
    return _clip(blob[i : m.end() + 90], 160)


def _tags_in(text: str) -> List[Tuple[str, str]]:
    blob = _spoken(text)
    if _SKIP_FIFTH.search(blob) and "測底" not in blob:
        blob = _SKIP_FIFTH.sub(" ", blob)
    out: List[Tuple[str, str]] = []
    seen = set()
    for tag, direc, pat in _TAGGERS:
        if tag in seen:
            continue
        if pat.search(blob):
            seen.add(tag)
            out.append((tag, direc))
    names = {t for t, _d in out}
    if "逃命波C-2" in names:
        out = [(t, d) for t, d in out if t != "C-1"]
    if _NEG_FIFTH.search(blob):
        out = [(t, d) for t, d in out if t not in {"末升段", "邪惡第五波"}]
    return out


def _merge(rows: List[Dict[str, str]], hit: Dict[str, str]) -> None:
    key = (hit.get("date") or "", hit.get("time") or "", hit.get("tag") or "")
    for old in rows:
        if (old.get("date") or "", old.get("time") or "", old.get("tag") or "") == key:
            return
    rows.append(hit)


def _from_rows(posts: Sequence[Dict[str, Any]]) -> List[Dict[str, str]]:
    out: List[Dict[str, str]] = []
    for p in posts or []:
        raw = str(p.get("text") or "")
        spoken = _spoken(raw)
        if not _INDEX_CTX.search(spoken):
            continue
        tags = _tags_in(raw)
        if not tags:
            continue
        day = str(p.get("date") or "")
        when = str(p.get("time") or "")
        aid = str(p.get("id") or p.get("parent") or "")
        for tag, direc in tags:
            _merge(
                out,
                {
                    "date": day,
                    "time": when,
                    "aid": aid,
                    "tag": tag,
                    "direc": direc,
                    "quote": _quote_near(raw, tag),
                },
            )
    return out


def _live_hits(db_path: str = "") -> List[Dict[str, str]]:
    posts: List[Dict[str, Any]] = []
    try:
        from biaoke_desk import load_corpus

        posts = list((load_corpus(db_path if db_path else None) or {}).get("posts") or [])
    except Exception:
        posts = []
    if not posts:
        try:
            from biaoke_desk import catchup_seed_rows

            posts = list(catchup_seed_rows() or [])
        except Exception:
            posts = []
    return _from_rows(posts)


def _sort_hits(rows: Sequence[Dict[str, str]]) -> List[Dict[str, str]]:
    return sorted(
        rows,
        key=lambda h: (
            h.get("date") or "",
            h.get("time") or "",
            _TAG_RANK.get(h.get("tag") or "", 0),
            h.get("aid") or "",
        ),
    )


def _one_per_stamp(rows: Sequence[Dict[str, str]]) -> List[Dict[str, str]]:
    best: Dict[Tuple[str, str, str], Dict[str, str]] = {}
    for h in rows:
        key = (h.get("date") or "", h.get("time") or "", h.get("aid") or "")
        old = best.get(key)
        if old is None or _TAG_RANK.get(h.get("tag") or "", 0) >= _TAG_RANK.get(
            old.get("tag") or "", 0
        ):
            best[key] = h
    return _sort_hits(list(best.values()))


def degree_hits(db_path: str = "") -> List[Dict[str, str]]:
    """時間序：他自己點過的大盤位階。掃 1709＋catchup，不發明浪。"""
    rows = [dict(x) for x in _CURATED]
    for hit in _live_hits(db_path):
        _merge(rows, hit)
    return _sort_hits(rows)


def degree_turns(db_path: str = "") -> List[Dict[str, str]]:
    """只留改口：連續同一標籤壓成一筆。"""
    out: List[Dict[str, str]] = []
    for h in _one_per_stamp(degree_hits(db_path)):
        if out and out[-1].get("tag") == h.get("tag"):
            out[-1] = h
            continue
        out.append(h)
    return out


def last_two(db_path: str = "") -> Tuple[Optional[Dict[str, str]], Optional[Dict[str, str]]]:
    hits = _one_per_stamp(degree_hits(db_path))
    if not hits:
        return None, None
    last = hits[-1]
    prev = None
    for h in reversed(hits[:-1]):
        if h.get("tag") != last.get("tag") or h.get("date") != last.get("date"):
            prev = h
            break
    return last, prev


def _compare(prev: Optional[Dict[str, str]], last: Optional[Dict[str, str]]) -> str:
    if not last:
        return "帶裡還沒接到他自己點名的位階，不准發明浪。"
    if not prev:
        return "這是帶裡最早一筆他自己點名的位階，前面沒得對。"
    a, b = prev.get("tag") or "", last.get("tag") or ""
    pair = (a, b)
    if pair == ("第五波測底", "逃命波C-2") or pair == ("頭肩底", "逃命波C-2"):
        return (
            f"先前 {prev.get('date')} 叫{a}等反彈，後來 {last.get('date')} 改口小心逃命波C-2："
            "同一組最差情境還在 C-1，強彈他當提高警惕，不是已確認 C-2／C-3。"
        )
    if pair == ("修正末端", "第五波測底") or pair == ("頭肩底", "第五波測底"):
        return (
            f"先前 {prev.get('date')} 叫{a}，後來 {last.get('date')} 收到{b}："
            "同一組細微波收斂，不是改口成大 3，也還沒發文升成 C-3。"
        )
    if a == "位階二" and b in {"修正末端", "第五波測底", "頭肩底", "C-1", "右肩"}:
        return (
            f"大一級他 {prev.get('date')} 仍叫位階二／右肩；"
            f"這一組細微波 {last.get('date')} 叫{b}。"
            "兩層並存，他慣用同一晚多標籤再用點數驗。沒把計數升成大 3。"
        )
    if a in {"波浪四", "大B波"} and b == "A波低":
        return (
            f"{prev.get('date')} 還在抄底／B 波框架，{last.get('date')} 收成 7/29 就是 A 波低——"
            "同向收斂。他自稱憑細微波抓轉折。"
        )
    if a == "細微波主跌" and b in {"右肩", "位階二"}:
        return (
            f"{prev.get('date')} 細微波主跌／估破 22000，後來 {last.get('date')} 改叫{b}："
            "中間官方柱對得上先破 22000 再築右肩，不是發明中間數了幾段。"
        )
    if a in {"3-3-4調整", "第4浪", "邪惡第五波", "大A-c", "末升段"}:
        return (
            f"先前 {prev.get('date')} 點「{a}」，後來 {last.get('date')} 點「{b}」。"
            "只記他自己的標籤，不准發明中間數了幾段。"
        )
    if a == "A波低" and b in {"位階二", "右肩", "修正末端"}:
        return (
            f"7/29 A 波低之後，{last.get('date')} 他改叫{b}："
            "大一級還在 2，不是再數一次教科書第五波。"
        )
    if b == "C-3" and a != "C-3":
        return (
            f"{last.get('date')} 只是預告要小心 C-2 轉 C-3，不是已確認。"
            "他自己說出現會發文；後來 9/14 仍言之過早。"
        )
    if a == b:
        return f"跟 {prev.get('date')} 同一標籤「{a}」，同向，沒改口。"
    return (
        f"先前 {prev.get('date')} 點「{a}」，後來 {last.get('date')} 點「{b}」。"
        "只記他自己的標籤，不准發明中間數了幾段。"
    )


def _twii_bar(db_path: str, ymd: str) -> Dict[str, Any]:
    day = _ymd(ymd)
    if not db_path or not os.path.isfile(db_path) or not day:
        return {}
    try:
        conn = sqlite3.connect(db_path, timeout=8.0)
        try:
            row = conn.execute(
                "SELECT date, open, high, low, close FROM index_daily "
                "WHERE (symbol='TWII' OR symbol='^TWII' OR symbol='' OR symbol IS NULL) "
                "AND REPLACE(CAST(date AS TEXT),'-','')=? LIMIT 1",
                (day,),
            ).fetchone()
        except sqlite3.Error:
            row = None
        finally:
            conn.close()
    except Exception:
        return {}
    if not row:
        return {}
    return {"date": row[0], "open": row[1], "high": row[2], "low": row[3], "close": row[4]}


def _twii_latest(db_path: str) -> Dict[str, Any]:
    if not db_path or not os.path.isfile(db_path):
        return {}
    try:
        from biaoke_brain import load_index_bars

        bars = load_index_bars(db_path, n=1) or []
        return dict(bars[-1]) if bars else {}
    except Exception:
        return {}


def _broke_low_since(db_path: str, ymd: str, level: float) -> Dict[str, Any]:
    day = _ymd(ymd)
    if not db_path or not os.path.isfile(db_path) or not day:
        return {}
    try:
        conn = sqlite3.connect(db_path, timeout=8.0)
        try:
            row = conn.execute(
                "SELECT date, low, close FROM index_daily "
                "WHERE (symbol='TWII' OR symbol='^TWII') "
                "AND REPLACE(CAST(date AS TEXT),'-','')>? AND low<? "
                "ORDER BY date DESC LIMIT 1",
                (day, float(level)),
            ).fetchone()
        except sqlite3.Error:
            row = None
        finally:
            conn.close()
    except Exception:
        return {}
    if not row:
        return {}
    return {"date": row[0], "low": row[1], "close": row[2]}


def _official_bits(db_path: str) -> List[str]:
    bits: List[str] = []
    last = _twii_latest(db_path)
    if last:
        bits.append(
            f"官方加權 {last.get('date') or ''} 收 {_px(last.get('close')) or '—'} "
            f"高 {_px(last.get('high')) or '—'} 低 {_px(last.get('low')) or '—'}"
        )
        try:
            close = float(last.get("close") or 0)
            hi = float(last.get("high") or 0)
            lo = float(last.get("low") or 0)
        except (TypeError, ValueError):
            close = hi = lo = 0.0
        if close >= 45839:
            bits.append(f"收 {_px(close)} 還在他自己點的 9/3 低 45839 之上")
        elif close > 0:
            bits.append(f"收 {_px(close)} 已低於 45839，覆巢先當有事")
        broke = _broke_low_since(db_path, "20260903", 45839.36)
        if broke:
            bits.append(
                f"{broke.get('date')} 官方低 {_px(broke.get('low'))} 已低於 45839；"
                f"當日收 {_px(broke.get('close'))}。"
                "右肩「低不破前低」這根低點先當有事，他 9/14 改用頭肩底頸線沒破，兩套一起留"
            )
        if hi >= 47578:
            bits.append(f"官方高 {_px(hi)} 已過 47578，才比較像維持右肩")
        elif hi > 0:
            bits.append(f"官方高 {_px(hi)} 還沒過 47578，右肩還沒做完")
    else:
        bits.append("官方加權這顆庫還沒這列，不准自己寫點位")
    a_low = _twii_bar(db_path, "20260729")
    if a_low:
        bits.append(
            f"7/29 官方低 {_px(a_low.get('low'))}，對得上他說的 A 波低 39385"
        )
    return bits


def _twii_span(db_path: str) -> Tuple[str, str]:
    if not db_path or not os.path.isfile(db_path):
        return "", ""
    try:
        conn = sqlite3.connect(db_path, timeout=8.0)
        try:
            row = conn.execute(
                "SELECT MIN(REPLACE(CAST(date AS TEXT),'-','')), "
                "MAX(REPLACE(CAST(date AS TEXT),'-','')) "
                "FROM index_daily WHERE symbol='TWII' OR symbol='^TWII'"
            ).fetchone()
        except sqlite3.Error:
            row = None
        finally:
            conn.close()
    except Exception:
        return "", ""
    if not row:
        return "", ""
    return _ymd(row[0]), _ymd(row[1])


_WAVE_NEED_YMD = "20240315"


def _tx_bar(db_path: str, ymd: str, session: str = "regular") -> Dict[str, Any]:
    day = _ymd(ymd)
    if not db_path or not os.path.isfile(db_path) or not day:
        return {}
    try:
        conn = sqlite3.connect(db_path, timeout=8.0)
        try:
            row = conn.execute(
                "SELECT date, open, high, low, close FROM futures_daily "
                "WHERE symbol='TX' AND session=? "
                "AND REPLACE(CAST(date AS TEXT),'-','')=? LIMIT 1",
                (session, day),
            ).fetchone()
        except sqlite3.Error:
            row = None
        finally:
            conn.close()
    except Exception:
        return {}
    if not row:
        return {}
    return {
        "date": row[0],
        "open": row[1],
        "high": row[2],
        "low": row[3],
        "close": row[4],
        "session": session,
    }


def _tx_span(db_path: str, session: str = "regular") -> Tuple[str, str]:
    if not db_path or not os.path.isfile(db_path):
        return "", ""
    try:
        conn = sqlite3.connect(db_path, timeout=8.0)
        try:
            row = conn.execute(
                "SELECT MIN(REPLACE(CAST(date AS TEXT),'-','')), "
                "MAX(REPLACE(CAST(date AS TEXT),'-','')) "
                "FROM futures_daily WHERE symbol='TX' AND session=?",
                (session,),
            ).fetchone()
        except sqlite3.Error:
            row = None
        finally:
            conn.close()
    except Exception:
        return "", ""
    if not row:
        return "", ""
    return _ymd(row[0]), _ymd(row[1])


def _tx_hl(
    db_path: str, start: str, end: str, session: str = "regular"
) -> Dict[str, Any]:
    a, b = _ymd(start), _ymd(end)
    if not db_path or not os.path.isfile(db_path) or not a or not b:
        return {}
    try:
        conn = sqlite3.connect(db_path, timeout=8.0)
        try:
            row = conn.execute(
                "SELECT MIN(low), MAX(high), MIN(REPLACE(CAST(date AS TEXT),'-','')), "
                "MAX(REPLACE(CAST(date AS TEXT),'-','')) "
                "FROM futures_daily WHERE symbol='TX' AND session=? "
                "AND REPLACE(CAST(date AS TEXT),'-','')>=? "
                "AND REPLACE(CAST(date AS TEXT),'-','')<=?",
                (session, a, b),
            ).fetchone()
        except sqlite3.Error:
            row = None
        finally:
            conn.close()
    except Exception:
        return {}
    if not row or row[0] is None:
        return {}
    return {"low": row[0], "high": row[1], "from": row[2], "to": row[3]}


def _need_wave_history(db_path: str) -> bool:
    start, _end = _twii_span(db_path)
    if not start or start > _WAVE_NEED_YMD:
        return True
    tx0, _tx1 = _tx_span(db_path)
    if not tx0 or tx0 > _WAVE_NEED_YMD:
        return True
    return False


def ensure_wave_history(db_path: str, *, force: bool = False) -> Dict[str, Any]:
    """波浪對質缺加權／台指期柱就自己抓。pytest 不打外網。"""
    out: Dict[str, Any] = {"ok": False, "twii": 0, "tx": {}}
    if not db_path or not os.path.isfile(db_path):
        out["reason"] = "no-db"
        return out
    if os.environ.get("PYTEST_CURRENT_TEST") and not force:
        out["reason"] = "pytest"
        return out
    if not force and not _need_wave_history(db_path):
        out["ok"] = True
        out["reason"] = "already"
        return out
    try:
        from biaoke_verify import refresh_recent_twii

        out["twii"] = int(
            refresh_recent_twii(
                db_path, range_="5y", skip_open_day=True, overwrite=False
            )
            or 0
        )
    except Exception:
        out["twii"] = 0
    try:
        from taiwan_market import backfill_tx_monthly_gap

        out["tx"] = backfill_tx_monthly_gap(db_path, force=force) or {}
    except Exception:
        out["tx"] = {}
    out["ok"] = True
    return out


def _hist_bits(db_path: str) -> List[str]:
    """沒講到的時間只拿官方柱對他點過的水平，不准補浪名。"""
    bits: List[str] = []
    start, _end = _twii_span(db_path)
    tx0, _tx1 = _tx_span(db_path)
    if start:
        bits.append(
            f"這顆庫加權日K 從 {start[:4]}-{start[4:6]}-{start[6:8]} 起才有柱"
        )
    else:
        bits.append("這顆庫還沒加權日K，更早的點位不准自己寫")
    if tx0:
        bits.append(
            f"台指期日盤從 {tx0[:4]}-{tx0[4:6]}-{tx0[6:8]} 起才有柱"
        )
    mar = _tx_bar(db_path, "20240319") or _twii_bar(db_path, "20240319")
    mar_hl = _tx_hl(db_path, "20240315", "20240322")
    if mar_hl.get("low"):
        lo = float(mar_hl["low"])
        gap = lo - 19660
        hit = "，對得上" if gap <= 40 else ("，接近" if gap <= 120 else "，當日還沒測到")
        bits.append(f"2024-03-15～19 台指期低 {_px(lo)}，他點回測 19660{hit}")
    elif mar:
        src = "台指期" if mar.get("session") else "加權"
        bits.append(
            f"2024-03-19 官方{src}低 {_px(mar.get('low'))}，他點回測 19660"
        )
    elif not tx0 or tx0 > "20240319":
        bits.append("19660 這顆庫還沒台指期柱，不對質")
    jun = _tx_hl(db_path, "20240528", "20240605")
    if jun.get("high"):
        hi = float(jun["high"])
        bits.append(
            f"2024-05 末～06-02 台指期高 {_px(hi)}，他點 19291～21937 五浪走完"
            + ("，對得上" if hi >= 21850 else "，還沒到")
        )
    elif not tx0 or tx0 > "20240602":
        bits.append("21937 這顆庫還沒台指期柱，不對質")
    jul = _tx_hl(db_path, "20240701", "20240731")
    if jul.get("high"):
        hi = float(jul["high"])
        bits.append(
            f"2024-07 台指期高 {_px(hi)}，他點邪惡第五波七月最多 24730"
            + ("，對得上" if hi >= 24600 else "，還沒到他點的滿足")
        )
    elif not tx0 or tx0 > "20240704":
        bits.append("24730 這顆庫還沒台指期柱，不對質")
    d304 = _twii_bar(db_path, "20250304")
    d311 = _twii_bar(db_path, "20250311")
    d331 = _twii_bar(db_path, "20250331")
    if d304 and d311 and d331:
        bits.append(
            f"2025-03-04 他估破 22000；當日官方低 {_px(d304.get('low'))} 還沒破，"
            f"3/11 低 {_px(d311.get('low'))} 微破，3/31 低 {_px(d331.get('low'))}。"
            "方向對，22000 偏高，他自己後來說跌到 21000／破 20000 言之過早"
        )
    return bits


def format_wave_path(db_path: str = "", *, n: int = 14) -> str:
    """從 2023 開示起，只排他自己改口過的大盤標籤。"""
    turns = degree_turns(db_path)
    if not turns:
        return (
            "2023-12 開示起公開文還沒寫死大盤浪名，不准補教科書浪。"
            "不數 5／9 段。"
        )
    bits = ["時間線只記他自己改口的標籤"]
    first = turns[0]
    if not str(first.get("date") or "").startswith("2023"):
        bits.append("2023-12 到第一筆之間公開文沒寫死浪名")
    pinned: List[Dict[str, str]] = [turns[0]]
    must = (
        "3-3-4調整",
        "第4浪",
        "邪惡第五波",
        "細微波主跌",
        "右肩",
        "A波低",
        "位階二",
        "第五波測底",
        "逃命波C-2",
    )
    for tag in must:
        seen_y = set()
        last_hit = None
        for t in turns:
            if t.get("tag") != tag:
                continue
            last_hit = t
            y = str(t.get("date") or "")[:4]
            if y in seen_y:
                continue
            seen_y.add(y)
            pinned.append(t)
        if last_hit is not None and tag in {"逃命波C-2", "位階二", "第五波測底"}:
            pinned.append(last_hit)
    pinned.append(turns[-1])
    uniq: List[Dict[str, str]] = []
    seen = set()
    for t in _sort_hits(pinned):
        key = (t.get("date"), t.get("time"), t.get("tag"), t.get("aid"))
        if key in seen:
            continue
        seen.add(key)
        uniq.append(t)
    show = uniq
    if len(show) > n:
        keep = {id(turns[0]), id(turns[-1])}
        for t in uniq:
            if t.get("tag") in {"A波低", "右肩", "細微波主跌", "逃命波C-2"}:
                keep.add(id(t))
        core = [t for t in uniq if id(t) in keep]
        extra = [t for t in uniq if id(t) not in keep]
        show = _sort_hits(core + extra[: max(0, n - len(core))])
        bits.append("中間改口有省略")
    bits.append(" → ".join(f"{t.get('date')} {t.get('tag')}" for t in show))
    bits.append("不准發明 5／9 段")
    return "。".join(bits)


def _direc_line(last: Dict[str, str]) -> str:
    tag = last.get("tag") or ""
    direc = last.get("direc") or ""
    if tag == "逃命波C-2":
        return (
            "方向：他點的是最差情境下小心逃命波 C-2，不是已確認下降浪。"
            "10:47 樓下：漲不動反而比較好；怕開牌前作 C-2、開牌後變 C-3。沒發文確認就不要替他升浪。"
            "強彈不追高。創意還沒連續漲勢，就不能說沒有下殺 43500 的危機。"
        )
    if direc == "retest" or tag in {"第五波測底", "修正末端", "頭肩底"}:
        return (
            "方向：這一組細微波他點的是修正末端／測底等反彈，不是已確認大 3 推動，"
            "也不是已確認 C-3 下殺。不追高；C-2 轉 C-3 他說會發文，沒發文就不要替他升浪。"
        )
    if direc == "side" or tag in {"位階二", "右肩"}:
        return (
            "方向：大一級他點高檔震盪／右肩／位階二，趨勢他仍說向上整理。"
            "還沒過 47578 不要當成突破；破他點的右肩低才先當覆巢。"
        )
    if direc == "up" or tag == "大B波":
        return "方向：他點的是反彈／B 波向上，時間可以很長，他自己說不要急著買。"
    if direc in {"down", "down_done"}:
        return "方向：他點的是下跌段或下跌剛走完。準備下降的時間先看他有沒有發文升成 C-3。"
    return "方向：只跟他最新標籤走，不准發明升或降裡面第幾浪。"


def format_wave_head(db_path: str = "") -> str:
    """巢穴／推論用短句，不吃掉官方四路。"""
    last, prev = last_two(db_path)
    if not last:
        return "還沒接到他自己點名的大盤位階，不准發明浪。位階不講死。"
    stamp = " ".join(x for x in (last.get("date") or "", last.get("time") or "") if x)
    prev_t = f"；再前 {prev.get('date')} {prev.get('tag')}" if prev else ""
    return (
        f"現在位階 {stamp} {last.get('tag')}{prev_t}。"
        "大一級還在位階二／右肩，C-3 沒發文。位階不講死。不數 5／9 段。"
    )


def format_wave_now(db_path: str = "", *, n: int = 900) -> str:
    """口語：現在位階＝他自己最近一次怎麼點＋再前一次＋官方對質。"""
    if db_path and n >= 500:
        try:
            ensure_wave_history(db_path)
        except Exception:
            pass
    last, prev = last_two(db_path)
    bits: List[str] = [format_wave_head(db_path)]
    if last:
        bits.append(_clip(last.get("quote") or "", 140))
    bits.append(_compare(prev, last))
    if last:
        bits.append(_direc_line(last))
    bits.append(
        "轉折錨：2026-07-31 他寫要這麼精準抓到 7/29 是 A 波低，憑細微波波型；"
        "官方加權當日低 39385 對得上。那次靠細微波＋台積電量價，不是發明公式。"
    )
    bits.extend(_official_bits(db_path))
    if n >= 500:
        bits.extend(_hist_bits(db_path))
        bits.append(format_wave_path(db_path, n=14))
    bits.append("同一晚可並存多標籤，用點數一驗再驗。不是買訊。")
    return _clip("。".join(b.rstrip("。") for b in bits if b), n)


def format_wave_eyes() -> str:
    return EYES


def _load_twii_bars(db_path: str, n: int = 80) -> List[Dict[str, Any]]:
    if not db_path or not os.path.isfile(db_path):
        return []
    try:
        conn = sqlite3.connect(db_path, timeout=8.0)
        conn.row_factory = sqlite3.Row
        try:
            rows = conn.execute(
                "SELECT date, open, high, low, close FROM index_daily "
                "WHERE symbol='TWII' OR symbol='^TWII' "
                "ORDER BY date DESC LIMIT ?",
                (int(n),),
            ).fetchall()
        except sqlite3.Error:
            rows = []
        finally:
            conn.close()
    except Exception:
        return []
    out = [dict(r) for r in rows]
    out.reverse()
    return out


_LOW_TAGS = {
    "A波低",
    "第五波測底",
    "逃命波C-2",
    "C-1",
    "細微波主跌",
    "波浪四",
    "第4浪",
    "大A-c",
}
_HIGH_TAGS = {"大B波", "邪惡第五波", "末升段"}
_SKIP_PATH = {"第五波條件"}
_UNCONFIRMED = {"C-3", "逃命波C-2"}
_PATH_SHORT = {
    "逃命波C-2": "逃命C-2",
    "第五波測底": "測底",
    "修正末端": "末端",
    "A波低": "A波低",
    "位階二": "位階二",
    "右肩": "右肩",
    "C-3": "小心C-3",
    "C-1": "C-1",
    "大B波": "大B波",
    "波浪四": "波浪四",
    "第4浪": "第4浪",
    "細微波主跌": "主跌",
    "邪惡第五波": "邪惡5",
    "末升段": "末升",
    "大A-c": "A-c",
    "第五波失敗": "五波失敗",
    "頭肩底": "頭肩底",
    "3-3-4調整": "3-3-4",
}


def _path_kind(tag: str) -> str:
    if tag in _LOW_TAGS:
        return "low"
    if tag in _HIGH_TAGS:
        return "high"
    return "close"


def _path_anchor_ymd(turn: Dict[str, str]) -> str:
    tag = str(turn.get("tag") or "")
    if tag == "A波低":
        return "20260729"
    return _ymd(turn.get("date"))


_SPAN_COLOR = {
    "2024-334": "#455a64",
    "2024-w4": "#455a64",
    "2024-w5": "#455a64",
    "2025-drop": "#455a64",
    "2025-sh": "#455a64",
    "2025-w5": "#455a64",
    "2026-A": "#2e7d32",
    "2026-B": "#1565c0",
    "2026-d2": "#455a64",
    "2026-C": "#6a1b9a",
}
_SPAN_MARK = {
    "2024-334": "3-4",
    "2024-w4": "4",
    "2024-w5": "5",
    "2025-drop": "主跌",
    "2025-sh": "右肩",
    "2025-w5": "5失敗",
    "2026-A": "A",
    "2026-B": "B",
    "2026-d2": "2",
    "2026-C": "C",
}
_TWII_MAIN_BARS = 168
_TWII_LONG_BARS = 560
_TWII_LOCATOR_RECT = (0.50, 0.695, 0.48, 0.268)
_ABC_A_START = "20260623"
_ABC_A_END = "20260729"


def span_of(date: str, tag: str) -> Dict[str, str]:
    """同一個「大B波」可能是不同區間。線要拆開，標哪一層。不發明段號。"""
    ymd = str(date or "").replace("-", "")[:8]
    tag = str(tag or "")
    if len(ymd) < 8:
        ymd = "99999999"
    if tag == "大B波":
        if ymd < "20250101":
            sid, slab = "2024-w4", "2024·第4浪修正"
            point = "2024·第4浪裡的大B"
        else:
            sid, slab = "2026-B", "2026·A波後大B（下降區裡）"
            point = "2026·A波後大B"
        return {
            "span": sid,
            "span_lab": slab,
            "span_color": _SPAN_COLOR.get(sid, "#6a1b9a"),
            "point_lab": point,
        }
    if ymd < "20240501":
        sid, slab = "2024-334", "2024·3-3-4調整"
    elif ymd < "20240704":
        sid, slab = "2024-w4", "2024·第4浪修正"
    elif ymd < "20250301":
        sid, slab = "2024-w5", "2024·邪惡第五波"
    elif ymd < "20250519":
        sid, slab = "2025-drop", "2025·細微波主跌"
    elif ymd < "20251201":
        sid, slab = "2025-sh", "2025·右肩（細微波後）"
    elif ymd < "20260701":
        sid, slab = "2025-w5", "2025-26·第五波條件／失敗"
    elif tag in {"第五波失敗", "大A-c", "波浪四", "A波低"}:
        sid, slab = "2026-A", "2026·A波 6/23–7/29"
    elif tag in {"C-3", "C-1", "第五波測底", "逃命波C-2"}:
        sid, slab = "2026-C", "2026·可能的C（未確認）"
    else:
        sid, slab = "2026-d2", "2026·大一級右肩／位階二"
    if tag == "A波低":
        point = "2026·A波低7/29"
    elif tag == "右肩" and sid == "2025-sh":
        point = "2025·右肩"
    elif tag == "右肩":
        point = "2026·位階二右肩"
    elif tag == "波浪四":
        point = "2026·波浪四／A"
    elif tag == "第4浪":
        point = "2024·第4浪"
    elif tag == "第五波失敗" and ymd.startswith("2026"):
        point = "2026·第五波失敗改A"
    else:
        point = _PATH_SHORT.get(tag, tag)
    return {
        "span": sid,
        "span_lab": slab,
        "span_color": _SPAN_COLOR.get(sid, "#6a1b9a"),
        "point_lab": point,
    }


def wave_chart_mark(tag: str = "", span: str = "") -> str:
    """主圖／縮圖只寫 A／B／C／2。長編嵌留在說明。"""
    t = str(tag or "")
    if t == "逃命波C-2":
        return "C-2"
    if t in {"C-3", "C-1"}:
        return t
    if t in {"A波低", "第五波失敗", "大A-c", "波浪四"}:
        return "A"
    if t == "大B波":
        return "B"
    if t in {"右肩", "位階二"}:
        return "2"
    sid = str(span or "")
    if sid and sid in _SPAN_MARK:
        return _SPAN_MARK[sid]
    return _PATH_SHORT.get(t, t)


def locator_wave_legs(path_pts: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """縮圖用：一段線一個 A／B／C。舊路徑仍給測試；主圖改走 locator_abc_legs。"""
    legs: List[Dict[str, Any]] = []
    for seg in wave_path_segments(path_pts):
        pts = list(seg.get("pts") or [])
        if len(pts) < 2:
            continue
        span = str(seg.get("span") or "")
        legs.append(
            {
                "xs": [float(p["i"]) for p in pts],
                "ys": [float(p["y"]) for p in pts],
                "color": str(seg.get("color") or _SPAN_COLOR.get(span, "#455a64")),
                "lab": _SPAN_MARK.get(span, ""),
                "lw": 1.25,
            }
        )
    return legs


def _ymd_index(rows: Sequence[Dict[str, Any]], ymd: str) -> Optional[int]:
    want = _ymd(ymd)
    if not want:
        return None
    for i, r in enumerate(rows or []):
        if _ymd(r.get("date")) == want:
            return i
    return None


def _md_slash(ymd: Any) -> str:
    t = _ymd(ymd)
    if len(t) == 8:
        return f"{int(t[4:6])}/{int(t[6:8])}"
    return t


def _ohlc_f(row: Optional[Dict[str, Any]], key: str) -> float:
    try:
        return float((row or {}).get(key) or 0)
    except (TypeError, ValueError):
        return 0.0


def wave_abc_story(
    rows: Sequence[Dict[str, Any]],
    last_tag: str = "",
) -> Dict[str, Any]:
    """2026 ABC 主線，給完全不懂波浪的人看。

    A 起＝6/23 第五波高；A 完＝7/29 低，同一天就是 B 起；
    B 高＝7/29 之後官方最高（對得上 9/8）；C 從 B 高往現在，虛線未確認。
    A 和 B 必須接在同一個 7/29 低，線不准斷。
    """
    bars = list(rows or [])
    out: Dict[str, Any] = {}
    if len(bars) < 4:
        return out
    i_a = _ymd_index(bars, _ABC_A_START)
    i_low = _ymd_index(bars, _ABC_A_END)
    if i_a is None or i_low is None or i_low <= i_a:
        return out
    y_a = _ohlc_f(bars[i_a], "high")
    y_low = _ohlc_f(bars[i_low], "low")
    if y_a <= 0 or y_low <= 0:
        return out
    out["a"] = {
        "xs": [float(i_a), float(i_low)],
        "ys": [y_a, y_low],
        "i0": i_a,
        "i1": i_low,
        "y0": y_a,
        "y1": y_low,
        "d0": str(bars[i_a].get("date") or ""),
        "d1": str(bars[i_low].get("date") or ""),
        "color": "#2e7d32",
        "unconfirmed": False,
    }
    out["fifth_high"] = {
        "i": i_a,
        "y": y_a,
        "date": str(bars[i_a].get("date") or ""),
        "text": f"5高 {_md_slash(bars[i_a].get('date'))} {_px(y_a)}＝A起",
    }
    out["a_done"] = {
        "i": i_low,
        "y": y_low,
        "date": str(bars[i_low].get("date") or ""),
        "text": f"{_md_slash(bars[i_low].get('date'))} A完＝B起 {_px(y_low)}",
    }
    i_b = None
    y_b = 0.0
    for i in range(i_low + 1, len(bars)):
        h = _ohlc_f(bars[i], "high")
        if h > y_b:
            y_b = h
            i_b = i
    if i_b is None or y_b <= 0:
        return out
    out["b"] = {
        "xs": [float(i_low), float(i_b)],
        "ys": [y_low, y_b],
        "i0": i_low,
        "i1": i_b,
        "y0": y_low,
        "y1": y_b,
        "d0": str(bars[i_low].get("date") or ""),
        "d1": str(bars[i_b].get("date") or ""),
        "color": "#1565c0",
        "unconfirmed": False,
    }
    out["b_high"] = {
        "i": i_b,
        "y": y_b,
        "date": str(bars[i_b].get("date") or ""),
        "text": f"{_md_slash(bars[i_b].get('date'))} B高 {_px(y_b)}",
    }
    last_i = len(bars) - 1
    if last_i > i_b:
        y_now = _ohlc_f(bars[last_i], "close") or _ohlc_f(bars[last_i], "low")
        tag = str(last_tag or "")
        c_lab = "C未確認"
        if "C-2" in tag:
            c_lab = "C-2未確認"
        elif "C-3" in tag:
            c_lab = "C-3未確認"
        out["c"] = {
            "xs": [float(i_b), float(last_i)],
            "ys": [y_b, y_now],
            "i0": i_b,
            "i1": last_i,
            "y0": y_b,
            "y1": y_now,
            "d0": str(bars[i_b].get("date") or ""),
            "d1": str(bars[last_i].get("date") or ""),
            "color": "#6a1b9a",
            "unconfirmed": True,
            "lab": c_lab,
        }
    return out


def locator_abc_legs(story: Dict[str, Any]) -> List[Dict[str, Any]]:
    """縮圖：A↓ B↑ C虛。圈字離開 K；線要細，K 才看得清。"""
    legs: List[Dict[str, Any]] = []
    spec = (
        ("a", "#2e7d32", "A", "left", "-", 0.95),
        ("b", "#1565c0", "B", "mid", "-", 0.95),
        ("c", "#6a1b9a", "C", "mid", (0, (3.2, 2.2)), 0.85),
    )
    for key, color, circ, side, ls, lw in spec:
        leg = story.get(key) or {}
        xs = list(leg.get("xs") or [])
        ys = list(leg.get("ys") or [])
        if len(xs) < 2:
            continue
        legs.append(
            {
                "xs": xs,
                "ys": ys,
                "color": color,
                "lab": "",
                "lw": lw,
                "ls": ls,
                "circle": circ,
                "circle_side": side,
                "dots": False,
            }
        )
    return legs


def wave_path_segments(path_pts: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """同一區間連成一條；跨年／跨層不接在一起。"""
    by: Dict[str, Dict[str, Any]] = {}
    order: List[str] = []
    for p in path_pts or []:
        sid = str(p.get("span") or "_")
        if sid not in by:
            by[sid] = {
                "span": sid,
                "lab": str(p.get("span_lab") or ""),
                "color": str(p.get("span_color") or "#6a1b9a"),
                "pts": [],
            }
            order.append(sid)
        by[sid]["pts"].append(p)
    for sid in order:
        by[sid]["pts"].sort(key=lambda x: (int(x.get("i") or 0), str(x.get("date") or "")))
    return [by[s] for s in order]


def wave_path_points(
    db_path: str, bars: Sequence[Dict[str, Any]]
) -> List[Dict[str, Any]]:
    """視窗內把他改口過的錨對到官方柱。晚於最後官方柱就釘在最後一根。不數段。"""
    rows = list(bars or [])
    if len(rows) < 2:
        return []
    by_ymd = {_ymd(b.get("date")): i for i, b in enumerate(rows) if _ymd(b.get("date"))}
    last_i = len(rows) - 1
    last_ymd = _ymd(rows[-1].get("date"))
    raw: List[Dict[str, Any]] = []
    for turn in degree_turns(db_path):
        tag = str(turn.get("tag") or "")
        if not tag or tag in _SKIP_PATH:
            continue
        ymd = _path_anchor_ymd(turn)
        if not ymd or not last_ymd:
            continue
        pinned = False
        if ymd > last_ymd:
            i = last_i
            pinned = True
        elif ymd in by_ymd:
            i = by_ymd[ymd]
        else:
            continue
        bar = rows[i]
        kind = _path_kind(tag)
        try:
            if kind == "low":
                y = float(bar.get("low") or bar.get("close") or 0)
            elif kind == "high":
                y = float(bar.get("high") or bar.get("close") or 0)
            else:
                y = float(bar.get("close") or 0)
        except (TypeError, ValueError):
            continue
        if y <= 0:
            continue
        sp = span_of(str(turn.get("date") or ""), tag)
        raw.append(
            {
                "i": i,
                "y": y,
                "tag": tag,
                "date": str(turn.get("date") or ""),
                "pinned": pinned,
                "kind": kind,
                "unconfirmed": tag in _UNCONFIRMED,
                "span": sp["span"],
                "span_lab": sp["span_lab"],
                "span_color": sp["span_color"],
                "point_lab": sp["point_lab"],
            }
        )
    raw.sort(key=lambda p: (int(p["i"]), -int(_TAG_RANK.get(p["tag"], 0))))
    out: List[Dict[str, Any]] = []
    for p in raw:
        if out and int(out[-1]["i"]) == int(p["i"]) and abs(float(out[-1]["y"]) - float(p["y"])) < 80:
            if int(_TAG_RANK.get(p["tag"], 0)) >= int(_TAG_RANK.get(out[-1]["tag"], 0)):
                out[-1] = p
            continue
        out.append(p)
    return out


def _wave_label_keep(p: Dict[str, Any], j: int, n_pts: int) -> bool:
    """主圖只留 A／B／C／2 與最後一點，長編嵌不貼上 K。"""
    if j >= n_pts - 1:
        return True
    if p.get("unconfirmed"):
        return True
    tag = str(p.get("tag") or "")
    return tag in {"A波低", "逃命波C-2", "C-3", "大B波", "右肩", "位階二"}


def wave_extend_rays(
    path_pts: Sequence[Any],
    n: int,
    last_tag: str = "",
) -> List[Dict[str, Any]]:
    """未出現的走法畫成延伸。只沿他自己點過的水平，不准發明 5／9。

    逃命波C-2／C-3／C-1／細微波主跌／大A-c → 原文最差 43500
    ＋分歧「若守住 9/3 低」45839.36。
    第五波測底／修正末端／頭肩底 → 只射 9/3 低。
    """
    pts = list(path_pts or [])
    if not pts or int(n or 0) < 2:
        return []
    last = pts[-1]
    if isinstance(last, dict):
        last_i = int(last.get("i") or 0)
        try:
            last_y = float(last.get("y") or 0)
        except (TypeError, ValueError):
            last_y = 0.0
        tag = last_tag or str(last.get("tag") or "")
    else:
        try:
            last_i = int(last[0])
            last_y = float(last[1])
        except (TypeError, ValueError, IndexError):
            return []
        tag = last_tag or (str(last[2]) if len(last) > 2 else "")
    if last_y <= 0:
        return []
    worst = 43500.0
    fork = 45839.36
    x1 = last_i
    x2 = int(n) - 1 + 8

    def _ray(kind: str, y2: float, label: str) -> Dict[str, Any]:
        return {
            "kind": kind,
            "x1": x1,
            "y1": last_y,
            "x2": x2,
            "y2": y2,
            "y": y2,
            "label": label,
        }

    bear = any(
        k in tag
        for k in ("逃命波C-2", "逃命波C-3", "逃命波C-1", "C-3", "細微波主跌", "大A-c")
    )
    if (not bear) and ("C-1" in tag and "C-2" not in tag):
        bear = True
    bottom = any(k in tag for k in ("第五波測底", "修正末端", "頭肩底"))
    if bear:
        return [
            _ray("worst", worst, "最差43500"),
            _ray("fork", fork, "若守45839"),
        ]
    if bottom:
        return [_ray("fork", fork, "延伸45839")]
    return []


def _paint_abc_on_ax(ax, story: Dict[str, Any], *, n: int, y_top: float, y_bot: float) -> None:
    """主圖只畫一條連好的 A↓B↑C虛。圈 A 在下降線左邊。"""
    from biaoke_chart import _circled_letter, _halo_line, _leader_note

    span = max(y_top - y_bot, 1.0)
    for key, lw in (("a", 1.7), ("b", 1.7), ("c", 1.35)):
        leg = story.get(key) or {}
        xs = list(leg.get("xs") or [])
        ys = list(leg.get("ys") or [])
        if len(xs) < 2:
            continue
        color = str(leg.get("color") or "#455a64")
        dashed = bool(leg.get("unconfirmed"))
        _halo_line(
            ax,
            xs,
            ys,
            color,
            lw=lw,
            halo=0.7,
            ls=(0, (5, 2.6)) if dashed else "-",
            z=7,
        )
        ax.scatter(
            xs,
            ys,
            s=36,
            facecolors="#ffffff" if dashed else color,
            edgecolors=color,
            linewidths=1.2,
            zorder=9,
        )
    a = story.get("a") or {}
    if a.get("xs"):
        i0 = float(a["xs"][0])
        y0 = float(a["ys"][0])
        dx = -max(5.2, n * 0.032)
        dy = span * 0.025
        if i0 + dx < 1.0:
            dx = max(3.2, n * 0.02)
            dy = span * 0.08
        _circled_letter(ax, i0, y0, "A", "#2e7d32", dx=dx, dy=dy, size=13)
    b = story.get("b") or {}
    if b.get("xs"):
        mx = (float(b["xs"][0]) + float(b["xs"][-1])) / 2.0
        my = (float(b["ys"][0]) + float(b["ys"][-1])) / 2.0
        _circled_letter(ax, mx, my, "B", "#1565c0", dx=0.0, dy=span * 0.055, size=13)
    c = story.get("c") or {}
    if c.get("xs"):
        mx = (float(c["xs"][0]) + float(c["xs"][-1])) / 2.0
        my = (float(c["ys"][0]) + float(c["ys"][-1])) / 2.0
        _circled_letter(ax, mx, my, "C", "#6a1b9a", dx=0.0, dy=-span * 0.045, size=13)
    fifth = story.get("fifth_high") or {}
    if fifth:
        _leader_note(
            ax,
            float(fifth["i"]),
            float(fifth["y"]),
            str(fifth.get("text") or ""),
            "#2e7d32",
            tx=max(0.6, float(fifth["i"]) - max(6.0, n * 0.04)),
            ty=y_top,
            size=10,
            ha="left",
            va="bottom",
        )
    done = story.get("a_done") or {}
    if done:
        _leader_note(
            ax,
            float(done["i"]),
            float(done["y"]),
            str(done.get("text") or ""),
            "#2e7d32",
            tx=float(done["i"]) + 5.2,
            ty=float(done["y"]) - span * 0.045,
            size=10,
            ha="left",
            va="top",
        )
    bh = story.get("b_high") or {}
    if bh:
        _leader_note(
            ax,
            float(bh["i"]),
            float(bh["y"]),
            str(bh.get("text") or ""),
            "#1565c0",
            tx=min(n - 1.2, float(bh["i"]) + 2.2),
            ty=y_top,
            size=10,
            ha="left",
            va="bottom",
        )
    if c.get("lab"):
        _leader_note(
            ax,
            float(c["xs"][-1]),
            float(c["ys"][-1]),
            str(c.get("lab") or "C未確認"),
            "#6a1b9a",
            tx=min(n + 6.5, float(c["xs"][-1]) + 3.2),
            ty=float(c["ys"][-1]),
            size=9,
            ha="left",
            va="center",
        )


def render_twii_degree_png(db_path: str, save_path: str) -> str:
    """加權日K＋2026 ABC 連線。A 接 B 不准斷。不數段、不畫假未來 K。"""
    bars = _load_twii_bars(db_path, n=_TWII_MAIN_BARS)
    if len(bars) < 8 or not save_path:
        return ""
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        from decision_card_signals import candle_up_taiwan
        from wayne_navigator import NAV_CHART_DPI, _fp, _mpl_serial
    except Exception:
        return ""

    path_pts = wave_path_points(db_path, bars)
    last_hit, _prev_hit = last_two(db_path)
    last_tag = str((last_hit or {}).get("tag") or "")
    if not last_tag and path_pts:
        last_tag = str(path_pts[-1].get("tag") or "")
    story = wave_abc_story(bars, last_tag)
    rays = wave_extend_rays(path_pts, len(bars), last_tag)
    long_bars = _load_twii_bars(db_path, n=_TWII_LONG_BARS)
    long_story = wave_abc_story(long_bars, last_tag) if long_bars else {}

    @_mpl_serial
    def _draw() -> str:
        from biaoke_chart import (
            _halo_line,
            _place_right_notes,
            paint_locator_inset,
        )

        n = len(bars)
        opens = [float(r.get("open") or r.get("close") or 0) for r in bars]
        highs = [float(r.get("high") or r.get("close") or 0) for r in bars]
        lows = [float(r.get("low") or r.get("close") or 0) for r in bars]
        closes = [float(r.get("close") or 0) for r in bars]
        ys = highs + lows
        keep_lv = {"他原文C波最差", "9/3低右肩"}
        for lv, lab, _d in _TWII_LEVELS:
            if lab in keep_lv:
                ys.append(lv)
        for r in rays:
            ys.append(float(r.get("y2") or r.get("y") or 0))
            ys.append(float(r.get("y1") or 0))
        for key in ("a", "b", "c"):
            for y in (story.get(key) or {}).get("ys") or []:
                ys.append(float(y))
        y_top = max(highs) + 620
        y_bot = min(lows) - 480
        ymin = min(ys) - 780
        ymax = max(ys) + 1100
        ymax = max(ymax, y_top + 280)
        ymin = min(ymin, y_bot - 280)
        os.makedirs(os.path.dirname(save_path) or ".", exist_ok=True)
        fig, ax = plt.subplots(figsize=(16.2, 9.4), dpi=NAV_CHART_DPI)
        fig.patch.set_facecolor("#ffffff")
        ax.set_facecolor("#ffffff")
        ax.axvspan(n - 0.45, n + 8.2, facecolor="#fff6e0", alpha=0.95, zorder=0)
        ax.axvline(n - 0.45, color="#ffcc80", linewidth=1.1, linestyle=":", zorder=2)
        x_gutter = n + 9.0
        for i in range(n):
            prev_c = closes[i - 1] if i else None
            up = candle_up_taiwan(closes[i], prev_c, opens[i])
            color = "#e53935" if up else "#00897b"
            ax.vlines(i, lows[i], highs[i], color=color, linewidth=1.2, zorder=3)
            y0, y1 = sorted((opens[i], closes[i]))
            ax.add_patch(
                plt.Rectangle(
                    (i - 0.34, y0),
                    0.68,
                    max(y1 - y0, 8),
                    facecolor=color,
                    edgecolor=color,
                    linewidth=0.4,
                    zorder=4,
                )
            )
        colors = {
            "他原文C波最差": "#90a4ae",
            "9/3低右肩": "#546e7a",
        }
        styles = {
            "他原文C波最差": (0, (4, 3)),
        }
        right_notes: list = []
        for lv, lab, _d in _TWII_LEVELS:
            if lab not in keep_lv:
                continue
            ax.axhline(
                lv,
                color=colors.get(lab, "#90a4ae"),
                linewidth=0.9,
                linestyle=styles.get(lab, "-"),
                zorder=2,
            )
            short_lv = lab.replace("他原文C波最差", "最差43500").replace("9/3低右肩", "9/3低")
            right_notes.append(
                {
                    "x": float(n - 1),
                    "y": float(lv),
                    "text": f"{short_lv} {_px(lv)}",
                    "color": colors.get(lab, "#546e7a"),
                    "size": 9,
                }
            )
        if story:
            _paint_abc_on_ax(ax, story, n=n, y_top=y_top, y_bot=y_bot)
        for r in rays:
            _halo_line(
                ax,
                [r["x1"], r["x2"]],
                [r["y1"], r["y2"]],
                "#6a1b9a",
                lw=1.1,
                halo=0.5,
                ls=(0, (4, 3)),
                z=5,
            )
            right_notes.append(
                {
                    "x": float(r["x2"]),
                    "y": float(r["y2"]),
                    "text": str(r.get("label") or ""),
                    "color": "#6a1b9a",
                    "size": 8,
                }
            )
        _place_right_notes(ax, right_notes, x_text=x_gutter, ymin=ymin, ymax=ymax, min_gap=520)
        last = bars[-1]
        as_of = _ymd(last.get("date"))
        as_show = f"{as_of[:4]}-{as_of[4:6]}-{as_of[6:8]}" if len(as_of) == 8 else as_of
        fig.text(
            0.055,
            0.968,
            "加權官方日K　2026 ABC（給看不懂波浪的人）",
            fontproperties=_fp(13, "bold"),
            color="#1f2933",
            ha="left",
            va="top",
        )
        fig.text(
            0.055,
            0.938,
            f"{as_show} 收 {_px(last.get('close'))}　現在標籤 {last_tag or '—'}",
            fontproperties=_fp(12, "bold"),
            color="#1f2933",
            ha="left",
            va="top",
        )
        fig.text(
            0.055,
            0.908,
            "綠實線Ａ＝6/23第五波高跌到7/29低（Ａ完＝Ｂ起）　藍實線Ｂ＝同一7/29低反彈到9/8高　紫虛線Ｃ＝9/8後還沒確認",
            fontproperties=_fp(9, "bold"),
            color="#37474f",
            ha="left",
            va="top",
        )
        ax.set_xlim(-0.6, n + 14)
        ax.set_ylim(ymin, ymax)
        ax.grid(True, linestyle=(0, (1.2, 1.6)), linewidth=0.5, color="#bdbdbd")
        from biaoke_chart import _axis_ticks

        ticks = _axis_ticks(n)
        labels = []
        for i in ticks:
            d = str(bars[i].get("date") or "")
            d = _ymd(d)
            labels.append(f"{d[4:6]}/{d[6:8]}" if len(d) == 8 else d)
        ticks.append(n - 1 + 8)
        labels.append("演算")
        ax.set_xticks(ticks)
        ax.set_xticklabels(labels, fontproperties=_fp(10, "bold"))
        ax.tick_params(labelsize=10)
        for lab in ax.get_yticklabels():
            lab.set_fontproperties(_fp(10, "bold"))
        fig.subplots_adjust(left=0.055, right=0.935, top=0.64, bottom=0.10)
        if long_bars and len(long_bars) > n + 16:
            paint_locator_inset(
                fig,
                long_bars,
                win_from=str(bars[0].get("date") or ""),
                win_to=str(bars[-1].get("date") or ""),
                rect=_TWII_LOCATOR_RECT,
                title="橙框＝大圖這段　圈A在下降線左　K在前　月份",
                legs=locator_abc_legs(long_story),
                k_on_top=True,
            )
        fig.text(
            0.055,
            0.028,
            "圈Ａ畫在下降Ａ線左邊。7/29 同一點接Ｂ。Ｃ是虛線＝未確認。不是 15 分、不發明段號、不是買訊。43500 是他原文最差。",
            fontproperties=_fp(8),
            color="#546e7a",
        )
        fig.savefig(save_path, dpi=NAV_CHART_DPI, facecolor=fig.get_facecolor())
        plt.close(fig)
        return save_path if os.path.isfile(save_path) else ""

    try:
        return _draw()
    except Exception:
        return ""


def build_twii_degree_chart(db_path: str, save_path: str) -> Dict[str, Any]:
    try:
        ensure_wave_history(db_path)
    except Exception:
        pass
    path = render_twii_degree_png(db_path, save_path)
    last, prev = last_two(db_path)
    try:
        from biaoke_forecast import record_twii, verify_due

        bars = _load_twii_bars(db_path, n=_TWII_MAIN_BARS)
        pts = wave_path_points(db_path, bars)
        tag = str((last or {}).get("tag") or "")
        rays = wave_extend_rays(pts, len(bars), tag)
        record_twii(db_path, bars, rays=rays, last_tag=tag)
        verify_due(db_path, "TWII")
    except Exception:
        pass
    cap_bits = [
        "加權官方日K＋2026 ABC 轉折線（不是15分、不是介紹圖／決策卡）",
        "A＝6/23第五波高跌到7/29低；7/29同一點＝A完也是B起；B＝反彈到9/8高；C虛線＝9/8後還沒確認。",
        "圈Ａ畫在下降Ａ線左邊。右上縮圖Ｋ在前、浪在後，避免線壓死Ｋ。",
        "線按區間拆開：2024第4浪裡的大B ≠ 2026 A波後大B。五月到現在大一級是右肩／位階二，不是一路大B。",
        format_wave_now(db_path, n=420),
    ]
    if last:
        cap_bits.append(f"最新標籤 {last.get('date')} {last.get('tag')}")
    if prev:
        cap_bits.append(f"再前 {prev.get('date')} {prev.get('tag')}")
    cap_bits.append("對得上他原文的層級才畫。不數 5／9 段。這不是買訊。")
    cap_bits.append("延伸線已建檔，官方柱走完再對質。不是保證。")
    return {
        "ok": bool(path),
        "path": path or "",
        "caption": _clip("\n".join(cap_bits), 1200),
    }
