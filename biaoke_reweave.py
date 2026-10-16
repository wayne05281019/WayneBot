# -*- coding: utf-8 -*-
"""飆大近窗活化串聯：抓到主文／自回就重織思考網，找脈絡黃金。

本質：在飆大鈕裡要像活人一樣想——為什麼改口、現在卡在哪、黃金在哪。
不准死背日期目錄。可跨主庫＋evolve 查閱。個股不發明 5／9。
切入編碼仍只認剛脫離零；口語黃金是活用不是改海選公式。
"""
from __future__ import annotations

import os
import re
import sqlite3
import time
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Sequence, Tuple
from zoneinfo import ZoneInfo

TAIPEI = ZoneInfo("Asia/Taipei")
REWEAVE_DAYS = 120  # 近四個月
_CACHE: Dict[str, Any] = {"key": "", "at": 0.0, "pack": None}
_CACHE_TTL = 90.0

_FIELD_MARKERS: Tuple[Tuple[str, Tuple[str, ...]], ...] = (
    ("記憶體", ("記憶體", "南亞科", "華邦電", "群聯", "模組")),
    ("散熱", ("散熱", "奇鋐", "健策", "雙鴻", "尼得科")),
    ("光通訊InP", ("InP", "聯亞", "全新", "IET", "光通訊")),
    ("ASIC", ("ASIC", "創意", "世芯", "智原")),
    ("CPO/FAU", ("CPO", "FAU", "矽光子", "大立光")),
    ("PCB/CCL", ("PCB", "CCL", "台光電", "金像電", "欣興")),
)
def _ymd_ago(days: int) -> str:
    dt = datetime.now(TAIPEI) - timedelta(days=max(1, int(days)))
    return dt.strftime("%Y-%m-%d")


def _today() -> str:
    return datetime.now(TAIPEI).strftime("%Y-%m-%d")


def load_voice_window(
    db_path: str,
    *,
    days: int = REWEAVE_DAYS,
) -> List[Dict[str, Any]]:
    """近窗他自己的主文＋自回（路人楼下不當判斷）。"""
    if not db_path or not os.path.isfile(db_path):
        return []
    start = _ymd_ago(days)
    end = _today()
    try:
        conn = sqlite3.connect(db_path, timeout=8.0)
        try:
            hit = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='biaoke_posts'"
            ).fetchone()
            if not hit:
                return []
            try:
                rows = conn.execute(
                    "SELECT id, date, time, text, IFNULL(kind,'post'), IFNULL(parent,''), "
                    "IFNULL(reply_to_text,'') "
                    "FROM biaoke_posts "
                    "WHERE date>=? AND date<=? AND IFNULL(kind,'')!='bystander' "
                    "ORDER BY date ASC, time ASC, id ASC",
                    (start, end),
                ).fetchall()
            except sqlite3.OperationalError:
                rows = conn.execute(
                    "SELECT id, date, time, text, IFNULL(kind,'post'), IFNULL(parent,'') "
                    "FROM biaoke_posts "
                    "WHERE date>=? AND date<=? AND IFNULL(kind,'')!='bystander' "
                    "ORDER BY date ASC, time ASC, id ASC",
                    (start, end),
                ).fetchall()
        finally:
            conn.close()
    except sqlite3.Error:
        return []
    out: List[Dict[str, Any]] = []
    for r in rows:
        kind = str(r[4] or "post")
        if kind not in ("post", "reply", ""):
            continue
        text = str(r[3] or "").strip()
        if not text:
            continue
        # 自回才進；路人已用 bystander 擋
        out.append(
            {
                "id": str(r[0] or ""),
                "date": str(r[1] or ""),
                "time": str(r[2] or ""),
                "text": text,
                "kind": kind or "post",
                "parent": str(r[5] or ""),
                "reply_to_text": str(r[6] or "") if len(r) > 6 else "",
            }
        )
    return out


def _first_last_dates(
    rows: Sequence[Dict[str, Any]], needles: Sequence[str]
) -> Tuple[str, str, int]:
    hits = [
        r
        for r in rows
        if any(n and n in str(r.get("text") or "") for n in needles)
    ]
    if not hits:
        return "", "", 0
    return str(hits[0].get("date") or ""), str(hits[-1].get("date") or ""), len(hits)


def _field_arc(rows: Sequence[Dict[str, Any]]) -> List[str]:
    """類股主戰場怎麼換——活人脈絡，不是清單。"""
    timed: List[Tuple[str, str, int]] = []
    for name, needles in _FIELD_MARKERS:
        a, b, n = _first_last_dates(rows, needles)
        if n:
            timed.append((a or "9999", name, n))
    timed.sort(key=lambda x: x[0])
    if not timed:
        return []
    path = "→".join(f"{name}" for _d, name, _n in timed[-5:])
    lines = [f"近四月主戰場脈絡：{path}（他自己文＋自回串起來，不是新聞標題）"]
    # 已退場主題：四月窗內提過、但最近沒再講＝不准建議買
    recent = list(rows)[-min(40, len(rows)) :]
    drone_recent = any("無人機" in str(r.get("text") or "") for r in recent)
    drone_ever = any("無人機" in str(r.get("text") or "") for r in rows)
    if drone_ever and not drone_recent:
        lines.append(
            "已退場：無人機近窗沒再講——不准再建議中光電／雷虎／事欣科那組。"
        )
    return lines


_SKIP_REPLY = re.compile(r"閱讀障礙")
_LEAD_QUOTE = re.compile(
    r"""^\s*(?:["“「『][^"”」』]{0,160}["”」』])\s*"""
)
_ANCHORS = ("聯亞", "大立光", "奇鋐", "奇宏", "創意", "台積電", "台指期")
_IF_EXAMPLE = re.compile(r"如果|舉例|譬如")
_LEVEL_NUM = re.compile(r"(?<!\d)(\d{4,6})(?!\d)")
# 台指期比「大盤」先配：同一句同時出現時，數字靠誰近就跟誰。
_SERIES_WORDS: Tuple[Tuple[str, Tuple[str, ...]], ...] = (
    ("TX", ("台指期",)),
    ("TWII", ("加權", "大盤")),
    ("2330", ("台積電",)),
    ("3443", ("創意",)),
    ("3081", ("聯亞",)),
    ("3017", ("奇鋐",)),
    ("3008", ("大立光",)),
)
_SERIES_LABEL = {
    "TX": "台指期",
    "TWII": "加權",
    "2330": "台積電",
    "3443": "創意",
    "3081": "聯亞",
    "3017": "奇鋐",
    "3008": "大立光",
}


def _row_sort_key(row: Dict[str, Any]) -> Tuple[str, str, str]:
    t = str(row.get("time") or "")
    parts = t.split(":")
    while len(parts) < 3:
        parts.append("00")
    clock = ":".join(p.zfill(2)[:2] if len(p) > 2 else p.zfill(2) for p in parts[:3])
    return (
        str(row.get("date") or ""),
        clock,
        str(row.get("id") or row.get("post_id") or ""),
    )


def _is_reply_row(row: Dict[str, Any]) -> bool:
    return str(row.get("kind") or "") == "reply"


def _norm_cmp(text: str) -> str:
    return re.sub(r"\s+", "", str(text or ""))


def _already_shown(bit: str, shown: Sequence[str]) -> bool:
    n = _norm_cmp(bit)
    if len(n) < 12:
        return False
    for s in shown:
        t = _norm_cmp(s)
        # 只在黃金句已經整段出現過才略過。他還說裡的短摘錄不准把較完整的自回蓋掉。
        if t and n in t:
            return True
    return False


def _clean_voice(text: str) -> str:
    s = str(text or "")
    try:
        from biaoke_ingest import scrub_cmoney_chrome

        s = scrub_cmoney_chrome(s)
    except Exception:
        pass
    s = re.sub(r"https://image\.cmoney\.tw/\S+", "", s, flags=re.I)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def _anchored_text(row: Dict[str, Any]) -> str:
    """他回在別人樓下時，自己那句沒寫股名，就沿用該樓點過的那一個名字。"""
    text = _clean_voice(str(row.get("text") or ""))
    if not text:
        return ""
    if any(name in text for name in _ANCHORS):
        return text
    # 0050／定期定額是他自己的完整句，不准把樓主股名黏上去。
    if re.search(r"0050|定期定額", text):
        return text
    parent = _clean_voice(str(row.get("reply_to_text") or ""))
    hits = [name for name in _ANCHORS if name in parent and name not in text]
    if len(hits) == 1 and (
        _LEVEL_NUM.search(text) or re.search(r"出清|觀察單|買回|止穩", text)
    ):
        return f"{hits[0]}，{text}"
    return text


def _lianya_kept(raw: str) -> str:
    """22:14 有人問清光是否包含聯亞。嘲諷詞不進話筒，聯亞還在要留下。"""
    if "聯亞" not in raw:
        return ""
    if not _SKIP_REPLY.search(raw):
        return ""
    if "清光" not in raw and "台積電" not in raw:
        return ""
    return (
        "有人問全部清光是否也包含聯亞，他說那是讀錯；"
        "那句是清光持股、包含台積電，聯亞還在，不在清光那句裡。"
    )


def _split_sents(text: str) -> List[str]:
    s = _clean_voice(text)
    parts = [p.strip(" ，、") for p in re.split(r"[。！？]", s) if p.strip()]
    if parts:
        return parts
    return [s] if s else []


def _strip_leading_quotes(text: str) -> str:
    """樓中樓常先引路人那句。引號裡不是他的判斷，留下引號後面他自己的話。"""
    s = _clean_voice(text)
    prev = None
    while s and prev != s:
        prev = s
        s = _LEAD_QUOTE.sub("", s).strip()
    return s


def _own_clip(text: str, shown: Sequence[str], *, limit: int = 220) -> str:
    """自回整則留。已經寫進大盤／前面黃金句的句子不再貼一次。"""
    body = _strip_leading_quotes(text)
    if not body or _SKIP_REPLY.search(body):
        return ""
    fresh = [p for p in _split_sents(body) if not _already_shown(p, shown)]
    if not fresh:
        return ""
    out = "。".join(fresh[:2]).strip()
    if len(out) > limit:
        out = out[:limit].rstrip("，、 ") + "…"
    if out and not out.endswith(("。", "…")):
        out += "。"
    return out


def _hit_clip(text: str, pat: re.Pattern[str], *, limit: int = 180) -> str:
    s = _clean_voice(text)
    if not s or _SKIP_REPLY.search(s):
        return ""
    parts = _split_sents(s)
    hit = [p for p in parts if pat.search(p)]
    use = hit or parts[:2]
    out = "。".join(use[:2]).strip()
    if len(out) > limit:
        out = out[:limit].rstrip("，、 ") + "…"
    if out and not out.endswith(("。", "…")):
        out += "。"
    return out


def _fmt_px(val: Any) -> str:
    try:
        x = float(val)
    except (TypeError, ValueError):
        return ""
    if abs(x - round(x)) < 1e-6:
        return str(int(round(x)))
    return f"{x:.2f}".rstrip("0").rstrip(".")


def _bar_closed(date_iso: str, session: str) -> bool:
    """盤中未收不當官方收。比今天早的日盤／夜盤才算已收。"""
    today = _today()
    if date_iso < today:
        return True
    if date_iso > today:
        return False
    now = datetime.now(TAIPEI)
    if session == "night":
        return (now.hour, now.minute) >= (5, 0)
    return (now.hour, now.minute) >= (13, 45)


def _ymd_iso(raw: str) -> str:
    s = str(raw or "").strip()
    if re.fullmatch(r"\d{8}", s):
        return f"{s[:4]}-{s[4:6]}-{s[6:8]}"
    return s


def _load_official_bar(db_path: str, series: str) -> Optional[Dict[str, Any]]:
    if not db_path or not os.path.isfile(db_path):
        return None
    try:
        conn = sqlite3.connect(db_path, timeout=8.0)
    except sqlite3.Error:
        return None
    try:
        if series == "TX":
            rows = conn.execute(
                "SELECT date, open, high, low, close, volume, session "
                "FROM futures_daily WHERE symbol='TX' AND session='regular' "
                "AND close IS NOT NULL ORDER BY date DESC LIMIT 6"
            ).fetchall()
            session = "regular"
        elif series == "TWII":
            rows = conn.execute(
                "SELECT date, open, high, low, close, volume "
                "FROM index_daily WHERE symbol='TWII' AND close IS NOT NULL "
                "ORDER BY date DESC LIMIT 6"
            ).fetchall()
            session = "regular"
        else:
            rows = conn.execute(
                "SELECT date, open, high, low, close, volume "
                "FROM daily_quotes WHERE stock_id=? AND close IS NOT NULL "
                "ORDER BY date DESC LIMIT 6",
                (series,),
            ).fetchall()
            session = "regular"
    except sqlite3.Error:
        return None
    finally:
        conn.close()
    for row in rows:
        date_iso = _ymd_iso(str(row[0] or ""))
        sess = session
        if series == "TX":
            sess = str(row[6] or "regular")
        if not date_iso or not _bar_closed(date_iso, sess):
            continue
        try:
            high = float(row[2])
            low = float(row[3])
            close = float(row[4])
            open_ = float(row[1]) if row[1] is not None else close
        except (TypeError, ValueError):
            continue
        vol = row[5]
        return {
            "date": date_iso,
            "open": open_,
            "high": high,
            "low": low,
            "close": close,
            "volume": vol,
            "session": sess,
        }
    return None


def _touch_phrase(high: float, low: float, px: float) -> str:
    p = _fmt_px(px)
    if low <= px <= high:
        return f"這根高低包住他說的{p}"
    if high < px:
        return f"高還沒到他說的{p}"
    return f"低還在他說的{p}之上"


def _series_near(sentence: str, start: int, end: int) -> str:
    best = ""
    best_d = 10**9
    for code, words in _SERIES_WORDS:
        for word in words:
            i = sentence.find(word)
            while i >= 0:
                d = min(abs(i - start), abs(i + len(word) - end))
                if d < best_d:
                    best_d = d
                    best = code
                i = sentence.find(word, i + 1)
    if best and best_d <= 40:
        return best
    return ""


def _levels_from_posts(posts: Sequence[Dict[str, Any]]) -> List[Tuple[str, float]]:
    """只配他同一句（或同一則接著講的點位）裡點名的價。不另造價。"""
    found: List[Tuple[str, float]] = []
    seen = set()
    for post in posts:
        text = _clean_voice(str(post.get("text") or ""))
        if not text:
            continue
        last = ""
        parts = [p.strip() for p in re.split(r"[。！？]", text) if p.strip()]
        if not parts:
            parts = [text]
        for sent in parts:
            named = ""
            for code, words in _SERIES_WORDS:
                if any(w in sent for w in words):
                    named = code
                    break
            if _IF_EXAMPLE.search(sent):
                if named:
                    last = named
                continue
            local = ""
            for m in _LEVEL_NUM.finditer(sent):
                num = m.group(1)
                if num.startswith("202"):
                    continue
                series = _series_near(sent, m.start(), m.end()) or local or named or last
                if not series:
                    continue
                local = series
                px = float(num)
                key = (series, px)
                if key in seen:
                    continue
                seen.add(key)
                found.append(key)
            if local or named:
                last = local or named
    return found


def _official_lines(db_path: str, levels: Sequence[Tuple[str, float]]) -> List[str]:
    grouped: Dict[str, List[float]] = {}
    order: List[str] = []
    for series, px in levels:
        if series not in grouped:
            order.append(series)
            grouped[series] = []
        if px not in grouped[series]:
            grouped[series].append(px)
    lines: List[str] = []
    for series in order:
        bar = _load_official_bar(db_path, series)
        if not bar:
            continue
        touches = [
            _touch_phrase(float(bar["high"]), float(bar["low"]), px)
            for px in grouped[series]
        ]
        name = _SERIES_LABEL.get(series, series)
        sess = ""
        if series == "TX":
            sess = "日盤" if bar.get("session") == "regular" else "夜盤"
        vol = bar.get("volume")
        vol_bit = ""
        vol_txt = _fmt_px(vol) if vol not in (None, "") else ""
        if vol_txt and vol_txt != "0":
            vol_bit = f" 量{vol_txt}"
        lines.append(
            f"官方柱：{name}{bar['date']}{sess} "
            f"開{_fmt_px(bar['open'])} 高{_fmt_px(bar['high'])} "
            f"低{_fmt_px(bar['low'])} 收{_fmt_px(bar['close'])}{vol_bit}，"
            + "、".join(touches)
            + "。"
        )
    return lines


def voice_gold_lines(
    rows: Sequence[Dict[str, Any]],
    db_path: str = "",
    *,
    shown: Sequence[str] = (),
) -> List[str]:
    """黃金脈絡起：最新主文之後他自己的每一則回都留，對過已收官方柱。

    不套舊雙箭頭稿、不補他沒講的價、不當買訊。路人列不要傳進來。
    關鍵字對不上的自回也要留。跟大盤欄整句重複的才略過。
    """
    voice = [
        r
        for r in rows
        if str(r.get("kind") or "") != "bystander" and str(r.get("text") or "").strip()
    ]
    if not voice:
        return []
    mains = [r for r in voice if not _is_reply_row(r)]
    if not mains:
        return []
    latest = max(mains, key=_row_sort_key)
    latest_key = _row_sort_key(latest)
    later = [
        r
        for r in voice
        if _is_reply_row(r) and _row_sort_key(r) >= latest_key
    ]
    later.sort(key=_row_sort_key)
    chunks: List[str] = []
    shown_now = [str(x) for x in shown if str(x or "").strip()]
    picked: List[Dict[str, Any]] = []
    for rep in later:
        raw = _clean_voice(str(rep.get("text") or ""))
        anchored = _anchored_text(rep)
        clip = _lianya_kept(raw)
        if not clip and _SKIP_REPLY.search(raw):
            continue
        if not clip:
            clip = _own_clip(anchored, shown_now + chunks, limit=220)
        if not clip:
            continue
        picked.append(rep)
        if not _already_shown(clip, shown_now + chunks):
            chunks.append(clip)
    if not chunks:
        clip = _hit_clip(
            str(latest.get("text") or ""),
            re.compile(r"點位|雙箭頭|主流|空方|波浪|必須|穿刺"),
        )
        if clip and not _already_shown(clip, shown_now):
            chunks.append(clip)
    # 官方柱只對最新主文＋這串拿進文案的自回。股名沿用他回的那一樓。
    level_posts = [latest]
    for rep in picked:
        leveled = dict(rep)
        leveled["text"] = _anchored_text(rep)
        level_posts.append(leveled)
    official = _official_lines(db_path, _levels_from_posts(level_posts))
    official = [x for x in official if not _already_shown(x, shown_now + chunks)]
    if not chunks and not official:
        return []
    out: List[str] = []
    if chunks:
        out.append("黃金脈絡：" + chunks[0])
        out.extend(chunks[1:])
        out.extend(official)
    else:
        out.append("黃金脈絡：" + official[0])
        out.extend(official[1:])
    return out


def reweave_gold(
    db_path: str = "",
    *,
    days: int = REWEAVE_DAYS,
    force: bool = False,
) -> Dict[str, Any]:
    """重織近四個月思考網，產出活人脈絡黃金。"""
    key = f"{db_path}|{int(days)}"
    now = time.time()
    if (
        not force
        and _CACHE.get("key") == key
        and _CACHE.get("pack")
        and now - float(_CACHE.get("at") or 0) < _CACHE_TTL
    ):
        return dict(_CACHE["pack"])
    rows = load_voice_window(db_path, days=days)
    out: Dict[str, Any] = {
        "ok": False,
        "days": int(days),
        "n_main": sum(1 for r in rows if str(r.get("kind") or "post") != "reply"),
        "n_reply": sum(1 for r in rows if str(r.get("kind") or "") == "reply"),
        "start": rows[0]["date"] if rows else "",
        "end": rows[-1]["date"] if rows else "",
        "lines": [],
        "gold": [],
    }
    if not rows:
        _CACHE.update({"key": key, "at": now, "pack": out})
        return out
    gold: List[str] = []
    gold.extend(voice_gold_lines(rows, db_path))
    for line in _field_arc(rows):
        if str(line).startswith("已退場") and line not in gold:
            gold.append(line)
    # 去重保序
    seen: List[str] = []
    for g in gold:
        g = str(g or "").strip()
        if g and g not in seen:
            seen.append(g)
    head = (
        f"近{int(days)}日活化：主文{out['n_main']}／自回{out['n_reply']}"
        f"（{out['start']}～{out['end']}）——像活人重讀一遍找脈絡，不是背稿。"
    )
    lines = [head] + seen
    lines.append(
        "飆大鈕本質：抓到文就擴張思考網、跨庫對官方柱、找出黃金；"
        "你在這顆鈕裡要活，不准當答錄機。"
    )
    out.update({"ok": True, "lines": lines, "gold": seen})
    _CACHE.update({"key": key, "at": now, "pack": dict(out)})
    return out


def record_reweave(
    db_path: str,
    events: Sequence[Dict[str, Any]] | None = None,
) -> Dict[str, Any]:
    """抓到主文／自回後強制重織。失敗吞掉，不准擋抓文。"""
    del events  # 觸發即可；材料從庫讀近四月
    try:
        return reweave_gold(db_path, force=True)
    except Exception:
        return {"ok": False, "lines": [], "gold": []}


def reweave_live_notes(db_path: str = "", ask: str = "") -> str:
    del ask
    pack = reweave_gold(db_path)
    if not pack.get("ok"):
        return ""
    bits = [
        "近四月活化思考網（真人角度，不准死背）：",
        "在飆大鈕裡你要想得像他：改口原因、不確定處、黃金買點條件、族群次層。",
        "可跨主庫日K／佔比／海選桶／tape 與 evolve live_judge。",
    ]
    for line in (pack.get("lines") or [])[:12]:
        bits.append("黃金｜" + line)
    return "\n".join(bits)


def format_reweave_html(db_path: str = "", *, limit: int = 6) -> str:
    from tg_layout import html_escape

    pack = reweave_gold(db_path)
    if not pack.get("ok"):
        return ""
    blocks = ["<b>近四月活化·脈絡黃金</b>"]
    for line in (pack.get("gold") or pack.get("lines") or [])[: max(1, int(limit))]:
        t = str(line).replace("不是買訊", "")
        blocks.append(html_escape(t))
    return "\n".join(blocks)


def reweave_focus_lines(db_path: str = "", *, limit: int = 4) -> List[str]:
    pack = reweave_gold(db_path)
    out: List[str] = []
    for line in (pack.get("gold") or [])[: max(1, int(limit))]:
        t = str(line).replace("不是買訊", "")
        if t:
            out.append(t)
    return out
